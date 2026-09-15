"""Métricas de drible e criação individual.

As consequências do drible — chute, gol, passe decisivo, assistência, pré-assistência e
falta sofrida — foram resolvidas na ingestão percorrendo a posse (ver
`fscout.ingestion.statsbomb.chains`), com janela de dez segundos na mesma posse.
"""

from __future__ import annotations

from fscout.db.models import Dribble, Event
from fscout.domain.pitch import Lane, VerticalThird
from fscout.metrics.registry import DE_LINHA, Aggregation, Unit, metric

FAMILIA = "drible"

CERTO = Dribble.is_complete.is_(True)

metric(key="dribles_tentados", label="Dribles tentados", family=FAMILIA, table=Dribble)
metric(
    key="dribles_certos",
    label="Dribles certos",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO,),
)
metric(
    key="aproveitamento_de_dribles",
    min_sample=10,
    label="Acerto no drible",
    family=FAMILIA,
    table=Dribble,
    aggregation=Aggregation.RATIO,
    numerator=(CERTO,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="dribles_na_area",
    label="Dribles certos dentro da área",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Dribble.in_penalty_area.is_(True)),
)
metric(
    key="dribles_no_terco_ofensivo",
    label="Dribles certos no terço ofensivo",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Event.third == VerticalThird.ATTACKING),
)
metric(
    key="dribles_pelas_pontas",
    label="Dribles certos pelas pontas",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Event.lane.in_((Lane.LEFT_WING, Lane.RIGHT_WING))),
)
metric(
    key="dribles_que_geraram_finalizacao",
    label="Dribles que geraram finalização",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Dribble.led_to_shot.is_(True)),
)
metric(
    key="dribles_que_geraram_gol",
    label="Dribles que geraram gol",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Dribble.led_to_goal.is_(True)),
)
metric(
    key="dribles_que_geraram_passe_decisivo",
    label="Dribles que geraram passe decisivo",
    family=FAMILIA,
    table=Dribble,
    predicate=(CERTO, Dribble.led_to_key_pass.is_(True)),
)
metric(
    key="faltas_sofridas_apos_drible",
    label="Faltas sofridas após drible",
    family=FAMILIA,
    table=Dribble,
    predicate=(Dribble.drew_foul.is_(True),),
    positions=DE_LINHA,
)
metric(
    key="canetas",
    label="Canetas",
    family=FAMILIA,
    table=Dribble,
    predicate=(Dribble.nutmeg.is_(True),),
)
