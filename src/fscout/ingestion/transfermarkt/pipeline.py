"""Orquestração do enriquecimento pelo Transfermarkt: ligar, preencher, reportar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fscout.config import get_settings
from fscout.db.models import IngestionRun, Player
from fscout.db.session import create_all, get_engine
from fscout.ingestion.transfermarkt.client import TransfermarktClient
from fscout.ingestion.transfermarkt.enricher import EnrichmentReport, enrich_players
from fscout.ingestion.transfermarkt.linker import SOURCE, LinkReport, link_transfermarkt
from fscout.linking.countries import CountryResolver

REVIEW_FILENAME = "revisao_ligacao_transfermarkt.csv"


@dataclass(frozen=True)
class TransfermarktReport:
    linking: LinkReport
    enrichment: EnrichmentReport
    review_path: Path


def enrich_from_transfermarkt(
    *,
    engine: Engine | None = None,
    client: TransfermarktClient | None = None,
    review_path: Path | None = None,
) -> TransfermarktReport:
    """Liga os atletas carregados ao Transfermarkt e preenche biografia e valor de mercado.

    Tudo numa transação: se a ligação ou o preenchimento falhar, o banco fica como estava.
    Os casos que as regras não decidiram vão para um CSV de revisão manual.
    """
    engine = engine or get_engine()
    create_all(engine)
    owns_client = client is None
    client = client or TransfermarktClient()

    try:
        with Session(engine) as session:
            run = IngestionRun(source=SOURCE, scope="ligação StatsBomb x Transfermarkt e biografia")
            session.add(run)
            session.commit()
            try:
                linking, tm_by_player = link_transfermarkt(session, client)
                enrichment = enrich_players(session, client, tm_by_player, CountryResolver(session))
                run.matches_ingested = linking.matches_linked
                run.status = "finished"
                review = _review_frame(session, linking)
            except Exception as exc:
                session.rollback()
                run.status = "failed"
                run.error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                run.finished_at = datetime.now()
                session.commit()
    finally:
        if owns_client:
            client.close()

    path = review_path or get_settings().processed_dir / REVIEW_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(path, index=False, encoding="utf-8-sig")
    return TransfermarktReport(linking=linking, enrichment=enrichment, review_path=path)


def _review_frame(session: Session, linking: LinkReport) -> pd.DataFrame:
    """Casos de revisão com o nome do atleta, para a conferência não exigir consulta ao banco."""
    frame = pd.DataFrame(
        linking.review,
        columns=["player_id", "motivo", "transfermarkt_player_id", "confianca"],
    )
    if frame.empty:
        return frame
    names = {
        player.id: player.full_name or player.name
        for player in session.query(Player).filter(Player.id.in_(frame.player_id.tolist()))
    }
    frame.insert(1, "atleta", frame.player_id.map(names))
    return frame.sort_values(["motivo", "atleta"])
