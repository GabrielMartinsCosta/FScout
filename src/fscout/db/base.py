"""Base declarativa, mixins e utilitários compartilhados pelo schema."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa de todas as tabelas."""


def enum_column(enum_cls: type[PyEnum], **kwargs: Any) -> Mapped[Any]:
    """Coluna de enum persistida como texto legível, com validação no banco.

    `native_enum=False` evita tipos ENUM nativos, que o SQLite não tem e que o
    Postgres só altera via migração. O resultado é um VARCHAR com CHECK constraint:
    portátil entre os dois bancos e legível numa consulta manual.
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            length=48,
            values_callable=lambda cls: [member.value for member in cls],
            validate_strings=True,
        ),
        **kwargs,
    )


class SourceRefMixin:
    """Rastreia de qual fonte veio cada registro e qual era seu identificador lá.

    O projeto ingere StatsBomb, CSV de clube e — futuramente — provedores comerciais.
    Sem esse par, duas fontes que descrevem o mesmo jogador colidem ou duplicam.
    Com ele, cada tabela ganha uma chave natural `(source, source_id)` que torna a
    ingestão idempotente: reprocessar a mesma partida atualiza em vez de duplicar.
    """

    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)


class TimestampMixin:
    """Marca temporal de criação, para auditoria de carga."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
