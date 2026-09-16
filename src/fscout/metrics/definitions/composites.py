"""Métricas compostas: as que cruzam famílias.

Participação em gols soma finalizações com passes, que saem de tabelas diferentes; minutos
por gol divide a minutagem do recorte por uma contagem. Nenhuma delas cabe numa consulta a
uma tabela só, e por isso são definidas a partir de métricas já calculadas.

"Minutos por gol" é invertida de propósito: menos é melhor, e o atleta que não marcou não
recebe um valor infinito — recebe nulo, que a interface mostra como ausência.
"""

from __future__ import annotations

from collections.abc import Mapping

from fscout.metrics.registry import DE_LINHA, Unit, composite

FAMILIA = "geral"

Valores = Mapping[str, float | None]


def _soma(valores: Valores, chaves: tuple[str, ...]) -> float | None:
    parcelas = [valores.get(chave) for chave in chaves]
    if any(parcela is None for parcela in parcelas):
        return None
    return float(sum(parcela for parcela in parcelas if parcela is not None))


def _minutos_por(valores: Valores, chaves: tuple[str, ...], minutos: int) -> float | None:
    total = _soma(valores, chaves)
    if not total or minutos <= 0:
        return None
    return round(minutos / total, 1)


composite(
    key="participacao_em_gols",
    label="Participação em gols",
    family=FAMILIA,
    inputs=("gols", "assistencias"),
    formula=lambda valores, _: _soma(valores, ("gols", "assistencias")),
    positions=DE_LINHA,
    description="Gols mais assistências.",
)
composite(
    key="minutos_por_gol",
    label="Minutos por gol",
    family=FAMILIA,
    inputs=("gols",),
    formula=lambda valores, minutos: _minutos_por(valores, ("gols",), minutos),
    unit=Unit.MINUTES,
    per_90=False,
    higher_is_better=False,
    positions=DE_LINHA,
    description="Minutagem do recorte dividida pelos gols. Nulo para quem não marcou.",
)
composite(
    key="minutos_por_participacao_em_gol",
    label="Minutos por participação em gol",
    family=FAMILIA,
    inputs=("gols", "assistencias"),
    formula=lambda valores, minutos: _minutos_por(valores, ("gols", "assistencias"), minutos),
    unit=Unit.MINUTES,
    per_90=False,
    higher_is_better=False,
    positions=DE_LINHA,
    description="Minutagem dividida por gols mais assistências.",
)
composite(
    key="minutos_por_finalizacao",
    label="Minutos por finalização",
    family=FAMILIA,
    inputs=("finalizacoes",),
    formula=lambda valores, minutos: _minutos_por(valores, ("finalizacoes",), minutos),
    unit=Unit.MINUTES,
    per_90=False,
    higher_is_better=False,
    positions=DE_LINHA,
)
composite(
    key="acoes_defensivas",
    label="Ações defensivas",
    family="defesa",
    inputs=("desarmes", "interceptacoes", "cortes", "bloqueios"),
    formula=lambda valores, _: _soma(
        valores, ("desarmes", "interceptacoes", "cortes", "bloqueios")
    ),
    description="Desarmes, interceptações, cortes e bloqueios somados.",
)
