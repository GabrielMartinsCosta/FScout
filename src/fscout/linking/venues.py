"""Identidade de estádios entre partidas e fontes.

Os nomes de estádio chegam sujos: espaços sobrando ("Al Janoub Stadium   "), apóstrofo
duplicado por escape mal feito na origem ("Levi''s Stadium"). Sem limpeza, o mesmo estádio
vira dois locais e é geocodificado duas vezes.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from fscout.db.models import Venue
from fscout.linking.countries import CountryResolver, country_key
from fscout.linking.names import normalize

_WHITESPACE = re.compile(r"\s+")


def clean_stadium_name(raw: str) -> str:
    """Nome de exibição: espaços colapsados e apóstrofo duplicado desfeito."""
    return _WHITESPACE.sub(" ", raw.replace("''", "'")).strip()


def venue_key(stadium: str, country: str | None) -> str:
    """Chave do local: nome normalizado mais o país, porque há estádios homônimos pelo mundo."""
    country_part = country_key(country) if country else ""
    return f"{normalize(clean_stadium_name(stadium))}|{country_part}"


class VenueResolver:
    """Resolve estádio e país para o id do local, criando-o na primeira vez."""

    def __init__(self, session: Session, countries: CountryResolver) -> None:
        self._session = session
        self._countries = countries
        self._ids: dict[str, int] = {}

    def resolve(self, stadium: str | None, country: str | None) -> int | None:
        if stadium is None or not stadium.strip():
            return None
        key = venue_key(stadium, country)
        if key not in self._ids:
            venue_id = self._session.scalar(select(Venue.id).where(Venue.key == key))
            if venue_id is None:
                venue = Venue(
                    key=key,
                    name=clean_stadium_name(stadium),
                    country_id=self._countries.resolve(country),
                )
                self._session.add(venue)
                self._session.flush()
                venue_id = venue.id
            self._ids[key] = venue_id
        return self._ids[key]
