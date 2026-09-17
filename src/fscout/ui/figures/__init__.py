"""Figuras do painel. Cada módulo constrói uma figura e não busca dado nenhum."""

from __future__ import annotations

import plotly.graph_objects as go

from fscout.ui.theme import Mode, tokens


def aviso_no_lugar_do_grafico(
    mensagem: str, mode: Mode | str = "light", altura: int = 470
) -> go.Figure:
    """Uma explicação onde o gráfico estaria, quando ele não se aplica.

    Gráfico vazio e gráfico inaplicável parecem a mesma coisa na tela, e não são: um diz
    "o atleta não fez isso", o outro diz "a fonte não registra isso". Deixar o leitor
    concluir o primeiro quando o caso é o segundo é o tipo de erro que a ferramenta
    inteira existe para evitar.
    """
    t = tokens(mode)
    figura = go.Figure()
    figura.update_layout(
        height=altura,
        paper_bgcolor=t.surface,
        plot_bgcolor=t.surface,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": mensagem,
                "showarrow": False,
                "align": "center",
                "font": {"color": t.muted, "size": 13},
                "x": 0.5,
                "y": 0.5,
                "xref": "paper",
                "yref": "paper",
            }
        ],
    )
    return figura
