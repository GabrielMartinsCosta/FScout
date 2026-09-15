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
    """Origem de um registro que pertence a uma única fonte e nunca é combinado.

    Vale para eventos: duas fontes que descrevem a mesma partida produzem sequências de
    ações diferentes, que não se fundem. Entidades que as fontes compartilham — atleta,
    clube, partida — não usam este mixin; a identidade delas em cada fonte fica em
    `external_ids`, para que o mesmo atleta vindo de duas fontes seja um registro só.

    O índice único `(source, source_id)` é declarado em cada tabela e já cobre a busca.
    """

    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))


class TimestampMixin:
    """Marca temporal de criação, para auditoria de carga."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
