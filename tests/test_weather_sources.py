"""Testes de estádios, geocodificação e clima, sem acesso à rede."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from fscout.config import Settings
from fscout.ingestion.geocoding import MIN_INTERVAL_S, NominatimGeocoder
from fscout.ingestion.openmeteo import OpenMeteoClient, parse_hourly
from fscout.ingestion.weather import summarize_match_weather
from fscout.linking.venues import clean_stadium_name, venue_key

# ----------------------------------------------------------------------------------------
# Nomes de estádio, com a sujeira real vista na StatsBomb
# ----------------------------------------------------------------------------------------


def test_limpeza_de_nome_de_estadio() -> None:
    assert clean_stadium_name("Al Janoub Stadium   ") == "Al Janoub Stadium"
    assert clean_stadium_name("Levi''s Stadium") == "Levi's Stadium"
    assert clean_stadium_name("Children''s  Mercy Park") == "Children's Mercy Park"


def test_chave_do_local_iguala_grafias_e_separa_paises() -> None:
    assert venue_key("Education City Stadium ", "Qatar") == venue_key(
        "Education City Stadium", "Qatar"
    )
    assert venue_key("Olympiastadion", "Germany") != venue_key("Olympiastadion", "Finland")


# ----------------------------------------------------------------------------------------
# Nominatim
# ----------------------------------------------------------------------------------------


def _geocoder(
    responses: dict[str, list[dict[str, Any]]],
) -> tuple[NominatimGeocoder, list[str], list[float]]:
    queries: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        queries.append(query)
        return httpx.Response(200, json=responses.get(query, []))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    geocoder = NominatimGeocoder(http=http, sleep=sleeps.append, clock=lambda: 0.0)
    return geocoder, queries, sleeps


def test_resultado_marcado_como_estadio_vence_a_ordem_de_relevancia() -> None:
    geocoder, _, _ = _geocoder(
        {
            "Hard Rock Stadium, United States": [
                {"lat": "25.95", "lon": "-80.23", "type": "bus_stop", "category": "highway"},
                {
                    "lat": "25.958",
                    "lon": "-80.239",
                    "type": "stadium",
                    "category": "leisure",
                    "osm_type": "way",
                    "osm_id": "171419981",
                    "display_name": "Hard Rock Stadium",
                },
            ]
        }
    )
    result = geocoder.geocode_stadium("Hard Rock Stadium", "United States")

    assert result is not None
    assert (result.latitude, result.longitude) == (25.958, -80.239)
    assert result.is_stadium
    assert result.osm_id == 171419981


def test_sem_resultado_com_pais_tenta_so_o_nome() -> None:
    geocoder, queries, _ = _geocoder(
        {"Stadium 974": [{"lat": "25.29", "lon": "51.56", "type": "stadium"}]}
    )
    result = geocoder.geocode_stadium("Stadium 974", "Qatar")

    assert queries == ["Stadium 974, Qatar", "Stadium 974"]
    assert result is not None and result.query == "Stadium 974"


def test_nada_encontrado() -> None:
    geocoder, _, _ = _geocoder({})
    assert geocoder.geocode_stadium("Estádio Inexistente", "Brazil") is None


def test_respeita_uma_requisicao_por_segundo() -> None:
    geocoder, queries, sleeps = _geocoder({})
    geocoder.geocode_stadium("A", "B")  # duas consultas seguidas no mesmo instante

    assert len(queries) == 2
    assert sleeps == [pytest.approx(MIN_INTERVAL_S)]


# ----------------------------------------------------------------------------------------
# Open-Meteo e resumo do clima da partida
# ----------------------------------------------------------------------------------------

PAYLOAD = {
    "timezone": "GMT",
    "utc_offset_seconds": 0,
    "hourly": {
        "time": [
            "2022-12-18T14:00",
            "2022-12-18T15:00",
            "2022-12-18T16:00",
            "2022-12-18T17:00",
            "2022-12-18T18:00",
        ],
        "temperature_2m": [25.0, 24.0, 23.0, 22.0, 21.0],
        "relative_humidity_2m": [40, 50, 60, 70, 80],
        "precipitation": [9.0, 1.5, 0.5, None, 7.0],
        "wind_speed_10m": [10.0, 12.0, 14.0, 16.0, 18.0],
    },
}


def test_resumo_das_duas_horas_a_partir_do_inicio() -> None:
    """Início 15:20 UTC: leituras de 15h, 16h e 17h."""
    summary = summarize_match_weather(parse_hourly(PAYLOAD), datetime(2022, 12, 18, 15, 20))

    assert summary is not None
    assert summary["temperature_c"] == pytest.approx(23.0)
    assert summary["relative_humidity_pct"] == pytest.approx(60.0)
    assert summary["wind_speed_kmh"] == pytest.approx(14.0)
    # Chuva: acumulados das 16h e 17h (0.5 e ausente); o das 15h é anterior ao jogo.
    assert summary["precipitation_mm"] == pytest.approx(0.5)


def test_partida_fora_da_serie_nao_ganha_clima_inventado() -> None:
    assert summarize_match_weather(parse_hourly(PAYLOAD), datetime(2022, 12, 20, 15, 0)) is None


def test_cliente_pede_utc_e_usa_cache_em_disco(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=PAYLOAD)

    settings = Settings(raw_dir=tmp_path)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenMeteoClient(settings=settings, http=http)
    first = client.hourly(25.4206, 51.4906, date(2022, 12, 18), date(2022, 12, 18))
    second = client.hourly(25.4206, 51.4906, date(2022, 12, 18), date(2022, 12, 18))

    assert len(calls) == 1
    assert calls[0].url.params["timezone"] == "GMT"
    assert first == second
