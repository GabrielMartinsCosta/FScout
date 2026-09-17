"""Sondagem: medir o que o plano cobre antes de construir em cima dele.

Esta sondagem já foi executada e decidiu o escopo do projeto. O que ela devolveu, na
conta gratuita, com sete requisições:

- Brasileirão Série A, Libertadores e as Séries B, C e D, com **2022 a 2024** acessíveis;
- **33 estatísticas por jogador e por partida**, em onze grupos;
- 1.668 registros de lesão só no Brasileirão de 2024.

E o que ela **não** achou, que é igualmente decisivo: nenhuma coordenada, nenhum xG,
nenhum pé usado, nenhum comprimento de passe. Essa é a fronteira entre as duas camadas
de dado do projeto — a agregada alimenta métrica, mas não alimenta mapa de campo.

O código continua aqui porque a sondagem é reexecutável e barata (o cache a torna
gratuita a partir da segunda vez), e porque o critério de decisão escrito em `avaliar`
é o que justifica, no texto do TCC, ter construído a camada agregada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fscout.ingestion.apifootball.client import ClienteApiFootball, RestricaoDePlano

# Teto de requisições da sondagem. Oito, e não seis, porque uma tentativa pode esbarrar
# em temporada não liberada e precisar de outra — a recusa também custa cota.
ORCAMENTO = 8

# Grupos de estatística que a camada agregada precisa ter para valer a construção. Sem
# finalização, passe e duelo sobra uma tabela de gols e cartões, que qualquer site já
# mostra e não é ferramenta de scouting.
GRUPOS_MINIMOS = frozenset({"shots", "passes", "duels"})


@dataclass
class Competicao:
    """Uma competição devolvida pelo plano, com o que a fonte declara cobrir."""

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
    # O que a assinatura realmente serve, que não é o que `/leagues` lista.
    restricao_do_plano: str = ""
    temporadas_acessiveis: list[int] = field(default_factory=list)
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


def competicoes_de(corpo: dict[str, Any]) -> list[Competicao]:
    """Lê a resposta de `/leagues` sem supor o formato dela."""
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


def achatar(estatisticas: dict[str, Any]) -> list[str]:
    """Transforma {"shots": {"total": 3}} em ["shots.total"], sem supor o formato."""
    chaves = []
    for grupo, campos in estatisticas.items():
        if isinstance(campos, dict):
            chaves.extend(f"{grupo}.{campo}" for campo in campos)
        else:
            chaves.append(str(grupo))
    return sorted(chaves)


# Códigos de partida terminada. Os três significam "Match Finished" na descrição longa
# da fonte, e confundir isso custa caro: a Copa América de 2024 tem 27 `FT`, 4 `PEN` e
# 1 `AET`, então aceitar só `FT` descartaria cinco jogos — inclusive a final. O erro não
# aparece em liga nacional, onde tudo termina em 90 minutos, e foi preciso um mata-mata
# para expô-lo.
STATUS_ENCERRADOS = frozenset({"FT", "AET", "PEN"})


def partidas_encerradas(corpo: dict[str, Any]) -> list[dict[str, Any]]:
    """Só os jogos já disputados, em qualquer forma de desfecho.

    Jogo não realizado não tem estatística de jogador, e pedi-lo gastaria cota à toa.
    """
    todas = corpo.get("response", []) or []
    return [
        partida
        for partida in todas
        if (((partida.get("fixture") or {}).get("status") or {}).get("short")) in STATUS_ENCERRADOS
    ]


def sondar(orcamento: int = ORCAMENTO) -> Sondagem:
    """Consulta o mínimo necessário para decidir se a camada agregada se sustenta."""
    relatorio = Sondagem()
    with ClienteApiFootball(orcamento=orcamento) as cliente:
        conta = (cliente.obter("status", cachear=False).get("response") or {}) or {}
        assinatura = conta.get("subscription", {}) or {}
        requisicoes = conta.get("requests", {}) or {}
        relatorio.plano = str(assinatura.get("plan", "desconhecido"))
        relatorio.requisicoes_usadas = requisicoes.get("current")
        relatorio.requisicoes_no_dia = requisicoes.get("limit_day")

        # "CONMEBOL" traz Libertadores e Sudamericana numa consulta só, em vez de duas.
        relatorio.competicoes.extend(competicoes_de(cliente.obter("leagues", country="Brazil")))
        relatorio.competicoes.extend(competicoes_de(cliente.obter("leagues", search="CONMEBOL")))

        serie_a = relatorio.competicao("serie a")
        if serie_a is None or not serie_a.temporadas:
            relatorio.avisos.append(
                "O plano não devolveu a Série A do Brasil com temporadas liberadas."
            )
            relatorio.gastas_aqui = cliente.gastas
            return relatorio

        # `/leagues` lista toda temporada que a competição já teve, e não as que a
        # assinatura serve. Quando a mais recente é recusada, a própria recusa informa o
        # intervalo liberado — então ela vira dado em vez de exceção.
        alvo = max(serie_a.temporadas)
        try:
            partidas = cliente.obter("fixtures", league=serie_a.id, season=alvo)
            relatorio.temporadas_acessiveis = list(serie_a.temporadas)
        except RestricaoDePlano as restricao:
            relatorio.restricao_do_plano = restricao.mensagem
            if restricao.intervalo is None:
                relatorio.avisos.append(
                    f"O plano recusou a temporada {alvo} sem dizer quais libera: "
                    f"{restricao.mensagem}"
                )
                relatorio.gastas_aqui = cliente.gastas
                return relatorio
            inicio, fim = restricao.intervalo
            relatorio.temporadas_acessiveis = [
                ano for ano in serie_a.temporadas if inicio <= ano <= fim
            ]
            if not relatorio.temporadas_acessiveis:
                relatorio.avisos.append(
                    f"O plano libera de {inicio} a {fim}, e a competição não tem "
                    "temporada nesse intervalo."
                )
                relatorio.gastas_aqui = cliente.gastas
                return relatorio
            alvo = max(relatorio.temporadas_acessiveis)
            partidas = cliente.obter("fixtures", league=serie_a.id, season=alvo)

        relatorio.temporada_testada = alvo
        encerradas = partidas_encerradas(partidas) or (partidas.get("response") or [])
        if not encerradas:
            relatorio.avisos.append(
                f"Nenhuma partida devolvida para a Série A de {alvo}: a temporada "
                "aparece liberada mas vem vazia."
            )
            relatorio.gastas_aqui = cliente.gastas
            return relatorio

        ultima = encerradas[-1]
        times = ultima.get("teams", {}) or {}
        relatorio.partida_de_exemplo = (
            f"{(times.get('home') or {}).get('name', '?')} x "
            f"{(times.get('away') or {}).get('name', '?')}"
        )
        fixture_id = (ultima.get("fixture", {}) or {}).get("id")

        if fixture_id is not None:
            jogadores = cliente.obter("fixtures/players", fixture=fixture_id)
            for time in jogadores.get("response", []) or []:
                for entrada in time.get("players", []) or []:
                    estatisticas = entrada.get("statistics") or []
                    if not estatisticas or not isinstance(estatisticas[0], dict):
                        continue
                    relatorio.jogador_de_exemplo = str(
                        (entrada.get("player", {}) or {}).get("name", "")
                    )
                    relatorio.estatisticas_do_jogador = achatar(estatisticas[0])
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

        try:
            lesoes = cliente.obter("injuries", league=serie_a.id, season=alvo)
            relatorio.lesoes_encontradas = lesoes.get("results")
        except RestricaoDePlano as restricao:
            relatorio.avisos.append(f"Lesões fora do plano: {restricao.mensagem}")

        relatorio.gastas_aqui = cliente.gastas

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
        """A camada só se justifica com competição **e** estatística que vire métrica."""
        return self.cobre_brasileirao and self.tem_estatistica_util


def avaliar(relatorio: Sondagem, minimo_de_temporadas: int = 2) -> Veredito:
    """Julga a sondagem por critérios escritos, em vez de impressão de quem olhou.

    É este julgamento que justifica, no texto do TCC, ter feito ou não a camada de dado
    agregado — e, se não, por quê.
    """
    veredito = Veredito()

    # O que conta é a temporada que a assinatura **serve**, não a que ela lista.
    # Julgar pela lista contaria histórico que a ingestão não conseguiria baixar.
    janela = (
        (min(relatorio.temporadas_acessiveis), max(relatorio.temporadas_acessiveis))
        if relatorio.temporadas_acessiveis
        else None
    )

    def acessiveis(competicao: Competicao | None) -> list[int]:
        if competicao is None:
            return []
        if janela is None:
            return list(competicao.temporadas)
        return [ano for ano in competicao.temporadas if janela[0] <= ano <= janela[1]]

    anos_serie_a = acessiveis(relatorio.competicao("serie a"))
    if len(anos_serie_a) < minimo_de_temporadas:
        veredito.motivos.append(
            f"Brasileirão com {len(anos_serie_a)} temporada(s) acessível(is), abaixo das "
            f"{minimo_de_temporadas} necessárias para haver histórico."
        )
    else:
        veredito.cobre_brasileirao = True
        veredito.motivos.append(
            f"Brasileirão: {len(anos_serie_a)} temporadas acessíveis "
            f"({anos_serie_a[0]} a {anos_serie_a[-1]})."
        )

    anos_libertadores = acessiveis(relatorio.competicao("libertadores"))
    if anos_libertadores:
        veredito.cobre_continental = True
        veredito.motivos.append(
            f"Libertadores: {len(anos_libertadores)} temporadas acessíveis "
            f"({anos_libertadores[0]} a {anos_libertadores[-1]})."
        )
    else:
        veredito.motivos.append("Libertadores sem temporada acessível no plano.")

    if relatorio.restricao_do_plano:
        veredito.motivos.append(f"Restrição declarada pelo plano: {relatorio.restricao_do_plano}")

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
