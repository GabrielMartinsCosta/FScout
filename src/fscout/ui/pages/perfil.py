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
from fscout.ui.figures import goal_mouth as figura_da_boca
from fscout.ui.figures import heatmap as figura_de_calor
from fscout.ui.figures import pass_map as figura_de_passes
from fscout.ui.figures import shot_map as figura_de_chutes
from fscout.ui.format import TRACO
from fscout.ui.theme import FONT_FAMILY, Mode, Tokens, tokens


class Ids:
    ATLETA = "perfil-atleta"
    SUBCONJUNTO = "perfil-subconjunto"
    PERSPECTIVA = "perfil-perspectiva"
    FICHA = "perfil-ficha"
    CARTOES = "perfil-cartoes"
    CHUTES = "perfil-chutes"
    RESUMO_CHUTES = "perfil-resumo-chutes"
    TABELA_CHUTES = "perfil-tabela-chutes"
    CALOR = "perfil-calor"
    TABELA_CALOR = "perfil-tabela-calor"
    BOCA = "perfil-boca"
    RESUMO_BOCA = "perfil-resumo-boca"
    PASSES = "perfil-passes"
    SUBCONJUNTO_PASSES = "perfil-subconjunto-passes"
    TABELA_PASSES = "perfil-tabela-passes"
    RESUMO_PASSES = "perfil-resumo-passes"


# Recortes de finalização. Ficam na linha de controles da tela, e não dentro de um
# cartão: filtro por gráfico faria o mapa de chutes e a boca do gol discordarem sem
# que o leitor tivesse como perceber.
SUBCONJUNTOS = [
    {"label": "Todas", "value": "todas"},
    {"label": "Só os gols", "value": "gols"},
    {"label": "Só pênaltis", "value": "penaltis"},
]

PERSPECTIVAS = [
    {"label": "De quem bate", "value": "batedor"},
    {"label": "De quem defende", "value": "goleiro"},
]


def filtrar_chutes(chutes: list[dict[str, Any]], subconjunto: str) -> list[dict[str, Any]]:
    """Recorta as finalizações sem consultar a API de novo.

    O mesmo conjunto alimenta o mapa de chutes, a boca do gol e a tabela, então os três
    mostram exatamente as mesmas finalizações.
    """
    if subconjunto == "gols":
        return [chute for chute in chutes if chute.get("is_goal")]
    if subconjunto == "penaltis":
        return [chute for chute in chutes if str(chute.get("shot_type")) == "penalty"]
    return chutes


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
    titulo: str,
    explicacao: str,
    grafico: Any,
    t: Tokens,
    tabela: Any = None,
    rodape: Any = None,
) -> html.Div:
    """Gráfico com sua tabela equivalente recolhida logo abaixo.

    `tabela` é opcional porque nem toda figura precisa de uma: quando o valor já está
    escrito dentro da marca, como na grade 3x3 da boca do gol, a tabela repetiria o que
    está à vista. O que não pode faltar é o valor ser legível sem depender da cor.
    """
    corpo: list[Any] = [
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
    ]
    if rodape is not None:
        corpo.append(rodape)
    if tabela is not None:
        corpo.append(
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
            )
        )
    return html.Div(
        corpo,
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
                    tiles.campo(
                        "Atleta",
                        dcc.Dropdown(id=Ids.ATLETA, placeholder="Busque pelo nome"),
                        t,
                        "420px",
                    ),
                    tiles.campo(
                        "Finalizações",
                        dcc.RadioItems(
                            id=Ids.SUBCONJUNTO,
                            options=SUBCONJUNTOS,
                            value="todas",
                            inline=True,
                            style={"color": t.ink, "fontSize": "12px"},
                        ),
                        t,
                        "260px",
                    ),
                    tiles.campo(
                        "Passes",
                        dcc.Dropdown(
                            id=Ids.SUBCONJUNTO_PASSES,
                            options=[
                                {"label": rotulo, "value": chave}
                                for chave, rotulo in figura_de_passes.SUBCONJUNTOS
                            ],
                            value="progressivos",
                            clearable=False,
                        ),
                        t,
                        "200px",
                    ),
                    tiles.campo(
                        "Boca do gol vista",
                        dcc.RadioItems(
                            id=Ids.PERSPECTIVA,
                            options=PERSPECTIVAS,
                            value="batedor",
                            inline=True,
                            style={"color": t.ink, "fontSize": "12px"},
                        ),
                        t,
                        "250px",
                    ),
                ],
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": "12px 18px",
                    "alignItems": "flex-end",
                    "marginBottom": "16px",
                },
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
                        t,
                        tabela=dash_table.DataTable(
                            id=Ids.TABELA_CHUTES, sort_action="native", **tiles.estilos_de_tabela(t)
                        ),
                        rodape=html.Div(
                            id=Ids.RESUMO_CHUTES,
                            style={"color": t.muted, "fontSize": "12px", "marginTop": "10px"},
                        ),
                    ),
                    cartao_de_grafico(
                        "Mapa de calor",
                        "Ações por célula da grade (6 x 5), contadas na ingestão. "
                        "Ataque para a direita.",
                        dcc.Graph(id=Ids.CALOR, config={"displayModeBar": False}),
                        t,
                        tabela=dash_table.DataTable(
                            id=Ids.TABELA_CALOR, **tiles.estilos_de_tabela(t)
                        ),
                    ),
                    cartao_de_grafico(
                        "Mapa de passes",
                        "Da origem ao destino, cor pelo desfecho. Ataque para a direita.",
                        dcc.Graph(id=Ids.PASSES, config={"displayModeBar": False}),
                        t,
                        tabela=dash_table.DataTable(
                            id=Ids.TABELA_PASSES,
                            sort_action="native",
                            page_size=25,
                            **tiles.estilos_de_tabela(t),
                        ),
                        rodape=html.Div(
                            id=Ids.RESUMO_PASSES,
                            style={"color": t.muted, "fontSize": "12px", "marginTop": "10px"},
                        ),
                    ),
                    cartao_de_grafico(
                        "Boca do gol",
                        "Em que parte do gol as finalizações entram. A contagem vai escrita "
                        "na célula, então o valor não depende da cor.",
                        dcc.Graph(id=Ids.BOCA, config={"displayModeBar": False}),
                        t,
                        rodape=html.Div(
                            id=Ids.RESUMO_BOCA,
                            style={"color": t.muted, "fontSize": "12px", "marginTop": "10px"},
                        ),
                    ),
                ],
                style={"display": "flex", "flexWrap": "wrap", "gap": "16px", "marginTop": "16px"},
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


DIRECOES = {"forward": "para frente", "sideways": "para o lado", "backward": "para trás"}
ALCANCES = {"short": "curto", "medium": "médio", "long": "longo"}

COLUNAS_DE_PASSES = [
    {"name": "Data", "id": "data"},
    {"name": "Min", "id": "min"},
    {"name": "Adversário", "id": "adversario"},
    {"name": "Para", "id": "destinatario"},
    {"name": "Desfecho", "id": "desfecho"},
    {"name": "Tipo", "id": "tipo"},
    {"name": "Comprimento (m)", "id": "comprimento"},
    {"name": "Alcance", "id": "alcance"},
    {"name": "Direção", "id": "direcao"},
]


def _linhas_de_passes(passes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "data": str(passe.get("match_date", ""))[:10],
            "min": passe.get("minute"),
            "adversario": passe.get("opponent") or TRACO,
            "destinatario": passe.get("recipient") or TRACO,
            "desfecho": "Certo" if passe.get("is_complete") else "Errado",
            "tipo": figura_de_passes.TIPOS.get(
                str(passe.get("pass_type")), str(passe.get("pass_type"))
            ),
            "comprimento": (
                f"{passe['length_m']:.1f}".replace(".", ",")
                if passe.get("length_m") is not None
                else TRACO
            ),
            "alcance": ALCANCES.get(str(passe.get("length_bucket")), TRACO),
            "direcao": DIRECOES.get(str(passe.get("direction")), TRACO),
        }
        for passe in passes
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
        Output(Ids.BOCA, "figure"),
        Output(Ids.RESUMO_BOCA, "children"),
        Output(Ids.PASSES, "figure"),
        Output(Ids.TABELA_PASSES, "columns"),
        Output(Ids.TABELA_PASSES, "data"),
        Output(Ids.RESUMO_PASSES, "children"),
        Input(Ids.ATLETA, "value"),
        Input(FiltroIds.ARMAZEM, "data"),
        Input(Ids.SUBCONJUNTO, "value"),
        Input(Ids.PERSPECTIVA, "value"),
        Input(Ids.SUBCONJUNTO_PASSES, "value"),
    )
    def _carregar(
        player_id: int | None,
        recorte: dict[str, Any] | None,
        subconjunto: str,
        perspectiva: str,
        subconjunto_passes: str,
    ) -> tuple[Any, ...]:
        t = tokens(mode)
        vazio_chutes = figura_de_chutes.mapa_de_chutes([], mode)
        vazio_calor = figura_de_calor.mapa_de_calor([], mode)
        vazio_boca = figura_da_boca.boca_do_gol([], mode, perspectiva)
        vazio_passes = figura_de_passes.mapa_de_passes([], mode)
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
                vazio_boca,
                "",
                vazio_passes,
                COLUNAS_DE_PASSES,
                [],
                "",
            )

        try:
            perfil = api_client.atleta(player_id)
            chutes = api_client.chutes(player_id, recorte)
            passes = api_client.passes(player_id, recorte)
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
                vazio_boca,
                "",
                vazio_passes,
                COLUNAS_DE_PASSES,
                [],
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

        # O mesmo conjunto alimenta mapa, tabela e boca do gol: se cada um filtrasse por
        # conta própria, os três poderiam mostrar finalizações diferentes.
        escolhidos = filtrar_chutes(chutes, subconjunto)

        desenhaveis = figura_de_chutes.com_coordenada(escolhidos)
        fora_do_mapa = len(escolhidos) - len(desenhaveis)
        resumo = f"{len(escolhidos)} finalizações no recorte"
        if subconjunto != "todas":
            resumo += f", de {len(chutes)} no total"
        if fora_do_mapa:
            resumo += f"; {fora_do_mapa} sem coordenada registrada, ausentes do mapa"
        resumo += ". A disputa de pênaltis não entra."

        contagem = figura_da_boca.contagens(escolhidos, perspectiva)
        resumo_boca = (
            f"{contagem['na_grade']} na boca do gol · "
            f"{contagem['fora']} para fora das traves ou por cima"
        )
        if contagem["sem_zona"]:
            resumo_boca += f" · {contagem['sem_zona']} sem zona registrada"
        resumo_boca += f". Grade {figura_da_boca.PERSPECTIVAS[perspectiva]}."

        passes_escolhidos = figura_de_passes.filtrar(passes, subconjunto_passes)
        conta_passes = figura_de_passes.contagens(passes_escolhidos)
        rotulo_passes = dict(figura_de_passes.SUBCONJUNTOS)[subconjunto_passes].lower()
        # "Tentativas" e não "passes": as métricas de mesmo nome no catálogo contam só
        # os completos, e sem essa palavra o rodapé contradiria o cartão ao lado.
        resumo_passes = (
            f"{conta_passes['tentativas']} tentativas ({rotulo_passes}), "
            f"{conta_passes['certos']} certas e {conta_passes['errados']} erradas, "
            f"de {len(passes)} passes no recorte"
        )
        if conta_passes["sem_coordenada"]:
            resumo_passes += f"; {conta_passes['sem_coordenada']} sem origem ou destino registrados"
        if conta_passes["tentativas"] - conta_passes["sem_coordenada"] > (
            figura_de_passes.MARCADORES_ATE
        ):
            resumo_passes += (
                f". Acima de {figura_de_passes.MARCADORES_ATE} passes os marcadores de "
                "destino são omitidos para o mapa continuar legível — os valores seguem "
                "na tabela"
            )
        resumo_passes += "."

        colunas_calor, linhas_calor = _tabela_de_calor(celulas)
        return (
            tiles.ficha(perfil, mode),
            cartoes,
            figura_de_chutes.mapa_de_chutes(escolhidos, mode),
            COLUNAS_DE_CHUTES,
            _linhas_de_chutes(escolhidos),
            figura_de_calor.mapa_de_calor(celulas, mode),
            colunas_calor,
            linhas_calor,
            resumo,
            figura_da_boca.boca_do_gol(escolhidos, mode, perspectiva),
            resumo_boca,
            figura_de_passes.mapa_de_passes(passes_escolhidos, mode),
            COLUNAS_DE_PASSES,
            _linhas_de_passes(passes_escolhidos),
            resumo_passes,
        )
