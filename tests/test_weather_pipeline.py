"""Teste do pipeline de clima com geocodificador e Open-Meteo falsos, sobre um banco real."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fscout.db.models import Competition, Match, MatchWeather, Season, Team, Venue
from fscout.db.session import build_engine, create_all
from fscout.ingestion.geocoding import GeocodeResult
from fscout.ingestion.openmeteo import HourlyWeather
from fscout.ingestion.weather import enrich_weather
from fscout.linking.countries import CountryResolver
from fscout.linking.venues import VenueResolver


class FakeGeocoder:
    def __init__(self, known: dict[str, tuple[float, float]]) -> None:
        self.known = known
        self.calls: list[str] = []

    def geocode_stadium(self, stadium: str, country: str | None) -> GeocodeResult | None:
        self.calls.append(stadium)
        if stadium not in self.known:
            return None
        latitude, longitude = self.known[stadium]
        return GeocodeResult(latitude, longitude, stadium, "way", 1, stadium, True)

    def close(self) -> None:
        pass


class FakeMeteo:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, date, date]] = []

    def hourly(self, latitude: float, longitude: float, start: date, end: date) -> HourlyWeather:
        self.calls.append((latitude, longitude, start, end))
        times = tuple(datetime(2024, 6, day, hour) for day in (20, 21) for hour in range(24))
        return HourlyWeather(
            times=times,
            values={
                "temperature_2m": tuple(20.0 + index % 24 for index in range(len(times))),
                "relative_humidity_2m": tuple(50.0 for _ in times),
                "precipitation": tuple(0.0 for _ in times),
                "wind_speed_10m": tuple(10.0 for _ in times),
            },
        )

    def close(self) -> None:
        pass


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(f"sqlite:///{tmp_path / 'clima.db'}")
    create_all(engine)
    with Session(engine) as session:
        countries = CountryResolver(session)
        venues = VenueResolver(session, countries)
        competition = Competition(name="Copa America")
        session.add(competition)
        session.flush()
        season = Season(competition_id=competition.id, name="2024")
        home, away = Team(name="Argentina"), Team(name="Canada")
        session.add_all([season, home, away])
        session.flush()

        def match(stadium: str, day: int, hour: int | None) -> Match:
            return Match(
                season_id=season.id,
                match_date=date(2024, 6, day),
                kickoff=None if hour is None else datetime(2024, 6, day, hour),
                home_team_id=home.id,
                away_team_id=away.id,
                stadium=stadium,
                venue_id=venues.resolve(stadium, "United States of America"),
            )

        session.add_all(
            [
                match("Mercedes-Benz Stadium", 20, 18),
                match("Mercedes-Benz Stadium  ", 21, 0),  # mesmo estádio, grafia suja
                match("Estádio Desconhecido", 21, 1),
                match("Mercedes-Benz Stadium", 21, None),  # sem horário de início
            ]
        )
        session.commit()
    yield engine
    engine.dispose()


def test_clima_por_partida_com_uma_consulta_por_estadio(engine: Engine, tmp_path: Path) -> None:
    geocoder = FakeGeocoder({"Mercedes-Benz Stadium": (33.7554, -84.4008)})
    meteo = FakeMeteo()
    report = enrich_weather(
        engine=engine, geocoder=geocoder, meteo=meteo, reference_path=tmp_path / "ausente.csv"
    )

    assert report.venues_total == 2
    assert report.venues_located == 1
    assert report.venues_unresolved == ["Estádio Desconhecido (United States of America)"]
    assert report.matches_with_weather == 2
    assert report.matches_without_kickoff == 1
    assert report.matches_without_location == 1
    assert len(meteo.calls) == 1

    with Session(engine) as session:
        first = session.scalars(select(MatchWeather).order_by(MatchWeather.kickoff_utc)).first()
        assert first is not None
        # Início 18h: leituras de 18h, 19h e 20h -> 38, 39 e 40 graus no clima falso.
        assert first.temperature_c == pytest.approx(39.0)


def test_correcao_manual_descarta_o_clima_buscado_no_lugar_errado(
    engine: Engine, tmp_path: Path
) -> None:
    """Foi o caso real do Q2 Stadium, geocodificado na Virgínia em vez de no Texas."""
    lugar_errado = FakeGeocoder({"Mercedes-Benz Stadium": (37.5512, -77.4878)})
    enrich_weather(
        engine=engine,
        geocoder=lugar_errado,
        meteo=FakeMeteo(),
        reference_path=tmp_path / "ausente.csv",
    )

    reference = tmp_path / "venues.csv"
    reference.write_text(
        "stadium,country,latitude,longitude,note\n"
        "Mercedes-Benz Stadium,United States,33.7554,-84.4008,corrigido a mao\n",
        encoding="utf-8",
    )
    meteo = FakeMeteo()
    report = enrich_weather(
        engine=engine, geocoder=FakeGeocoder({}), meteo=meteo, reference_path=reference
    )

    assert report.weather_discarded == 2
    assert meteo.calls[0][:2] == (33.7554, -84.4008)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MatchWeather)) == 2


def test_coordenada_manual_tem_precedencia_e_reexecucao_nao_duplica(
    engine: Engine, tmp_path: Path
) -> None:
    reference = tmp_path / "venues.csv"
    reference.write_text(
        "stadium,country,latitude,longitude,note\n"
        "Estádio Desconhecido,United States,40.0,-75.0,corrigido a mao\n",
        encoding="utf-8",
    )
    geocoder = FakeGeocoder({"Mercedes-Benz Stadium": (33.7554, -84.4008)})

    enrich_weather(engine=engine, geocoder=geocoder, meteo=FakeMeteo(), reference_path=reference)
    report = enrich_weather(
        engine=engine, geocoder=geocoder, meteo=FakeMeteo(), reference_path=reference
    )

    assert geocoder.calls == ["Mercedes-Benz Stadium"]  # geocodificado uma única vez
    assert report.venues_located == 2
    assert report.venues_manual == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MatchWeather)) == 3
        manual = session.scalars(select(Venue).where(Venue.geocode_source == "manual")).one()
        assert (manual.latitude, manual.longitude) == (40.0, -75.0)
