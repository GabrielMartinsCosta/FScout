"""Identidade de países entre fontes.

A StatsBomb escreve "United States of America" e "Venezuela (Bolivarian Republic)"; o
Transfermarkt, "United States" e "Venezuela". Sem uma chave comum, o mesmo país vira dois
registros e o mapa-múndi divide a seleção americana ao meio.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fscout.db.models import Country
from fscout.linking.names import normalize

# Grafia normalizada -> grafia canônica normalizada. Só entram variações observadas ou
# conhecidas entre StatsBomb, Transfermarkt e FIFA; o resto casa pela normalização.
COUNTRY_ALIASES: dict[str, str] = {
    "united states of america": "united states",
    "usa": "united states",
    "venezuela bolivarian republic": "venezuela",
    "korea republic": "south korea",
    "republic of korea": "south korea",
    "korea south": "south korea",
    "korea dpr": "north korea",
    "korea north": "north korea",
    "cote d ivoire": "ivory coast",
    "ir iran": "iran",
    "iran islamic republic": "iran",
    "turkiye": "turkey",
    "czechia": "czech republic",
    "bosnia herzegovina": "bosnia and herzegovina",
    "china pr": "china",
    "republic of ireland": "ireland",
    "cabo verde": "cape verde",
    "cape verde islands": "cape verde",
    "congo dr": "dr congo",
    "democratic republic of the congo": "dr congo",
    "the gambia": "gambia",
    "iran islamic republic of": "iran",
    "congo kinshasa": "dr congo",
    "macedonia republic of": "north macedonia",
    "macedonia": "north macedonia",
    "curacao": "curacao",
}


def country_key(name: str) -> str:
    """Chave canônica do país: nome normalizado, com as variações conhecidas unificadas."""
    normalized = normalize(name)
    return COUNTRY_ALIASES.get(normalized, normalized)


class CountryResolver:
    """Resolve nomes de país de qualquer fonte para o id canônico, criando quando preciso.

    O primeiro nome visto para um país vira o nome do registro; os seguintes, de outras
    fontes, caem no mesmo registro pela chave.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._ids: dict[str, int] | None = None

    def resolve(self, name: str | None) -> int | None:
        if name is None or not name.strip():
            return None
        ids = self._index()
        key = country_key(name)
        if key not in ids:
            country = Country(name=name.strip())
            self._session.add(country)
            self._session.flush()
            ids[key] = country.id
        return ids[key]

    def _index(self) -> dict[str, int]:
        if self._ids is None:
            self._ids = {
                country_key(name): country_id
                for country_id, name in self._session.execute(select(Country.id, Country.name))
            }
        return self._ids
