"""Adaptador do API-Football: a camada de dado agregado.

É a segunda camada de dado do projeto, e existe por um limite de mercado, não de
pesquisa: **não há dado de evento aberto para o futebol de clubes sul-americano**. Esse
dado é produzido por pessoas assistindo à partida e marcando cada ação, e é vendido.

O que esta fonte entrega são 33 estatísticas por jogador e por partida — suficiente para
métrica, insuficiente para mapa de campo, porque não vem coordenada nenhuma. Daí a regra
que governa o uso dela em todo o sistema: as duas camadas **nunca se comparam em
silêncio**.
"""

from fscout.ingestion.apifootball.client import (
    ChaveAusente,
    ClienteApiFootball,
    OrcamentoEsgotado,
    RestricaoDePlano,
)
from fscout.ingestion.apifootball.download import (
    Progresso,
    baixar_lesoes,
    baixar_partidas,
    orcamento_do_dia,
)
from fscout.ingestion.apifootball.probe import Sondagem, Veredito, avaliar, sondar

__all__ = [
    "ChaveAusente",
    "ClienteApiFootball",
    "OrcamentoEsgotado",
    "Progresso",
    "RestricaoDePlano",
    "Sondagem",
    "Veredito",
    "avaliar",
    "baixar_lesoes",
    "baixar_partidas",
    "orcamento_do_dia",
    "sondar",
]
