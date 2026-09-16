"""Sondagem do API-Football: medir a camada 2 antes de construí-la.

Este módulo **não ingere nada**. Ele responde uma pergunta de escopo, e a pergunta mudou
de tamanho: não é mais "dá para preencher lesões", é "dá para cobrir o futebol
sul-americano de clubes com profundidade suficiente para a ferramenta valer a pena".

O pano de fundo: não existe dado de evento aberto para Brasileirão e Libertadores. O que
existe é estatística agregada por jogador e por partida. A ferramenta já calcula 108
métricas como consultas sobre eventos, e essa camada não tem como ser alimentada aqui.
Então a decisão real é se a camada agregada entrega o bastante para justificar uma
segunda via de dados, com a regra de nunca comparar as duas em silêncio.

Essa decisão não se toma por impressão. A sondagem gasta seis requisições das cem
diárias e traz três coisas:

1. **Quais competições sul-americanas o plano libera**, e com quantas temporadas.
2. **O que a própria fonte declara cobrir** de cada temporada (o objeto `coverage`).
3. **Uma partida real de exemplo**, com as estatísticas de um jogador de verdade — porque
   bandeira de cobertura é promessa e amostra é prova.

Nada aqui assume o formato da resposta. A documentação do serviço bloqueia leitura
automatizada, então os campos são lidos com `.get`, o que vier é achatado e relatado como
chegou, e o que faltar aparece como ausente. Prefiro relatar o que chegou a afirmar o que
deveria ter chegado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from fscout.config import get_settings

TEMPO_LIMITE = 30.0

# Teto de requisições que a sondagem se permite. A cota gratuita é de 100 por dia.
ORCAMENTO = 6

# Grupos de estatística que a camada 2 precisa ter para valer a construção. Sem
# finalização, passe e duelo não dá para montar métrica de scouting nenhuma — seria uma
# tabela de gols e cartões, que qualquer site já mostra.
GRUPOS_MINIMOS = frozenset({"shots", "passes", "duels"})


class ChaveAusente(RuntimeError):
    """Sem chave configurada. Erro esperado, com instrução em vez de traço de pilha."""


@dataclass
class Competicao:
    """Uma competição liberada pelo plano, com o que a fonte declara cobrir."""

    id: int | None = None
    nome: str = ""
    pais: str = ""
    tipo: str = ""
    temporadas: list[int] = field(default_factory=list)
    # O objeto `coverage` da temporada mais recente: o que a fonte *afirma* entregar.
    cobertura: dict[str, Any] = field(default_factory=dict)

    @property
    def resumo_de_temporadas(self) -> str:
        if not self.temporadas:
            return "nenhuma"
        return f"{len(self.temporadas)}: de {self.temporadas[0]} a {self.temporadas[-1]}"


@dataclass
class Sondagem:
    """O que a sondagem descobriu, para a decisão ser tomada sobre fato."""

    plano: str = "desconhecido"
    requisicoes_usadas: int | None = None
    requisicoes_no_dia: int | None = None
    competicoes: list[Competicao] = field(default_factory=list)
    partida_de_exemplo: str = ""
    # Chaves achatadas ("shots.total", "passes.key") encontradas numa partida real.
    estatisticas_do_jogador: list[str] = field(default_factory=list)
    jogador_de_exemplo: str = ""
    grupos_encontrados: set[str] = field(default_factory=set)
    lesoes_encontradas: int | None = None
    temporada_testada: int | None = None
    gastas_aqui: int = 0
    avisos: list[str] = field(default_factory=list)

    def competicao(self, *termos: str) -> Competicao | None:
        """Primeira competição cujo nome contenha todos os termos, sem diferenciar caixa."""
        for competicao in self.competicoes:
            nome = competicao.nome.lower()
            if all(termo.lower() in nome for termo in termos):
                return competicao
        return None


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
    # O serviço responde 200 com os erros no corpo, em vez de usar o status HTTP.
    erros = corpo.get("errors")
    if isinstance(erros, dict) and erros:
        raise RuntimeError(f"{caminho}: {erros}")
    return corpo


def _competicoes_de(corpo: dict[str, Any]) -> list[Competicao]:
    encontradas = []
    for item in corpo.get("response", []) or []:
        dados = item.get("league", {}) or {}
        pais = item.get("country", {}) or {}
        temporadas = item.get("seasons", []) or []
        anos = sorted({t.get("year") for t in temporadas if t.get("year") is not None})
        recente = max(
            (t for t in temporadas if t.get("year") is not None),
            key=lambda t: t["year"],
            default={},
        )
        encontradas.append(
            Competicao(
                id=dados.get("id"),
                nome=str(dados.get("name", "")),
                pais=str(pais.get("name", "")),
                tipo=str(dados.get("type", "")),
                temporadas=anos,
                cobertura=recente.get("coverage", {}) or {},
            )
        )
    return encontradas


def _achatar(estatisticas: dict[str, Any]) -> list[str]:
    """Transforma {"shots": {"total": 3}} em ["shots.total"], sem supor o formato."""
    chaves = []
    for grupo, campos in estatisticas.items():
        if isinstance(campos, dict):
            chaves.extend(f"{grupo}.{campo}" for campo in campos)
        else:
            chaves.append(str(grupo))
    return sorted(chaves)


def sondar() -> Sondagem:
    """Consulta o mínimo necessário para decidir se a camada 2 se sustenta."""
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

        # Brasileirão e as copas continentais. "CONMEBOL" traz Libertadores e
        # Sudamericana numa consulta só, em vez de duas.
        relatorio.competicoes.extend(_competicoes_de(_pedir(cliente, "/leagues", country="Brazil")))
        relatorio.gastas_aqui += 1
        relatorio.competicoes.extend(
            _competicoes_de(_pedir(cliente, "/leagues", search="CONMEBOL"))
        )
        relatorio.gastas_aqui += 1

        serie_a = relatorio.competicao("serie a")
        if serie_a is None or not serie_a.temporadas:
            relatorio.avisos.append(
                "O plano não devolveu a Série A do Brasil com temporadas liberadas."
            )
            return relatorio

        alvo = max(serie_a.temporadas)
        relatorio.temporada_testada = alvo

        # A prova: uma partida real, e as estatísticas de um jogador real dentro dela.
        partidas = _pedir(cliente, "/fixtures", league=serie_a.id, season=alvo, last=1)
        relatorio.gastas_aqui += 1
        lista = partidas.get("response", []) or []
        if not lista:
            relatorio.avisos.append(
                f"Nenhuma partida devolvida para a Série A de {alvo}: a temporada "
                "aparece liberada mas vem vazia."
            )
            return relatorio

        primeira = lista[0]
        times = primeira.get("teams", {}) or {}
        relatorio.partida_de_exemplo = (
            f"{(times.get('home') or {}).get('name', '?')} x "
            f"{(times.get('away') or {}).get('name', '?')}"
        )
        fixture_id = (primeira.get("fixture", {}) or {}).get("id")

        if fixture_id is not None:
            jogadores = _pedir(cliente, "/fixtures/players", fixture=fixture_id)
            relatorio.gastas_aqui += 1
            for time in jogadores.get("response", []) or []:
                for entrada in time.get("players", []) or []:
                    estatisticas = entrada.get("statistics") or []
                    if not estatisticas or not isinstance(estatisticas[0], dict):
                        continue
                    relatorio.jogador_de_exemplo = str(
                        (entrada.get("player", {}) or {}).get("name", "")
                    )
                    relatorio.estatisticas_do_jogador = _achatar(estatisticas[0])
                    relatorio.grupos_encontrados = {
                        chave.split(".", 1)[0] for chave in relatorio.estatisticas_do_jogador
                    }
                    break
                if relatorio.estatisticas_do_jogador:
                    break
            if not relatorio.estatisticas_do_jogador:
                relatorio.avisos.append(
                    "A partida veio sem estatística por jogador — a camada agregada "
                    "ficaria sem o que virar métrica."
                )

        lesoes = _pedir(cliente, "/injuries", league=serie_a.id, season=alvo)
        relatorio.gastas_aqui += 1
        relatorio.lesoes_encontradas = lesoes.get("results")

    return relatorio


@dataclass
class Veredito:
    """A decisão, com o motivo escrito ao lado dela."""

    cobre_brasileirao: bool = False
    cobre_continental: bool = False
    tem_estatistica_util: bool = False
    tem_lesoes: bool = False
    motivos: list[str] = field(default_factory=list)

    @property
    def vale_a_camada_2(self) -> bool:
        """A camada 2 só se justifica com competição **e** estatística que vire métrica."""
        return self.cobre_brasileirao and self.tem_estatistica_util


def avaliar(relatorio: Sondagem, minimo_de_temporadas: int = 2) -> Veredito:
    """Julga a sondagem por critérios escritos, em vez de impressão de quem olhou.

    É este julgamento que justifica, no texto do TCC, ter feito ou não a camada de
    dado agregado — e, se não, por quê.
    """
    veredito = Veredito()

    serie_a = relatorio.competicao("serie a")
    if serie_a is None or len(serie_a.temporadas) < minimo_de_temporadas:
        quantas = len(serie_a.temporadas) if serie_a else 0
        veredito.motivos.append(
            f"Brasileirão com {quantas} temporada(s) liberada(s), abaixo das "
            f"{minimo_de_temporadas} necessárias para haver histórico."
        )
    else:
        veredito.cobre_brasileirao = True
        veredito.motivos.append(f"Brasileirão: {serie_a.resumo_de_temporadas}.")

    libertadores = relatorio.competicao("libertadores")
    if libertadores and libertadores.temporadas:
        veredito.cobre_continental = True
        veredito.motivos.append(f"Libertadores: {libertadores.resumo_de_temporadas}.")
    else:
        veredito.motivos.append("Libertadores não liberada no plano.")

    faltando = GRUPOS_MINIMOS - relatorio.grupos_encontrados
    if relatorio.estatisticas_do_jogador and not faltando:
        veredito.tem_estatistica_util = True
        veredito.motivos.append(
            f"{len(relatorio.estatisticas_do_jogador)} estatísticas por jogador numa "
            "partida real, incluindo finalização, passe e duelo."
        )
    elif relatorio.estatisticas_do_jogador:
        veredito.motivos.append(
            "Estatística por jogador existe, mas sem os grupos mínimos: falta "
            + ", ".join(sorted(faltando))
            + "."
        )
    else:
        veredito.motivos.append("Nenhuma estatística por jogador foi obtida na amostra.")

    if relatorio.lesoes_encontradas:
        veredito.tem_lesoes = True
        veredito.motivos.append(
            f"{relatorio.lesoes_encontradas} registros de lesão na temporada testada."
        )
    else:
        veredito.motivos.append("O endpoint de lesões não devolveu registros.")

    return veredito
