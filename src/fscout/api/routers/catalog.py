"""Catálogo de métricas.

A interface se monta a partir daqui: os seletores de métrica, o radar e a tabela
comparativa leem este endpoint em vez de carregarem listas escritas à mão.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from fscout.api.schemas import MetricDefinitionOut
from fscout.domain.enums import DataTier, PositionGroup
from fscout.metrics.registry import REGISTRY, CompositeSpec, Spec

router = APIRouter(prefix="/catalog", tags=["catálogo"])


def to_definition(spec: Spec) -> MetricDefinitionOut:
    composta = isinstance(spec, CompositeSpec)
    return MetricDefinitionOut(
        key=spec.key,
        label=spec.label,
        family=spec.family,
        unit=str(spec.unit),
        kind="composite" if composta else str(spec.aggregation),
        per_90=spec.per_90,
        higher_is_better=spec.higher_is_better,
        positions=list(spec.positions),
        data_tiers=list(spec.data_tiers),
        min_sample=0 if composta else spec.min_sample,
        inputs=list(spec.inputs) if composta else [],
        description=spec.description,
    )


@router.get("", summary="Definições operacionais de todas as métricas")
def list_metrics(
    family: str | None = None,
    position: PositionGroup | None = None,
    data_tier: DataTier | None = None,
) -> list[MetricDefinitionOut]:
    """O catálogo, opcionalmente recortado.

    `data_tier` importa: métrica de uma granularidade não se calcula na outra, e uma tela
    que oferecesse "gols de fora da área" sobre dado agregado prometeria o que a fonte
    não tem.
    """
    specs = REGISTRY.by_family(family) if family else tuple(REGISTRY)
    if family and not specs:
        raise HTTPException(404, f"família desconhecida: {family}")
    if position is not None:
        specs = tuple(spec for spec in specs if spec.applies_to(position))
    if data_tier is not None:
        specs = tuple(spec for spec in specs if spec.applies_to_tier(data_tier))
    return [to_definition(spec) for spec in specs]


@router.get("/families", summary="Famílias de métricas e quantas cada uma tem")
def list_families() -> dict[str, int]:
    return {familia: len(REGISTRY.by_family(familia)) for familia in REGISTRY.families()}


@router.get("/{key}", summary="Uma métrica pela chave")
def get_metric(key: str) -> MetricDefinitionOut:
    if key not in REGISTRY:
        raise HTTPException(404, f"métrica desconhecida: {key}")
    return to_definition(REGISTRY[key])
