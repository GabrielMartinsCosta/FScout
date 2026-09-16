"""Baixa uma temporada em várias sessões, respeitando a cota diária.

Uma temporada do Brasileirão tem 380 partidas e o plano gratuito dá 100 requisições por
dia. Não existe "baixar a temporada" como operação única: existe **baixar um pedaço por
dia até acabar**. Este módulo é feito para isso.

A retomada não usa arquivo de estado nem banco: ela usa o próprio cache. Partida cujo
JSON já está em disco é pulada sem custar cota, então rodar de novo continua exatamente
de onde parou — e rodar duas vezes no mesmo dia não gasta nada além do que faltava.

Nada é gravado no banco aqui. O cache cru fica como estava na fonte, o que permite
conferir depois qualquer número carregado contra o que o serviço realmente respondeu,
sem gastar requisição nenhuma.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fscout.ingestion.apifootball.client import ClienteApiFootball, OrcamentoEsgotado
from fscout.ingestion.apifootball.probe import partidas_encerradas

logger = logging.getLogger(__name__)

ENDPOINT_DE_PARTIDAS = "fixtures"
ENDPOINT_DE_JOGADORES = "fixtures/players"
ENDPOINT_DE_LESOES = "injuries"


@dataclass
class Progresso:
    """Onde a carga chegou, e quanto ainda falta."""

    competicao: int
    temporada: int
    partidas_encerradas: int = 0
    ja_em_cache: int = 0
    baixadas_agora: int = 0
    faltam: int = 0
    gastas: int = 0
    aproveitadas: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def concluido(self) -> bool:
        return self.partidas_encerradas > 0 and self.faltam == 0

    @property
    def por_cento(self) -> float:
        if not self.partidas_encerradas:
            return 0.0
        prontas = self.partidas_encerradas - self.faltam
        return 100.0 * prontas / self.partidas_encerradas

    def dias_restantes(self, cota_diaria: int) -> int:
        """Quantos dias de cota ainda seriam necessários, arredondando para cima."""
        if self.faltam <= 0 or cota_diaria <= 0:
            return 0
        return -(-self.faltam // cota_diaria)


def orcamento_do_dia(margem: int = 2) -> tuple[int, int]:
    """Quanto ainda cabe hoje e qual é o limite diário, perguntando à própria conta.

    Custa uma requisição e vale a pena: chutar a folga é como a cota estoura no meio de
    uma carga longa. A margem existe para sobrar fôlego caso outra coisa consuma cota no
    mesmo dia.

    Devolve os dois números porque eles respondem perguntas diferentes: o primeiro diz
    quanto dá para baixar agora, o segundo permite estimar em quantos dias a carga acaba.
    """
    with ClienteApiFootball(orcamento=None) as cliente:
        usadas, limite = cliente.cota_do_dia()
    if limite is None:
        return 0, 0
    return max(int(limite) - int(usadas or 0) - margem, 0), int(limite)


def baixar_partidas(competicao: int, temporada: int, orcamento: int | None = None) -> Progresso:
    """Baixa as estatísticas por jogador de cada partida encerrada da temporada.

    Args:
        competicao: id da competição no API-Football (71 é a Série A do Brasil).
        temporada: ano da temporada.
        orcamento: teto de requisições desta sessão. `None` não põe teto.
    """
    progresso = Progresso(competicao=competicao, temporada=temporada)
    with ClienteApiFootball(orcamento=orcamento) as cliente:
        try:
            calendario = cliente.obter(ENDPOINT_DE_PARTIDAS, league=competicao, season=temporada)
        except OrcamentoEsgotado as erro:
            progresso.avisos.append(str(erro))
            return _fechar(progresso, cliente)

        encerradas = partidas_encerradas(calendario)
        progresso.partidas_encerradas = len(encerradas)
        if not encerradas:
            progresso.avisos.append(
                f"A temporada {temporada} da competição {competicao} não devolveu "
                "nenhuma partida encerrada."
            )
            return _fechar(progresso, cliente)

        pendentes = []
        for partida in encerradas:
            identificador = (partida.get("fixture") or {}).get("id")
            if identificador is None:
                continue
            caminho = cliente.caminho_no_cache(ENDPOINT_DE_JOGADORES, {"fixture": identificador})
            if caminho.exists():
                progresso.ja_em_cache += 1
            else:
                pendentes.append(identificador)

        progresso.faltam = len(pendentes)
        for identificador in pendentes:
            try:
                cliente.obter(ENDPOINT_DE_JOGADORES, fixture=identificador)
            except OrcamentoEsgotado as erro:
                progresso.avisos.append(str(erro))
                break
            progresso.baixadas_agora += 1
            progresso.faltam -= 1

        return _fechar(progresso, cliente)


def baixar_lesoes(competicao: int, temporada: int, orcamento: int | None = None) -> Progresso:
    """Baixa o histórico de lesões da temporada, que vem paginado.

    Fica em comando separado do calendário de propósito: são 1.668 registros só no
    Brasileirão de 2024, e paginados eles consomem cota que talvez você prefira gastar
    nas partidas primeiro.
    """
    progresso = Progresso(competicao=competicao, temporada=temporada)
    with ClienteApiFootball(orcamento=orcamento) as cliente:
        paginas = cliente.paginas(ENDPOINT_DE_LESOES, league=competicao, season=temporada)
        registros = sum(len(pagina.get("response") or []) for pagina in paginas)
        total_declarado = (paginas[0].get("results") if paginas else 0) or 0
        paginacao = (paginas[0].get("paging") or {}) if paginas else {}

        progresso.partidas_encerradas = int(total_declarado)
        progresso.baixadas_agora = registros
        progresso.faltam = max(int(total_declarado) - registros, 0)
        if progresso.faltam:
            progresso.avisos.append(
                f"Faltam {progresso.faltam} registros: a lista tem "
                f"{paginacao.get('total', '?')} páginas e a cota acabou antes do fim. "
                "Rode de novo amanhã para continuar."
            )
        return _fechar(progresso, cliente)


def _fechar(progresso: Progresso, cliente: ClienteApiFootball) -> Progresso:
    progresso.gastas = cliente.gastas
    progresso.aproveitadas = cliente.aproveitadas
    return progresso
