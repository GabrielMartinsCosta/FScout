"""Atletas: busca, ficha e os dados brutos que alimentam os mapas de campo."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from fscout.api.deps import SessionDep, SliceDep
from fscout.api.schemas import (
    ClubSpellOut,
    HeatmapCellOut,
    PassOut,
    PlayerProfileOut,
    PlayerSummaryOut,
    ShotOut,
)
from fscout.db.models import (
    Appearance,
    Competition,
    Country,
    Event,
    Match,
    Pass,
    Player,
    PlayerClubSpell,
    PlayerNationality,
    PlayerValuation,
    Season,
    Shot,
    Team,
)
from fscout.domain.enums import PositionGroup
from fscout.metrics.context import Slice, appearance_conditions

router = APIRouter(prefix="/players", tags=["atletas"])

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def _com_contexto(consulta: Select) -> Select:
    """Liga partida, temporada e competição a uma consulta que já tem `Appearance`.

    É o que os filtros de recorte enxergam: sem esses vínculos, "na Champions" e "em junho"
    não teriam onde ser aplicados.
    """
    return (
        consulta.join(Match, Match.id == Appearance.match_id)
        .join(Season, Season.id == Match.season_id)
        .join(Competition, Competition.id == Season.competition_id)
    )


def _filtrar(consulta: Select, recorte: Slice) -> Select:
    for condicao in appearance_conditions(recorte):
        consulta = consulta.where(condicao)
    return consulta


def _idade(nascimento: date | None, referencia: date) -> int | None:
    if nascimento is None:
        return None
    fez_aniversario = (referencia.month, referencia.day) >= (nascimento.month, nascimento.day)
    return referencia.year - nascimento.year - (0 if fez_aniversario else 1)


def _posicoes(session: Session, player_ids: list[int]) -> dict[int, PositionGroup | None]:
    """Posição em que cada atleta mais atuou, considerando todas as partidas carregadas."""
    if not player_ids:
        return {}
    melhor: dict[int, tuple[int, PositionGroup | None]] = {}
    for player_id, grupo, minutos in session.execute(
        select(Appearance.player_id, Appearance.position_group, func.sum(Appearance.minutes_played))
        .where(Appearance.player_id.in_(player_ids))
        .group_by(Appearance.player_id, Appearance.position_group)
    ):
        total = int(minutos or 0)
        if player_id not in melhor or total > melhor[player_id][0]:
            melhor[player_id] = (total, grupo)
    return {player_id: grupo for player_id, (_, grupo) in melhor.items()}


def _nacionalidades_principais(session: Session, player_ids: list[int]) -> dict[int, str]:
    if not player_ids:
        return {}
    return dict(
        session.execute(
            select(PlayerNationality.player_id, Country.name)
            .join(Country, Country.id == PlayerNationality.country_id)
            .where(
                PlayerNationality.player_id.in_(player_ids),
                PlayerNationality.is_primary.is_(True),
            )
        ).all()
    )


@router.get("", summary="Busca de atletas dentro de um recorte")
def search_players(
    session: SessionDep,
    recorte: SliceDep,
    search: str | None = None,
    limit: int = LIMITE_PADRAO,
) -> list[PlayerSummaryOut]:
    """Atletas que atuaram no recorte, dos mais para os menos utilizados."""
    minutos_no_recorte = func.sum(Appearance.minutes_played)
    consulta = _filtrar(
        _com_contexto(
            select(
                Player.id,
                Player.name,
                Player.full_name,
                Player.birth_date,
                func.count(func.distinct(Appearance.match_id)),
                minutos_no_recorte,
            )
            .join(Appearance, Appearance.player_id == Player.id)
            .group_by(Player.id)
        ),
        recorte,
    )
    if search:
        padrao = f"%{search}%"
        consulta = consulta.where(Player.name.ilike(padrao) | Player.full_name.ilike(padrao))
    if recorte.min_minutes is not None:
        consulta = consulta.having(minutos_no_recorte >= recorte.min_minutes)

    linhas = session.execute(
        consulta.order_by(minutos_no_recorte.desc()).limit(min(limit, LIMITE_MAXIMO))
    ).all()
    identificadores = [linha[0] for linha in linhas]
    posicoes = _posicoes(session, identificadores)
    nacionalidades = _nacionalidades_principais(session, identificadores)
    hoje = date.today()

    return [
        PlayerSummaryOut(
            id=player_id,
            name=nome,
            full_name=nome_completo,
            position_group=posicoes.get(player_id),
            nationality=nacionalidades.get(player_id),
            age=_idade(nascimento, hoje),
            matches=int(partidas or 0),
            minutes=int(minutos or 0),
        )
        for player_id, nome, nome_completo, nascimento, partidas, minutos in linhas
    ]


@router.get("/{player_id}", summary="Ficha do atleta")
def get_player(session: SessionDep, player_id: int) -> PlayerProfileOut:
    """Ficha completa, incluindo o que veio de fontes fora dos eventos."""
    player = session.get(Player, player_id)
    if player is None:
        raise HTTPException(404, f"atleta desconhecido: {player_id}")

    partidas, minutos = session.execute(
        select(func.count(), func.sum(Appearance.minutes_played)).where(
            Appearance.player_id == player_id
        )
    ).one()
    nacionalidades = list(
        session.scalars(
            select(Country.name)
            .join(PlayerNationality, PlayerNationality.country_id == Country.id)
            .where(PlayerNationality.player_id == player_id)
            .order_by(PlayerNationality.is_primary.desc(), Country.name)
        )
    )
    valorizacao = session.scalars(
        select(PlayerValuation)
        .where(PlayerValuation.player_id == player_id)
        .order_by(PlayerValuation.valuation_date.desc())
        .limit(1)
    ).first()
    passagens = [
        ClubSpellOut(team=nome, start_date=spell.start_date, end_date=spell.end_date)
        for spell, nome in session.execute(
            select(PlayerClubSpell, Team.name)
            .join(Team, Team.id == PlayerClubSpell.team_id)
            .where(PlayerClubSpell.player_id == player_id)
            .order_by(PlayerClubSpell.start_date)
        )
    ]
    pais_de_nascimento = (
        session.get(Country, player.birth_country_id) if player.birth_country_id else None
    )

    return PlayerProfileOut(
        id=player.id,
        name=player.name,
        full_name=player.full_name,
        position_group=_posicoes(session, [player_id]).get(player_id),
        nationality=nacionalidades[0] if nacionalidades else None,
        age=_idade(player.birth_date, date.today()),
        matches=int(partidas or 0),
        minutes=int(minutos or 0),
        birth_date=player.birth_date,
        height_cm=player.height_cm,
        preferred_foot=str(player.preferred_foot) if player.preferred_foot else None,
        birth_country=pais_de_nascimento.name if pais_de_nascimento else None,
        nationalities=nacionalidades,
        market_value_eur=valorizacao.market_value if valorizacao else None,
        market_value_date=valorizacao.valuation_date if valorizacao else None,
        contract_until=valorizacao.contract_until if valorizacao else None,
        club_spells=passagens,
    )


@router.get("/{player_id}/shots", summary="Finalizações do atleta, para o mapa de chutes")
def player_shots(session: SessionDep, recorte: SliceDep, player_id: int) -> list[ShotOut]:
    """Uma linha por finalização, com origem, destino e desfecho.

    A disputa de pênaltis fica de fora: as cobranças estão no banco, mas não pertencem ao
    mapa de chutes do jogo.
    """
    adversario = aliased(Team)
    consulta = _filtrar(
        _com_contexto(
            select(Shot, Event, Match.match_date, adversario.name)
            .select_from(Shot)
            .join(Event, Event.id == Shot.event_id)
            .join(
                Appearance,
                (Appearance.match_id == Shot.match_id) & (Appearance.player_id == Shot.player_id),
            )
            .join(adversario, adversario.id == Appearance.opponent_team_id)
        ),
        recorte,
    ).where(Shot.player_id == player_id, Shot.is_shootout.is_(False))

    return [
        ShotOut(
            match_date=data,
            minute=evento.minute,
            opponent=oponente,
            x=evento.x,
            y=evento.y,
            end_y=shot.end_y,
            end_z=shot.end_z,
            outcome=str(shot.outcome),
            is_goal=shot.is_goal,
            shot_type=str(shot.shot_type),
            body_part=str(shot.body_part) if shot.body_part else None,
            play_pattern=str(evento.play_pattern) if evento.play_pattern else None,
            distance_m=shot.distance_m,
            xg=shot.xg,
            goal_mouth_zone=str(shot.goal_mouth_zone) if shot.goal_mouth_zone else None,
        )
        for shot, evento, data, oponente in session.execute(
            consulta.order_by(Match.match_date, Event.minute)
        )
    ]


@router.get("/{player_id}/passes", summary="Passes do atleta, para o mapa de passes")
def player_passes(session: SessionDep, recorte: SliceDep, player_id: int) -> list[PassOut]:
    """Uma linha por passe, com origem, destino e as marcas que a tela usa para filtrar.

    Sem limite de linhas de propósito: o mapa precisa do conjunto inteiro para que a
    contagem exibida seja a contagem real. Um teto silencioso faria a tela afirmar
    "212 passes progressivos" quando o número verdadeiro fosse outro.
    """
    adversario = aliased(Team)
    recebedor = aliased(Player)
    consulta = _filtrar(
        _com_contexto(
            select(Pass, Event, Match.match_date, adversario.name, recebedor.name)
            .select_from(Pass)
            .join(Event, Event.id == Pass.event_id)
            .join(
                Appearance,
                (Appearance.match_id == Pass.match_id) & (Appearance.player_id == Pass.player_id),
            )
            .join(adversario, adversario.id == Appearance.opponent_team_id)
            .outerjoin(recebedor, recebedor.id == Pass.recipient_player_id)
        ),
        recorte,
    ).where(Pass.player_id == player_id)

    return [
        PassOut(
            match_date=data,
            minute=evento.minute,
            opponent=oponente,
            recipient=destinatario,
            x=evento.x,
            y=evento.y,
            end_x=passe.end_x,
            end_y=passe.end_y,
            outcome=str(passe.outcome),
            is_complete=passe.is_complete,
            pass_type=str(passe.pass_type),
            height=str(passe.height) if passe.height else None,
            body_part=str(passe.body_part) if passe.body_part else None,
            length_m=passe.length_m,
            length_bucket=passe.length_bucket,
            direction=passe.direction,
            is_cross=passe.is_cross,
            is_switch=passe.is_switch,
            is_through_ball=passe.is_through_ball,
            is_progressive=passe.is_progressive,
            into_penalty_area=passe.into_penalty_area,
            is_shot_assist=passe.is_shot_assist,
            is_goal_assist=passe.is_goal_assist,
            is_pre_assist=passe.is_pre_assist,
        )
        for passe, evento, data, oponente, destinatario in session.execute(
            consulta.order_by(Match.match_date, Event.minute)
        )
    ]


@router.get("/{player_id}/heatmap", summary="Ações por célula do campo, para o mapa de calor")
def player_heatmap(session: SessionDep, recorte: SliceDep, player_id: int) -> list[HeatmapCellOut]:
    """Contagem por célula da grade, pré-calculada na ingestão."""
    consulta = _filtrar(
        _com_contexto(
            select(Event.grid_col, Event.grid_row, func.count())
            .select_from(Event)
            .join(
                Appearance,
                (Appearance.match_id == Event.match_id) & (Appearance.player_id == Event.player_id),
            )
            .group_by(Event.grid_col, Event.grid_row)
        ),
        recorte,
    ).where(Event.player_id == player_id, Event.grid_col.is_not(None))

    return [
        HeatmapCellOut(grid_col=coluna, grid_row=linha, actions=total)
        for coluna, linha, total in session.execute(consulta)
    ]
