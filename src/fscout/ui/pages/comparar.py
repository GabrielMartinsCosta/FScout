"""Tela de comparação: radar de percentis e a tabela N atletas x M métricas.

A tabela é o critério de pronto da fase de visualização, e não por acaso: ela é a forma
que não tem teto. O radar comporta três séries porque acima disso as cores deixam de
ser distinguíveis; a tabela compara quantos atletas e quantas métricas forem pedidos,
sem depender de cor nenhuma. Quando as duas discordariam, é a tabela que fica.

**Recorte independente por linha** é o que responde "2024 contra 2025": os mesmos
atletas, avaliados duas vezes sob janelas diferentes. A API já aceita K recortes numa
chamada só, então a tela apenas monta o segundo e manda junto.

O radar aceita indistintamente três atletas num recorte ou um atleta em dois recortes —
o que ele conta é **série desenhada**, e o teto de três vale para o total.
"""

from __future__ import annotations

from typing import Any

from dash import Input, Output, dash_table, dcc, html

from fscout.ui import api_client
from fscout.ui.components.filters import Ids as FiltroIds
from fscout.ui.components.tiles import campo, estilos_de_tabela
from fscout.ui.figures.radar import MAX_SERIES_TODOS_OS_PARES, radar
from fscout.ui.format import TRACO, formatar_percentil, formatar_valor
from fscout.ui.theme import FONT_FAMILY, Mode, tokens


class Ids:
    ATLETAS = "comparar-atletas"
    METRICAS = "comparar-metricas"
    PERIODO2 = "comparar-periodo2"
    MODO = "comparar-modo"
    RADAR = "comparar-radar"
    NOTA = "comparar-nota"
    TABELA = "comparar-tabela"


# Métricas iniciais do radar, por granularidade. As duas listas não têm chave em comum
# porque as camadas não compartilham métrica nenhuma: escolher a camada troca o conjunto
# inteiro, e não um subconjunto.
METRICAS_PADRAO = {
    "event": (
        "gols",
        "assistencias",
        "xg",
        "passes_progressivos",
        "dribles_certos",
        "acoes_defensivas",
        "duelos_aereos_ganhos",
        "aproveitamento_de_passes",
    ),
    "aggregate": (
        "gols_ag",
        "assistencias_ag",
        "finalizacoes_ag",
        "passes_decisivos_ag",
        "dribles_certos_ag",
        "acoes_defensivas_ag",
        "duelos_ganhos_ag",
        "aproveitamento_de_passes_ag",
    ),
}

CAMADA_PADRAO = "event"

MODOS = [
    {"label": "Valor", "value": "valor"},
    {"label": "Percentil", "value": "percentil"},
]

ROTULO_BASE = "Recorte principal"


def opcoes_de_metrica(camada: str) -> list[dict[str, Any]]:
    """Métricas que existem naquela granularidade, e só elas.

    Oferecer "gols de fora da área" sobre dado agregado prometeria o que a fonte não tem:
    o seletor não deve listar o que o motor vai recusar.
    """
    try:
        catalogo = api_client.catalogo(data_tier=camada)
    except (api_client.ApiIndisponivel, api_client.ErroDaApi):
        return []
    return [
        {"label": f"{definicao['label']} · {definicao['family']}", "value": definicao["key"]}
        for definicao in catalogo
    ]


def layout(mode: Mode | str = "light") -> html.Div:
    t = tokens(mode)
    return html.Div(
        [
            html.Div(
                [
                    campo(
                        "Atletas",
                        dcc.Dropdown(id=Ids.ATLETAS, multi=True, placeholder="Busque pelo nome"),
                        t,
                        "420px",
                    ),
                    campo(
                        "Métricas",
                        # Opções e seleção vêm do callback, porque dependem da camada
                        # escolhida na barra de recortes.
                        dcc.Dropdown(id=Ids.METRICAS, multi=True),
                        t,
                        "460px",
                    ),
                    campo(
                        "Segundo recorte (opcional)",
                        dcc.DatePickerRange(
                            id=Ids.PERIODO2,
                            display_format="DD/MM/YYYY",
                            start_date_placeholder_text="Início",
                            end_date_placeholder_text="Fim",
                            clearable=True,
                        ),
                        t,
                        "250px",
                    ),
                    campo(
                        "Tabela mostra",
                        dcc.RadioItems(
                            id=Ids.MODO,
                            options=MODOS,
                            value="valor",
                            inline=True,
                            style={"color": t.ink, "fontSize": "12px"},
                        ),
                        t,
                        "190px",
                    ),
                ],
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": "12px 16px",
                    "alignItems": "flex-end",
                    "padding": "14px 16px",
                    "backgroundColor": t.surface,
                    "border": f"1px solid {t.border}",
                    "borderRadius": "10px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
            html.Div(
                [
                    html.Div(
                        "Radar de percentis",
                        style={"color": t.ink, "fontSize": "15px", "fontWeight": 600},
                    ),
                    html.Div(
                        "Percentil dentro do grupo de posição, no recorte selecionado. "
                        "Mais longe do centro é sempre melhor.",
                        style={"color": t.muted, "fontSize": "12px", "margin": "2px 0 10px"},
                    ),
                    dcc.Loading(
                        dcc.Graph(id=Ids.RADAR, config={"displayModeBar": False}),
                        type="default",
                        delay_show=150,
                        overlay_style={"visibility": "visible", "opacity": 0.45},
                    ),
                    html.Div(
                        id=Ids.NOTA,
                        style={"color": t.muted, "fontSize": "12px", "marginTop": "8px"},
                    ),
                ],
                style={
                    "backgroundColor": t.surface,
                    "border": f"1px solid {t.border}",
                    "borderRadius": "10px",
                    "padding": "16px 18px",
                    "marginTop": "16px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
            html.Div(
                [
                    html.Div(
                        "Tabela comparativa",
                        style={"color": t.ink, "fontSize": "15px", "fontWeight": 600},
                    ),
                    html.Div(
                        "Uma linha por atleta e recorte. Sem teto de série: é a forma que "
                        "continua legível onde o radar não caberia.",
                        style={"color": t.muted, "fontSize": "12px", "margin": "2px 0 10px"},
                    ),
                    dcc.Loading(
                        dash_table.DataTable(
                            id=Ids.TABELA, sort_action="native", **estilos_de_tabela(t)
                        ),
                        type="default",
                        delay_show=150,
                        overlay_style={"visibility": "visible", "opacity": 0.45},
                    ),
                ],
                style={
                    "backgroundColor": t.surface,
                    "border": f"1px solid {t.border}",
                    "borderRadius": "10px",
                    "padding": "16px 18px",
                    "marginTop": "16px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
        ]
    )


def montar_recortes(
    recorte: dict[str, Any] | None, inicio: str | None, fim: str | None
) -> list[dict[str, Any]]:
    """O recorte da barra e, quando pedido, um segundo com outra janela de datas.

    O segundo herda tudo do primeiro e troca só as datas: é o que faz a comparação
    isolar o período, em vez de comparar coisas diferentes por dois motivos ao mesmo
    tempo.
    """
    base = dict(recorte or {})
    base["label"] = ROTULO_BASE
    recortes = [base]
    if inicio or fim:
        segundo = dict(recorte or {})
        if inicio:
            segundo["date_from"] = inicio
        if fim:
            segundo["date_to"] = fim
        segundo["label"] = f"{(inicio or '...')[:10]} a {(fim or '...')[:10]}"
        recortes.append(segundo)
    return recortes


def registrar(app: Any, mode: Mode | str = "light") -> None:
    @app.callback(
        Output(Ids.METRICAS, "options"),
        Output(Ids.METRICAS, "value"),
        Input(FiltroIds.ARMAZEM, "data"),
    )
    def _metricas_da_camada(
        recorte: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Trocar a granularidade troca o conjunto inteiro de métricas.

        A seleção é reposta, e não preservada, porque nenhuma chave sobrevive à troca:
        manter a anterior deixaria o radar pedindo métricas que a camada nova não tem.
        """
        camada = str((recorte or {}).get("data_tier") or CAMADA_PADRAO)
        opcoes = opcoes_de_metrica(camada)
        disponiveis = {opcao["value"] for opcao in opcoes}
        padrao = [
            chave
            for chave in METRICAS_PADRAO.get(camada, METRICAS_PADRAO[CAMADA_PADRAO])
            if chave in disponiveis
        ]
        return opcoes, padrao

    @app.callback(
        Output(Ids.ATLETAS, "options"),
        Input(FiltroIds.ARMAZEM, "data"),
    )
    def _opcoes_de_atleta(recorte: dict[str, Any] | None) -> list[dict[str, Any]]:
        try:
            atletas = api_client.buscar_atletas(recorte, limit=300)
        except (api_client.ApiIndisponivel, api_client.ErroDaApi):
            return []
        return [
            {
                "label": f"{atleta['name']} · {int(atleta.get('minutes') or 0)} min",
                "value": atleta["id"],
            }
            for atleta in atletas
        ]

    @app.callback(
        Output(Ids.RADAR, "figure"),
        Output(Ids.NOTA, "children"),
        Output(Ids.TABELA, "columns"),
        Output(Ids.TABELA, "data"),
        Input(FiltroIds.ARMAZEM, "data"),
        Input(Ids.ATLETAS, "value"),
        Input(Ids.METRICAS, "value"),
        Input(Ids.PERIODO2, "start_date"),
        Input(Ids.PERIODO2, "end_date"),
        Input(Ids.MODO, "value"),
    )
    def _comparar(
        recorte: dict[str, Any] | None,
        player_ids: list[int] | None,
        metricas: list[str] | None,
        inicio: str | None,
        fim: str | None,
        modo: str,
    ) -> tuple[Any, Any, list[dict], list[dict]]:
        t = tokens(mode)
        figura_vazia, _ = radar([], [], mode)

        if not player_ids or not metricas:
            return figura_vazia, "Escolha ao menos um atleta e uma métrica.", [], []

        recortes = montar_recortes(recorte, inicio, fim)
        try:
            resposta = api_client.comparar(player_ids, metricas, recortes)
        except (api_client.ApiIndisponivel, api_client.ErroDaApi) as erro:
            return figura_vazia, html.Span(str(erro), style={"color": t.critical}), [], []

        definicoes = resposta.get("definitions", [])
        celulas = resposta.get("cells", [])
        if not celulas:
            return figura_vazia, "Nenhum atleta tem minutagem neste recorte.", [], []

        varios_recortes = len(recortes) > 1
        series = [
            {
                "player": {
                    "name": (
                        f"{celula['player']['name']} · {celula['slice_label']}"
                        if varios_recortes
                        else celula["player"]["name"]
                    )
                },
                "values": celula.get("values", {}),
            }
            for celula in celulas
        ]

        notas: list[str] = []
        if len(series) <= MAX_SERIES_TODOS_OS_PARES:
            figura, excluidas = radar(series, definicoes, mode)
            if excluidas:
                notas.append(
                    "Fora do radar por falta de percentil no recorte: " + ", ".join(excluidas) + "."
                )
        else:
            figura = figura_vazia
            notas.append(
                f"{len(series)} séries pedidas e o radar comporta "
                f"{MAX_SERIES_TODOS_OS_PARES}: acima disso as cores deixam de ser "
                "distinguíveis sob daltonismo. A tabela abaixo compara todas."
            )

        por_chave = {definicao["key"]: definicao for definicao in definicoes}
        colunas: list[dict[str, Any]] = [{"name": "Atleta", "id": "atleta"}]
        if varios_recortes:
            colunas.append({"name": "Recorte", "id": "recorte"})
        colunas += [
            {"name": por_chave[chave]["label"], "id": chave}
            for chave in metricas
            if chave in por_chave
        ]

        linhas = []
        for celula in celulas:
            linha: dict[str, Any] = {
                "atleta": celula["player"]["name"],
                "recorte": celula.get("slice_label", ""),
            }
            for chave in metricas:
                definicao = por_chave.get(chave)
                medida = celula.get("values", {}).get(chave)
                if definicao is None or medida is None:
                    linha[chave] = TRACO
                elif modo == "percentil":
                    linha[chave] = formatar_percentil(medida)
                else:
                    linha[chave] = formatar_valor(definicao, medida)
            linhas.append(linha)

        return figura, " ".join(notas), colunas, linhas
