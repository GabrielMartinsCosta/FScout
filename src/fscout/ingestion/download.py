"""Download de arquivos para o cache local, comum a todas as fontes."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHUNK_BYTES = 1 << 20


class SourceUnavailableError(RuntimeError):
    """A fonte não respondeu depois de todas as tentativas."""


def download_to_cache(http: httpx.Client, url: str, path: Path, *, attempts: int) -> None:
    """Baixa `url` para `path` com novas tentativas e escrita atômica.

    O conteúdo é gravado por partes num arquivo `.part` e só então renomeado, então um
    download interrompido nunca vira cache válido — nem para arquivos de dezenas de MB.
    Recurso inexistente (404) falha na hora: repetir não muda a resposta.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with http.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        handle.write(chunk)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise FileNotFoundError(f"Recurso inexistente: {url}") from exc
            last_error = exc
        except httpx.TransportError as exc:
            last_error = exc
        else:
            partial.replace(path)
            return

        logger.debug("Tentativa %d de %d falhou para %s: %s", attempt, attempts, url, last_error)
        if attempt < attempts:
            time.sleep(2 ** (attempt - 1))

    partial.unlink(missing_ok=True)
    raise SourceUnavailableError(f"Falha ao baixar {url}: {last_error}") from last_error
