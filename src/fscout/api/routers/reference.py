"""Competições, temporadas e equipes: o que preenche os filtros da interface."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from fscout.api.deps import SessionDep
from fscout.api.schemas import CompetitionOut, SeasonOut, TeamOut
from fscout.db.models import Appearance, Competition, Country, Match, Season, Team

router = APIRouter(tags=["referências"])


@router.get("/competitions", summary="Competições carregadas, com suas temporadas")
def list_competitions(session: SessionDep) -> list[CompetitionOut]:
    partidas_por_temporada = dict(
        session.execute(select(Match.season_id, func.count()).group_by(Match.season_id)).all()
    )
    temporadas: dict[int, list[SeasonOut]] = {}
    for season in session.scalars(select(Season).order_by(Season.name)):
        temporadas.setdefault(season.competition_id, []).append(
            SeasonOut(
                id=season.id,
                name=season.name,
                start_date=season.start_date,
                end_date=season.end_date,
                matches=partidas_por_temporada.get(season.id, 0),
            )
        )

    saida: list[CompetitionOut] = []
    for competition, country in session.execute(
        select(Competition, Country.name)
        .outerjoin(Country, Country.id == Competition.country_id)
        .order_by(Competition.name)
    ):
        saida.append(
            CompetitionOut(
                id=competition.id,
                name=competition.name,
                type=competition.type,
                country=country,
                seasons=temporadas.get(competition.id, []),
            )
        )
    return saida


@router.get("/teams", summary="Equipes, opcionalmente as de uma competição")
def list_teams(session: SessionDep, competition_id: int | None = None) -> list[TeamOut]:
    consulta = (
        select(Team, Country.name).outerjoin(Country, Country.id == Team.country_id).distinct()
    )
    if competition_id is not None:
        consulta = (
            consulta.join(Appearance, Appearance.team_id == Team.id)
            .join(Match, Match.id == Appearance.match_id)
            .join(Season, Season.id == Match.season_id)
            .where(Season.competition_id == competition_id)
        )
    return [
        TeamOut(
            id=team.id,
            name=team.name,
            country=country,
            is_national_team=team.is_national_team,
        )
        for team, country in session.execute(consulta.order_by(Team.name))
    ]
