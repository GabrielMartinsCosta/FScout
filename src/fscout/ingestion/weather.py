"""Clima das partidas: localiza os estádios e busca a condição no horário do jogo.

Duas etapas, ambas idempotentes:

1. **Localização.** Cada estádio é geocodificado uma vez pelo OpenStreetMap. Coordenadas
   corrigidas à mão em `data/reference/venues.csv` têm precedência — é o caminho para os
   estádios que a busca automática não encontra ou encontra errado.
2. **Clima.** Para cada estádio, uma única consulta ao Open-Meteo cobre todas as suas
   partidas. Cada partida recebe o resumo das duas horas a partir do início.

Definição operacional do "clima da partida", a ser declarada no TCC: temperatura, umidade
e vento são a média das leituras horárias do início até duas horas depois; precipitação é
a soma do acumulado nas duas horas seguintes ao início.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from fscout.config import PROJECT_ROOT
from fscout.db.models import Match, MatchWeather, Venue
from fscout.db.session import create_all, get_engine
from fscout.ingestion.geocoding import NominatimGeocoder
from fscout.ingestion.openmeteo import HourlyWeather, OpenMeteoClient
from fscout.linking.venues import venue_key

logger = logging.getLogger(__name__)

SOURCE = "open-meteo"
GEOCODE_SOURCE = "nominatim"
MANUAL_SOURCE = "manual"
MATCH_WINDOW_HOURS = 2
REFERENCE_FILE = PROJECT_ROOT / "data" / "reference" / "venues.csv"


@dataclass
class WeatherReport:
    venues_total: int = 0
    venues_located: int = 0
    venues_manual: int = 0
    venues_unresolved: list[str] = field(default_factory=list)
    venues_to_check: list[str] = field(default_factory=list)
    matches_total: int = 0
    matches_with_weather: int = 0
    matches_without_kickoff: int = 0
    matches_without_location: int = 0
    weather_discarded: int = 0


def summarize_match_weather(
    weather: HourlyWeather, kickoff_utc: datetime
) -> dict[str, float | None] | None:
    """Resumo do clima nas duas horas a partir do início da partida."""
    start = kickoff_utc.replace(minute=0, second=0, microsecond=0)
    readings = weather.readings_between(start, start + timedelta(hours=MATCH_WINDOW_HOURS))
    if not readings:
        return None

    def mean(name: str) -> float | None:
        values = [reading[name] for reading in readings if reading[name] is not None]
        return round(fmean(values), 2) if values else None

    # A precipitação horária é o acumulado da hora anterior: a leitura do próprio horário de
    # início descreve o período antes do jogo e fica de fora da soma.
    rain = [
        reading["precipitation"] for reading in readings[1:] if reading["precipitation"] is not None
    ]
    return {
        "temperature_c": mean("temperature_2m"),
        "relative_humidity_pct": mean("relative_humidity_2m"),
        "wind_speed_kmh": mean("wind_speed_10m"),
        "precipitation_mm": round(sum(rain), 2) if rain else None,
    }


def enrich_weather(
    *,
    engine: Engine | None = None,
    geocoder: NominatimGeocoder | None = None,
    meteo: OpenMeteoClient | None = None,
    reference_path: Path = REFERENCE_FILE,
) -> WeatherReport:
    engine = engine or get_engine()
    create_all(engine)
    owns_geocoder, owns_meteo = geocoder is None, meteo is None
    geocoder = geocoder or NominatimGeocoder()
    meteo = meteo or OpenMeteoClient()
    report = WeatherReport()

    try:
        with Session(engine) as session:
            _locate_venues(session, geocoder, reference_path, report)
            session.commit()
            _fetch_weather(session, meteo, report)
            session.commit()
    finally:
        if owns_geocoder:
            geocoder.close()
        if owns_meteo:
            meteo.close()
    return report


def _locate_venues(
    session: Session, geocoder: NominatimGeocoder, reference_path: Path, report: WeatherReport
) -> None:
    manual = _read_reference(reference_path)
    venues = session.scalars(select(Venue)).all()
    report.venues_total = len(venues)

    for venue in venues:
        country = venue.country.name if venue.country else None
        if venue.key in manual:
            latitude, longitude = manual[venue.key]
            if (venue.latitude, venue.longitude) != (latitude, longitude):
                report.weather_discarded += _discard_weather(session, venue.id)
            venue.latitude, venue.longitude = latitude, longitude
            venue.geocode_source = MANUAL_SOURCE
            report.venues_manual += 1
        elif venue.latitude is None:
            result = geocoder.geocode_stadium(venue.name, country)
            if result is None:
                report.venues_unresolved.append(f"{venue.name} ({country})")
                continue
            venue.latitude, venue.longitude = result.latitude, result.longitude
            venue.geocode_source = GEOCODE_SOURCE
            venue.geocode_query = result.query
            venue.osm_type, venue.osm_id = result.osm_type, result.osm_id
            venue.geocoded_as_stadium = result.is_stadium
            logger.info("Estádio localizado: %s -> %s", venue.name, result.display_name)

        if venue.geocode_source == GEOCODE_SOURCE and not venue.geocoded_as_stadium:
            report.venues_to_check.append(f"{venue.name} ({country})")

    session.flush()
    report.venues_located = sum(1 for venue in venues if venue.latitude is not None)


def _fetch_weather(session: Session, meteo: OpenMeteoClient, report: WeatherReport) -> None:
    report.matches_total = session.scalar(select(func.count()).select_from(Match)) or 0
    pending = session.execute(
        select(Match.id, Match.kickoff, Venue.id, Venue.latitude, Venue.longitude)
        .select_from(Match)
        .outerjoin(Venue, Venue.id == Match.venue_id)
        .outerjoin(MatchWeather, MatchWeather.match_id == Match.id)
        .where(MatchWeather.match_id.is_(None))
    ).all()

    by_venue: dict[tuple[int, float, float], list[tuple[int, datetime]]] = defaultdict(list)
    for match_id, kickoff, venue_id, latitude, longitude in pending:
        if kickoff is None:
            report.matches_without_kickoff += 1
        elif latitude is None or longitude is None:
            report.matches_without_location += 1
        else:
            by_venue[(venue_id, latitude, longitude)].append((match_id, kickoff))

    for (venue_id, latitude, longitude), matches in by_venue.items():
        first = min(kickoff for _, kickoff in matches).date()
        last = (max(kickoff for _, kickoff in matches) + timedelta(hours=MATCH_WINDOW_HOURS)).date()
        weather = meteo.hourly(latitude, longitude, first, last)
        for match_id, kickoff in matches:
            summary = summarize_match_weather(weather, kickoff)
            if summary is not None:
                session.add(
                    MatchWeather(
                        match_id=match_id,
                        venue_id=venue_id,
                        kickoff_utc=kickoff,
                        source=SOURCE,
                        **summary,
                    )
                )
    session.flush()
    report.matches_with_weather = (
        session.scalar(select(func.count()).select_from(MatchWeather)) or 0
    )


def _discard_weather(session: Session, venue_id: int) -> int:
    """Apaga o clima gravado de um local cuja coordenada mudou.

    Sem isso a correção manual não teria efeito: o clima antigo, buscado na coordenada
    errada, continuaria no banco, porque a etapa seguinte só preenche partidas sem clima.
    """
    result = session.execute(delete(MatchWeather).where(MatchWeather.venue_id == venue_id))
    return result.rowcount or 0


def _read_reference(path: Path) -> dict[str, tuple[float, float]]:
    """Coordenadas manuais: colunas `stadium`, `country`, `latitude`, `longitude`."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            venue_key(row["stadium"], row.get("country") or None): (
                float(row["latitude"]),
                float(row["longitude"]),
            )
            for row in csv.DictReader(handle)
            if row.get("stadium") and row.get("latitude") and row.get("longitude")
        }
