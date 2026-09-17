"""Carga da camada agregada: do cache em disco para o banco.

Separada do baixador de propósito. Baixar depende de cota diária e leva dias; carregar
lê o que já está em disco e leva segundos. Misturar os dois faria a carga só rodar quando
houvesse rede e cota, e obrigaria a recarregar tudo a cada sessão.

A consequência prática é que esta carga **nunca vai à rede**. Ela roda sobre o que o
`baixar` já trouxe, quantas vezes for preciso, sem gastar requisição — e é isso que
permite corrigir o mapeamento e recarregar sem custo.

Como o carregador é o mesmo das fontes de evento, tudo o que ele já garantia continua
valendo aqui: identidade resolvida por `external_ids`, uma transação por partida e
substituição integral no recarregamento.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from fscout.db.session import get_engine
from fscout.ingestion.apifootball.client import ClienteApiFootball
from fscout.ingestion.apifootball.download import ENDPOINT_DE_JOGADORES, ENDPOINT_DE_PARTIDAS
from fscout.ingestion.apifootball.mapper import (
    FONTE,
    build_match_bundle,
    competition_row,
    season_row,
)
from fscout.ingestion.apifootball.probe import partidas_encerradas
from fscout.ingestion.loader import Loader, refresh_player_profiles, refresh_season_dates

logger = logging.getLogger(__name__)


@dataclass
class RelatorioDeCarga:
    """O que entrou no banco, e o que não fechou."""

    competicao: str = ""
    temporada: str = ""
    partidas_no_calendario: int = 0
    partidas_sem_cache: int = 0
    partidas_carregadas: int = 0
    atletas: int = 0
    estatisticas: int = 0
    placares_divergentes: list[str] = field(default_factory=list)
    posicoes_desconhecidas: Counter[str] = field(default_factory=Counter)

    @property
    def completa(self) -> bool:
        return self.partidas_no_calendario > 0 and self.partidas_sem_cache == 0


def _ler(caminho: Path) -> dict[str, Any] | None:
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_temporada(competicao: int, temporada: int) -> RelatorioDeCarga:
    """Carrega no banco as partidas desta temporada que já estão em cache.

    Partida ainda não baixada é apenas contada e pulada: numa carga que leva dias, o
    normal é rodar com o cache pela metade.
    """
    relatorio = RelatorioDeCarga(temporada=str(temporada))

    # O cliente entra só para saber onde o cache mora; nenhuma chamada sai daqui.
    with ClienteApiFootball(orcamento=0) as cliente:
        caminho_calendario = cliente.caminho_no_cache(
            ENDPOINT_DE_PARTIDAS, {"league": competicao, "season": temporada}
        )
        calendario = _ler(caminho_calendario)
        if calendario is None:
            raise FileNotFoundError(
                f"O calendário de {competicao}/{temporada} não está em cache. "
                "Rode `fscout api-football baixar` antes de carregar."
            )
        caminhos = {
            str((partida.get("fixture") or {}).get("id")): cliente.caminho_no_cache(
                ENDPOINT_DE_JOGADORES, {"fixture": (partida.get("fixture") or {}).get("id")}
            )
            for partida in partidas_encerradas(calendario)
        }

    encerradas = partidas_encerradas(calendario)
    relatorio.partidas_no_calendario = len(encerradas)
    if not encerradas:
        return relatorio

    liga = encerradas[0].get("league") or {}
    relatorio.competicao = str(liga.get("name", ""))

    atletas_vistos: set[int] = set()
    with Session(get_engine()) as session:
        loader = Loader(session, FONTE)
        competition_id = loader.load_competition(competition_row(liga))
        season_id = loader.load_season(season_row(liga), competition_id)
        session.commit()

        for partida in encerradas:
            identificador = str((partida.get("fixture") or {}).get("id"))
            jogadores = _ler(caminhos[identificador])
            if jogadores is None:
                relatorio.partidas_sem_cache += 1
                continue

            bundle = build_match_bundle(partida, jogadores)
            if not bundle.appearances:
                # Partida encerrada sem escalação: a fonte tem buracos, e carregar uma
                # partida vazia criaria minutagem zerada que sujaria toda média.
                relatorio.partidas_sem_cache += 1
                continue

            resultado = loader.replace_match(bundle, season_id)
            session.commit()

            relatorio.partidas_carregadas += 1
            relatorio.estatisticas += len(bundle.player_match_stats)
            atletas_vistos.update(resultado.player_ids)
            if not bundle.goal_check.ok:
                relatorio.placares_divergentes.append(
                    f"{identificador}: placar {bundle.goal_check.expected}, "
                    f"gols por atleta {bundle.goal_check.from_events}"
                )
            for participacao in bundle.appearances:
                if participacao.get("position_group") is None:
                    relatorio.posicoes_desconhecidas[str(participacao.get("position"))] += 1

        refresh_season_dates(session, season_id)
        refresh_player_profiles(session, atletas_vistos)
        session.commit()

    relatorio.atletas = len(atletas_vistos)
    return relatorio
