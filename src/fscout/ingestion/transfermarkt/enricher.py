"""Biografia e mercado vindos do Transfermarkt, aplicados aos atletas ligados.

Precedência por campo: data de nascimento, altura, pé preferencial e país de nascimento
não são informados por nenhuma fonte de eventos, então o Transfermarkt é o dono desses
campos e os sobrescreve. Nacionalidade é acrescentada, nunca substituída, porque a
StatsBomb já registra a seleção que o atleta defende.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from fscout.db.models import Player, PlayerNationality, PlayerValuation
from fscout.domain.enums import Foot
from fscout.ingestion.transfermarkt.client import TransfermarktClient
from fscout.linking.countries import CountryResolver

SOURCE = "transfermarkt"
IN_CLAUSE_CHUNK = 500

FOOT: Mapping[str, Foot] = {"left": Foot.LEFT, "right": Foot.RIGHT, "both": Foot.BOTH}


@dataclass
class EnrichmentReport:
    players: int = 0
    birth_date: int = 0
    height: int = 0
    foot: int = 0
    birth_country: int = 0
    nationalities_added: int = 0
    valuations: int = 0
    contracts: int = 0


def enrich_players(
    session: Session,
    client: TransfermarktClient,
    tm_by_player: Mapping[int, int],
    countries: CountryResolver,
) -> EnrichmentReport:
    """Preenche biografia, nacionalidade e série de valor de mercado dos atletas ligados."""
    report = EnrichmentReport(players=len(tm_by_player))
    if not tm_by_player:
        return report

    wanted = set(tm_by_player.values())
    profiles = client.read(
        "players",
        usecols=[
            "player_id",
            "date_of_birth",
            "height_in_cm",
            "foot",
            "country_of_citizenship",
            "country_of_birth",
            "contract_expiration_date",
        ],
        parse_dates=["date_of_birth", "contract_expiration_date"],
    )
    profiles = profiles[profiles.player_id.isin(wanted)].set_index("player_id")

    contracts: dict[int, date] = {}
    for player_id, tm_id in tm_by_player.items():
        if tm_id not in profiles.index:
            continue
        profile = profiles.loc[tm_id]
        player = session.get(Player, player_id)
        if player is None:
            continue

        player.birth_date = _date(profile.date_of_birth)
        player.height_cm = _int(profile.height_in_cm)
        player.preferred_foot = FOOT.get(str(profile.foot))
        player.birth_country_id = countries.resolve(_text(profile.country_of_birth))
        report.birth_date += player.birth_date is not None
        report.height += player.height_cm is not None
        report.foot += player.preferred_foot is not None
        report.birth_country += player.birth_country_id is not None

        citizenship = countries.resolve(_text(profile.country_of_citizenship))
        if citizenship is not None:
            report.nationalities_added += _ensure_nationality(session, player_id, citizenship)

        contract = _date(profile.contract_expiration_date)
        if contract is not None:
            contracts[player_id] = contract

    report.valuations, report.contracts = _replace_valuations(
        session, client, tm_by_player, contracts
    )
    session.flush()
    return report


def _replace_valuations(
    session: Session,
    client: TransfermarktClient,
    tm_by_player: Mapping[int, int],
    contracts: Mapping[int, date],
) -> tuple[int, int]:
    """Substitui a série de valor de mercado vinda do Transfermarkt.

    O fim de contrato só existe como valor corrente, então é anotado no registro de
    valorização mais recente de cada atleta.
    """
    player_ids = sorted(tm_by_player)
    for start in range(0, len(player_ids), IN_CLAUSE_CHUNK):
        session.execute(
            delete(PlayerValuation).where(
                PlayerValuation.player_id.in_(player_ids[start : start + IN_CLAUSE_CHUNK]),
                PlayerValuation.source == SOURCE,
            )
        )

    player_by_tm = {tm_id: player_id for player_id, tm_id in tm_by_player.items()}
    history = client.read(
        "player_valuations",
        usecols=["player_id", "date", "market_value_in_eur"],
        parse_dates=["date"],
    )
    history = history[history.player_id.isin(player_by_tm)].sort_values(["player_id", "date"])
    if history.empty:
        return 0, 0

    latest_index = set(history.groupby("player_id").tail(1).index)
    rows: list[dict[str, Any]] = []
    for index, row in zip(history.index, history.itertuples(), strict=True):
        player_id = player_by_tm[row.player_id]
        rows.append(
            {
                "player_id": player_id,
                "valuation_date": row.date.date(),
                "market_value": float(row.market_value_in_eur),
                "currency": "EUR",
                "contract_until": contracts.get(player_id) if index in latest_index else None,
                "source": SOURCE,
            }
        )
    session.execute(insert(PlayerValuation), rows)
    return len(rows), sum(1 for row in rows if row["contract_until"] is not None)


def _ensure_nationality(session: Session, player_id: int, country_id: int) -> int:
    existing = set(
        session.scalars(
            select(PlayerNationality.country_id).where(PlayerNationality.player_id == player_id)
        )
    )
    if country_id in existing:
        return 0
    session.add(
        PlayerNationality(player_id=player_id, country_id=country_id, is_primary=not existing)
    )
    return 1


def _date(value: Any) -> date | None:
    return None if pd.isna(value) else pd.Timestamp(value).date()


def _int(value: Any) -> int | None:
    return None if pd.isna(value) else int(value)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
