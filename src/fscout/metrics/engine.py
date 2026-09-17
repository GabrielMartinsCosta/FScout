"""Motor de avaliação: transforma `MetricSpec` mais `Slice` em números.

Uma consulta por métrica, agrupada por atleta, com os filtros do recorte aplicados sempre no
mesmo lugar. O motor não conhece nenhuma estatística em particular — ele sabe contar, somar,
tirar média e dividir, e é o catálogo que diz o que contar.

Quatro cuidados que valem para toda métrica e por isso vivem aqui, e não em cada definição:

- **Disputa de pênaltis** fica de fora, a menos que a métrica peça o contrário.
- **Piso de minutagem** é aplicado depois da agregação: comparar quem jogou 90 minutos com
  quem jogou 3.000 em valor absoluto não diz nada.
- **Amostra insuficiente** não vira número: razão e média abaixo do mínimo saem nulas.
- **Percentil** é calculado dentro do grupo de posição do atleta, respeitando o sentido da
  métrica (em gols sofridos, menos é melhor). Comparar o passe de um zagueiro com o de um
  atacante produziria um ranking sem significado.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from fscout.db.models import Event
from fscout.domain.enums import DataTier, PositionGroup
from fscout.metrics.context import (
    Slice,
    appearance_conditions,
    join_context,
    minutes_query,
    position_groups_query,
)
from fscout.metrics.registry import (
    REGISTRY,
    Aggregation,
    CompositeSpec,
    MetricSpec,
    MetricValue,
    Spec,
)

PER_90_MINUTES = 90

# A disputa de pênaltis é um período próprio: fica de fora por padrão.
SHOOTOUT_PERIOD = 5

# Abaixo de dois atletas no grupo, percentil não significa nada.
MIN_POPULATION = 2


def minutes_by_player(session: Session, recorte: Slice) -> dict[int, int]:
    """Minutos de cada atleta dentro do recorte."""
    return {
        player_id: int(minutos or 0)
        for player_id, minutos in session.execute(minutes_query(recorte)).all()
    }


def position_groups_by_player(session: Session, recorte: Slice) -> dict[int, PositionGroup | None]:
    """Grupo de posição de cada atleta: aquele em que mais jogou dentro do recorte.

    É o recorte que decide, e não o histórico: quem atuou de lateral na competição analisada
    é comparado com laterais, mesmo que jogue de meia no clube.
    """
    melhor: dict[int, tuple[int, PositionGroup | None]] = {}
    for player_id, grupo, minutos in session.execute(position_groups_query(recorte)).all():
        total = int(minutos or 0)
        if player_id not in melhor or total > melhor[player_id][0]:
            melhor[player_id] = (total, grupo)
    return {player_id: grupo for player_id, (_, grupo) in melhor.items()}


def evaluate(
    session: Session,
    specs: Sequence[Spec],
    recorte: Slice,
    *,
    minutes: Mapping[int, int] | None = None,
    with_percentiles: bool = True,
) -> dict[int, dict[str, MetricValue]]:
    """Avalia as definições pedidas e devolve os valores por atleta.

    Atletas sem nenhuma ação da métrica ainda aparecem, com valor zero, desde que tenham
    minutagem no recorte: ausência de chute é informação, não ausência de dado.

    Métricas compostas trazem junto as métricas de que dependem, que também aparecem no
    resultado.
    """
    minutos = dict(minutes) if minutes is not None else minutes_by_player(session, recorte)
    if recorte.min_minutes is not None:
        minutos = {
            player_id: total for player_id, total in minutos.items() if total >= recorte.min_minutes
        }

    # Métrica que não existe na camada pedida é omitida, e não calculada como zero:
    # "finalizações fora da área" sobre dado agregado não vale zero, vale desconhecido.
    # Quem chamou pode listar as omitidas com `metricas_fora_da_camada`.
    aplicaveis = [spec for spec in specs if spec.applies_to_tier(recorte.data_tier)]
    basicas, compostas = _separar(aplicaveis)
    basicas = [spec for spec in basicas if spec.applies_to_tier(recorte.data_tier)]
    resultados: dict[int, dict[str, MetricValue]] = {player_id: {} for player_id in minutos}

    for spec in basicas:
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

    for spec in compostas:
        for player_id, total_minutos in minutos.items():
            medidas = resultados[player_id]
            entradas = {chave: medidas[chave].value for chave in spec.inputs if chave in medidas}
            valor = spec.formula(entradas, total_minutos)
            medidas[spec.key] = MetricValue(
                key=spec.key,
                value=valor,
                sample=min(
                    (medidas[chave].sample for chave in spec.inputs if chave in medidas), default=0
                ),
                minutes=total_minutos,
                per_90=_por_90(spec, valor, total_minutos),
            )

    if with_percentiles:
        grupos = position_groups_by_player(session, recorte)
        for spec in (*basicas, *compostas):
            _preencher_percentis(spec, resultados, grupos)
    return resultados


def metricas_fora_da_camada(specs: Sequence[Spec], tier: DataTier) -> list[str]:
    """Chaves das métricas pedidas que não se calculam naquela granularidade.

    Existe para a tela poder **nomear** o que ficou de fora. Sumir com a métrica sem
    dizer nada faria o leitor concluir que o atleta não tem aquela ação, quando o caso é
    que a fonte não registra aquilo.
    """
    return [spec.key for spec in specs if not spec.applies_to_tier(tier)]


def _separar(specs: Sequence[Spec]) -> tuple[list[MetricSpec], list[CompositeSpec]]:
    """Separa métricas de compostas e acrescenta as dependências que faltarem."""
    basicas: dict[str, MetricSpec] = {}
    compostas: dict[str, CompositeSpec] = {}
    for spec in specs:
        if isinstance(spec, CompositeSpec):
            compostas[spec.key] = spec
        else:
            basicas[spec.key] = spec
    for spec in compostas.values():
        for chave in spec.inputs:
            dependencia = REGISTRY[chave]
            if chave not in basicas and isinstance(dependencia, MetricSpec):
                basicas[chave] = dependencia
    return list(basicas.values()), list(compostas.values())


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


def _por_90(spec: Spec, valor: float | None, minutos: int) -> float | None:
    if not spec.per_90 or valor is None or minutos <= 0:
        return None
    return round(valor * PER_90_MINUTES / minutos, 4)


def _preencher_percentis(
    spec: Spec,
    resultados: dict[int, dict[str, MetricValue]],
    grupos: Mapping[int, PositionGroup | None],
) -> None:
    """Percentil dentro do grupo de posição, pelo posto médio em caso de empate.

    Atleta cujo grupo não está entre os da métrica não recebe percentil: um atacante não é
    ranqueado em defesas de goleiro.
    """
    por_grupo: dict[PositionGroup, list[MetricValue]] = defaultdict(list)
    for player_id, medidas in resultados.items():
        grupo = grupos.get(player_id)
        medida = medidas.get(spec.key)
        if grupo is None or medida is None or not spec.applies_to(grupo):
            continue
        por_grupo[grupo].append(medida)

    for medidas_do_grupo in por_grupo.values():
        _ranquear(spec, medidas_do_grupo)


def _ranquear(spec: Spec, medidas: Sequence[MetricValue]) -> None:
    """Usa o valor por 90 minutos quando a métrica admite, e o bruto quando não."""
    com_valor = [
        (medida, medida.per_90 if spec.per_90 and medida.per_90 is not None else medida.value)
        for medida in medidas
    ]
    presentes = [(medida, valor) for medida, valor in com_valor if valor is not None]
    if len(presentes) < MIN_POPULATION:
        return

    ordenados = sorted(valor for _, valor in presentes)
    total = len(ordenados)
    for medida, valor in presentes:
        menores = sum(1 for outro in ordenados if outro < valor)
        iguais = sum(1 for outro in ordenados if outro == valor)
        posicao = (menores + iguais / 2) / total
        medida.percentile = round(100 * (posicao if spec.higher_is_better else 1 - posicao), 1)
        medida.population = total
