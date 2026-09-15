"""Acesso ao repositório StatsBomb Open Data, com cache em disco."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from fscout.config import PROJECT_ROOT, Settings, get_settings

logger = logging.getLogger(__name__)


class SourceUnavailableError(RuntimeError):
    """A fonte não respondeu depois de todas as tentativas."""


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
        raw_dir = Path(self._settings.raw_dir)
        if not raw_dir.is_absolute():
            raw_dir = PROJECT_ROOT / raw_dir
        self._cache_dir = raw_dir / "statsbomb"
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
        url = f"{self._base_url}/{relative}"
        attempts = self._settings.http_max_retries
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._http.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise FileNotFoundError(f"Recurso inexistente na StatsBomb: {url}") from exc
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            else:
                self._write_atomically(self._cache_path(relative), response.content)
                return

            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))

        raise SourceUnavailableError(f"Falha ao baixar {url}: {last_error}") from last_error

    @staticmethod
    def _write_atomically(path: Path, content: bytes) -> None:
        """Grava em arquivo temporário e renomeia: download interrompido nunca vira cache."""
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        partial.write_bytes(content)
        partial.replace(path)
