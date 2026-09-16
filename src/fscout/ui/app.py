"""Montagem do painel.

O layout é uma **função**, não um valor: o Dash a executa a cada carregamento de
página. Com isso o painel pode subir antes da API — quando ela ficar pronta, basta
recarregar a página e os filtros aparecem preenchidos. Layout fixo obrigaria a derrubar
e subir o painel de novo, o que é um atrito bobo durante o desenvolvimento.

As duas telas ficam montadas no DOM ao mesmo tempo, e as abas só trocam a visibilidade.
A alternativa (o Dash trocar o conteúdo da aba) apagaria os componentes da tela oculta,
e os callbacks dela passariam a apontar para coisas que não existem — o que só se
resolve silenciando exceções de callback, que é justamente o que esconderia um erro de
verdade no dia em que ele aparecesse.
"""

from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, dcc, html

from fscout.ui import api_client
from fscout.ui.components import filters
from fscout.ui.components.filters import Ids as FiltroIds
from fscout.ui.pages import comparar, perfil
from fscout.ui.theme import FONT_FAMILY, Mode, tokens

ABAS = "painel-abas"
PAINEL_PERFIL = "painel-perfil"
PAINEL_COMPARAR = "painel-comparar"

SUBTITULO = "Análise evento a evento. Os filtros abaixo valem para tudo o que aparece na tela."


def _aviso_de_api(mode: Mode | str) -> Any:
    t = tokens(mode)
    if api_client.saude():
        return None
    return html.Div(
        "A API não está respondendo. Suba-a em outro terminal com `fscout api` e "
        "recarregue esta página.",
        style={
            "backgroundColor": t.surface,
            "border": f"1px solid {t.critical}",
            "borderRadius": "8px",
            "color": t.critical,
            "fontSize": "13px",
            "padding": "10px 14px",
            "marginBottom": "14px",
        },
    )


def _layout(mode: Mode | str) -> html.Div:
    t = tokens(mode)
    try:
        competicoes = api_client.competicoes()
    except (api_client.ApiIndisponivel, api_client.ErroDaApi):
        competicoes = []

    return html.Div(
        [
            dcc.Store(id=FiltroIds.ARMAZEM, data={}),
            html.Div(
                [
                    html.Div(
                        "FScout",
                        style={"color": t.ink, "fontSize": "22px", "fontWeight": 600},
                    ),
                    html.Div(
                        SUBTITULO,
                        style={"color": t.muted, "fontSize": "13px", "marginTop": "2px"},
                    ),
                ],
                style={"marginBottom": "16px"},
            ),
            _aviso_de_api(mode),
            filters.barra(competicoes, mode),
            dcc.Tabs(
                id=ABAS,
                value="perfil",
                children=[
                    dcc.Tab(label="Perfil do atleta", value="perfil"),
                    dcc.Tab(label="Comparação", value="comparar"),
                ],
                style={"marginTop": "18px"},
            ),
            html.Div(perfil.layout(mode), id=PAINEL_PERFIL, style={"marginTop": "18px"}),
            html.Div(
                comparar.layout(mode),
                id=PAINEL_COMPARAR,
                style={"marginTop": "18px", "display": "none"},
            ),
        ],
        style={
            "backgroundColor": t.page,
            "fontFamily": FONT_FAMILY,
            "minHeight": "100vh",
            "padding": "24px 28px 48px",
        },
    )


def criar_app(mode: Mode | str = "light") -> Dash:
    """Monta o painel e liga os callbacks das duas telas."""
    app = Dash(__name__, title="FScout")
    app.layout = lambda: _layout(mode)

    @app.callback(
        Output(PAINEL_PERFIL, "style"),
        Output(PAINEL_COMPARAR, "style"),
        Input(ABAS, "value"),
    )
    def _trocar_aba(aba: str) -> tuple[dict[str, Any], dict[str, Any]]:
        visivel = {"marginTop": "18px"}
        oculto = {"marginTop": "18px", "display": "none"}
        return (visivel, oculto) if aba == "perfil" else (oculto, visivel)

    @app.callback(
        Output(FiltroIds.TEMPORADA, "options"),
        Input(FiltroIds.COMPETICAO, "value"),
    )
    def _temporadas(competition_ids: list[int] | None) -> list[dict[str, Any]]:
        try:
            competicoes = api_client.competicoes()
        except (api_client.ApiIndisponivel, api_client.ErroDaApi):
            return []
        return filters.opcoes_de_temporada(competicoes, competition_ids)

    @app.callback(
        Output(FiltroIds.ARMAZEM, "data"),
        Input(FiltroIds.COMPETICAO, "value"),
        Input(FiltroIds.TEMPORADA, "value"),
        Input(FiltroIds.PERIODO, "start_date"),
        Input(FiltroIds.PERIODO, "end_date"),
        Input(FiltroIds.MANDO, "value"),
        Input(FiltroIds.MINUTOS, "value"),
    )
    def _recorte(
        competition_ids: list[int] | None,
        season_ids: list[int] | None,
        inicio: str | None,
        fim: str | None,
        mando: str | None,
        minutos: int | None,
    ) -> dict[str, Any]:
        return filters.montar_recorte(competition_ids, season_ids, inicio, fim, mando, minutos)

    perfil.registrar(app, mode)
    comparar.registrar(app, mode)
    return app


app = criar_app()
