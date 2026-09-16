"""Tela do perfil: quem é o atleta, o que ele produziu e onde ele agiu.

Cada gráfico vem acompanhado da **tabela equivalente**, e isso não é redundância. Três
motivos, nesta ordem de importância: duas cores da paleta clara ficam abaixo de 3:1
contra a superfície e a regra só as libera com o valor legível em outro lugar; escala
contínua de cor não é canal acessível sozinha; e uma banca vai querer conferir o número
que está no desenho. A tabela sai da mesma resposta da API que o gráfico, então não há
como os dois discordarem.

As métricas dos cartões mudam conforme a posição: mostrar "defesas de pênalti" para um
atacante gastaria espaço com nada, e esconder "gols evitados" de um goleiro esconderia
justamente o que importa.
"""

from __future__ import annotations

from typing import Any

from dash import Input, Output, dash_table, dcc, html

from fscout.ui import api_client
from fscout.ui.components import tiles
from fscout.ui.components.filters import Ids as FiltroIds
from fscout.ui.figures import heatmap as figura_de_calor
from fscout.ui.figures import shot_map as figura_de_chutes
from fscout.ui.format import TRACO
from fscout.ui.theme import FONT_FAMILY, Mode, Tokens, tokens


class Ids:
    ATLETA = "perfil-atleta"
    FICHA = "perfil-ficha"
    CARTOES = "perfil-cartoes"
    CHUTES = "perfil-chutes"
    RESUMO_CHUTES = "perfil-resumo-chutes"
    TABELA_CHUTES = "perfil-tabela-chutes"
    CALOR = "perfil-calor"
    TABELA_CALOR = "perfil-tabela-calor"


# Métricas dos cartões, por posição. Chaves do catálogo, não texto livre.
CARTOES_LINHA = (
    "gols",
    "assistencias",
    "xg",
    "participacao_em_gols",
    "aproveitamento_de_passes",
    "acoes_defensivas",
)
CARTOES_GOLEIRO = (
    "defesas",
    "gols_sofridos",
    "aproveitamento_em_defesas",
    "gols_evitados",
    "defesas_de_penalti",
    "saidas_do_gol",
)


def metricas_do_perfil(posicao: str | None) -> tuple[str, ...]:
    return CARTOES_GOLEIRO if posicao == "goalkeeper" else CARTOES_LINHA


def cartao_de_grafico(
    titulo: str, explicacao: str, grafico: Any, tabela: Any, t: Tokens
) -> html.Div:
    """Gráfico com sua tabela equivalente recolhida logo abaixo."""
    return html.Div(
        [
            html.Div(titulo, style={"color": t.ink, "fontSize": "15px", "fontWeight": 600}),
            html.Div(
                explicacao,
                style={"color": t.muted, "fontSize": "12px", "margin": "2px 0 10px"},
            ),
            dcc.Loading(
                grafico,
                type="default",
                delay_show=150,
                # Segura o desenho anterior esmaecido enquanto recarrega, em vez de
                # piscar um esqueleto e sacudir o layout.
                overlay_style={"visibility": "visible", "opacity": 0.45},
            ),
            html.Details(
                [
                    html.Summary(
                        "Ver os mesmos dados em tabela",
                        style={
                            "color": t.ink_secondary,
                            "fontSize": "12px",
                            "cursor": "pointer",
                            "marginTop": "10px",
                        },
                    ),
                    html.Div(tabela, style={"marginTop": "10px"}),
                ]
            ),
        ],
        style={
            "backgroundColor": t.surface,
            "border": f"1px solid {t.border}",
            "borderRadius": "10px",
            "padding": "16px 18px",
            "fontFamily": FONT_FAMILY,
            "flex": "1 1 460px",
            "minWidth": "340px",
        },
    )


def layout(mode: Mode | str = "light") -> html.Div:
    t = tokens(mode)
    return html.Div(
        [
            html.Div(
                [
                    html.Label(
                        "Atleta",
                        style={
                            "color": t.ink_secondary,
                            "fontSize": "11px",
                            "display": "block",
                            "marginBottom": "4px",
                        },
                    ),
                    dcc.Dropdown(
                        id=Ids.ATLETA,
                        placeholder="Busque pelo nome",
                        style={"maxWidth": "420px"},
                    ),
                ],
                style={"marginBottom": "16px"},
            ),
            dcc.Loading(
                html.Div(id=Ids.FICHA),
                type="default",
                delay_show=150,
                overlay_style={"visibility": "visible", "opacity": 0.45},
            ),
            html.Div(id=Ids.CARTOES, style={"marginTop": "16px"}),
            html.Div(
                [
                    cartao_de_grafico(
                        "Mapa de chutes",
                        "Tamanho pelo xG, cor pelo desfecho. Escala de tamanho absoluta, "
                        "para dois atletas serem comparáveis lado a lado.",
                        dcc.Graph(id=Ids.CHUTES, config={"displayModeBar": False}),
                        dash_table.DataTable(
                            id=Ids.TABELA_CHUTES, sort_action="native", **tiles.estilos_de_tabela(t)
                        ),
                        t,
                    ),
                    cartao_de_grafico(
                        "Mapa de calor",
                        "Ações por célula da grade (6 x 5), contadas na ingestão. "
                        "Ataque para a direita.",
                        dcc.Graph(id=Ids.CALOR, config={"displayModeBar": False}),
                        dash_table.DataTable(id=Ids.TABELA_CALOR, **tiles.estilos_de_tabela(t)),
                        t,
                    ),
                ],
                style={"display": "flex", "flexWrap": "wrap", "gap": "16px", "marginTop": "16px"},
            ),
            html.Div(
                id=Ids.RESUMO_CHUTES,
                style={"color": t.muted, "fontSize": "12px", "marginTop": "10px"},
            ),
        ]
    )


def _linhas_de_chutes(chutes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "data": str(chute.get("match_date", ""))[:10],
            "min": chute.get("minute"),
            "adversario": chute.get("opponent") or TRACO,
            "desfecho": figura_de_chutes.DESFECHOS.get(
                str(chute.get("outcome")), str(chute.get("outcome"))
            ),
            "xg": f"{chute['xg']:.2f}".replace(".", ",") if chute.get("xg") is not None else TRACO,
            "distancia": (
                f"{chute['distance_m']:.1f}".replace(".", ",")
                if chute.get("distance_m") is not None
                else TRACO
            ),
            "parte": figura_de_chutes.PARTES_DO_CORPO.get(str(chute.get("body_part")), TRACO),
        }
        for chute in chutes
    ]


COLUNAS_DE_CHUTES = [
    {"name": "Data", "id": "data"},
    {"name": "Min", "id": "min"},
    {"name": "Adversário", "id": "adversario"},
    {"name": "Desfecho", "id": "desfecho"},
    {"name": "xG", "id": "xg"},
    {"name": "Distância (m)", "id": "distancia"},
    {"name": "Parte do corpo", "id": "parte"},
]


def _tabela_de_calor(celulas: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    grade = figura_de_calor.matriz(celulas)
    colunas = [{"name": "Faixa", "id": "faixa"}] + [
        {"name": f"Coluna {indice + 1}", "id": f"c{indice}"} for indice in range(len(grade[0]))
    ]
    linhas = [
        {"faixa": f"{indice + 1}", **{f"c{coluna}": valor for coluna, valor in enumerate(linha)}}
        for indice, linha in enumerate(grade)
    ]
    return colunas, linhas


def registrar(app: Any, mode: Mode | str = "light") -> None:
    """Liga os callbacks da tela. O recorte vem do armazém preenchido pela barra."""

    @app.callback(
        Output(Ids.ATLETA, "options"),
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
        Output(Ids.FICHA, "children"),
        Output(Ids.CARTOES, "children"),
        Output(Ids.CHUTES, "figure"),
        Output(Ids.TABELA_CHUTES, "columns"),
        Output(Ids.TABELA_CHUTES, "data"),
        Output(Ids.CALOR, "figure"),
        Output(Ids.TABELA_CALOR, "columns"),
        Output(Ids.TABELA_CALOR, "data"),
        Output(Ids.RESUMO_CHUTES, "children"),
        Input(Ids.ATLETA, "value"),
        Input(FiltroIds.ARMAZEM, "data"),
    )
    def _carregar(player_id: int | None, recorte: dict[str, Any] | None) -> tuple[Any, ...]:
        t = tokens(mode)
        vazio_chutes = figura_de_chutes.mapa_de_chutes([], mode)
        vazio_calor = figura_de_calor.mapa_de_calor([], mode)
        colunas_calor, linhas_calor = _tabela_de_calor([])

        if not player_id:
            aviso = html.Div(
                "Escolha um atleta para ver a ficha.",
                style={"color": t.muted, "fontSize": "13px"},
            )
            return (
                aviso,
                None,
                vazio_chutes,
                COLUNAS_DE_CHUTES,
                [],
                vazio_calor,
                colunas_calor,
                linhas_calor,
                "",
            )

        try:
            perfil = api_client.atleta(player_id)
            chutes = api_client.chutes(player_id, recorte)
            celulas = api_client.mapa_de_calor(player_id, recorte)
            chaves = metricas_do_perfil(str(perfil.get("position_group") or ""))
            definicoes = {
                definicao["key"]: definicao
                for definicao in api_client.catalogo()
                if definicao["key"] in chaves
            }
            avaliacoes = api_client.avaliar(list(chaves), recorte, [player_id])
        except (api_client.ApiIndisponivel, api_client.ErroDaApi) as erro:
            aviso = html.Div(str(erro), style={"color": t.critical, "fontSize": "13px"})
            return (
                aviso,
                None,
                vazio_chutes,
                COLUNAS_DE_CHUTES,
                [],
                vazio_calor,
                colunas_calor,
                linhas_calor,
                "",
            )

        medidas = avaliacoes[0]["values"] if avaliacoes else {}
        cartoes = tiles.linha_de_cartoes(
            [
                tiles.cartao_de_metrica(definicoes[chave], medidas[chave], mode)
                for chave in chaves
                if chave in definicoes and chave in medidas
            ],
            mode,
        )

        desenhaveis = figura_de_chutes.com_coordenada(chutes)
        fora_do_mapa = len(chutes) - len(desenhaveis)
        resumo = f"{len(chutes)} finalizações no recorte"
        if fora_do_mapa:
            resumo += f"; {fora_do_mapa} sem coordenada registrada, ausentes do mapa"
        resumo += ". A disputa de pênaltis não entra."

        colunas_calor, linhas_calor = _tabela_de_calor(celulas)
        return (
            tiles.ficha(perfil, mode),
            cartoes,
            figura_de_chutes.mapa_de_chutes(chutes, mode),
            COLUNAS_DE_CHUTES,
            _linhas_de_chutes(chutes),
            figura_de_calor.mapa_de_calor(celulas, mode),
            colunas_calor,
            linhas_calor,
            resumo,
        )
