"""Cliente do API-Football: cache em disco e consciência de cota.

O plano gratuito dá 100 requisições por dia, e uma temporada do Brasileirão tem 380
partidas. Isso torna a carga uma operação de **vários dias**, e é essa restrição que
desenha este módulo:

- **Cache em disco.** Toda resposta é gravada. Rodar de novo não regasta o que já veio,
  então o baixador é retomável de graça: ele simplesmente pula o que está em cache.
- **Orçamento explícito.** O cliente conta as requisições que realmente foram à rede e
  para quando chega ao limite, em vez de estourar a cota e passar o dia inteiro
  recebendo erro.
- **A recusa é informação.** O serviço responde 200 com o erro no corpo. Restrição de
  plano vira exceção própria, porque ela diz o que a assinatura cobre.

O cache também serve de auditoria: o que foi carregado no banco pode ser conferido
contra o JSON cru que veio da fonte, sem gastar requisição nenhuma.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from fscout.config import get_settings

logger = logging.getLogger(__name__)

TEMPO_LIMITE = 30.0
# Pausa entre requisições que vão à rede. O plano gratuito limita por minuto além de por
# dia; um segundo mantém folga sem tornar a carga lenta demais.
PAUSA_PADRAO = 1.0
TENTATIVAS_APOS_LIMITE = 1
ESPERA_APOS_LIMITE = 60.0

TAMANHO_MAXIMO_DO_NOME = 80


class ChaveAusente(RuntimeError):
    """Sem chave configurada. Erro esperado, com instrução em vez de traço de pilha."""


class OrcamentoEsgotado(RuntimeError):
    """O orçamento de requisições acabou. Não é falha: é o limite combinado."""


class RestricaoDePlano(RuntimeError):
    """O plano lista o recurso mas não o serve.

    É a distinção que precisa ser descoberta cedo: `/leagues` devolve todas as temporadas
    que a competição já teve, e não as que a assinatura libera. A mensagem costuma trazer
    o intervalo permitido ("try from 2022 to 2024"), então ela é aproveitada em vez de
    descartada — é informação de cobertura disfarçada de erro.
    """

    def __init__(self, mensagem: str, intervalo: tuple[int, int] | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.intervalo = intervalo


def intervalo_do_plano(mensagem: str) -> tuple[int, int] | None:
    """Extrai "de 2022 a 2024" da mensagem de restrição, quando ela traz isso."""
    achado = re.search(r"from\s+(\d{4})\s+to\s+(\d{4})", mensagem, re.IGNORECASE)
    if not achado:
        return None
    return int(achado.group(1)), int(achado.group(2))


def _nome_de_arquivo(parametros: dict[str, Any]) -> str:
    """Nome legível para o cache, com resumo no fim quando ficaria longo demais.

    Legível importa: conferir uma carga contra a fonte é abrir o arquivo certo, e
    `fixture-1234567.json` diz o que é enquanto um hash puro não diria nada.
    """
    partes = [f"{chave}-{valor}" for chave, valor in sorted(parametros.items())]
    nome = "_".join(partes) if partes else "sem-parametros"
    nome = re.sub(r"[^A-Za-z0-9_.-]", "-", nome)
    if len(nome) > TAMANHO_MAXIMO_DO_NOME:
        resumo = hashlib.sha1(nome.encode("utf-8")).hexdigest()[:8]
        nome = f"{nome[:TAMANHO_MAXIMO_DO_NOME]}-{resumo}"
    return f"{nome}.json"


class ClienteApiFootball:
    """Acesso ao API-Football com cache, orçamento e tratamento das recusas de plano."""

    def __init__(
        self,
        orcamento: int | None = None,
        pausa: float = PAUSA_PADRAO,
        http: httpx.Client | None = None,
    ) -> None:
        """
        Args:
            orcamento: teto de requisições que irão à rede. `None` significa sem teto —
                use com cuidado no plano gratuito.
            pausa: segundos entre requisições de rede.
        """
        configuracao = get_settings()
        chave = configuracao.api_football_key
        if not chave:
            raise ChaveAusente(
                "FSCOUT_API_FOOTBALL_KEY não está configurada. Crie a conta em "
                "dashboard.api-football.com e escreva a chave no arquivo .env, na raiz "
                "do projeto: FSCOUT_API_FOOTBALL_KEY=sua_chave"
            )
        self._cache = configuracao.resolved_raw_dir / "apifootball"
        self._orcamento = orcamento
        self._pausa = pausa
        self._gastas = 0
        self._aproveitadas = 0
        self._proprio = http is None
        self._http = http or httpx.Client(
            base_url=configuracao.api_football_base_url,
            headers={"x-apisports-key": chave},
            timeout=TEMPO_LIMITE,
        )

    def __enter__(self) -> ClienteApiFootball:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._proprio:
            self._http.close()

    @property
    def gastas(self) -> int:
        """Requisições que foram de fato à rede nesta execução."""
        return self._gastas

    @property
    def aproveitadas(self) -> int:
        """Respostas servidas pelo cache, que não custaram cota."""
        return self._aproveitadas

    @property
    def restante(self) -> int | None:
        if self._orcamento is None:
            return None
        return max(self._orcamento - self._gastas, 0)

    def caminho_no_cache(self, endpoint: str, parametros: dict[str, Any]) -> Path:
        return self._cache / endpoint.strip("/").replace("/", "_") / _nome_de_arquivo(parametros)

    def obter(self, endpoint: str, *, cachear: bool = True, **parametros: Any) -> dict[str, Any]:
        """Uma resposta do serviço, do cache quando já houver.

        Raises:
            OrcamentoEsgotado: quando a resposta exigiria rede e o teto já foi atingido.
            RestricaoDePlano: quando a assinatura não cobre o que foi pedido.
        """
        arquivo = self.caminho_no_cache(endpoint, parametros)
        if cachear and arquivo.exists():
            self._aproveitadas += 1
            return json.loads(arquivo.read_text(encoding="utf-8"))

        if self._orcamento is not None and self._gastas >= self._orcamento:
            raise OrcamentoEsgotado(
                f"orçamento de {self._orcamento} requisições esgotado; "
                "o que já veio está em cache e a próxima execução continua daqui"
            )

        corpo = self._buscar(endpoint, parametros)
        if cachear:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
        return corpo

    def _buscar(self, endpoint: str, parametros: dict[str, Any]) -> dict[str, Any]:
        for tentativa in range(TENTATIVAS_APOS_LIMITE + 1):
            if self._gastas or tentativa:
                time.sleep(self._pausa)
            resposta = self._http.get(f"/{endpoint.strip('/')}", params=parametros)
            self._gastas += 1
            if resposta.status_code == httpx.codes.TOO_MANY_REQUESTS:
                if tentativa >= TENTATIVAS_APOS_LIMITE:
                    resposta.raise_for_status()
                logger.warning("Limite por minuto atingido; aguardando para tentar de novo")
                time.sleep(ESPERA_APOS_LIMITE)
                continue
            resposta.raise_for_status()
            return self._conferir(resposta.json())
        raise RuntimeError("inalcançável")

    @staticmethod
    def _conferir(corpo: dict[str, Any]) -> dict[str, Any]:
        # O serviço responde 200 com os erros no corpo, em vez de usar o status HTTP.
        erros = corpo.get("errors")
        if isinstance(erros, dict) and erros:
            restricao = erros.get("plan")
            if restricao:
                raise RestricaoDePlano(str(restricao), intervalo_do_plano(str(restricao)))
            raise RuntimeError(str(erros))
        return corpo

    def cota_do_dia(self) -> tuple[int | None, int | None]:
        """Requisições já usadas hoje e o limite diário, direto da conta.

        Custa uma requisição e não é cacheada: o número muda a cada chamada, e um valor
        velho faria o baixador acreditar numa folga que não existe mais.
        """
        conta = self.obter("status", cachear=False).get("response", {}) or {}
        requisicoes = conta.get("requests", {}) or {}
        return requisicoes.get("current"), requisicoes.get("limit_day")

    def paginas(self, endpoint: str, **parametros: Any) -> list[dict[str, Any]]:
        """Todas as páginas de um endpoint paginado, respeitando o orçamento.

        Para ao esgotar o orçamento e devolve o que conseguiu, em vez de levantar erro:
        numa carga de vários dias, meia lista hoje e a outra metade amanhã é o
        comportamento correto.
        """
        primeira = self.obter(endpoint, **parametros)
        paginas = [primeira]
        total = ((primeira.get("paging") or {}).get("total")) or 1
        for numero in range(2, int(total) + 1):
            try:
                paginas.append(self.obter(endpoint, page=numero, **parametros))
            except OrcamentoEsgotado:
                logger.info("Orçamento esgotado na página %d de %d", numero, total)
                break
        return paginas
