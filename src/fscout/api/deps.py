"""Dependências compartilhadas pelos roteadores."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from fscout.db.session import get_session_factory
from fscout.domain.enums import CompetitionType, DataTier, HomeAway, PositionGroup
from fscout.metrics.context import Slice


def get_session() -> Iterator[Session]:
    """Sessão por requisição. Nos testes, é substituída por `dependency_overrides`."""
    with get_session_factory()() as session:
        yield session


def slice_from_query(
    competition_ids: Annotated[list[int] | None, Query()] = None,
    season_ids: Annotated[list[int] | None, Query()] = None,
    competition_types: Annotated[list[CompetitionType] | None, Query()] = None,
    team_ids: Annotated[list[int] | None, Query()] = None,
    opponent_team_ids: Annotated[list[int] | None, Query()] = None,
    position_groups: Annotated[list[PositionGroup] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    home_away: HomeAway | None = None,
    min_minutes: int | None = None,
    label: str | None = None,
    data_tier: DataTier = DataTier.EVENT,
) -> Slice:
    """Monta o recorte a partir dos parâmetros de consulta.

    Todos os endpoints de leitura aceitam o mesmo conjunto, para que "gols em junho" e
    "gols contra o Real Madrid" sejam a mesma chamada com argumentos diferentes.
    """
    return Slice(
        competition_ids=tuple(competition_ids or ()),
        season_ids=tuple(season_ids or ()),
        competition_types=tuple(competition_types or ()),
        team_ids=tuple(team_ids or ()),
        opponent_team_ids=tuple(opponent_team_ids or ()),
        position_groups=tuple(position_groups or ()),
        date_from=date_from,
        date_to=date_to,
        home_away=home_away,
        min_minutes=min_minutes,
        label=label,
        data_tier=data_tier,
    )


SessionDep = Annotated[Session, Depends(get_session)]
SliceDep = Annotated[Slice, Depends(slice_from_query)]
