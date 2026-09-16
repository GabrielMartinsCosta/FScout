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


# Chave canônica -> código ISO 3166-1 alpha-3. É o que permite posicionar um país no
# mapa-múndi sem geocodificar nada: a biblioteca de mapas já sabe onde fica cada código.
#
# Três grupos merecem atenção, e estão comentados onde aparecem:
#
# 1. **Seleções britânicas.** Inglaterra, Escócia e País de Gales são seleções distintas
#    no futebol e o mesmo Estado soberano no mapa. Recebem GBR e, por consequência,
#    dividem um marcador. A tabela equivalente mantém as três separadas.
# 2. **Territórios ultramarinos** (Guiana Francesa, Guadalupe, Martinica, Ilha de Man)
#    têm código próprio, mas mapas de baixa resolução costumam desenhá-los junto da
#    metrópole. Ficam com o código correto; se o mapa não os mostrar, aparecem na tabela.
# 3. **Estados que deixaram de existir.** Vêm das datas de nascimento do Transfermarkt
#    (Tchecoslováquia, URSS, Iugoslávia, Sérvia e Montenegro). Não recebem código: onde a
#    sucessão é ambígua, inventar um país seria pior que declarar a ausência. Zaire e a
#    Alemanha Oriental são exceções: o território é o mesmo de hoje, sem ambiguidade.
ISO3_POR_CHAVE: dict[str, str] = {
    "albania": "ALB",
    "algeria": "DZA",
    "angola": "AGO",
    "argentina": "ARG",
    "australia": "AUS",
    "austria": "AUT",
    "belgium": "BEL",
    "bolivia": "BOL",
    "bosnia and herzegovina": "BIH",
    "brazil": "BRA",
    "cameroon": "CMR",
    "canada": "CAN",
    "cape verde": "CPV",
    "central african republic": "CAF",
    "chile": "CHL",
    "china": "CHN",
    "colombia": "COL",
    "costa rica": "CRI",
    "croatia": "HRV",
    "curacao": "CUW",
    "czech republic": "CZE",
    "denmark": "DNK",
    "dominican republic": "DOM",
    "dr congo": "COD",
    "east germany gdr": "DEU",  # mesmo território, reunificado
    "ecuador": "ECU",
    "egypt": "EGY",
    "england": "GBR",  # seleção própria, Estado compartilhado
    "equatorial guinea": "GNQ",
    "france": "FRA",
    "french guiana": "GUF",  # território ultramarino
    "gambia": "GMB",
    "georgia": "GEO",
    "germany": "DEU",
    "ghana": "GHA",
    "greece": "GRC",
    "guadeloupe": "GLP",  # território ultramarino
    "guinea": "GIN",
    "guinea bissau": "GNB",
    "honduras": "HND",
    "hungary": "HUN",
    "iran": "IRN",
    "iraq": "IRQ",
    "ireland": "IRL",
    "isle of man": "IMN",  # dependência da Coroa
    "israel": "ISR",
    "italy": "ITA",
    "ivory coast": "CIV",
    "jamaica": "JAM",
    "japan": "JPN",
    "kenya": "KEN",
    "mali": "MLI",
    "martinique": "MTQ",  # território ultramarino
    "mexico": "MEX",
    "montenegro": "MNE",
    "morocco": "MAR",
    "netherlands": "NLD",
    "nicaragua": "NIC",
    "nigeria": "NGA",
    "north korea": "PRK",
    "north macedonia": "MKD",
    "panama": "PAN",
    "paraguay": "PRY",
    "peru": "PER",
    "poland": "POL",
    "portugal": "PRT",
    "qatar": "QAT",
    "romania": "ROU",
    "russia": "RUS",
    "saudi arabia": "SAU",
    "scotland": "GBR",  # seleção própria, Estado compartilhado
    "senegal": "SEN",
    "serbia": "SRB",
    "slovakia": "SVK",
    "slovenia": "SVN",
    "south africa": "ZAF",
    "south korea": "KOR",
    "spain": "ESP",
    "sudan": "SDN",
    "sweden": "SWE",
    "switzerland": "CHE",
    "togo": "TGO",
    "tunisia": "TUN",
    "turkey": "TUR",
    "ukraine": "UKR",
    "united states": "USA",
    "uruguay": "URY",
    "uzbekistan": "UZB",
    "venezuela": "VEN",
    "wales": "GBR",  # seleção própria, Estado compartilhado
    "zaire": "COD",  # mesmo território, renomeado em 1997
}

# Estados extintos cuja sucessão é ambígua. Ficam sem código de propósito, e são listados
# aqui para que a ausência apareça como decisão registrada, e não como esquecimento.
SEM_CODIGO_ATUAL: frozenset[str] = frozenset(
    {
        "cssr",  # Tchecoslováquia: virou Chéquia e Eslováquia
        "jugoslawien sfr",  # Iugoslávia socialista: virou seis países
        "yugoslavia republic",
        "serbia and montenegro",  # separou-se em 2006
        "udssr",  # União Soviética: quinze repúblicas
    }
)


def country_key(name: str) -> str:
    """Chave canônica do país: nome normalizado, com as variações conhecidas unificadas."""
    normalized = normalize(name)
    return COUNTRY_ALIASES.get(normalized, normalized)


def iso3_de(name: str) -> str | None:
    """Código ISO 3166-1 alpha-3 do país, ou `None` quando não há um que sirva."""
    return ISO3_POR_CHAVE.get(country_key(name))


def preencher_iso3(session: Session) -> tuple[int, list[str]]:
    """Grava o código ISO nos países que ainda não o têm.

    Idempotente: rodar de novo não muda nada. Devolve quantos foram preenchidos e os
    nomes que ficaram sem código, para quem chamou poder mostrá-los em vez de deixar a
    lacuna passar em silêncio.
    """
    preenchidos = 0
    sem_codigo: list[str] = []
    for country in session.scalars(select(Country)):
        codigo = iso3_de(country.name)
        if codigo is None:
            sem_codigo.append(country.name)
            continue
        if country.iso3 != codigo:
            country.iso3 = codigo
            preenchidos += 1
    session.commit()
    return preenchidos, sorted(sem_codigo)


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
