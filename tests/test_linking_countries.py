"""Testes da resolução de países entre fontes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fscout.db.models import Country
from fscout.db.session import build_engine, create_all
from fscout.linking.countries import CountryResolver


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
