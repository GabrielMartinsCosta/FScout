"""Testes do motor de métricas, sobre um banco pequeno e controlado.

As asserções conferem contra contagens feitas à mão a partir das finalizações montadas no
fixture — é o teste que garante que "gols de canhota de fora da área" significa o que diz.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fscout.db.models import (
    Appearance,
    Competition,
    Event,
    Match,
    Player,
    Season,
    Shot,
    Team,
)
from fscout.db.session import build_engine, create_all
from fscout.domain.enums import (
    BodyPart,
    CompetitionType,
    EventType,
    HomeAway,
    PlayPattern,
    PositionGroup,
    ShotOutcome,
    ShotType,
)
from fscout.metrics.context import Slice
from fscout.metrics.definitions import shooting  # noqa: F401  (registra o catálogo)
from fscout.metrics.engine import evaluate, minutes_by_player
from fscout.metrics.registry import REGISTRY, Aggregation, MetricSpec, Unit

RODADA_1 = date(2024, 6, 20)
RODADA_2 = date(2024, 6, 27)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(f"sqlite:///{tmp_path / 'metricas.db'}")
    create_all(engine)

    with Session(engine) as session:
        competicao = Competition(name="Liga", type=CompetitionType.NATIONAL_LEAGUE)
        session.add(competicao)
        session.flush()
        temporada = Season(competition_id=competicao.id, name="2024")
        casa, visitante = Team(name="Casa"), Team(name="Visita")
        artilheiro = Player(name="Artilheiro", primary_position_group=PositionGroup.FORWARD)
        reserva = Player(name="Reserva", primary_position_group=PositionGroup.FORWARD)
        session.add_all([temporada, casa, visitante, artilheiro, reserva])
        session.flush()

        partidas = {}
        for rodada, mandante, visitantee in (
            (RODADA_1, casa, visitante),
            (RODADA_2, visitante, casa),
        ):
            partida = Match(
                season_id=temporada.id,
                match_date=rodada,
                kickoff=datetime(rodada.year, rodada.month, rodada.day, 20),
                home_team_id=mandante.id,
                away_team_id=visitantee.id,
            )
            session.add(partida)
            session.flush()
            partidas[rodada] = partida

        def participa(jogador: Player, rodada: date, minutos: int, mando: HomeAway) -> None:
            partida = partidas[rodada]
            session.add(
                Appearance(
                    match_id=partida.id,
                    player_id=jogador.id,
                    team_id=casa.id,
                    opponent_team_id=visitante.id,
                    home_away=mando,
                    position_group=PositionGroup.FORWARD,
                    minutes_played=minutos,
                )
            )

        participa(artilheiro, RODADA_1, 90, HomeAway.HOME)
        participa(artilheiro, RODADA_2, 90, HomeAway.AWAY)
        participa(reserva, RODADA_1, 45, HomeAway.HOME)
        session.flush()

        sequencia = iter(range(1, 1000))

        def finaliza(
            jogador: Player,
            rodada: date,
            *,
            gol: bool = False,
            no_alvo: bool = False,
            pe: BodyPart = BodyPart.RIGHT_FOOT,
            na_area: bool = True,
            tipo: ShotType = ShotType.OPEN_PLAY,
            padrao: PlayPattern = PlayPattern.REGULAR_PLAY,
            xg: float | None = 0.1,
            disputa: bool = False,
            bloqueada: bool = False,
        ) -> None:
            indice = next(sequencia)
            partida = partidas[rodada]
            evento = Event(
                source="teste",
                source_id=f"e{indice}",
                match_id=partida.id,
                sequence=indice,
                period=5 if disputa else 1,
                minute=10,
                second=0,
                type=EventType.SHOT,
                team_id=casa.id,
                player_id=jogador.id,
                play_pattern=padrao,
            )
            session.add(evento)
            session.flush()
            session.add(
                Shot(
                    event_id=evento.id,
                    player_id=jogador.id,
                    match_id=partida.id,
                    shot_type=tipo,
                    outcome=ShotOutcome.GOAL if gol else ShotOutcome.SAVED,
                    body_part=pe,
                    is_goal=gol,
                    is_on_target=gol or no_alvo,
                    was_blocked=bloqueada,
                    in_penalty_area=na_area,
                    in_six_yard_box=False,
                    is_shootout=disputa,
                    distance_m=12.0 if na_area else 25.0,
                    xg=xg,
                )
            )

        # Artilheiro, rodada 1 (em casa): gol de canhota na área vindo de escanteio,
        # finalização de fora da área no alvo e uma bloqueada.
        finaliza(
            artilheiro,
            RODADA_1,
            gol=True,
            pe=BodyPart.LEFT_FOOT,
            padrao=PlayPattern.FROM_CORNER,
            xg=0.4,
        )
        finaliza(artilheiro, RODADA_1, no_alvo=True, na_area=False, xg=0.05)
        finaliza(artilheiro, RODADA_1, bloqueada=True, xg=0.02)
        # Artilheiro, rodada 2 (fora): gol de pênalti e um pênalti perdido na disputa.
        finaliza(artilheiro, RODADA_2, gol=True, tipo=ShotType.PENALTY, xg=0.78)
        finaliza(artilheiro, RODADA_2, tipo=ShotType.PENALTY, disputa=True, xg=0.78)
        # Reserva: um gol de cabeça.
        finaliza(reserva, RODADA_1, gol=True, pe=BodyPart.HEAD, xg=0.3)
        session.commit()

    yield engine
    engine.dispose()


def _valores(
    engine: Engine, chaves: list[str], recorte: Slice
) -> dict[str, dict[str, float | None]]:
    """Valores por nome de atleta, para as asserções ficarem legíveis."""
    with Session(engine) as session:
        resultados = evaluate(session, REGISTRY.select(chaves), recorte)
        nomes = {player_id: session.get(Player, player_id).name for player_id in resultados}
    return {
        nomes[player_id]: {chave: medida.value for chave, medida in medidas.items()}
        for player_id, medidas in resultados.items()
    }


def test_contagens_por_recorte_de_finalizacao(engine: Engine) -> None:
    valores = _valores(
        engine,
        [
            "gols",
            "finalizacoes",
            "gols_canhota",
            "gols_de_cabeca",
            "gols_de_escanteio",
            "gols_de_penalti",
            "gols_fora_da_area",
            "finalizacoes_fora_da_area",
        ],
        Slice(),
    )

    assert valores["Artilheiro"]["gols"] == 2
    assert valores["Artilheiro"]["finalizacoes"] == 4  # a cobrança da disputa não conta
    assert valores["Artilheiro"]["gols_canhota"] == 1
    assert valores["Artilheiro"]["gols_de_escanteio"] == 1
    assert valores["Artilheiro"]["gols_de_penalti"] == 1
    assert valores["Artilheiro"]["gols_fora_da_area"] == 0
    assert valores["Artilheiro"]["finalizacoes_fora_da_area"] == 1
    assert valores["Reserva"]["gols_de_cabeca"] == 1
    assert valores["Reserva"]["gols_canhota"] == 0


def test_disputa_de_penaltis_nao_entra_em_nenhuma_metrica(engine: Engine) -> None:
    valores = _valores(engine, ["penaltis_cobrados", "gols_de_penalti"], Slice())
    assert valores["Artilheiro"]["penaltis_cobrados"] == 1


def test_razoes_e_medias(engine: Engine) -> None:
    """A conta da razão e da média, com métricas locais sem piso de amostra.

    O catálogo exige amostra mínima nessas métricas, e o fixture tem poucas finalizações de
    propósito: a supressão por amostra insuficiente é verificada no teste seguinte.
    """
    locais = (
        MetricSpec(
            key="acerto_no_alvo_teste",
            label="Acerto no alvo",
            family="teste",
            table=Shot,
            aggregation=Aggregation.RATIO,
            numerator=(Shot.is_on_target.is_(True),),
            unit=Unit.PERCENT,
            per_90=False,
        ),
        MetricSpec(
            key="conversao_teste",
            label="Conversão",
            family="teste",
            table=Shot,
            aggregation=Aggregation.RATIO,
            numerator=(Shot.is_goal.is_(True),),
            unit=Unit.PERCENT,
            per_90=False,
        ),
        MetricSpec(
            key="xg_medio_teste",
            label="xG médio",
            family="teste",
            table=Shot,
            aggregation=Aggregation.AVERAGE,
            value_column=Shot.xg,
            unit=Unit.XG,
            per_90=False,
        ),
        REGISTRY["xg"],
    )

    with Session(engine) as session:
        resultados = evaluate(session, locais, Slice())
        nomes = {pid: session.get(Player, pid).name for pid in resultados}
    artilheiro = next(m for pid, m in resultados.items() if nomes[pid] == "Artilheiro")

    xg_total = 0.4 + 0.05 + 0.02 + 0.78
    assert artilheiro["acerto_no_alvo_teste"].value == pytest.approx(3 / 4)
    assert artilheiro["conversao_teste"].value == pytest.approx(2 / 4)
    assert artilheiro["xg_medio_teste"].value == pytest.approx(xg_total / 4)
    assert artilheiro["xg"].value == pytest.approx(xg_total)


def test_normalizacao_por_90_minutos(engine: Engine) -> None:
    with Session(engine) as session:
        resultados = evaluate(session, REGISTRY.select(["gols"]), Slice())
        minutos = minutes_by_player(session, Slice())
        por_jogador = {
            session.get(Player, player_id).name: medidas["gols"]
            for player_id, medidas in resultados.items()
        }

    assert sorted(minutos.values()) == [45, 180]
    assert por_jogador["Artilheiro"].per_90 == pytest.approx(1.0)  # 2 gols em 180 minutos
    assert por_jogador["Reserva"].per_90 == pytest.approx(2.0)  # 1 gol em 45 minutos


def test_recorte_por_data_e_por_mando(engine: Engine) -> None:
    primeira = _valores(engine, ["gols"], Slice(date_to=RODADA_1))
    fora = _valores(engine, ["gols"], Slice(home_away=HomeAway.AWAY))

    assert primeira["Artilheiro"]["gols"] == 1
    assert fora["Artilheiro"]["gols"] == 1
    assert "Reserva" not in fora  # só jogou em casa


def test_piso_de_minutagem_remove_quem_jogou_pouco(engine: Engine) -> None:
    valores = _valores(engine, ["gols"], Slice(min_minutes=90))
    assert set(valores) == {"Artilheiro"}


def test_razao_com_amostra_insuficiente_nao_e_divulgada(engine: Engine) -> None:
    """Aproveitamento exige amostra: 100% em um chute so nao e informacao."""
    valores = _valores(
        engine, ["aproveitamento_de_finalizacoes", "conversao_de_finalizacoes"], Slice()
    )

    # Artilheiro tem 4 finalizacoes e Reserva tem 1; o minimo da metrica e 10.
    assert valores["Artilheiro"]["aproveitamento_de_finalizacoes"] is None
    assert valores["Reserva"]["conversao_de_finalizacoes"] is None


def test_percentil_respeita_o_sentido_da_metrica(engine: Engine) -> None:
    with Session(engine) as session:
        resultados = evaluate(
            session, REGISTRY.select(["gols", "finalizacoes_bloqueadas"]), Slice()
        )
        por_nome = {
            session.get(Player, player_id).name: medidas
            for player_id, medidas in resultados.items()
        }

    # Reserva tem 2 gols por 90 contra 1 do Artilheiro: fica acima em gols.
    assert por_nome["Reserva"]["gols"].percentile > por_nome["Artilheiro"]["gols"].percentile
    # Em finalizações bloqueadas, menos é melhor: quem não tem nenhuma fica acima.
    assert (
        por_nome["Reserva"]["finalizacoes_bloqueadas"].percentile
        > por_nome["Artilheiro"]["finalizacoes_bloqueadas"].percentile
    )


def test_metricas_compostas_cruzam_familias(engine: Engine) -> None:
    """Participação em gols soma finalizações com passes, que saem de tabelas diferentes."""
    valores = _valores(engine, ["participacao_em_gols", "minutos_por_gol", "assistencias"], Slice())

    assert valores["Artilheiro"]["assistencias"] == 0
    assert valores["Artilheiro"]["participacao_em_gols"] == 2
    assert valores["Artilheiro"]["minutos_por_gol"] == pytest.approx(90.0)  # 180 min, 2 gols
    assert valores["Reserva"]["minutos_por_gol"] == pytest.approx(45.0)  # 45 min, 1 gol


def test_composta_sem_denominador_fica_nula() -> None:
    """Quem não marcou não recebe minutagem infinita por gol: recebe ausência."""
    spec = REGISTRY["minutos_por_gol"]
    assert spec.formula({"gols": 0.0}, 180) is None
    assert spec.formula({"gols": None}, 180) is None
    assert spec.formula({"gols": 2.0}, 180) == pytest.approx(90.0)


def test_percentil_so_existe_dentro_do_grupo_de_posicao(engine: Engine) -> None:
    """Atacante não é ranqueado em métrica de goleiro, ainda que o valor seja calculado."""
    with Session(engine) as session:
        resultados = evaluate(session, REGISTRY.select(["gols", "defesas"]), Slice())

    for medidas in resultados.values():
        assert medidas["gols"].percentile is not None
        assert medidas["gols"].population == 2  # os dois atletas são atacantes
        assert medidas["defesas"].percentile is None
        assert medidas["defesas"].population == 0
