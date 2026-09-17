"""Métricas da camada agregada: o que dá para calcular sem evento.

Estas métricas existem porque não há dado de evento aberto para o futebol de clubes
sul-americano. Elas rodam sobre `player_match_stats`, onde **cada linha é uma partida com
contadores**, e não uma ação — o que muda a forma de quase tudo:

- Contagem vira **soma de coluna**, e não contagem de linhas.
- Aproveitamento vira `soma(numerador) / soma(denominador)`, a agregação `RATE`, com o
  piso de amostra caindo sobre o denominador: "mínimo de dez finalizações", e não
  "mínimo de dez partidas".

**O que não está aqui é tão importante quanto o que está.** Sem coordenada não existe
"gol de fora da área", "passe para a área" nem "finalização na pequena área"; sem pé
usado não existe "gol de canhota"; sem xG não existe nada derivado dele. São 33 medidas
contra as 108 métricas da camada de evento, e a diferença é a fronteira declarada entre
as duas camadas.

A nota da fonte (`source_rating`) está gravada no banco e **não vira métrica**: é o
resultado de um modelo fechado, e apoiar um número do trabalho nela contradiria a
rastreabilidade que ele defende.

As chaves levam o sufixo `_ag` porque medem a mesma ideia por outro caminho. "Gols" da
camada de evento sai de finalizações individuais com coordenada; "gols" daqui sai de um
total que a fonte já entregou somado. São números diferentes, e misturá-los era
justamente o risco que a separação de camadas existe para impedir.
"""

from __future__ import annotations

from fscout.db.models import PlayerMatchStat as PMS
from fscout.domain.enums import DataTier, PositionGroup
from fscout.metrics.registry import DE_LINHA, Aggregation, Unit, metric

FAMILIA_FINALIZACAO = "finalizacao"
FAMILIA_PASSE = "passe"
FAMILIA_DRIBLE = "drible"
FAMILIA_DEFESA = "defesa"
FAMILIA_DISCIPLINA = "disciplina"
FAMILIA_GOLEIRO = "goleiro"
FAMILIA_GERAL = "geral"

SO_AGREGADO: tuple[DataTier, ...] = (DataTier.AGGREGATE,)
SO_GOLEIRO: tuple[PositionGroup, ...] = (PositionGroup.GOALKEEPER,)


def soma(chave: str, rotulo: str, familia: str, coluna, **extras):
    """Uma contagem da fonte, somada sobre as partidas do recorte."""
    return metric(
        key=chave,
        label=rotulo,
        family=familia,
        table=PMS,
        aggregation=Aggregation.SUM,
        value_column=coluna,
        data_tiers=SO_AGREGADO,
        **extras,
    )


def aproveitamento(
    chave: str, rotulo: str, familia: str, acertos, tentativas, minimo: int, **extras
):
    """Razão entre duas somas, com piso de amostra sobre o denominador."""
    return metric(
        key=chave,
        label=rotulo,
        family=familia,
        table=PMS,
        aggregation=Aggregation.RATE,
        numerator_column=acertos,
        value_column=tentativas,
        unit=Unit.PERCENT,
        per_90=False,
        min_sample=minimo,
        data_tiers=SO_AGREGADO,
        **extras,
    )


# ----------------------------------------------------------------------------------------
# Finalização
# ----------------------------------------------------------------------------------------

soma("gols_ag", "Gols", FAMILIA_FINALIZACAO, PMS.goals, description="Total da fonte agregada.")
soma("finalizacoes_ag", "Finalizações", FAMILIA_FINALIZACAO, PMS.shots_total)
soma("finalizacoes_no_alvo_ag", "Finalizações no alvo", FAMILIA_FINALIZACAO, PMS.shots_on_target)
aproveitamento(
    "aproveitamento_de_finalizacoes_ag",
    "Acerto no alvo",
    FAMILIA_FINALIZACAO,
    PMS.shots_on_target,
    PMS.shots_total,
    minimo=10,
    description="Finalizações no alvo sobre finalizações, com mínimo de dez.",
)
aproveitamento(
    "conversao_de_finalizacoes_ag",
    "Conversão de finalizações",
    FAMILIA_FINALIZACAO,
    PMS.goals,
    PMS.shots_total,
    minimo=10,
    description="Gols por finalização.",
)
soma("gols_de_penalti_ag", "Gols de pênalti", FAMILIA_FINALIZACAO, PMS.penalties_scored)
soma(
    "penaltis_perdidos_ag",
    "Pênaltis perdidos",
    FAMILIA_FINALIZACAO,
    PMS.penalties_missed,
    higher_is_better=False,
)
aproveitamento(
    "aproveitamento_de_penaltis_ag",
    "Aproveitamento de pênaltis",
    FAMILIA_FINALIZACAO,
    PMS.penalties_scored,
    # Cobranças = convertidos mais perdidos. A fonte não traz o total, e somar as duas
    # colunas é o que existe — pênalti defendido entra em "perdido" para quem bate.
    PMS.penalties_scored + PMS.penalties_missed,
    minimo=3,
)

# ----------------------------------------------------------------------------------------
# Passe
# ----------------------------------------------------------------------------------------

soma("assistencias_ag", "Assistências", FAMILIA_PASSE, PMS.assists)
soma("passes_tentados_ag", "Passes tentados", FAMILIA_PASSE, PMS.passes_total)
soma("passes_certos_ag", "Passes certos", FAMILIA_PASSE, PMS.passes_accurate)
soma(
    "passes_decisivos_ag",
    "Passes decisivos",
    FAMILIA_PASSE,
    PMS.passes_key,
    description="Passe que gerou finalização, segundo a fonte.",
)
aproveitamento(
    "aproveitamento_de_passes_ag",
    "Acerto no passe",
    FAMILIA_PASSE,
    PMS.passes_accurate,
    PMS.passes_total,
    minimo=100,
)

# ----------------------------------------------------------------------------------------
# Drible
# ----------------------------------------------------------------------------------------

soma("dribles_tentados_ag", "Dribles tentados", FAMILIA_DRIBLE, PMS.dribbles_attempted)
soma("dribles_certos_ag", "Dribles certos", FAMILIA_DRIBLE, PMS.dribbles_successful)
aproveitamento(
    "aproveitamento_de_dribles_ag",
    "Acerto no drible",
    FAMILIA_DRIBLE,
    PMS.dribbles_successful,
    PMS.dribbles_attempted,
    minimo=10,
)
soma(
    "dribles_sofridos_ag",
    "Dribles sofridos",
    FAMILIA_DRIBLE,
    PMS.dribbled_past,
    higher_is_better=False,
    positions=DE_LINHA,
)

# ----------------------------------------------------------------------------------------
# Defesa e duelo
# ----------------------------------------------------------------------------------------

soma("desarmes_ag", "Desarmes", FAMILIA_DEFESA, PMS.tackles)
soma("bloqueios_ag", "Bloqueios", FAMILIA_DEFESA, PMS.blocks)
soma("interceptacoes_ag", "Interceptações", FAMILIA_DEFESA, PMS.interceptions)
soma("duelos_ag", "Duelos disputados", FAMILIA_DEFESA, PMS.duels_total)
soma("duelos_ganhos_ag", "Duelos ganhos", FAMILIA_DEFESA, PMS.duels_won)
aproveitamento(
    "aproveitamento_em_duelos_ag",
    "Aproveitamento em duelos",
    FAMILIA_DEFESA,
    PMS.duels_won,
    PMS.duels_total,
    minimo=20,
)
soma(
    "acoes_defensivas_ag",
    "Ações defensivas",
    FAMILIA_DEFESA,
    PMS.tackles + PMS.blocks + PMS.interceptions,
    description="Desarmes, bloqueios e interceptações somados.",
)

# ----------------------------------------------------------------------------------------
# Disciplina
# ----------------------------------------------------------------------------------------

soma(
    "faltas_cometidas_ag",
    "Faltas cometidas",
    FAMILIA_DISCIPLINA,
    PMS.fouls_committed,
    higher_is_better=False,
)
soma("faltas_sofridas_ag", "Faltas sofridas", FAMILIA_DISCIPLINA, PMS.fouls_drawn)
soma(
    "cartoes_amarelos_ag",
    "Cartões amarelos",
    FAMILIA_DISCIPLINA,
    PMS.yellow_cards,
    higher_is_better=False,
)
soma(
    "cartoes_vermelhos_ag",
    "Cartões vermelhos",
    FAMILIA_DISCIPLINA,
    PMS.red_cards,
    higher_is_better=False,
)
soma(
    "penaltis_cometidos_ag",
    "Pênaltis cometidos",
    FAMILIA_DISCIPLINA,
    PMS.penalties_committed,
    higher_is_better=False,
)
soma("penaltis_sofridos_ag", "Pênaltis sofridos", FAMILIA_DISCIPLINA, PMS.penalties_won)
soma("impedimentos_ag", "Impedimentos", FAMILIA_DISCIPLINA, PMS.offsides, higher_is_better=False)

# ----------------------------------------------------------------------------------------
# Goleiro
# ----------------------------------------------------------------------------------------

soma("defesas_ag", "Defesas", FAMILIA_GOLEIRO, PMS.saves, positions=SO_GOLEIRO)
soma(
    "gols_sofridos_ag",
    "Gols sofridos",
    FAMILIA_GOLEIRO,
    PMS.goals_conceded,
    higher_is_better=False,
    positions=SO_GOLEIRO,
)
soma(
    "defesas_de_penalti_ag",
    "Defesas de pênalti",
    FAMILIA_GOLEIRO,
    PMS.penalties_saved,
    positions=SO_GOLEIRO,
)
aproveitamento(
    "aproveitamento_em_defesas_ag",
    "Aproveitamento em defesas",
    FAMILIA_GOLEIRO,
    PMS.saves,
    # Finalizações enfrentadas = defendidas mais sofridas. A fonte não traz o total.
    PMS.saves + PMS.goals_conceded,
    minimo=20,
    positions=SO_GOLEIRO,
)

# ----------------------------------------------------------------------------------------
# Geral
# ----------------------------------------------------------------------------------------

soma(
    "participacao_em_gols_ag",
    "Participação em gols",
    FAMILIA_GERAL,
    PMS.goals + PMS.assists,
    positions=DE_LINHA,
    description="Gols mais assistências.",
)
