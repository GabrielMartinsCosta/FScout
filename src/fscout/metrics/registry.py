"""Catálogo de métricas.

Cada métrica é um **dado**, não uma função solta: declara de que tabela sai, que filtro a
define, como agrega e a quem se aplica. Três consequências práticas:

- acrescentar uma estatística é acrescentar um registro, não escrever consulta nova;
- a interface se monta sozinha, lendo o catálogo em vez de listas escritas à mão;
- exportado, o catálogo **é** a tabela de definições operacionais da metodologia do TCC.

A comparação entre atletas fica correta por construção: `positions` impede comparar clean
sheet de goleiro com drible de ponta, `higher_is_better` orienta a escala do gráfico e
`per_90` evita confrontar quem jogou 300 minutos com quem jogou 3.000 em valores absolutos.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement

from fscout.domain.enums import PositionGroup

TODAS_AS_POSICOES: tuple[PositionGroup, ...] = (
    PositionGroup.GOALKEEPER,
    PositionGroup.DEFENDER,
    PositionGroup.MIDFIELDER,
    PositionGroup.FORWARD,
)

DE_LINHA: tuple[PositionGroup, ...] = (
    PositionGroup.DEFENDER,
    PositionGroup.MIDFIELDER,
    PositionGroup.FORWARD,
)


class Aggregation(StrEnum):
    """Como as linhas filtradas viram um número."""

    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    RATIO = "ratio"


class Unit(StrEnum):
    COUNT = "count"
    PERCENT = "percent"
    METERS = "meters"
    SECONDS = "seconds"
    XG = "xg"


@dataclass(frozen=True, eq=False)
class MetricSpec:
    """Definição operacional de uma métrica.

    `predicate` delimita as linhas que a métrica considera; em razões, `numerator` delimita,
    dentro dessas, as que contam como sucesso — "aproveitamento de chutes" tem como universo
    as finalizações e como sucesso as que foram ao gol.
    """

    key: str
    label: str
    family: str
    table: type[Any]
    aggregation: Aggregation = Aggregation.COUNT
    predicate: tuple[ColumnElement[bool], ...] = ()
    numerator: tuple[ColumnElement[bool], ...] = ()
    value_column: Any = None
    unit: Unit = Unit.COUNT
    per_90: bool = True
    higher_is_better: bool = True
    positions: tuple[PositionGroup, ...] = TODAS_AS_POSICOES
    include_shootout: bool = False
    # Razao ou media abaixo deste numero de linhas nao e divulgada: 100% de aproveitamento
    # em um unico duelo nao e informacao, e distorce comparacao e percentil.
    min_sample: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if self.aggregation is Aggregation.RATIO and not self.numerator:
            raise ValueError(f"{self.key}: razão exige `numerator`")
        if self.aggregation in (Aggregation.SUM, Aggregation.AVERAGE) and self.value_column is None:
            raise ValueError(f"{self.key}: {self.aggregation} exige `value_column`")
        if self.aggregation is Aggregation.RATIO and self.per_90:
            raise ValueError(f"{self.key}: razão não se normaliza por 90 minutos")

    def applies_to(self, position: PositionGroup | None) -> bool:
        return position is None or position in self.positions


class MetricRegistry:
    """Coleção de métricas, indexada por chave."""

    def __init__(self) -> None:
        self._specs: dict[str, MetricSpec] = {}

    def register(self, spec: MetricSpec) -> MetricSpec:
        if spec.key in self._specs:
            raise ValueError(f"métrica duplicada: {spec.key}")
        self._specs[spec.key] = spec
        return spec

    def __getitem__(self, key: str) -> MetricSpec:
        return self._specs[key]

    def __iter__(self) -> Iterator[MetricSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, key: object) -> bool:
        return key in self._specs

    def families(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(spec.family for spec in self))

    def by_family(self, family: str) -> tuple[MetricSpec, ...]:
        return tuple(spec for spec in self if spec.family == family)

    def for_position(self, position: PositionGroup | None) -> tuple[MetricSpec, ...]:
        return tuple(spec for spec in self if spec.applies_to(position))

    def select(self, keys: Sequence[str]) -> tuple[MetricSpec, ...]:
        return tuple(self[key] for key in keys)


REGISTRY = MetricRegistry()


def metric(**campos: Any) -> MetricSpec:
    """Cria a métrica e a registra no catálogo global."""
    return REGISTRY.register(MetricSpec(**campos))


@dataclass
class MetricValue:
    """Resultado de uma métrica para um atleta num recorte."""

    key: str
    value: float | None
    sample: int = 0
    minutes: int = 0
    per_90: float | None = None
    percentile: float | None = None
    context: dict[str, Any] = field(default_factory=dict)
