"""Testes da resolução de países entre fontes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fscout.db.models import Country
from fscout.db.session import build_engine, create_all
from fscout.linking.countries import (
    SEM_CODIGO_ATUAL,
    CountryResolver,
    country_key,
    iso3_de,
    preencher_iso3,
)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'paises.db'}")
    create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_grafia_de_outra_fonte_cai_no_pais_existente(session: Session) -> None:
    session.add(Country(name="United States of America"))
    session.flush()
    resolver = CountryResolver(session)

    existente = resolver.resolve("United States of America")
    assert resolver.resolve("United States") == existente
    assert session.scalar(select(func.count()).select_from(Country)) == 1


def test_pais_novo_e_criado_uma_unica_vez(session: Session) -> None:
    resolver = CountryResolver(session)
    primeiro = resolver.resolve("Brazil")
    assert resolver.resolve("  Brazil ") == primeiro
    assert session.scalar(select(func.count()).select_from(Country)) == 1


def test_nome_vazio_nao_cria_pais(session: Session) -> None:
    resolver = CountryResolver(session)
    assert resolver.resolve(None) is None
    assert resolver.resolve("   ") is None
    assert session.scalar(select(func.count()).select_from(Country)) == 0


# ----------------------------------------------------------------------------------------
# Código ISO: o que posiciona o mapa-múndi
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "codigo"),
    [
        ("Brazil", "BRA"),
        ("United States of America", "USA"),  # grafia da StatsBomb
        ("Venezuela (Bolivarian Republic)", "VEN"),
        ("Iran, Islamic Republic of", "IRN"),
        ("Korea (South)", "KOR"),
        ("Czech Republic", "CZE"),
    ],
)
def test_codigo_iso_atravessa_as_grafias_das_fontes(nome: str, codigo: str) -> None:
    """O código sai da chave canônica, então cada fonte pode escrever como quiser."""
    assert iso3_de(nome) == codigo


def test_selecoes_britanicas_compartilham_o_estado_soberano() -> None:
    """São três seleções e um país no mapa. O mapa soma; a tabela mantém separadas."""
    assert iso3_de("England") == iso3_de("Scotland") == iso3_de("Wales") == "GBR"


def test_estado_extinto_de_sucessao_ambigua_fica_sem_codigo() -> None:
    """Escolher um sucessor plantaria um marcador onde ninguém jogou."""
    for nome in ("CSSR", "UdSSR", "Serbia and Montenegro"):
        assert country_key(nome) in SEM_CODIGO_ATUAL
        assert iso3_de(nome) is None


def test_territorio_renomeado_mantem_o_codigo_de_hoje() -> None:
    """Zaire e a atual República Democrática do Congo são o mesmo território."""
    assert iso3_de("Zaire") == iso3_de("Congo Kinshasa") == "COD"


def test_preenchimento_e_idempotente_e_relata_o_que_ficou_de_fora(session: Session) -> None:
    session.add_all([Country(name="Brazil"), Country(name="England"), Country(name="UdSSR")])
    session.flush()

    preenchidos, sem_codigo = preencher_iso3(session)
    assert preenchidos == 2
    assert sem_codigo == ["UdSSR"]

    # Rodar de novo não deve reescrever nada: é o que permite chamar sem medo.
    assert preencher_iso3(session) == (0, ["UdSSR"])
    assert session.scalar(select(Country.iso3).where(Country.name == "England")) == "GBR"
