"""Sondagem do API-Football: descobrir o que o plano cobre antes de escrever o adaptador.

Este módulo **não ingere nada**. Ele responde uma pergunta de viabilidade: o plano
gratuito dá 100 requisições por dia e limita temporadas históricas, e os dois itens que
faltam na especificação — histórico de lesões e totais do Brasileirão — são justamente
históricos. Escrever um adaptador inteiro para descobrir depois que a temporada de 2023
não vem seria gastar dias no lugar errado.

Então a ordem é: sondar, ler o que voltou, e só então decidir. A sondagem gasta poucas
requisições e diz quantas gastou, para a cota do dia não evaporar sem aviso.

Nada aqui assume o formato da resposta. Os campos são lidos com `.get` e o que não vier
aparece como ausente, porque a documentação do serviço bloqueia leitura automatizada e
eu prefiro relatar o que chegou a afirmar o que deveria ter chegado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from fscout.config import get_settings

TEMPO_LIMITE = 30.0

# Requisições que a sondagem se permite gastar. A cota gratuita é de 100 por dia.
ORCAMENTO = 4


class ChaveAusente(RuntimeError):
    """Sem chave configurada. Erro esperado, com instrução em vez de traço de pilha."""


@dataclass
class Sondagem:
    """O que a sondagem descobriu, para a decisão ser tomada sobre fato."""

    plano: str = "desconhecido"
    requisicoes_usadas: int | None = None
    requisicoes_no_dia: int | None = None
    ligas_do_brasil: list[dict[str, Any]] = field(default_factory=list)
    temporadas_do_brasileirao: list[int] = field(default_factory=list)
    lesoes_encontradas: int | None = None
    temporada_testada: int | None = None
    gastas_aqui: int = 0
    avisos: list[str] = field(default_factory=list)


def _cliente() -> httpx.Client:
    chave = get_settings().api_football_key
    if not chave:
        raise ChaveAusente(
            "FSCOUT_API_FOOTBALL_KEY não está configurada. Crie a conta em "
            "dashboard.api-football.com e escreva a chave no arquivo .env, na raiz do "
            "projeto: FSCOUT_API_FOOTBALL_KEY=sua_chave"
        )
    return httpx.Client(
        base_url=get_settings().api_football_base_url,
        headers={"x-apisports-key": chave},
        timeout=TEMPO_LIMITE,
    )


def _pedir(cliente: httpx.Client, caminho: str, **parametros: Any) -> dict[str, Any]:
    resposta = cliente.get(caminho, params=parametros)
    resposta.raise_for_status()
    corpo = resposta.json()
    # O serviço devolve 200 com a lista de erros no corpo, em vez de status HTTP.
    erros = corpo.get("errors")
    if erros and not isinstance(erros, list):
        raise RuntimeError(f"{caminho}: {erros}")
    return corpo


def sondar() -> Sondagem:
    """Consulta o mínimo necessário para saber se os itens pendentes são viáveis."""
    relatorio = Sondagem()
    with _cliente() as cliente:
        estado = _pedir(cliente, "/status")
        relatorio.gastas_aqui += 1
        conta = estado.get("response", {}) or {}
        assinatura = conta.get("subscription", {}) or {}
        requisicoes = conta.get("requests", {}) or {}
        relatorio.plano = str(assinatura.get("plan", "desconhecido"))
        relatorio.requisicoes_usadas = requisicoes.get("current")
        relatorio.requisicoes_no_dia = requisicoes.get("limit_day")

        ligas = _pedir(cliente, "/leagues", country="Brazil")
        relatorio.gastas_aqui += 1
        for liga in ligas.get("response", []) or []:
            dados = liga.get("league", {}) or {}
            temporadas = liga.get("seasons", []) or []
            relatorio.ligas_do_brasil.append(
                {
                    "id": dados.get("id"),
                    "nome": dados.get("name"),
                    "tipo": dados.get("type"),
                    "temporadas": sorted(
                        {t.get("year") for t in temporadas if t.get("year") is not None}
                    ),
                }
            )

        serie_a = next(
            (
                liga
                for liga in relatorio.ligas_do_brasil
                if str(liga["nome"]).strip().lower() == "serie a"
            ),
            None,
        )
        if serie_a is None:
            relatorio.avisos.append("O plano não devolveu a Série A do Brasil na lista de ligas.")
            return relatorio

        relatorio.temporadas_do_brasileirao = list(serie_a["temporadas"])
        if not relatorio.temporadas_do_brasileirao:
            relatorio.avisos.append("A Série A veio sem nenhuma temporada liberada.")
            return relatorio

        # Testa a lesão na temporada mais recente liberada: se nem nela vier, não virá
        # em nenhuma outra.
        alvo = max(relatorio.temporadas_do_brasileirao)
        relatorio.temporada_testada = alvo
        lesoes = _pedir(cliente, "/injuries", league=serie_a["id"], season=alvo)
        relatorio.gastas_aqui += 1
        relatorio.lesoes_encontradas = lesoes.get("results")
        erros = lesoes.get("errors")
        if isinstance(erros, dict) and erros:
            relatorio.avisos.append(f"O endpoint de lesões respondeu: {erros}")

    return relatorio


def vale_a_pena(relatorio: Sondagem, minimo_de_temporadas: int = 2) -> tuple[bool, str]:
    """Julga a viabilidade com um critério escrito, em vez de impressão.

    O histórico é o ponto: com uma temporada só não há "histórico de lesões" nem
    comparação entre anos, que é o que a especificação pede.
    """
    if not relatorio.temporadas_do_brasileirao:
        return False, "nenhuma temporada do Brasileirão liberada no plano"
    quantas = len(relatorio.temporadas_do_brasileirao)
    if quantas < minimo_de_temporadas:
        return False, f"só {quantas} temporada liberada, sem histórico para comparar"
    if not relatorio.lesoes_encontradas:
        return (
            False,
            "o endpoint de lesões não devolveu registros na temporada testada",
        )
    return True, f"{quantas} temporadas e lesões disponíveis"
