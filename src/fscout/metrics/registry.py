"""Catálogo de métricas.

Cada métrica é um **dado**, não uma função solta: declara de que tabela sai, que filtro a
define, como agrega e a quem se aplica. Três consequências práticas:

- acrescentar uma estatística é acrescentar um registro, não escrever consulta nova;
- a interface se monta sozinha, lendo o catálogo em vez de listas escritas à mão;
- exportado, o catálogo **é** a tabela de definições operacionais da metodologia do TCC.

A comparação entre atletas fica correta por construção: `positions` impede comparar clean
sheet de goleiro com drible de ponta, `higher_is_better` orienta a escala do gráfico,
`per_90` evita confrontar quem jogou 300 minutos com quem jogou 3.000 e `min_sample` impede
que 100% de aproveitamento em um único duelo lidere um ranking.

Há dois tipos de definição. A **métrica** sai de uma consulta a uma tabela. A **composta**
não tem consulta própria: combina métricas já calculadas, e é assim que "participação em
gols" soma gols com assistências, que vêm de tabelas diferentes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement

from fscout.domain.enums import DataTier, PositionGroup

# Quase toda métrica do catálogo é uma consulta sobre eventos, e só existe onde há
# evento. Declarar o padrão aqui evita repeti-lo em 108 registros.
SOMENTE_EVENTO: tuple[DataTier, ...] = (DataTier.EVENT,)
AMBAS_AS_CAMADAS: tuple[DataTier, ...] = (DataTier.EVENT, DataTier.AGGREGATE)

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
    # Razão entre duas somas, e não entre linhas. Existe para a camada agregada, onde
    # cada linha é uma partida com contadores: "aproveitamento de finalização" ali é
    # `soma(no alvo) / soma(finalizações)`, e não a proporção de linhas que deram certo.
    # A amostra passa a ser o **denominador somado**, o que torna o piso significativo:
    # "mínimo de 10 finalizações" em vez de "mínimo de 10 partidas".
    RATE = "rate"


class Unit(StrEnum):
    COUNT = "count"
    PERCENT = "percent"
    METERS = "meters"
    MINUTES = "minutes"
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
    # Só em `RATE`: a coluna (ou expressão) somada no numerador. O denominador é
    # `value_column`, para que o piso de amostra caia sobre ele.
    numerator_column: Any = None
    unit: Unit = Unit.COUNT
    per_90: bool = True
    higher_is_better: bool = True
    positions: tuple[PositionGroup, ...] = TODAS_AS_POSICOES
    # Camadas em que a métrica pode ser calculada. "Finalizações fora da área" exige
    # coordenada e só existe sobre evento; "gols" existe nas duas.
    data_tiers: tuple[DataTier, ...] = SOMENTE_EVENTO
    include_shootout: bool = False
    # Razão ou média abaixo deste número de linhas não é divulgada: 100% de aproveitamento
    # em um único duelo não é informação, e distorce comparação e percentil.
    min_sample: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if self.aggregation is Aggregation.RATIO and not self.numerator:
            raise ValueError(f"{self.key}: razão exige `numerator`")
        if (
            self.aggregation in (Aggregation.SUM, Aggregation.AVERAGE, Aggregation.RATE)
            and self.value_column is None
        ):
            raise ValueError(f"{self.key}: {self.aggregation} exige `value_column`")
        if self.aggregation is Aggregation.RATE and self.numerator_column is None:
            raise ValueError(f"{self.key}: razão entre somas exige `numerator_column`")
        if self.aggregation in (Aggregation.RATIO, Aggregation.RATE) and self.per_90:
            raise ValueError(f"{self.key}: razão não se normaliza por 90 minutos")

    def applies_to(self, position: PositionGroup | None) -> bool:
        return position is None or position in self.positions

    def applies_to_tier(self, tier: DataTier) -> bool:
        """Se a métrica pode ser calculada com o dado daquela granularidade."""
        return tier in self.data_tiers


# A fórmula recebe os valores das métricas de entrada e a minutagem do atleta no recorte.
CompositeFormula = Callable[[Mapping[str, float | None], int], float | None]


@dataclass(frozen=True, eq=False)
class CompositeSpec:
    """Métrica derivada de outras, sem consulta própria.

    Existe porque algumas estatísticas pedidas cruzam famílias: participação em gols soma
    `shots` com `passes`, e minutos por gol divide a minutagem por uma contagem.
    """

    key: str
    label: str
    family: str
    inputs: tuple[str, ...]
    formula: CompositeFormula
    unit: Unit = Unit.COUNT
    per_90: bool = True
    higher_is_better: bool = True
    positions: tuple[PositionGroup, ...] = TODAS_AS_POSICOES
    data_tiers: tuple[DataTier, ...] = SOMENTE_EVENTO
    description: str = ""

    def applies_to(self, position: PositionGroup | None) -> bool:
        return position is None or position in self.positions

    def applies_to_tier(self, tier: DataTier) -> bool:
        """Uma composta vale na camada em que todas as suas entradas valem."""
        return tier in self.data_tiers


Spec = MetricSpec | CompositeSpec


class MetricRegistry:
    """Coleção de definições, indexada por chave. Aceita métricas e compostas."""

    def __init__(self) -> None:
        self._specs: dict[str, Spec] = {}

    def register(self, spec: Spec) -> Spec:
        if spec.key in self._specs:
            raise ValueError(f"métrica duplicada: {spec.key}")
        self._specs[spec.key] = spec
        return spec

    def __getitem__(self, key: str) -> Spec:
        return self._specs[key]

    def __iter__(self) -> Iterator[Spec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, key: object) -> bool:
        return key in self._specs

    def families(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(spec.family for spec in self))

    def by_family(self, family: str) -> tuple[Spec, ...]:
        return tuple(spec for spec in self if spec.family == family)

    def for_position(self, position: PositionGroup | None) -> tuple[Spec, ...]:
        return tuple(spec for spec in self if spec.applies_to(position))

    def select(self, keys: Sequence[str]) -> tuple[Spec, ...]:
        return tuple(self[key] for key in keys)


REGISTRY = MetricRegistry()


def metric(**campos: Any) -> MetricSpec:
    """Cria a métrica e a registra no catálogo global."""
    spec = MetricSpec(**campos)
    REGISTRY.register(spec)
    return spec


def composite(**campos: Any) -> CompositeSpec:
    """Cria a métrica composta e a registra no catálogo global."""
    spec = CompositeSpec(**campos)
    REGISTRY.register(spec)
    return spec


@dataclass
class MetricValue:
    """Resultado de uma métrica para um atleta num recorte.

    `population` diz quantos atletas do mesmo grupo de posição entraram no cálculo do
    percentil — sem isso, "percentil 90" pode significar "melhor que nove de dez" ou
    "melhor que um de dois".
    """

    key: str
    value: float | None
    sample: int = 0
    minutes: int = 0
    per_90: float | None = None
    percentile: float | None = None
    population: int = 0
    context: dict[str, Any] = field(default_factory=dict)
