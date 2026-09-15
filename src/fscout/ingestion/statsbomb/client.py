"""Acesso ao repositório StatsBomb Open Data, com cache em disco."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from fscout.config import Settings, get_settings
from fscout.ingestion.download import download_to_cache

logger = logging.getLogger(__name__)


class StatsBombClient:
    """Lê os JSON do open-data, baixando só o que ainda não está em cache.

    O cache espelha a estrutura do repositório (`competitions.json`,
    `matches/<competição>/<temporada>.json`, `events/<partida>.json`,
    `lineups/<partida>.json`). Arquivo de partida nunca é rebaixado: dado de jogo
    encerrado não muda, e a ingestão vai ser executada dezenas de vezes durante o
    desenvolvimento sem poder depender da rede a cada execução.

    Os índices (`competitions.json` e listas de partidas) são a exceção lógica — mudam
    quando a StatsBomb publica dados novos. Para atualizá-los, basta apagar o arquivo
    do cache.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http: httpx.Client | None = None,
        max_workers: int = 8,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.statsbomb_base_url.rstrip("/")
        self._cache_dir = self._settings.resolved_raw_dir / "statsbomb"
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=self._settings.http_timeout_seconds, follow_redirects=True
        )
        self._max_workers = max_workers

    def __enter__(self) -> StatsBombClient:
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

    # ------------------------------------------------------------------------------------
    # Recursos
    # ------------------------------------------------------------------------------------

    def competitions(self) -> list[dict[str, Any]]:
        return self._read("competitions.json")

    def matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        return self._read(f"matches/{competition_id}/{season_id}.json")

    def events(self, match_id: int) -> list[dict[str, Any]]:
        return self._read(f"events/{match_id}.json")

    def lineups(self, match_id: int) -> list[dict[str, Any]]:
        return self._read(f"lineups/{match_id}.json")

    def prefetch_matches(self, match_ids: Iterable[int]) -> int:
        """Baixa em paralelo eventos e escalações ausentes do cache.

        Download é limitado por rede, não por CPU, então threads bastam. Separar o
        download da carga também isola as falhas: um erro de rede aparece antes de
        qualquer escrita no banco. Devolve quantos arquivos foram baixados.
        """
        missing = [
            relative
            for match_id in match_ids
            for relative in (f"events/{match_id}.json", f"lineups/{match_id}.json")
            if not self._cache_path(relative).exists()
        ]
        if missing:
            logger.info("Baixando %d arquivos da StatsBomb Open Data", len(missing))
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                list(pool.map(self._download, missing))
        return len(missing)

    # ------------------------------------------------------------------------------------
    # Cache e rede
    # ------------------------------------------------------------------------------------

    def _cache_path(self, relative: str) -> Path:
        return self._cache_dir / relative

    def _read(self, relative: str) -> Any:
        path = self._cache_path(relative)
        if not path.exists():
            self._download(relative)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _download(self, relative: str) -> None:
        download_to_cache(
            self._http,
            f"{self._base_url}/{relative}",
            self._cache_path(relative),
            attempts=self._settings.http_max_retries,
        )
