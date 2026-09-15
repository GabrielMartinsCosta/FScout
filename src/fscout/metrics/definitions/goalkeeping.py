"""Métricas de goleiro.

"Gols evitados" é a diferença entre o xG das finalizações enfrentadas e os gols sofridos.
Vale a ressalva metodológica: o xG da StatsBomb é calculado **antes** do chute, e não a
partir da qualidade do remate, então o indicador aqui é uma aproximação do que a literatura
chama de *post-shot expected goals*.

Defesas da disputa de pênaltis ficam de fora, como no resto do catálogo.
"""

from __future__ import annotations

from sqlalchemy import case, func

from fscout.db.models import GoalkeeperAction
from fscout.domain.enums import GoalkeeperActionType, PositionGroup
from fscout.metrics.registry import Aggregation, Unit, metric

FAMILIA = "goleiro"
GOLEIROS = (PositionGroup.GOALKEEPER,)

DEFENDEU = GoalkeeperAction.is_save.is_(True)
SOFREU = GoalkeeperAction.conceded_goal.is_(True)
ENFRENTOU_CHUTE = GoalkeeperAction.shot_event_id.is_not(None)

metric(
    key="defesas",
    label="Defesas",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(DEFENDEU,),
    positions=GOLEIROS,
)
metric(
    key="gols_sofridos",
    label="Gols sofridos",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(SOFREU,),
    higher_is_better=False,
    positions=GOLEIROS,
)
metric(
    key="aproveitamento_em_defesas",
    min_sample=10,
    label="Defesas sobre finalizações enfrentadas",
    family=FAMILIA,
    table=GoalkeeperAction,
    aggregation=Aggregation.RATIO,
    predicate=(ENFRENTOU_CHUTE,),
    numerator=(DEFENDEU,),
    unit=Unit.PERCENT,
    per_90=False,
    positions=GOLEIROS,
)
metric(
    key="gols_evitados",
    label="Gols evitados",
    family=FAMILIA,
    table=GoalkeeperAction,
    aggregation=Aggregation.SUM,
    predicate=(ENFRENTOU_CHUTE,),
    value_column=func.coalesce(GoalkeeperAction.shot_xg, 0.0) - case((SOFREU, 1.0), else_=0.0),
    unit=Unit.XG,
    positions=GOLEIROS,
    description="xG das finalizações enfrentadas menos os gols sofridos.",
)
metric(
    key="defesas_de_fora_da_area",
    label="Defesas em chutes de fora da área",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(DEFENDEU, GoalkeeperAction.shot_from_outside_box.is_(True)),
    positions=GOLEIROS,
)
metric(
    key="defesas_de_dentro_da_area",
    label="Defesas em chutes de dentro da área",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(DEFENDEU, GoalkeeperAction.shot_from_outside_box.is_(False)),
    positions=GOLEIROS,
)
metric(
    key="defesas_de_penalti",
    label="Defesas de pênalti",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(GoalkeeperAction.is_penalty_save.is_(True),),
    positions=GOLEIROS,
)
metric(
    key="defesas_com_rebote",
    label="Defesas que deram rebote",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(GoalkeeperAction.gave_rebound.is_(True),),
    higher_is_better=False,
    positions=GOLEIROS,
)
metric(
    key="proporcao_de_rebotes",
    min_sample=5,
    label="Rebotes sobre defesas",
    family=FAMILIA,
    table=GoalkeeperAction,
    aggregation=Aggregation.RATIO,
    predicate=(DEFENDEU,),
    numerator=(GoalkeeperAction.gave_rebound.is_(True),),
    unit=Unit.PERCENT,
    per_90=False,
    higher_is_better=False,
    positions=GOLEIROS,
)
metric(
    key="saidas_do_gol",
    label="Saídas do gol",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(GoalkeeperAction.is_sweeper.is_(True),),
    positions=GOLEIROS,
    description="Intervenções fora da área pequena, antecipando a bola.",
)
metric(
    key="bolas_encaixadas",
    label="Bolas encaixadas",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(GoalkeeperAction.action_type == GoalkeeperActionType.COLLECTED,),
    positions=GOLEIROS,
)
metric(
    key="socos",
    label="Socos",
    family=FAMILIA,
    table=GoalkeeperAction,
    predicate=(GoalkeeperAction.action_type == GoalkeeperActionType.PUNCH,),
    positions=GOLEIROS,
)
metric(
    key="distancia_media_do_chute_enfrentado",
    min_sample=5,
    label="Distância média do chute enfrentado",
    family=FAMILIA,
    table=GoalkeeperAction,
    aggregation=Aggregation.AVERAGE,
    predicate=(ENFRENTOU_CHUTE,),
    value_column=GoalkeeperAction.shot_distance_m,
    unit=Unit.METERS,
    per_90=False,
    positions=GOLEIROS,
)
