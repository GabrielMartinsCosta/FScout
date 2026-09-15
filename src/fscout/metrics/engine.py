"""Motor de avaliação: transforma `MetricSpec` mais `Slice` em números.

Uma consulta por métrica, agrupada por atleta, com os filtros do recorte aplicados sempre no
mesmo lugar. O motor não conhece nenhuma estatística em particular — ele sabe contar, somar,
tirar média e dividir, e é o catálogo que diz o que contar.

Três cuidados que valem para toda métrica e por isso vivem aqui, e não em cada definição:

- **Disputa de pênaltis** fica de fora, a menos que a métrica peça o contrário.
- **Piso de minutagem** é aplicado depois da agregação: comparar quem jogou 90 minutos com
  quem jogou 3.000 em valor absoluto não diz nada.
- **Percentil** é calculado dentro da população avaliada, respeitando o sentido da métrica
  (em gols sofridos, menos é melhor).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from fscout.db.models import Event
from fscout.metrics.context import Slice, appearance_conditions, join_context, minutes_query
from fscout.metrics.registry import Aggregation, MetricSpec, MetricValue

PER_90_MINUTES = 90

# A disputa de penaltis e um periodo proprio: fica de fora por padrao.
SHOOTOUT_PERIOD = 5


def minutes_by_player(session: Session, recorte: Slice) -> dict[int, int]:
    """Minutos de cada atleta dentro do recorte."""
    return {
        player_id: int(minutos or 0)
        for player_id, minutos in session.execute(minutes_query(recorte)).all()
    }


def evaluate(
    session: Session,
    specs: Sequence[MetricSpec],
    recorte: Slice,
    *,
    minutes: Mapping[int, int] | None = None,
    with_percentiles: bool = True,
) -> dict[int, dict[str, MetricValue]]:
    """Avalia as métricas pedidas e devolve os valores por atleta.

    Atletas sem nenhuma ação da métrica ainda aparecem, com valor zero, desde que tenham
    minutagem no recorte: ausência de chute é informação, não ausência de dado.
    """
    minutos = dict(minutes) if minutes is not None else minutes_by_player(session, recorte)
    if recorte.min_minutes is not None:
        minutos = {
            player_id: total for player_id, total in minutos.items() if total >= recorte.min_minutes
        }

    resultados: dict[int, dict[str, MetricValue]] = {player_id: {} for player_id in minutos}
    for spec in specs:
        brutos = _evaluate_one(session, spec, recorte)
        for player_id, total_minutos in minutos.items():
            valor, amostra = brutos.get(player_id, (_valor_vazio(spec), 0))
            if amostra < spec.min_sample:
                valor = None
            resultados[player_id][spec.key] = MetricValue(
                key=spec.key,
                value=valor,
                sample=amostra,
                minutes=total_minutos,
                per_90=_por_90(spec, valor, total_minutos),
            )
        if with_percentiles:
            _preencher_percentis(spec, resultados)
    return resultados


def _evaluate_one(
    session: Session, spec: MetricSpec, recorte: Slice
) -> dict[int, tuple[float | None, int]]:
    consulta = _montar_consulta(spec, recorte)
    brutos: dict[int, tuple[float | None, int]] = {}
    for player_id, valor, amostra in session.execute(consulta).all():
        if player_id is None:
            continue
        brutos[int(player_id)] = (None if valor is None else float(valor), int(amostra or 0))
    return brutos


def _montar_consulta(spec: MetricSpec, recorte: Slice) -> Select[Any]:
    origem = spec.table
    valor, amostra = _expressoes(spec)
    consulta = select(origem.player_id, valor, amostra).select_from(origem)
    if origem is not Event:
        # As projeções guardam `event_id`; métrica sobre o próprio evento dispensa o join.
        consulta = consulta.join(Event, Event.id == origem.event_id)
    consulta = join_context(consulta, origem)

    condicoes = list(appearance_conditions(recorte)) + list(spec.predicate)
    if not spec.include_shootout:
        if hasattr(origem, "is_shootout"):
            condicoes.append(origem.is_shootout.is_(False))
        elif origem is Event:
            condicoes.append(Event.period != SHOOTOUT_PERIOD)
    for condicao in condicoes:
        consulta = consulta.where(condicao)
    return consulta.group_by(origem.player_id)


def _expressoes(spec: MetricSpec) -> tuple[Any, Any]:
    """Expressão do valor e do tamanho da amostra, conforme a agregação."""
    amostra = func.count()
    if spec.aggregation is Aggregation.COUNT:
        return amostra, amostra
    if spec.aggregation is Aggregation.SUM:
        return func.sum(spec.value_column), amostra
    if spec.aggregation is Aggregation.AVERAGE:
        return func.avg(spec.value_column), amostra
    sucessos = func.sum(case((and_(*spec.numerator), 1), else_=0))
    return sucessos * 1.0 / func.nullif(amostra, 0), amostra


def _valor_vazio(spec: MetricSpec) -> float | None:
    """Sem nenhuma linha, contagem e soma valem zero; média e razão não existem."""
    return 0.0 if spec.aggregation in (Aggregation.COUNT, Aggregation.SUM) else None


def _por_90(spec: MetricSpec, valor: float | None, minutos: int) -> float | None:
    if not spec.per_90 or valor is None or minutos <= 0:
        return None
    return round(valor * PER_90_MINUTES / minutos, 4)


def _preencher_percentis(spec: MetricSpec, resultados: dict[int, dict[str, MetricValue]]) -> None:
    """Percentil dentro da população avaliada, pelo posto médio em caso de empate.

    Usa o valor por 90 minutos quando a métrica admite normalização; caso contrário, o valor
    bruto. Métrica em que menos é melhor tem a escala invertida.
    """
    medidas = [resultado[spec.key] for resultado in resultados.values() if spec.key in resultado]
    valores = [
        (medida, medida.per_90 if spec.per_90 and medida.per_90 is not None else medida.value)
        for medida in medidas
    ]
    presentes = [(medida, valor) for medida, valor in valores if valor is not None]
    if len(presentes) < 2:
        return

    ordenados = sorted(valor for _, valor in presentes)
    total = len(ordenados)
    for medida, valor in presentes:
        menores = sum(1 for outro in ordenados if outro < valor)
        iguais = sum(1 for outro in ordenados if outro == valor)
        posicao = (menores + iguais / 2) / total
        medida.percentile = round(100 * (posicao if spec.higher_is_better else 1 - posicao), 1)
