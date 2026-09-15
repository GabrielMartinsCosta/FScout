"""Acesso às tabelas do transfermarkt-datasets, com cache em disco.

O dataset é publicado como CSVs comprimidos, um por tabela, e é substituído por inteiro a
cada atualização. Diferente da StatsBomb, não há arquivo por partida: a unidade de cache é
a tabela. Para buscar uma versão nova, basta apagar o arquivo correspondente do cache.

A atualização automática do dataset está pausada desde julho de 2026 (ver
`docs/FONTES.md`), o que torna o cache, na prática, uma cópia estável.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import pandas as pd

from fscout.config import Settings, get_settings
from fscout.ingestion.download import download_to_cache

logger = logging.getLogger(__name__)

TABLES = frozenset(
    {
        "appearances",
        "clubs",
        "competitions",
        "countries",
        "game_lineups",
        "games",
        "national_teams",
        "player_valuations",
        "players",
        "transfers",
    }
)


class TransfermarktClient:
    """Baixa sob demanda e lê as tabelas do dataset como DataFrames."""

    def __init__(self, settings: Settings | None = None, http: httpx.Client | None = None) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.transfermarkt_base_url.rstrip("/")
        self._cache_dir = self._settings.resolved_raw_dir / "transfermarkt"
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=self._settings.http_timeout_seconds, follow_redirects=True
        )

    def __enter__(self) -> TransfermarktClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def path(self, table: str) -> Path:
        """Caminho local da tabela, baixando-a se ainda não estiver em cache."""
        if table not in TABLES:
            raise ValueError(f"Tabela desconhecida no transfermarkt-datasets: {table!r}")
        path = self._cache_dir / f"{table}.csv.gz"
        if not path.exists():
            logger.info("Baixando %s do transfermarkt-datasets", table)
            download_to_cache(
                self._http,
                f"{self._base_url}/{table}.csv.gz",
                path,
                attempts=self._settings.http_max_retries,
            )
        return path

    def read(self, table: str, **read_csv_options: Any) -> pd.DataFrame:
        """Lê a tabela inteira. Use `usecols` para tabelas grandes como `appearances`."""
        return pd.read_csv(self.path(table), low_memory=False, **read_csv_options)
