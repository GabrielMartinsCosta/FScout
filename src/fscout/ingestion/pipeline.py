"""Orquestração da ingestão StatsBomb: da temporada escolhida ao banco carregado."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fscout.db.models import IngestionRun, Match
from fscout.db.session import create_all, get_engine
from fscout.ingestion.loader import Loader, refresh_player_profiles, refresh_season_dates
from fscout.ingestion.statsbomb.client import StatsBombClient
from fscout.ingestion.statsbomb.mapper import (
    SOURCE,
    build_match_bundle,
    competition_row,
    season_row,
)
from fscout.ingestion.statsbomb.vocab import Vocabulary

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class IngestionReport:
    competition: str
    season: str
    matches_selected: int
    matches_loaded: int = 0
    matches_skipped: int = 0
    events_loaded: int = 0
    goal_mismatches: list[str] = field(default_factory=list)
    unmapped_values: Counter[tuple[str, str]] = field(default_factory=Counter)


def ingest_season(
    competition_id: int,
    season_id: int,
    *,
    limit: int | None = None,
    match_ids: Iterable[int] | None = None,
    refresh: bool = False,
    client: StatsBombClient | None = None,
    engine: Engine | None = None,
    progress: ProgressCallback | None = None,
) -> IngestionReport:
    """Carrega partidas de uma temporada da StatsBomb.

    Partidas já presentes no banco são puladas, a menos que `refresh` seja verdadeiro. Cada
    partida é confirmada numa transação própria: uma falha interrompe a carga, mas preserva
    as partidas já concluídas, e a próxima execução retoma de onde parou.
    """
    engine = engine or get_engine()
    create_all(engine)
    owns_client = client is None
    client = client or StatsBombClient()

    try:
        record = _find_season(client.competitions(), competition_id, season_id)
        matches = sorted(
            client.matches(competition_id, season_id),
            key=lambda match: (match["match_date"], match["match_id"]),
        )
        if match_ids is not None:
            wanted = set(match_ids)
            matches = [match for match in matches if match["match_id"] in wanted]
        if limit is not None:
            matches = matches[:limit]

        report = IngestionReport(
            competition=record["competition_name"],
            season=record["season_name"],
            matches_selected=len(matches),
        )
        with Session(engine) as session:
            _run(session, client, record, matches, refresh, report, progress)
        return report
    finally:
        if owns_client:
            client.close()


def _run(
    session: Session,
    client: StatsBombClient,
    record: dict[str, Any],
    matches: list[dict[str, Any]],
    refresh: bool,
    report: IngestionReport,
    progress: ProgressCallback | None,
) -> None:
    vocab = Vocabulary()
    run = IngestionRun(
        source=SOURCE,
        scope=f"{record['competition_id']}/{record['season_id']} "
        f"{record['competition_name']} {record['season_name']}",
    )
    session.add(run)
    session.commit()

    try:
        loader = Loader(session, SOURCE)
        competition_db_id = loader.load_competition(competition_row(record))
        season_db_id = loader.load_season(season_row(record), competition_db_id)
        session.commit()

        already_loaded = (
            set()
            if refresh
            else loader.existing_ids(Match, (str(match["match_id"]) for match in matches))
        )
        pending = [match for match in matches if str(match["match_id"]) not in already_loaded]
        report.matches_skipped = len(matches) - len(pending)
        client.prefetch_matches(match["match_id"] for match in pending)

        touched_players: set[int] = set()
        for position, match in enumerate(pending, start=1):
            label = (
                f"{match['home_team']['home_team_name']} x {match['away_team']['away_team_name']}"
            )
            if progress is not None:
                progress(position, len(pending), label)

            bundle = build_match_bundle(
                match,
                client.events(match["match_id"]),
                client.lineups(match["match_id"]),
                is_international=bool(record.get("competition_international")),
                vocab=vocab,
            )
            result = loader.replace_match(bundle, season_db_id)
            touched_players |= result.player_ids

            if not bundle.goal_check.ok:
                expected, found = bundle.goal_check.expected, bundle.goal_check.from_events
                message = f"{match['match_id']} {label}: placar {expected}, eventos {found}"
                report.goal_mismatches.append(message)
                logger.warning("Placar não confere: %s", message)

            run.matches_ingested += 1
            run.events_ingested += result.events
            session.commit()
            report.matches_loaded += 1
            report.events_loaded += result.events

        refresh_season_dates(session, season_db_id)
        refresh_player_profiles(session, touched_players)
        run.status = "finished"
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report.unmapped_values = vocab.misses
        run.warnings = _warnings_summary(report) or None
        run.finished_at = datetime.now()
        session.commit()


def _find_season(
    records: list[dict[str, Any]], competition_id: int, season_id: int
) -> dict[str, Any]:
    for record in records:
        if record["competition_id"] == competition_id and record["season_id"] == season_id:
            return record
    raise LookupError(
        f"Temporada {competition_id}/{season_id} não existe na StatsBomb Open Data. "
        "Use `fscout competitions` para ver as disponíveis."
    )


def _warnings_summary(report: IngestionReport) -> str:
    lines = [f"placar divergente: {message}" for message in report.goal_mismatches]
    lines += [
        f"valor não mapeado: {field_name}={value!r} ({count}x)"
        for (field_name, value), count in report.unmapped_values.most_common()
    ]
    return "\n".join(lines)
