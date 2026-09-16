"""Recorte de análise: o objeto que delimita *quais* ações entram numa métrica.

Todo recorte pedido na especificação — por campeonato, por tipo de competição, por janela de
datas, contra um adversário, dentro ou fora de casa — é o mesmo objeto com argumentos
diferentes. Nenhuma métrica implementa recorte por conta própria: ela declara o que conta, e
o `Slice` declara onde.

É isso que faz "Messi em junho e julho de 2024" e "Messi na Champions contra o Real Madrid"
serem a mesma operação. Como o objeto é imutável, ele também serve de chave de cache.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select
from sqlalchemy.orm import aliased

from fscout.db.models import Appearance, Competition, Match, Season
from fscout.domain.enums import CompetitionType, HomeAway, PositionGroup


@dataclass(frozen=True)
class Slice:
    """Delimita o conjunto de partidas e atletas de uma análise.

    Campos vazios não filtram. `min_minutes` não é filtro de linha: é um piso de minutagem
    aplicado depois da agregação, para não comparar quem jogou 90 minutos com quem jogou 3000.
    """

    player_ids: tuple[int, ...] = ()
    team_ids: tuple[int, ...] = ()
    opponent_team_ids: tuple[int, ...] = ()
    competition_ids: tuple[int, ...] = ()
    competition_types: tuple[CompetitionType, ...] = ()
    season_ids: tuple[int, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    home_away: HomeAway | None = None
    position_groups: tuple[PositionGroup, ...] = ()
    min_minutes: int | None = None
    label: str | None = None

    def with_(self, **changes: Any) -> Slice:
        """Cópia com campos trocados, para derivar recortes ("o mesmo, mas em 2025")."""
        return replace(self, **changes)

    @property
    def describe(self) -> str:
        """Rótulo de exibição. Sem rótulo explícito, descreve o que o recorte restringe."""
        if self.label:
            return self.label
        partes = []
        if self.date_from or self.date_to:
            partes.append(f"{self.date_from or '...'} a {self.date_to or '...'}")
        if self.competition_ids or self.competition_types:
            partes.append("competições selecionadas")
        if self.opponent_team_ids:
            partes.append("adversários selecionados")
        if self.home_away:
            partes.append(str(self.home_away))
        return " · ".join(partes) if partes else "tudo"


def appearance_conditions(recorte: Slice) -> list[ColumnElement[bool]]:
    """Condições do recorte sobre a participação e a partida.

    Pressupõe que a consulta já tenha `Appearance`, `Match`, `Season` e `Competition`
    disponíveis — use `join_context` para isso.
    """
    condicoes: list[ColumnElement[bool]] = []
    if recorte.player_ids:
        condicoes.append(Appearance.player_id.in_(recorte.player_ids))
    if recorte.team_ids:
        condicoes.append(Appearance.team_id.in_(recorte.team_ids))
    if recorte.opponent_team_ids:
        condicoes.append(Appearance.opponent_team_id.in_(recorte.opponent_team_ids))
    if recorte.position_groups:
        condicoes.append(Appearance.position_group.in_(recorte.position_groups))
    if recorte.home_away is not None:
        condicoes.append(Appearance.home_away == recorte.home_away)
    if recorte.season_ids:
        condicoes.append(Match.season_id.in_(recorte.season_ids))
    if recorte.date_from is not None:
        condicoes.append(Match.match_date >= recorte.date_from)
    if recorte.date_to is not None:
        condicoes.append(Match.match_date <= recorte.date_to)
    if recorte.competition_ids:
        condicoes.append(Season.competition_id.in_(recorte.competition_ids))
    if recorte.competition_types:
        condicoes.append(Competition.type.in_(recorte.competition_types))
    return condicoes


def join_context(consulta: Select[Any], origem: Any) -> Select[Any]:
    """Liga uma tabela de projeção à participação, à partida e à competição.

    A projeção guarda `match_id` e `player_id`; é a participação que sabe o adversário, o
    mando e a minutagem, e é a competição que sabe se o jogo foi de liga, copa ou seleção.
    """
    return (
        consulta.join(
            Appearance,
            (Appearance.match_id == origem.match_id) & (Appearance.player_id == origem.player_id),
        )
        .join(Match, Match.id == Appearance.match_id)
        .join(Season, Season.id == Match.season_id)
        .join(Competition, Competition.id == Season.competition_id)
    )


def minutes_query(recorte: Slice) -> Select[Any]:
    """Minutos por atleta dentro do recorte, base da normalização por 90 minutos."""
    from sqlalchemy import func, select

    consulta = (
        select(Appearance.player_id, func.sum(Appearance.minutes_played))
        .join(Match, Match.id == Appearance.match_id)
        .join(Season, Season.id == Match.season_id)
        .join(Competition, Competition.id == Season.competition_id)
        .group_by(Appearance.player_id)
    )
    for condicao in appearance_conditions(recorte):
        consulta = consulta.where(condicao)
    return consulta


def opponents_of(player_ids: Sequence[int]) -> Any:
    """Adversários já enfrentados pelos atletas, para montar o recorte "contra o time X"."""
    from sqlalchemy import distinct, select

    adversario = aliased(Appearance)
    return (
        select(distinct(adversario.opponent_team_id))
        .where(adversario.player_id.in_(player_ids))
        .order_by(adversario.opponent_team_id)
    )


def position_groups_query(recorte: Slice) -> Select[Any]:
    """Minutos por atleta e grupo de posição dentro do recorte.

    O grupo em que o atleta mais atuou define com quem ele é comparado no percentil. Quem
    jogou de lateral na competição analisada é comparado com laterais, mesmo que atue em
    outra função no clube.
    """
    from sqlalchemy import func, select

    consulta = (
        select(
            Appearance.player_id,
            Appearance.position_group,
            func.sum(Appearance.minutes_played),
        )
        .join(Match, Match.id == Appearance.match_id)
        .join(Season, Season.id == Match.season_id)
        .join(Competition, Competition.id == Season.competition_id)
        .group_by(Appearance.player_id, Appearance.position_group)
    )
    for condicao in appearance_conditions(recorte):
        consulta = consulta.where(condicao)
    return consulta
