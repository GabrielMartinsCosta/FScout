"""Métricas defensivas e de duelo.

Desarme, interceptação, corte, bloqueio, recuperação, pressão e duelo aéreo chegam da fonte
como tipos distintos e foram normalizados num eixo único na ingestão, o que permite compor
índices agregados sem unir seis tabelas.

O duelo aéreo ganho merece nota: a fonte só registra como evento o duelo aéreo **perdido**;
o ganho aparece como marca em passes, cortes e finalizações. A ingestão cria as duas linhas,
e é por isso que aproveitamento aéreo é uma razão sobre `defensive_actions`, e não uma
contagem de eventos de duelo.
"""

from __future__ import annotations

from fscout.db.models import DefensiveAction, Event
from fscout.domain.enums import DefensiveActionType
from fscout.domain.pitch import VerticalThird
from fscout.metrics.registry import DE_LINHA, Aggregation, Unit, metric

FAMILIA = "defesa"

COM_SUCESSO = DefensiveAction.is_successful.is_(True)
AEREO = DefensiveAction.action_type == DefensiveActionType.AERIAL_DUEL

metric(
    key="desarmes",
    label="Desarmes certos",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.TACKLE, COM_SUCESSO),
)
metric(
    key="aproveitamento_em_desarmes",
    min_sample=10,
    label="Acerto no desarme",
    family=FAMILIA,
    table=DefensiveAction,
    aggregation=Aggregation.RATIO,
    predicate=(DefensiveAction.action_type == DefensiveActionType.TACKLE,),
    numerator=(COM_SUCESSO,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="interceptacoes",
    label="Interceptações",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.INTERCEPTION, COM_SUCESSO),
)
metric(
    key="cortes",
    label="Cortes",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.CLEARANCE,),
)
metric(
    key="bloqueios",
    label="Bloqueios",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.BLOCK,),
)
metric(
    key="roubadas_de_bola",
    label="Recuperações de bola",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.BALL_RECOVERY, COM_SUCESSO),
)
metric(
    key="pressoes",
    label="Pressões",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.PRESSURE,),
)
metric(
    key="pressoes_no_campo_de_ataque",
    label="Pressões no terço ofensivo",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(
        DefensiveAction.action_type == DefensiveActionType.PRESSURE,
        Event.third == VerticalThird.ATTACKING,
    ),
)
metric(
    key="duelos_aereos_ganhos",
    label="Duelos aéreos ganhos",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(AEREO, COM_SUCESSO),
)
metric(
    key="aproveitamento_aereo",
    min_sample=10,
    label="Acerto no duelo aéreo",
    family=FAMILIA,
    table=DefensiveAction,
    aggregation=Aggregation.RATIO,
    predicate=(AEREO,),
    numerator=(COM_SUCESSO,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="acoes_defensivas_na_propria_area",
    label="Ações defensivas na própria área",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.in_own_penalty_area.is_(True),),
)
metric(
    key="dribles_sofridos",
    label="Dribles sofridos",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.DRIBBLED_PAST,),
    higher_is_better=False,
    positions=DE_LINHA,
)
metric(
    key="erros_que_geraram_perigo",
    label="Erros que geraram perigo",
    family=FAMILIA,
    table=DefensiveAction,
    predicate=(DefensiveAction.action_type == DefensiveActionType.ERROR,),
    higher_is_better=False,
)
