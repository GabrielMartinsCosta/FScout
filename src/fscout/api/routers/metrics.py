"""Avaliação de métricas e comparação entre atletas."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fscout.api.deps import SessionDep
from fscout.api.routers.catalog import to_definition
from fscout.api.schemas import (
    CompareOut,
    CompareRequest,
    ComparisonCellOut,
    EvaluateRequest,
    MetricValueOut,
    PlayerMetricsOut,
    PlayerSummaryOut,
)
from fscout.db.models import Appearance, Player
from fscout.metrics.context import Slice
from fscout.metrics.engine import evaluate
from fscout.metrics.registry import REGISTRY, MetricValue

router = APIRouter(tags=["métricas"])


def _specs(chaves: list[str]):
    desconhecidas = [chave for chave in chaves if chave not in REGISTRY]
    if desconhecidas:
        raise HTTPException(404, f"métricas desconhecidas: {', '.join(desconhecidas)}")
    if not chaves:
        raise HTTPException(422, "informe ao menos uma métrica")
    return REGISTRY.select(chaves)


def _resumos(session: Session, player_ids: list[int]) -> dict[int, PlayerSummaryOut]:
    if not player_ids:
        return {}
    totais = {
        player_id: (int(partidas or 0), int(minutos or 0))
        for player_id, partidas, minutos in session.execute(
            select(
                Appearance.player_id,
                func.count(func.distinct(Appearance.match_id)),
                func.sum(Appearance.minutes_played),
            )
            .where(Appearance.player_id.in_(player_ids))
            .group_by(Appearance.player_id)
        )
    }
    resumos: dict[int, PlayerSummaryOut] = {}
    for player in session.scalars(select(Player).where(Player.id.in_(player_ids))):
        partidas, minutos = totais.get(player.id, (0, 0))
        resumos[player.id] = PlayerSummaryOut(
            id=player.id,
            name=player.name,
            full_name=player.full_name,
            position_group=player.primary_position_group,
            age=player.age,
            matches=partidas,
            minutes=minutos,
        )
    return resumos


def _valores(medidas: dict[str, MetricValue]) -> dict[str, MetricValueOut]:
    return {
        chave: MetricValueOut(
            key=medida.key,
            value=medida.value,
            per_90=medida.per_90,
            percentile=medida.percentile,
            population=medida.population,
            sample=medida.sample,
            minutes=medida.minutes,
        )
        for chave, medida in medidas.items()
    }


@router.post("/metrics/evaluate", summary="Avalia métricas num recorte")
def evaluate_metrics(session: SessionDep, pedido: EvaluateRequest) -> list[PlayerMetricsOut]:
    """Avalia as métricas pedidas e devolve um registro por atleta do recorte.

    O percentil é calculado sobre toda a população do recorte, e não só sobre os atletas
    pedidos: filtrar antes tornaria o percentil dependente de quem foi consultado.
    """
    specs = _specs(pedido.metrics)
    recorte = pedido.slice.to_slice()
    resultados = evaluate(session, specs, recorte)

    escolhidos = pedido.player_ids or list(resultados)
    resumos = _resumos(session, escolhidos)
    return [
        PlayerMetricsOut(player=resumos[player_id], values=_valores(resultados[player_id]))
        for player_id in escolhidos
        if player_id in resultados and player_id in resumos
    ]


@router.post("/compare", summary="Compara atletas em vários recortes")
def compare_players(session: SessionDep, pedido: CompareRequest) -> CompareOut:
    """N atletas x M métricas x K recortes.

    Recortes diferentes para os mesmos atletas é o que permite "2024 contra 2025"; atletas
    diferentes no mesmo recorte é a comparação usual.
    """
    if not pedido.player_ids:
        raise HTTPException(422, "informe ao menos um atleta")
    specs = _specs(pedido.metrics)
    resumos = _resumos(session, pedido.player_ids)

    celulas: list[ComparisonCellOut] = []
    for indice, entrada in enumerate(pedido.slices or [], start=1):
        recorte: Slice = entrada.to_slice()
        resultados = evaluate(session, specs, recorte)
        rotulo = recorte.describe if recorte.describe != "tudo" else f"recorte {indice}"
        for player_id in pedido.player_ids:
            if player_id not in resultados or player_id not in resumos:
                continue
            celulas.append(
                ComparisonCellOut(
                    slice_label=rotulo,
                    player=resumos[player_id],
                    values=_valores(resultados[player_id]),
                )
            )
    return CompareOut(
        definitions=[to_definition(spec) for spec in specs],
        cells=celulas,
    )
