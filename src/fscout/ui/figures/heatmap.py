"""Mapa de calor: onde o atleta age, a partir das células de grade pré-calculadas.

A grade é contada na ingestão (6 colunas x 5 linhas, `domain/pitch.py`), não estimada a
cada requisição. Duas consequências: a tela responde rápido sobre 662 mil eventos, e o
número que aparece é uma contagem exata de ações, não uma densidade suavizada cujo
parâmetro ninguém consegue justificar numa defesa.

Magnitude pede **um matiz só, do claro ao escuro** — nunca arco-íris. A rampa é a azul
da paleta de referência, e o degrau mais claro significa "quase nada", podendo recuar
em direção à superfície. Como a cor sozinha não é canal acessível numa escala contínua,
a tela que usa este gráfico precisa oferecer a tabela equivalente ao lado.

O vão de 2px entre células é a mesma regra de sempre: quem separa as marcas é a
superfície, não um traço desenhado em volta delas.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.domain.pitch import DEFAULT_GRID_COLS, DEFAULT_GRID_ROWS, PITCH_LENGTH, PITCH_WIDTH
from fscout.ui import pitch
from fscout.ui.theme import Mode, escala_sequencial, tokens

Celula = dict[str, Any]

VAO = 2  # vão da superfície entre células
TERCOS = ("campo de defesa", "meio-campo", "campo de ataque")


def matriz(
    celulas: list[Celula], cols: int = DEFAULT_GRID_COLS, rows: int = DEFAULT_GRID_ROWS
) -> list[list[int]]:
    """Contagens em forma de matriz `[linha][coluna]`, com zero onde não houve ação.

    Exposta separadamente porque a tabela equivalente ao gráfico lê daqui: as duas
    leituras saem do mesmo número, então não há como divergirem.
    """
    grade = [[0 for _ in range(cols)] for _ in range(rows)]
    for celula in celulas:
        coluna = int(celula.get("grid_col", -1))
        linha = int(celula.get("grid_row", -1))
        if 0 <= coluna < cols and 0 <= linha < rows:
            grade[linha][coluna] = int(celula.get("actions", 0))
    return grade


def descrever(coluna: int, linha: int, cols: int, rows: int) -> str:
    """Nome futebolístico da célula, para o leitor não ter que traduzir índices."""
    terco = TERCOS[min(coluna * len(TERCOS) // cols, len(TERCOS) - 1)]
    return f"{terco} · faixa {linha + 1} de {rows}, da esquerda de quem ataca"


def mapa_de_calor(
    celulas: list[Celula],
    mode: Mode | str = "light",
    altura: int = 470,
    cols: int = DEFAULT_GRID_COLS,
    rows: int = DEFAULT_GRID_ROWS,
) -> go.Figure:
    """Campo inteiro, com a contagem de ações por célula."""
    t = tokens(mode)
    grade = matriz(celulas, cols, rows)

    largura_celula = PITCH_LENGTH / cols
    altura_celula = PITCH_WIDTH / rows
    centros_x = [(coluna + 0.5) * largura_celula for coluna in range(cols)]
    centros_y = [(linha + 0.5) * altura_celula for linha in range(rows)]
    descricoes = [
        [descrever(coluna, linha, cols, rows) for coluna in range(cols)] for linha in range(rows)
    ]

    figura = pitch.figura(mode, x_min=0.0, x_max=PITCH_LENGTH, altura=altura)
    figura.add_trace(
        go.Heatmap(
            z=grade,
            x=centros_x,
            y=centros_y,
            text=descricoes,
            xgap=VAO,
            ygap=VAO,
            zmin=0,
            colorscale=escala_sequencial(),
            hovertemplate="<b>%{z} ações</b><br>%{text}<extra></extra>",
            colorbar={
                "title": {"text": "ações", "font": {"color": t.ink_secondary, "size": 11}},
                "tickfont": {"color": t.muted, "size": 10},
                "outlinewidth": 0,
                "thickness": 12,
                "len": 0.62,
                "x": 1.02,
            },
        )
    )
    # As linhas do campo passam a valer como referência **sobre** as células: por baixo
    # elas sumiriam atrás dos degraus escuros da rampa.
    figura.update_shapes(layer="above")
    figura.update_layout(
        margin={"l": 8, "r": 76, "t": 8, "b": 8},
        hoverlabel={
            "bgcolor": t.surface,
            "bordercolor": t.border,
            "font": {"color": t.ink, "size": 12},
        },
    )
    return figura
