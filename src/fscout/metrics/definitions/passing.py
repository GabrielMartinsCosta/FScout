"""Métricas de passe, assistência e criação.

Cobre o que a especificação pede: assistências, pré-assistências, passes decisivos, pé
usado, alcance curto, médio e longo, direção, cruzamentos, passes que entram na área e na
pequena área, bola parada e aproveitamento por faixa de distância.

Passe progressivo e entrada na área são atributos **geométricos da tentativa**; quando a
métrica quer só os que deram certo, o filtro de conclusão entra explicitamente.
"""

from __future__ import annotations

from fscout.db.models import Pass
from fscout.domain.enums import BodyPart, PassType
from fscout.metrics.registry import Aggregation, Unit, metric

FAMILIA = "passe"

COMPLETO = Pass.is_complete.is_(True)
JOGO_CORRIDO = Pass.pass_type == PassType.OPEN_PLAY
CURTO = Pass.length_bucket == "short"
MEDIO = Pass.length_bucket == "medium"
LONGO = Pass.length_bucket == "long"
PARA_FRENTE = Pass.direction == "forward"

# ----------------------------------------------------------------------------------------
# Criação
# ----------------------------------------------------------------------------------------

metric(
    key="assistencias",
    label="Assistências",
    family=FAMILIA,
    table=Pass,
    predicate=(Pass.is_goal_assist.is_(True),),
    description="Passe imediatamente anterior ao gol.",
)
metric(
    key="pre_assistencias",
    label="Pré-assistências",
    family=FAMILIA,
    table=Pass,
    predicate=(Pass.is_pre_assist.is_(True),),
    description="Passe para quem deu a assistência, na mesma posse.",
)
metric(
    key="passes_decisivos",
    label="Passes decisivos",
    family=FAMILIA,
    table=Pass,
    predicate=(Pass.is_shot_assist.is_(True),),
    description="Passes que terminaram em finalização, inclusive os que viraram gol.",
)
metric(
    key="passes_decisivos_de_bola_parada",
    label="Passes decisivos de bola parada",
    family=FAMILIA,
    table=Pass,
    predicate=(
        Pass.is_shot_assist.is_(True),
        Pass.pass_type.in_((PassType.CORNER, PassType.FREE_KICK)),
    ),
)

# ----------------------------------------------------------------------------------------
# Volume e aproveitamento
# ----------------------------------------------------------------------------------------

metric(key="passes_tentados", label="Passes tentados", family=FAMILIA, table=Pass)
metric(
    key="passes_certos",
    label="Passes certos",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO,),
)
metric(
    key="aproveitamento_de_passes",
    min_sample=50,
    label="Acerto no passe",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.RATIO,
    numerator=(COMPLETO,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="aproveitamento_de_passes_curtos",
    min_sample=20,
    label="Acerto no passe curto",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.RATIO,
    predicate=(CURTO,),
    numerator=(COMPLETO,),
    unit=Unit.PERCENT,
    per_90=False,
    description="Até 15 metros.",
)
metric(
    key="aproveitamento_de_passes_medios",
    min_sample=20,
    label="Acerto no passe médio",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.RATIO,
    predicate=(MEDIO,),
    numerator=(COMPLETO,),
    unit=Unit.PERCENT,
    per_90=False,
    description="Entre 15 e 30 metros.",
)
metric(
    key="aproveitamento_de_passes_longos",
    min_sample=10,
    label="Acerto no passe longo",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.RATIO,
    predicate=(LONGO,),
    numerator=(COMPLETO,),
    unit=Unit.PERCENT,
    per_90=False,
    description="Acima de 30 metros.",
)
metric(
    key="distancia_media_do_passe",
    min_sample=20,
    label="Distância média do passe",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.AVERAGE,
    value_column=Pass.length_m,
    unit=Unit.METERS,
    per_90=False,
)

# ----------------------------------------------------------------------------------------
# Progressão e penetração
# ----------------------------------------------------------------------------------------

metric(
    key="passes_progressivos",
    label="Passes progressivos certos",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.is_progressive.is_(True)),
    description="Critério Wyscout de aproximação ao gol, contando só os completos.",
)
metric(
    key="passes_para_a_area",
    label="Passes certos para dentro da área",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.into_penalty_area.is_(True)),
)
metric(
    key="passes_para_a_pequena_area",
    label="Passes certos para a pequena área",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.into_six_yard_box.is_(True)),
)
metric(
    key="passes_para_frente",
    label="Passes certos para frente",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, PARA_FRENTE),
)
metric(
    key="bolas_em_profundidade",
    label="Bolas em profundidade certas",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.is_through_ball.is_(True)),
)

# ----------------------------------------------------------------------------------------
# Cruzamento e bola parada
# ----------------------------------------------------------------------------------------

metric(
    key="cruzamentos",
    label="Cruzamentos",
    family=FAMILIA,
    table=Pass,
    predicate=(Pass.is_cross.is_(True),),
)
metric(
    key="aproveitamento_de_cruzamentos",
    min_sample=10,
    label="Acerto no cruzamento",
    family=FAMILIA,
    table=Pass,
    aggregation=Aggregation.RATIO,
    predicate=(Pass.is_cross.is_(True),),
    numerator=(COMPLETO,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="escanteios_cobrados",
    label="Escanteios cobrados",
    family=FAMILIA,
    table=Pass,
    predicate=(Pass.pass_type == PassType.CORNER,),
)
metric(
    key="passes_de_canhota",
    label="Passes certos de perna esquerda",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.body_part == BodyPart.LEFT_FOOT),
)
metric(
    key="passes_de_cabeca",
    label="Passes certos de cabeça",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.body_part == BodyPart.HEAD),
)
metric(
    key="inversoes_de_jogo",
    label="Inversões de jogo certas",
    family=FAMILIA,
    table=Pass,
    predicate=(COMPLETO, Pass.is_switch.is_(True)),
    description="Mudança de lado do campo em um único passe.",
)
