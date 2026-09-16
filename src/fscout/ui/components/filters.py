"""Barra de recortes: uma linha, acima de tudo o que ela delimita.

Os filtros ficam **fora** dos cartões de gráfico e valem para a tela inteira. Não é
arranjo estético: se cada gráfico tivesse o seu próprio recorte, dois números da mesma
tela poderiam discordar sem que o leitor tivesse como perceber. Um recorte só, no topo,
faz com que tudo abaixo concorde por construção.

Os campos são os mesmos que a API aceita (`slice_from_query`), com os mesmos nomes. A
tela não inventa filtro nenhum: ela preenche o `Slice` que o motor de métricas já sabia
aplicar, e é por isso que "gols em junho" e "gols contra determinado adversário" são a
mesma chamada com argumentos diferentes.
"""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from fscout.ui.theme import FONT_FAMILY, Mode, Tokens, tokens


class Ids:
    """Identificadores dos controles, num lugar só para os callbacks não os soletrarem."""

    COMPETICAO = "recorte-competicao"
    TEMPORADA = "recorte-temporada"
    PERIODO = "recorte-periodo"
    MANDO = "recorte-mando"
    MINUTOS = "recorte-minutos"
    ARMAZEM = "recorte-armazem"


MANDOS = [
    {"label": "Casa e fora", "value": "todos"},
    {"label": "Só em casa", "value": "home"},
    {"label": "Só fora", "value": "away"},
    {"label": "Campo neutro", "value": "neutral"},
]


def opcoes_de_competicao(competicoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": f"{competicao['name']}"
            + (f" ({competicao['country']})" if competicao.get("country") else ""),
            "value": competicao["id"],
        }
        for competicao in competicoes
    ]


def opcoes_de_temporada(
    competicoes: list[dict[str, Any]], competition_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Temporadas das competições escolhidas, ou de todas quando nada foi escolhido.

    O nome da competição vai junto porque "2024" sozinho aparece em mais de uma.
    """
    escolhidas = set(competition_ids or [])
    opcoes = []
    for competicao in competicoes:
        if escolhidas and competicao["id"] not in escolhidas:
            continue
        for temporada in competicao.get("seasons", []):
            if not temporada.get("matches"):
                continue  # temporada sem partida carregada não filtra nada
            opcoes.append(
                {
                    "label": f"{competicao['name']} · {temporada['name']}",
                    "value": temporada["id"],
                }
            )
    return opcoes


def _campo(titulo: str, controle: Any, t: Tokens, largura: str) -> html.Div:
    return html.Div(
        [
            html.Label(
                titulo,
                style={
                    "color": t.ink_secondary,
                    "fontSize": "11px",
                    "display": "block",
                    "marginBottom": "4px",
                },
            ),
            controle,
        ],
        style={"flex": f"0 1 {largura}", "minWidth": "150px"},
    )


def barra(competicoes: list[dict[str, Any]], mode: Mode | str = "light") -> html.Div:
    """A linha de filtros. Tudo que estiver abaixo dela responde ao mesmo recorte."""
    t = tokens(mode)
    return html.Div(
        [
            _campo(
                "Competição",
                dcc.Dropdown(
                    id=Ids.COMPETICAO,
                    options=opcoes_de_competicao(competicoes),
                    multi=True,
                    placeholder="Todas",
                ),
                t,
                "260px",
            ),
            _campo(
                "Temporada",
                dcc.Dropdown(
                    id=Ids.TEMPORADA,
                    options=opcoes_de_temporada(competicoes),
                    multi=True,
                    placeholder="Todas",
                ),
                t,
                "280px",
            ),
            _campo(
                "Período",
                dcc.DatePickerRange(
                    id=Ids.PERIODO,
                    display_format="DD/MM/YYYY",
                    start_date_placeholder_text="Início",
                    end_date_placeholder_text="Fim",
                    clearable=True,
                ),
                t,
                "250px",
            ),
            _campo(
                "Mando",
                dcc.Dropdown(id=Ids.MANDO, options=MANDOS, value="todos", clearable=False),
                t,
                "170px",
            ),
            _campo(
                "Mínimo de minutos",
                dcc.Input(
                    id=Ids.MINUTOS,
                    type="number",
                    min=0,
                    step=90,
                    placeholder="sem piso",
                    style={"width": "100%", "height": "36px", "fontFamily": FONT_FAMILY},
                ),
                t,
                "150px",
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
    )


def montar_recorte(
    competition_ids: list[int] | None = None,
    season_ids: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    home_away: str | None = None,
    min_minutes: int | None = None,
) -> dict[str, Any]:
    """Traduz os controles para o recorte que a API entende.

    Campo vazio não vira filtro: ausência e "tudo" são a mesma coisa para o `Slice`.
    """
    recorte: dict[str, Any] = {}
    if competition_ids:
        recorte["competition_ids"] = competition_ids
    if season_ids:
        recorte["season_ids"] = season_ids
    if date_from:
        recorte["date_from"] = date_from
    if date_to:
        recorte["date_to"] = date_to
    if home_away and home_away != "todos":
        recorte["home_away"] = home_away
    if min_minutes:
        recorte["min_minutes"] = int(min_minutes)
    return recorte
