"""Teste de ponta a ponta da ligação com o Transfermarkt, sobre a Copa América 2024.

Usa o cache local do transfermarkt-datasets e é pulado se ele não existir: são ~190 MB,
que o teste não deve baixar sozinho. Para preparar o cache, rode `fscout transfermarkt`
uma vez.

As asserções usam fatos verificáveis (data de nascimento do Messi, dupla nacionalidade
de Jonathan Bell) e propriedades estruturais (todas as partidas ligadas, reexecução sem
duplicar), não números copiados da própria implementação.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fscout.config import get_settings
from fscout.db.models import Country, ExternalId, Player, PlayerNationality, PlayerValuation
from fscout.db.session import build_engine
from fscout.domain.enums import Foot
from fscout.ingestion.download import SourceUnavailableError
from fscout.ingestion.pipeline import ingest_season
from fscout.ingestion.transfermarkt.pipeline import TransfermarktReport, enrich_from_transfermarkt

pytestmark = pytest.mark.integration

COPA_AMERICA, SEASON_2024 = 223, 282
REQUIRED_TABLES = ("games", "game_lineups", "players", "player_valuations")


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    cache = get_settings().resolved_raw_dir / "transfermarkt"
    missing = [table for table in REQUIRED_TABLES if not (cache / f"{table}.csv.gz").exists()]
    if missing:
        pytest.skip(f"cache do Transfermarkt ausente ({', '.join(missing)})")

    engine = build_engine(f"sqlite:///{tmp_path_factory.mktemp('tm') / 'copa.db'}")
    try:
        ingest_season(COPA_AMERICA, SEASON_2024, engine=engine)
    except SourceUnavailableError as exc:
        pytest.skip(f"StatsBomb Open Data indisponível: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def report(engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> TransfermarktReport:
    review = tmp_path_factory.mktemp("revisao") / "revisao.csv"
    return enrich_from_transfermarkt(engine=engine, review_path=review)


@pytest.fixture
def session(engine: Engine, report: TransfermarktReport) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def _player(session: Session, name: str) -> Player:
    return session.scalars(select(Player).where(Player.name == name)).one()


def test_todas_as_partidas_e_selecoes_ligadas(report: TransfermarktReport) -> None:
    assert report.linking.matches_linked == report.linking.matches_total == 32
    assert report.linking.teams_linked == 16


def test_atletas_ligados_pela_escalacao(report: TransfermarktReport) -> None:
    linking = report.linking
    assert linking.players_by_lineup == linking.players_total
    assert linking.review == []


def test_metodo_por_nome_medido_contra_a_escalacao(report: TransfermarktReport) -> None:
    precision = report.linking.fallback_precision
    assert precision is not None and precision >= 0.95


def test_biografia_do_messi(session: Session) -> None:
    messi = _player(session, "Lionel Messi")
    assert messi.birth_date == date(1987, 6, 24)
    assert messi.height_cm == 170
    assert messi.preferred_foot is Foot.LEFT
    assert session.scalar(
        select(func.count())
        .select_from(PlayerValuation)
        .where(PlayerValuation.player_id == messi.id)
    )


def test_dupla_nacionalidade_sem_duplicar_pais(session: Session) -> None:
    """Jonathan Bell defende a Jamaica e tem cidadania americana.

    A StatsBomb escreve "United States of America" e o Transfermarkt, "United States":
    as duas grafias precisam cair no mesmo país.
    """
    bell = _player(session, "Jonathan Bell")
    countries = set(
        session.scalars(
            select(Country.name)
            .join(PlayerNationality, PlayerNationality.country_id == Country.id)
            .where(PlayerNationality.player_id == bell.id)
        )
    )
    assert len(countries) == 2
    assert "Jamaica" in countries
    united_states = session.scalar(
        select(func.count()).select_from(Country).where(Country.name.like("United States%"))
    )
    assert united_states == 1


def test_reexecucao_nao_duplica(
    engine: Engine, report: TransfermarktReport, tmp_path_factory
) -> None:
    def counts() -> tuple[int, int, int]:
        with Session(engine) as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(ExternalId)
                    .where(ExternalId.source == "transfermarkt")
                )
                or 0,
                session.scalar(select(func.count()).select_from(PlayerValuation)) or 0,
                session.scalar(select(func.count()).select_from(PlayerNationality)) or 0,
            )

    before = counts()
    enrich_from_transfermarkt(
        engine=engine, review_path=tmp_path_factory.mktemp("revisao2") / "revisao.csv"
    )
    assert counts() == before
