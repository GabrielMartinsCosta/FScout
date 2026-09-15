"""Teste de ponta a ponta com a final da Copa do Mundo de 2022.

Argentina 3 x 3 França, com prorrogação e disputa de pênaltis. É a partida escolhida
porque concentra os casos difíceis: acréscimos longos, gols de pênalti, disputa de
pênaltis que não pode virar gol, campo neutro, cartão sem localização.

As asserções usam fatos públicos e verificáveis da partida — Messi 2 gols (um de
pênalti), Mbappé 3 gols (dois de pênalti), Di María 1 gol —, não valores copiados da
própria implementação.

Baixa cerca de 4 MB na primeira execução e usa o cache local nas seguintes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fscout.db.models import (
    Appearance,
    DisciplinaryAction,
    Event,
    ExternalId,
    Match,
    Pass,
    Player,
    Shot,
)
from fscout.db.session import build_engine
from fscout.domain.enums import ShotType, Venue
from fscout.ingestion.pipeline import IngestionReport, ingest_season
from fscout.ingestion.statsbomb.client import SourceUnavailableError

pytestmark = pytest.mark.integration

WORLD_CUP, SEASON_2022, FINAL = 43, 106, 3869685


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    path: Path = tmp_path_factory.mktemp("fscout") / "final.db"
    engine = build_engine(f"sqlite:///{path}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def report(engine: Engine) -> IngestionReport:
    try:
        return ingest_season(WORLD_CUP, SEASON_2022, match_ids=[FINAL], engine=engine)
    except SourceUnavailableError as exc:
        pytest.skip(f"StatsBomb Open Data indisponível: {exc}")


@pytest.fixture
def session(engine: Engine, report: IngestionReport) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def _player(session: Session, fragment: str) -> int:
    return session.scalars(select(Player.id).where(Player.full_name.like(f"%{fragment}%"))).one()


def _goals(session: Session, player_id: int, shot_type: ShotType | None = None) -> int:
    query = (
        select(func.count())
        .select_from(Shot)
        .where(Shot.player_id == player_id, Shot.is_goal.is_(True), Shot.is_shootout.is_(False))
    )
    if shot_type is not None:
        query = query.where(Shot.shot_type == shot_type)
    return session.scalar(query) or 0


def test_carga_sem_divergencias(report: IngestionReport) -> None:
    assert report.matches_loaded == 1
    assert report.events_loaded == 4407
    assert report.goal_mismatches == []
    assert not report.unmapped_values, report.unmapped_values


def test_placar_e_campo_neutro(session: Session) -> None:
    match = session.scalars(select(Match)).one()
    assert (match.home_score, match.away_score) == (3, 3)
    assert match.is_neutral_venue
    venues = set(session.scalars(select(Appearance.venue)))
    assert venues == {Venue.NEUTRAL}


def test_gols_por_jogador(session: Session) -> None:
    messi = _player(session, "Messi")
    mbappe = _player(session, "Mbappé")
    di_maria = _player(session, "Di María")

    assert _goals(session, messi) == 2
    assert _goals(session, messi, ShotType.PENALTY) == 1
    assert _goals(session, mbappe) == 3
    assert _goals(session, mbappe, ShotType.PENALTY) == 2
    assert _goals(session, di_maria) == 1


def test_disputa_de_penaltis_nao_vira_gol(session: Session) -> None:
    shootout = session.scalar(select(func.count()).select_from(Shot).where(Shot.is_shootout))
    regular_goals = session.scalar(
        select(func.count()).select_from(Shot).where(Shot.is_goal, Shot.is_shootout.is_(False))
    )
    assert shootout == 8
    assert regular_goals == 6


def test_assistencia_e_pre_assistencia_coerentes(session: Session) -> None:
    assert session.scalar(select(func.count()).select_from(Pass).where(Pass.is_goal_assist)) >= 1

    assisters = set(session.scalars(select(Pass.player_id).where(Pass.is_goal_assist)))
    pre_assist_recipients = set(
        session.scalars(select(Pass.recipient_player_id).where(Pass.is_pre_assist))
    )
    assert pre_assist_recipients
    assert pre_assist_recipients <= assisters


def test_minutagem(session: Session) -> None:
    messi = _player(session, "Messi")
    appearance = session.scalars(select(Appearance).where(Appearance.player_id == messi)).one()
    assert appearance.is_starter
    assert appearance.minutes_played == 120
    # Tempo efetivo inclui cerca de 21 minutos de acréscimos somados nos quatro períodos.
    assert appearance.seconds_on_pitch > 140 * 60

    full_match = session.scalars(
        select(Appearance.minutes_played).where(
            Appearance.is_starter, Appearance.minute_off.is_(None)
        )
    ).all()
    assert full_match and set(full_match) == {120}


def test_cartoes(session: Session) -> None:
    cards = session.scalar(
        select(func.count())
        .select_from(DisciplinaryAction)
        .where(DisciplinaryAction.card.is_not(None))
    )
    assert cards == 8


def test_identidade_registrada_por_fonte(session: Session) -> None:
    messi = _player(session, "Messi")
    link = session.scalars(
        select(ExternalId).where(ExternalId.entity == "players", ExternalId.entity_id == messi)
    ).one()
    assert (link.source, link.source_id, link.matched_by) == ("statsbomb", "5503", "created")


def test_recarga_e_idempotente(engine: Engine, report: IngestionReport) -> None:
    def counts() -> tuple[int, int, int, int]:
        with Session(engine) as session:
            return tuple(  # type: ignore[return-value]
                session.scalar(select(func.count()).select_from(model)) or 0
                for model in (Match, Player, Event, Shot)
            )

    before = counts()

    skipped = ingest_season(WORLD_CUP, SEASON_2022, match_ids=[FINAL], engine=engine)
    assert (skipped.matches_loaded, skipped.matches_skipped) == (0, 1)

    reloaded = ingest_season(WORLD_CUP, SEASON_2022, match_ids=[FINAL], refresh=True, engine=engine)
    assert reloaded.matches_loaded == 1
    assert counts() == before
