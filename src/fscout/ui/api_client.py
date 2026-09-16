"""Cliente da API, único caminho por onde o painel obtém dados.

O painel **não abre o banco**. Tudo o que ele desenha passa pelos mesmos endpoints
documentados em `/docs`, pela mesma razão que a API existe: se a tela lesse o banco
direto, haveria duas definições de "gols em junho" — a da API e a da tela — e elas
divergiriam no dia em que uma das duas mudasse. Com um caminho só, o número que
aparece no gráfico é, por construção, o número que a API devolve.

O recorte trafega como um dicionário simples, porque é o que o `dcc.Store` do Dash
guarda: em `GET` ele vira parâmetro de consulta, em `POST` vira corpo. As duas formas
descrevem o mesmo `Slice` do lado de lá.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx

from fscout.config import get_settings

# Recorte como o painel o carrega: chaves iguais às de `SliceIn`, valores JSON.
Recorte = dict[str, Any]

TEMPO_LIMITE = 60.0  # avaliar o catálogo sobre 662 mil eventos não é instantâneo


class ApiIndisponivel(RuntimeError):
    """A API não respondeu.

    Erro esperado, não defeito: o painel e a API são dois processos, e é normal abrir
    um antes do outro. A mensagem diz o que fazer em vez de despejar o traço de pilha.
    """


class ErroDaApi(RuntimeError):
    """A API respondeu com erro. Carrega a explicação que ela mesma deu."""


@lru_cache(maxsize=1)
def _cliente() -> httpx.Client:
    """Cliente único, com conexões reaproveitadas entre as chamadas da tela."""
    return httpx.Client(base_url=get_settings().api_url, timeout=TEMPO_LIMITE)


def _pedir(metodo: str, caminho: str, **kwargs: Any) -> Any:
    try:
        resposta = _cliente().request(metodo, caminho, **kwargs)
        resposta.raise_for_status()
    except httpx.HTTPStatusError as erro:
        detalhe = ""
        try:
            detalhe = erro.response.json().get("detail", "")
        except ValueError:
            detalhe = erro.response.text[:200]
        raise ErroDaApi(detalhe or f"a API respondeu {erro.response.status_code}") from erro
    except httpx.HTTPError as erro:
        raise ApiIndisponivel(
            f"não consegui falar com a API em {get_settings().api_url}. "
            "Suba-a em outro terminal com `fscout api`."
        ) from erro
    return resposta.json()


def limpar(recorte: Recorte | None) -> Recorte:
    """Remove do recorte o que não restringe nada.

    Campo vazio e campo ausente significam a mesma coisa para o `Slice`, mas mandar
    `competition_ids=[]` pela consulta gera parâmetro inútil na URL.
    """
    if not recorte:
        return {}
    return {
        chave: valor
        for chave, valor in recorte.items()
        if valor is not None and valor != [] and valor != ""
    }


# -- referências, que preenchem os filtros ------------------------------------------
def saude() -> bool:
    try:
        return _pedir("GET", "/health").get("status") == "ok"
    except (ApiIndisponivel, ErroDaApi):
        return False


def competicoes() -> list[dict[str, Any]]:
    return _pedir("GET", "/competitions")


def equipes(competition_id: int | None = None) -> list[dict[str, Any]]:
    parametros = {"competition_id": competition_id} if competition_id else {}
    return _pedir("GET", "/teams", params=parametros)


# -- catálogo -----------------------------------------------------------------------
def catalogo(family: str | None = None, position: str | None = None) -> list[dict[str, Any]]:
    """As definições das métricas. A tela se monta a partir daqui, não de listas fixas."""
    return _pedir("GET", "/catalog", params=limpar({"family": family, "position": position}))


def familias() -> dict[str, int]:
    return _pedir("GET", "/catalog/families")


# -- atletas ------------------------------------------------------------------------
def buscar_atletas(
    recorte: Recorte | None = None, search: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    parametros = limpar(recorte)
    parametros.update(limpar({"search": search, "limit": limit}))
    return _pedir("GET", "/players", params=parametros)


def atleta(player_id: int) -> dict[str, Any]:
    return _pedir("GET", f"/players/{player_id}")


def chutes(player_id: int, recorte: Recorte | None = None) -> list[dict[str, Any]]:
    return _pedir("GET", f"/players/{player_id}/shots", params=limpar(recorte))


def passes(player_id: int, recorte: Recorte | None = None) -> list[dict[str, Any]]:
    return _pedir("GET", f"/players/{player_id}/passes", params=limpar(recorte))


def paises(player_id: int, recorte: Recorte | None = None) -> list[dict[str, Any]]:
    """Produção contra as equipes de cada país, base do mapa-múndi."""
    return _pedir("GET", f"/players/{player_id}/countries", params=limpar(recorte))


def mapa_de_calor(player_id: int, recorte: Recorte | None = None) -> list[dict[str, Any]]:
    return _pedir("GET", f"/players/{player_id}/heatmap", params=limpar(recorte))


# -- métricas -----------------------------------------------------------------------
def avaliar(
    metricas: list[str], recorte: Recorte | None = None, player_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Avalia métricas num recorte.

    O percentil vem calculado sobre toda a população do recorte, e não só sobre os
    atletas pedidos — é o que impede dois atletas comparados entre si de saírem sempre
    como percentil 0 e 100.
    """
    corpo = {
        "metrics": metricas,
        "slice": limpar(recorte),
        "player_ids": player_ids or [],
    }
    return _pedir("POST", "/metrics/evaluate", json=corpo)


def comparar(
    player_ids: list[int], metricas: list[str], recortes: list[Recorte] | None = None
) -> dict[str, Any]:
    """N atletas x M métricas x K recortes.

    Recortes diferentes para os mesmos atletas é o que responde "2024 contra 2025".
    """
    corpo = {
        "player_ids": player_ids,
        "metrics": metricas,
        "slices": [limpar(recorte) for recorte in (recortes or [{}])],
    }
    return _pedir("POST", "/compare", json=corpo)
