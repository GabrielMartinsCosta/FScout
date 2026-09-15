"""Geocodificação de estádios pelo Nominatim (OpenStreetMap).

Nenhuma das fontes de partidas informa a coordenada do estádio, e sem ela não há como
buscar o clima. O Nominatim é gratuito, mas a política de uso exige identificação no
User-Agent e no máximo uma requisição por segundo — respeitadas aqui. Como os estádios
são poucos (dezenas) e o resultado vai para o banco, cada um é consultado uma vez só.

Dados © colaboradores do OpenStreetMap, licença ODbL.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "FScout-TCC/0.1 (projeto academico de analise de futebol)"
MIN_INTERVAL_S = 1.1
RESULTS_PER_QUERY = 5


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    display_name: str
    osm_type: str | None
    osm_id: int | None
    query: str
    is_stadium: bool


class NominatimGeocoder:
    """Busca a coordenada de um estádio, preferindo resultados marcados como estádio."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def __enter__(self) -> NominatimGeocoder:
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

    def geocode_stadium(self, stadium: str, country: str | None) -> GeocodeResult | None:
        """Tenta "estádio, país" e depois só o nome do estádio.

        Entre os resultados de uma consulta, um marcado como estádio vence a ordem de
        relevância do Nominatim: "Hard Rock Stadium" também devolve ruas e pontos de ônibus.
        """
        queries = [f"{stadium}, {country}", stadium] if country else [stadium]
        for query in queries:
            results = self._search(query)
            if not results:
                continue
            stadiums = [item for item in results if _is_stadium(item)]
            chosen = stadiums[0] if stadiums else results[0]
            return GeocodeResult(
                latitude=float(chosen["lat"]),
                longitude=float(chosen["lon"]),
                display_name=str(chosen.get("display_name", "")),
                osm_type=chosen.get("osm_type"),
                osm_id=_as_int(chosen.get("osm_id")),
                query=query,
                is_stadium=bool(stadiums),
            )
        return None

    def _search(self, query: str) -> list[dict[str, Any]]:
        self._respect_rate_limit()
        response = self._http.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "limit": RESULTS_PER_QUERY},
        )
        response.raise_for_status()
        return list(response.json())

    def _respect_rate_limit(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = MIN_INTERVAL_S - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request = now


def _is_stadium(item: dict[str, Any]) -> bool:
    return item.get("type") == "stadium" or (
        item.get("category") == "leisure" and "stadium" in str(item.get("type", ""))
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
