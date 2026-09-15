"""Métricas de falta e cartão.

Os recortes de campo usam a perspectiva de quem cometeu a falta: "campo de defesa" é o campo
do próprio atleta. Eventos sem coordenada — cartão por reclamação, por exemplo — ficam de
fora dos recortes espaciais, e não são contados como se estivessem em algum lugar.
"""

from __future__ import annotations

from fscout.db.models import DisciplinaryAction
from fscout.domain.enums import CardType
from fscout.metrics.registry import metric

FAMILIA = "disciplina"

FALTA_COMETIDA = DisciplinaryAction.is_foul_committed.is_(True)

metric(
    key="faltas_cometidas",
    label="Faltas cometidas",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(FALTA_COMETIDA,),
    higher_is_better=False,
)
metric(
    key="faltas_sofridas",
    label="Faltas sofridas",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.is_foul_won.is_(True),),
)
metric(
    key="cartoes_amarelos",
    label="Cartões amarelos",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.card == CardType.YELLOW,),
    higher_is_better=False,
)
metric(
    key="cartoes_vermelhos",
    label="Cartões vermelhos",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.card.in_((CardType.RED, CardType.SECOND_YELLOW)),),
    higher_is_better=False,
    description="Inclui o segundo amarelo.",
)
metric(
    key="cartoes_no_campo_de_defesa",
    label="Cartões no próprio campo",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.card.is_not(None), DisciplinaryAction.in_own_half.is_(True)),
    higher_is_better=False,
)
metric(
    key="cartoes_no_campo_de_ataque",
    label="Cartões no campo adversário",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.card.is_not(None), DisciplinaryAction.in_own_half.is_(False)),
    higher_is_better=False,
)
metric(
    key="faltas_perto_da_propria_area",
    label="Faltas perto da própria área",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(FALTA_COMETIDA, DisciplinaryAction.near_own_penalty_area.is_(True)),
    higher_is_better=False,
    description="Dentro da própria área ou a até dez metros dela.",
)
metric(
    key="penaltis_cometidos",
    label="Pênaltis cometidos",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.conceded_penalty.is_(True),),
    higher_is_better=False,
)
metric(
    key="penaltis_sofridos",
    label="Pênaltis sofridos",
    family=FAMILIA,
    table=DisciplinaryAction,
    predicate=(DisciplinaryAction.won_penalty.is_(True),),
)
