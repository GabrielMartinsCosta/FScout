"""Métricas de finalização.

Cobre a lista pedida na especificação: gols por pé, de cabeça, dentro e fora da área, na
pequena área, de pênalti, de falta, acrobáticos, vindos de escanteio ou de cruzamento, o
canto do gol e os aproveitamentos.

Cada métrica é um filtro sobre `shots` mais, quando precisa, um sobre `events` — nenhuma
delas exige coluna nova no banco. Cobranças da disputa de pênaltis ficam de fora por padrão,
regra aplicada pelo motor.
"""

from __future__ import annotations

from sqlalchemy import case, func, select

from fscout.db.models import Event, Pass, Shot
from fscout.domain.enums import BodyPart, PlayPattern, ShotTechnique, ShotType
from fscout.metrics.registry import (
    DE_LINHA,
    Aggregation,
    Unit,
    metric,
)

FAMILIA = "finalizacao"

# Blocos reutilizados pelas definições abaixo.
GOL = Shot.is_goal.is_(True)
NO_ALVO = Shot.is_on_target.is_(True)
JOGO_CORRIDO = Shot.shot_type == ShotType.OPEN_PLAY
FORA_DA_AREA = Shot.in_penalty_area.is_(False)
DENTRO_DA_AREA = Shot.in_penalty_area.is_(True)
PEQUENA_AREA = Shot.in_six_yard_box.is_(True)
ACROBATICO = Shot.technique.in_(
    (ShotTechnique.OVERHEAD_KICK, ShotTechnique.DIVING_HEADER, ShotTechnique.VOLLEY)
)

# "Gol vindo de cruzamento" é o gol cujo passe-chave foi um cruzamento: a ligação existe em
# `shots.key_pass_event_id`, e não numa coluna de cruzamento na finalização.
DE_CRUZAMENTO = Shot.key_pass_event_id.in_(select(Pass.event_id).where(Pass.is_cross.is_(True)))

# ----------------------------------------------------------------------------------------
# Volume
# ----------------------------------------------------------------------------------------

metric(
    key="gols",
    label="Gols",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL,),
    description="Gols marcados, sem contar a disputa de pênaltis.",
)
metric(
    key="finalizacoes",
    label="Finalizações",
    family=FAMILIA,
    table=Shot,
    description="Total de finalizações.",
)
metric(
    key="finalizacoes_no_alvo",
    label="Finalizações no alvo",
    family=FAMILIA,
    table=Shot,
    predicate=(NO_ALVO,),
)
metric(
    key="gols_jogo_corrido",
    label="Gols em jogo corrido",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, JOGO_CORRIDO),
    description="Exclui pênaltis, faltas e cobranças diretas de escanteio.",
)

# ----------------------------------------------------------------------------------------
# Parte do corpo
# ----------------------------------------------------------------------------------------

metric(
    key="gols_canhota",
    label="Gols de perna esquerda",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Shot.body_part == BodyPart.LEFT_FOOT),
)
metric(
    key="gols_destra",
    label="Gols de perna direita",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Shot.body_part == BodyPart.RIGHT_FOOT),
)
metric(
    key="gols_de_cabeca",
    label="Gols de cabeça",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Shot.body_part == BodyPart.HEAD),
)
metric(
    key="finalizacoes_de_cabeca",
    label="Finalizações de cabeça",
    family=FAMILIA,
    table=Shot,
    predicate=(Shot.body_part == BodyPart.HEAD,),
)

# ----------------------------------------------------------------------------------------
# Região do campo
# ----------------------------------------------------------------------------------------

metric(
    key="gols_fora_da_area",
    label="Gols de fora da área",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, FORA_DA_AREA),
)
metric(
    key="gols_dentro_da_area",
    label="Gols dentro da área",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, DENTRO_DA_AREA),
)
metric(
    key="gols_na_pequena_area",
    label="Gols na pequena área",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, PEQUENA_AREA),
)
metric(
    key="finalizacoes_fora_da_area",
    label="Finalizações de fora da área",
    family=FAMILIA,
    table=Shot,
    predicate=(FORA_DA_AREA,),
)
metric(
    key="distancia_media_da_finalizacao",
    min_sample=5,
    label="Distância média da finalização",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.AVERAGE,
    value_column=Shot.distance_m,
    unit=Unit.METERS,
    per_90=False,
    higher_is_better=False,
    description="Média da distância até o gol, em metros.",
)

# ----------------------------------------------------------------------------------------
# Origem da jogada
# ----------------------------------------------------------------------------------------

metric(
    key="gols_de_escanteio",
    label="Gols vindos de escanteio",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Event.play_pattern == PlayPattern.FROM_CORNER),
)
metric(
    key="gols_de_cruzamento",
    label="Gols vindos de cruzamento",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, DE_CRUZAMENTO),
    description="Gol cuja finalização foi assistida por um cruzamento.",
)
metric(
    key="gols_de_contra_ataque",
    label="Gols em contra-ataque",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Event.play_pattern == PlayPattern.FROM_COUNTER),
)
metric(
    key="gols_acrobaticos",
    label="Gols acrobáticos",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, ACROBATICO),
    description="Bicicleta, voleio ou cabeceio em mergulho.",
)

# ----------------------------------------------------------------------------------------
# Bola parada
# ----------------------------------------------------------------------------------------

metric(
    key="penaltis_cobrados",
    label="Pênaltis cobrados",
    family=FAMILIA,
    table=Shot,
    predicate=(Shot.shot_type == ShotType.PENALTY,),
)
metric(
    key="gols_de_penalti",
    label="Gols de pênalti",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Shot.shot_type == ShotType.PENALTY),
)
metric(
    key="aproveitamento_de_penaltis",
    min_sample=3,
    label="Aproveitamento de pênaltis",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.RATIO,
    predicate=(Shot.shot_type == ShotType.PENALTY,),
    numerator=(GOL,),
    unit=Unit.PERCENT,
    per_90=False,
)
metric(
    key="gols_de_falta",
    label="Gols de falta",
    family=FAMILIA,
    table=Shot,
    predicate=(GOL, Shot.shot_type == ShotType.FREE_KICK),
)
metric(
    key="faltas_cobradas_ao_gol",
    label="Faltas cobradas em direção ao gol",
    family=FAMILIA,
    table=Shot,
    predicate=(Shot.shot_type == ShotType.FREE_KICK,),
)

# ----------------------------------------------------------------------------------------
# Aproveitamento e qualidade
# ----------------------------------------------------------------------------------------

metric(
    key="aproveitamento_de_finalizacoes",
    min_sample=10,
    label="Finalizações no alvo",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.RATIO,
    numerator=(NO_ALVO,),
    unit=Unit.PERCENT,
    per_90=False,
    description="Proporção das finalizações que foram ao gol.",
)
metric(
    key="conversao_de_finalizacoes",
    min_sample=10,
    label="Conversão de finalizações",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.RATIO,
    numerator=(GOL,),
    unit=Unit.PERCENT,
    per_90=False,
    description="Proporção das finalizações que viraram gol.",
)
metric(
    key="bolas_na_trave",
    label="Bolas na trave",
    family=FAMILIA,
    table=Shot,
    predicate=(Shot.hit_post.is_(True),),
)
metric(
    key="finalizacoes_bloqueadas",
    label="Finalizações bloqueadas",
    family=FAMILIA,
    table=Shot,
    predicate=(Shot.was_blocked.is_(True),),
    higher_is_better=False,
)
metric(
    key="xg",
    label="Gols esperados (xG)",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.SUM,
    value_column=Shot.xg,
    unit=Unit.XG,
    description="Soma do xG das finalizações, conforme o modelo da StatsBomb.",
)
metric(
    key="xg_por_finalizacao",
    min_sample=5,
    label="xG por finalização",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.AVERAGE,
    value_column=Shot.xg,
    unit=Unit.XG,
    per_90=False,
    description="Qualidade média das chances criadas para si.",
)
metric(
    key="saldo_de_gols_sobre_xg",
    label="Gols acima do esperado",
    family=FAMILIA,
    table=Shot,
    aggregation=Aggregation.SUM,
    value_column=case((GOL, 1.0), else_=0.0) - func.coalesce(Shot.xg, 0.0),
    unit=Unit.XG,
    positions=DE_LINHA,
    description="Gols marcados menos xG acumulado: finalização acima ou abaixo da chance criada.",
)
