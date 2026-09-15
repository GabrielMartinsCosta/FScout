"""Métricas gerais de participação, definidas sobre a própria tabela de eventos.

São as únicas que não saem de uma projeção: contam ações de qualquer tipo, filtradas por
setor do campo ou por pressão do adversário. Servem de denominador para leituras de volume
("quanto o atleta participa") e de base para o mapa de calor.
"""

from __future__ import annotations

from fscout.db.models import Event
from fscout.domain.enums import EventType
from fscout.domain.pitch import (
    PENALTY_AREA_MAX_Y,
    PENALTY_AREA_MIN_X,
    PENALTY_AREA_MIN_Y,
    VerticalThird,
)
from fscout.metrics.registry import DE_LINHA, metric

FAMILIA = "geral"

COM_BOLA = Event.type.in_((EventType.PASS, EventType.SHOT, EventType.DRIBBLE, EventType.CARRY))
NA_AREA_ADVERSARIA = (
    (Event.x >= PENALTY_AREA_MIN_X)
    & (Event.y >= PENALTY_AREA_MIN_Y)
    & (Event.y <= PENALTY_AREA_MAX_Y)
)

metric(
    key="acoes_com_bola",
    label="Ações com bola",
    family=FAMILIA,
    table=Event,
    predicate=(COM_BOLA,),
    description="Passes, conduções, dribles e finalizações.",
)
metric(
    key="acoes_no_terco_ofensivo",
    label="Ações no terço ofensivo",
    family=FAMILIA,
    table=Event,
    predicate=(COM_BOLA, Event.third == VerticalThird.ATTACKING),
)
metric(
    key="acoes_na_area_adversaria",
    label="Ações na área adversária",
    family=FAMILIA,
    table=Event,
    predicate=(COM_BOLA, NA_AREA_ADVERSARIA),
    positions=DE_LINHA,
)
metric(
    key="acoes_sob_pressao",
    label="Ações sob pressão",
    family=FAMILIA,
    table=Event,
    predicate=(COM_BOLA, Event.under_pressure.is_(True)),
    description="Ações executadas com um adversário pressionando.",
)
metric(
    key="perdas_de_posse",
    label="Perdas de posse",
    family=FAMILIA,
    table=Event,
    predicate=(Event.type.in_((EventType.MISCONTROL, EventType.DISPOSSESSED)),),
    higher_is_better=False,
    description="Domínios errados e bolas perdidas em disputa.",
)
metric(
    key="conducoes",
    label="Conduções",
    family=FAMILIA,
    table=Event,
    predicate=(Event.type == EventType.CARRY,),
)
