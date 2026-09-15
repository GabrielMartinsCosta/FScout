"""Criação do engine e gerenciamento de sessões."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from fscout.config import get_settings
from fscout.db.base import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine único do processo, configurado a partir de `Settings`."""
    settings = get_settings()
    url = settings.resolved_database_url
    engine = create_engine(url, future=True)

    if url.startswith("sqlite"):
        _tune_sqlite(engine)
    return engine


def _tune_sqlite(engine: Engine) -> None:
    """Ajusta o SQLite para carga em lote e para consultas analíticas.

    Os padrões do SQLite são conservadores demais para ingerir centenas de milhares de
    eventos: sem WAL e com `synchronous=FULL` cada transação espera o disco. Chaves
    estrangeiras também vêm desligadas por padrão, o que silenciaria erros de integridade
    justamente durante a ingestão, que é quando eles precisam aparecer.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")  # 64 MB de cache de páginas
        cursor.close()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Fábrica de sessões vinculada ao engine do processo."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sessão transacional: confirma ao sair sem erro, desfaz em caso de exceção."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Cria as tabelas que ainda não existem.

    Suficiente enquanto o schema está em construção. A partir do momento em que houver
    um banco carregado que não se queira recriar, a evolução passa a exigir migrações
    versionadas (Alembic) — trocar `create_all` por migração é uma decisão de projeto,
    não um detalhe: veja `docs/ROADMAP.md`.
    """
    import fscout.db.models  # noqa: F401  (registra os mapeamentos antes do create_all)

    Base.metadata.create_all(get_engine())


def drop_all() -> None:
    """Remove todas as tabelas. Destrutivo; existe para recriar o banco em testes."""
    import fscout.db.models  # noqa: F401

    Base.metadata.drop_all(get_engine())
