"""Clima histórico por coordenada e hora, via Open-Meteo.

A API de arquivo do Open-Meteo entrega reanálise meteorológica (ERA5) hora a hora, sem
chave, gratuita para uso não comercial. Uma requisição cobre um intervalo de datas, então
um estádio com dez partidas custa uma consulta, não dez. As respostas ficam em cache em
disco: o clima de 2022 não muda.

A série é pedida em UTC, o mesmo fuso do horário de início das partidas na StatsBomb.
Pedir no fuso local exigiria converter o horário do jogo e tratar horário de verão, que
muda no meio de uma temporada europeia.

Dados sob licença CC BY 4.0, com atribuição ao Open-Meteo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from fscout.config import Settings, get_settings

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "GMT"
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
)

Reading = dict[str, float | None]


@dataclass(frozen=True)
class HourlyWeather:
    """Série horária em UTC, horários sem fuso explícito."""

    times: tuple[datetime, ...]
    values: dict[str, tuple[float | None, ...]]

    def readings_between(self, start: datetime, end: datetime) -> list[Reading]:
        """Leituras de hora cheia no intervalo fechado [start, end], em ordem."""
        return [
            {name: series[index] for name, series in self.values.items()}
            for index, moment in enumerate(self.times)
            if start <= moment <= end
        ]


class OpenMeteoClient:
    def __init__(self, settings: Settings | None = None, http: httpx.Client | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache_dir = self._settings.resolved_raw_dir / "openmeteo"
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=self._settings.http_timeout_seconds)

    def __enter__(self) -> OpenMeteoClient:
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

    def hourly(self, latitude: float, longitude: float, start: date, end: date) -> HourlyWeather:
        """Série horária em UTC entre `start` e `end`, inclusive."""
        path = self._cache_path(latitude, longitude, start, end)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            response = self._http.get(
                ARCHIVE_URL,
                params={
                    "latitude": round(latitude, 4),
                    "longitude": round(longitude, 4),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "timezone": TIMEZONE,
                },
            )
            response.raise_for_status()
            payload = response.json()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        return parse_hourly(payload)

    def _cache_path(self, latitude: float, longitude: float, start: date, end: date) -> Path:
        name = f"{latitude:.4f}_{longitude:.4f}_{start.isoformat()}_{end.isoformat()}.json"
        return self._cache_dir / name


def parse_hourly(payload: dict[str, Any]) -> HourlyWeather:
    hourly = payload.get("hourly") or {}
    return HourlyWeather(
        times=tuple(datetime.fromisoformat(value) for value in hourly.get("time", [])),
        values={
            name: tuple(None if value is None else float(value) for value in hourly.get(name, []))
            for name in HOURLY_VARIABLES
        },
    )
