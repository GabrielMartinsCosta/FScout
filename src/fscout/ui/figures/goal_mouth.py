"""Boca do gol: em que parte do gol o atleta acerta, e em que canto bate o pênalti.

A zona já vem calculada da ingestão (`shots.goal_mouth_zone`), então esta figura não
refaz geometria nenhuma — ela só conta e desenha. São nove zonas mais `off_target`, e
essa décima **não entra na grade**: ela não é uma parte do gol, é a ausência dele.
Espalhá-la pelas bordas inflaria zonas que não foram acertadas. Ela é relatada por fora.

**Perspectiva importa e é a ambiguidade clássica da análise de pênaltis.** O canto
esquerdo de quem bate é o canto direito de quem defende. A zona é gravada na
perspectiva do batedor; `mirror_to_keeper_view` troca para a de quem defende, e a tela
diz qual das duas está mostrando — sem isso, "bate sempre no canto esquerdo" é uma frase
que significa duas coisas opostas.

Aqui a contagem vai escrita dentro de cada célula. São nove células: rotular todas é o
que torna o valor legível sem depender de cor nem de passar o mouse, que é justamente o
que a escala contínua de cor exige. A tinta de cada rótulo sai da luminosidade do
preenchimento, para o número nunca sumir no degrau escuro da rampa.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.domain.pitch import (
    GOAL_CROSSBAR_Z,
    GOAL_LEFT_POST_Y,
    GOAL_RIGHT_POST_Y,
    GoalMouthZone,
    mirror_to_keeper_view,
)
from fscout.ui.theme import Mode, escala_sequencial, tinta_sobre, tokens

Chute = dict[str, Any]

LARGURA_DO_GOL = GOAL_RIGHT_POST_Y - GOAL_LEFT_POST_Y  # 8 jardas
COLUNAS = ("left", "center", "right")
# De cima para baixo na tela, que é como se olha para um gol.
LINHAS = ("high", "mid", "low")

ROTULOS_DE_COLUNA = {
    "batedor": ("Esquerda", "Meio", "Direita"),
    "goleiro": ("Esquerda", "Meio", "Direita"),
}
ROTULOS_DE_LINHA = ("Alto", "Meia altura", "Rasteiro")

PERSPECTIVAS = {
    "batedor": "na perspectiva de quem bate",
    "goleiro": "na perspectiva de quem defende",
}

VAO = 2
ESPESSURA_DA_TRAVE = 3


def zonas_dos_chutes(chutes: list[Chute], perspectiva: str = "batedor") -> list[GoalMouthZone]:
    """Zonas válidas dos chutes, já na perspectiva pedida."""
    zonas: list[GoalMouthZone] = []
    for chute in chutes:
        bruta = chute.get("goal_mouth_zone")
        if not bruta:
            continue
        zona = GoalMouthZone(str(bruta))
        zonas.append(mirror_to_keeper_view(zona) if perspectiva == "goleiro" else zona)
    return zonas


def matriz(chutes: list[Chute], perspectiva: str = "batedor") -> list[list[int]]:
    """Contagem por zona, em `[linha][coluna]`, de cima para baixo e da esquerda."""
    grade = [[0 for _ in COLUNAS] for _ in LINHAS]
    for zona in zonas_dos_chutes(chutes, perspectiva):
        if zona is GoalMouthZone.OFF_TARGET:
            continue
        coluna, _, linha = str(zona).partition("_")
        grade[LINHAS.index(linha)][COLUNAS.index(coluna)] += 1
    return grade


def contagens(chutes: list[Chute], perspectiva: str = "batedor") -> dict[str, int]:
    """Quantos entraram na grade, quantos foram para fora e quantos não têm zona."""
    zonas = zonas_dos_chutes(chutes, perspectiva)
    fora = sum(1 for zona in zonas if zona is GoalMouthZone.OFF_TARGET)
    return {
        "na_grade": len(zonas) - fora,
        "fora": fora,
        "sem_zona": len(chutes) - len(zonas),
    }


def _frame_do_gol(cor: str) -> list[dict[str, Any]]:
    """Traves e travessão, desenhados por fora das células."""
    espessura = {"color": cor, "width": ESPESSURA_DA_TRAVE}
    return [
        {"type": "line", "x0": 0, "y0": 0, "x1": 0, "y1": GOAL_CROSSBAR_Z, "line": espessura},
        {
            "type": "line",
            "x0": LARGURA_DO_GOL,
            "y0": 0,
            "x1": LARGURA_DO_GOL,
            "y1": GOAL_CROSSBAR_Z,
            "line": espessura,
        },
        {
            "type": "line",
            "x0": 0,
            "y0": GOAL_CROSSBAR_Z,
            "x1": LARGURA_DO_GOL,
            "y1": GOAL_CROSSBAR_Z,
            "line": espessura,
        },
        {
            "type": "line",
            "x0": 0,
            "y0": 0,
            "x1": LARGURA_DO_GOL,
            "y1": 0,
            "line": {"color": cor, "width": 1},
        },
    ]


def boca_do_gol(
    chutes: list[Chute],
    mode: Mode | str = "light",
    perspectiva: str = "batedor",
    altura: int = 330,
) -> go.Figure:
    """Grade 3x3 da boca do gol, com a contagem escrita em cada zona."""
    t = tokens(mode)
    grade = matriz(chutes, perspectiva)
    maximo = max((max(linha) for linha in grade), default=0)

    largura_celula = LARGURA_DO_GOL / 3
    altura_celula = GOAL_CROSSBAR_Z / 3
    centros_x = [(indice + 0.5) * largura_celula for indice in range(3)]
    # A primeira linha é a mais alta, então a ordem vertical é invertida na hora de
    # posicionar: `LINHAS[0]` ("high") fica no topo do gol.
    centros_y = [(2 - indice + 0.5) * altura_celula for indice in range(3)]

    rotulos_coluna = ROTULOS_DE_COLUNA[perspectiva]
    descricoes = [
        [f"{ROTULOS_DE_LINHA[linha]} · {rotulos_coluna[coluna]}" for coluna in range(3)]
        for linha in range(3)
    ]

    figura = go.Figure(
        go.Heatmap(
            z=grade,
            x=centros_x,
            y=centros_y,
            text=descricoes,
            xgap=VAO,
            ygap=VAO,
            zmin=0,
            colorscale=escala_sequencial(),
            showscale=False,  # a contagem está escrita na célula; a barra seria redundante
            hovertemplate="<b>%{z} finalizações</b><br>%{text}<extra></extra>",
        )
    )

    for indice_linha, linha in enumerate(grade):
        for indice_coluna, valor in enumerate(linha):
            proporcao = (valor / maximo) if maximo else 0.0
            figura.add_annotation(
                x=centros_x[indice_coluna],
                y=centros_y[indice_linha],
                text=str(valor),
                showarrow=False,
                font={
                    "size": 15,
                    # Única exceção à regra de texto não vestir cor de dado: o rótulo
                    # está *dentro* do preenchimento, então a tinta sai da luminosidade.
                    "color": tinta_sobre(proporcao),
                },
            )

    figura.update_layout(
        height=altura,
        paper_bgcolor=t.surface,
        plot_bgcolor=t.surface,
        shapes=_frame_do_gol(t.axis),
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        dragmode=False,
        hoverlabel={
            "bgcolor": t.surface,
            "bordercolor": t.border,
            "font": {"color": t.ink, "size": 12},
        },
    )
    margem_x = LARGURA_DO_GOL * 0.06
    figura.update_xaxes(range=[-margem_x, LARGURA_DO_GOL + margem_x], visible=False)
    figura.update_yaxes(
        range=[-GOAL_CROSSBAR_Z * 0.12, GOAL_CROSSBAR_Z * 1.12],
        visible=False,
        scaleanchor="x",
        scaleratio=1,
    )
    return figura
