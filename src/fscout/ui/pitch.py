"""Desenho do campo, sob as figuras que acontecem sobre ele.

O campo é **cenário, não dado**: sai em linha de um fio, na cor mais recessiva do tema,
e por baixo das marcas (`layer="below"`). Quem tem que saltar aos olhos é o chute, não
a linha da grande área.

As coordenadas são as mesmas do banco (StatsBomb, 120x80 jardas, origem no canto
superior esquerdo), sem nenhuma conversão no meio. Isso é deliberado: um chute gravado
em `x=108, y=40` é desenhado em `x=108, y=40`, então o que aparece na tela pode ser
conferido contra o banco sem refazer conta nenhuma.

Como `y` cresce "para baixo" no campo desenhado, o eixo vertical é invertido na
exibição — é o que faz a faixa `y=0` aparecer em cima, do lado esquerdo de quem ataca.
A proporção fica travada (`scaleanchor`), senão o campo estica com a janela e as
distâncias mentem.
"""

from __future__ import annotations

import math
from typing import Any

import plotly.graph_objects as go

from fscout.domain.pitch import (
    GOAL_LEFT_POST_Y,
    GOAL_RIGHT_POST_Y,
    PENALTY_AREA_MAX_Y,
    PENALTY_AREA_MIN_X,
    PENALTY_AREA_MIN_Y,
    PITCH_LENGTH,
    PITCH_WIDTH,
    SIX_YARD_BOX_MAX_Y,
    SIX_YARD_BOX_MIN_X,
    SIX_YARD_BOX_MIN_Y,
)
from fscout.ui.theme import Mode, Tokens, tokens

LINHA = 1  # um fio; o campo não disputa atenção com os dados
RAIO_CIRCULO_CENTRAL = 10.0
RAIO_MARCA_PENAL = 0.4
PROFUNDIDADE_DO_GOL = 2.0  # só para o gol aparecer fora da linha de fundo
MARGEM = 3.0

# Meio-campo e marcas de pênalti, nas duas metades.
MEIO_CAMPO_X = PITCH_LENGTH / 2
MARCA_ATACADA_X = 108.0
MARCA_DEFENDIDA_X = PITCH_LENGTH - MARCA_ATACADA_X  # 12.0

# Arco da meia-lua: o pedaço do círculo de 10 jardas em torno da marca que fica *fora*
# da grande área. Em vez de arco SVG (cuja bandeira de sentido é fácil de errar), os
# pontos são calculados aqui — o resultado é o mesmo e não depende de convenção.
_COS_LIMITE = (PENALTY_AREA_MIN_X - MARCA_ATACADA_X) / RAIO_CIRCULO_CENTRAL  # -0.6
_ABERTURA = math.degrees(math.acos(_COS_LIMITE))  # ~126.87°


def _caminho_de_arco(
    cx: float, cy: float, raio: float, de_graus: float, ate_graus: float, passos: int = 40
) -> str:
    pontos = []
    for i in range(passos + 1):
        angulo = math.radians(de_graus + (ate_graus - de_graus) * i / passos)
        pontos.append(f"{cx + raio * math.cos(angulo):.3f},{cy + raio * math.sin(angulo):.3f}")
    return "M " + " L ".join(pontos)


def _retangulo(x0: float, y0: float, x1: float, y1: float, cor: str) -> dict[str, Any]:
    return {
        "type": "rect",
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "line": {"color": cor, "width": LINHA},
        "fillcolor": "rgba(0,0,0,0)",
        "layer": "below",
    }


def _linha(x0: float, y0: float, x1: float, y1: float, cor: str) -> dict[str, Any]:
    return {
        "type": "line",
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "line": {"color": cor, "width": LINHA},
        "layer": "below",
    }


def _circulo(
    cx: float, cy: float, raio: float, cor: str, preenchido: bool = False
) -> dict[str, Any]:
    return {
        "type": "circle",
        "x0": cx - raio,
        "y0": cy - raio,
        "x1": cx + raio,
        "y1": cy + raio,
        "line": {"color": cor, "width": LINHA},
        "fillcolor": cor if preenchido else "rgba(0,0,0,0)",
        "layer": "below",
    }


def _arco(caminho: str, cor: str) -> dict[str, Any]:
    return {
        "type": "path",
        "path": caminho,
        "line": {"color": cor, "width": LINHA},
        "layer": "below",
    }


def formas(t: Tokens, x_min: float = 0.0, x_max: float = PITCH_LENGTH) -> list[dict[str, Any]]:
    """Formas do campo visíveis na faixa `[x_min, x_max]`.

    Recortar importa: o mapa de chutes mostra só o campo de ataque, e desenhar a área
    defendida fora da vista deixaria o Plotly reservando espaço para nada.
    """
    cor = t.axis
    candidatas: list[tuple[float, float, dict[str, Any]]] = [
        # (x inicial, x final, forma)
        (0.0, PITCH_LENGTH, _retangulo(0, 0, PITCH_LENGTH, PITCH_WIDTH, cor)),
        (MEIO_CAMPO_X, MEIO_CAMPO_X, _linha(MEIO_CAMPO_X, 0, MEIO_CAMPO_X, PITCH_WIDTH, cor)),
        (
            MEIO_CAMPO_X - RAIO_CIRCULO_CENTRAL,
            MEIO_CAMPO_X + RAIO_CIRCULO_CENTRAL,
            _circulo(MEIO_CAMPO_X, PITCH_WIDTH / 2, RAIO_CIRCULO_CENTRAL, cor),
        ),
        (
            MEIO_CAMPO_X,
            MEIO_CAMPO_X,
            _circulo(MEIO_CAMPO_X, PITCH_WIDTH / 2, RAIO_MARCA_PENAL, cor, preenchido=True),
        ),
        # Metade atacada: a que o mapa de chutes mostra.
        (
            PENALTY_AREA_MIN_X,
            PITCH_LENGTH,
            _retangulo(
                PENALTY_AREA_MIN_X, PENALTY_AREA_MIN_Y, PITCH_LENGTH, PENALTY_AREA_MAX_Y, cor
            ),
        ),
        (
            SIX_YARD_BOX_MIN_X,
            PITCH_LENGTH,
            _retangulo(
                SIX_YARD_BOX_MIN_X, SIX_YARD_BOX_MIN_Y, PITCH_LENGTH, SIX_YARD_BOX_MAX_Y, cor
            ),
        ),
        (
            MARCA_ATACADA_X,
            MARCA_ATACADA_X,
            _circulo(MARCA_ATACADA_X, PITCH_WIDTH / 2, RAIO_MARCA_PENAL, cor, preenchido=True),
        ),
        (
            PITCH_LENGTH,
            PITCH_LENGTH + PROFUNDIDADE_DO_GOL,
            _retangulo(
                PITCH_LENGTH,
                GOAL_LEFT_POST_Y,
                PITCH_LENGTH + PROFUNDIDADE_DO_GOL,
                GOAL_RIGHT_POST_Y,
                cor,
            ),
        ),
        (
            MARCA_ATACADA_X - RAIO_CIRCULO_CENTRAL,
            PENALTY_AREA_MIN_X,
            _arco(
                _caminho_de_arco(
                    MARCA_ATACADA_X,
                    PITCH_WIDTH / 2,
                    RAIO_CIRCULO_CENTRAL,
                    _ABERTURA,
                    360 - _ABERTURA,
                ),
                cor,
            ),
        ),
        # Metade defendida, espelhada.
        (
            0.0,
            PITCH_LENGTH - PENALTY_AREA_MIN_X,
            _retangulo(
                0,
                PENALTY_AREA_MIN_Y,
                PITCH_LENGTH - PENALTY_AREA_MIN_X,
                PENALTY_AREA_MAX_Y,
                cor,
            ),
        ),
        (
            0.0,
            PITCH_LENGTH - SIX_YARD_BOX_MIN_X,
            _retangulo(
                0,
                SIX_YARD_BOX_MIN_Y,
                PITCH_LENGTH - SIX_YARD_BOX_MIN_X,
                SIX_YARD_BOX_MAX_Y,
                cor,
            ),
        ),
        (
            MARCA_DEFENDIDA_X,
            MARCA_DEFENDIDA_X,
            _circulo(MARCA_DEFENDIDA_X, PITCH_WIDTH / 2, RAIO_MARCA_PENAL, cor, preenchido=True),
        ),
        (
            -PROFUNDIDADE_DO_GOL,
            0.0,
            _retangulo(-PROFUNDIDADE_DO_GOL, GOAL_LEFT_POST_Y, 0, GOAL_RIGHT_POST_Y, cor),
        ),
        (
            PITCH_LENGTH - PENALTY_AREA_MIN_X,
            MARCA_DEFENDIDA_X + RAIO_CIRCULO_CENTRAL,
            _arco(
                _caminho_de_arco(
                    MARCA_DEFENDIDA_X,
                    PITCH_WIDTH / 2,
                    RAIO_CIRCULO_CENTRAL,
                    -_ABERTURA + 180,
                    _ABERTURA - 180,
                ),
                cor,
            ),
        ),
    ]
    return [forma for inicio, fim, forma in candidatas if fim >= x_min and inicio <= x_max]


def figura(
    mode: Mode | str = "light",
    x_min: float = 0.0,
    x_max: float = PITCH_LENGTH,
    altura: int = 460,
) -> go.Figure:
    """Figura vazia com o campo desenhado e os eixos travados.

    As marcas de dados entram depois, com `add_trace`, nas mesmas coordenadas do banco.
    """
    t = tokens(mode)
    figura_ = go.Figure()
    figura_.update_layout(
        shapes=formas(t, x_min, x_max),
        paper_bgcolor=t.surface,
        plot_bgcolor=t.surface,
        height=altura,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        showlegend=False,
        dragmode=False,
    )
    figura_.update_xaxes(
        range=[x_min - MARGEM, x_max + MARGEM],
        visible=False,
        constrain="domain",
    )
    # `y` cresce para baixo no campo desenhado, daí a inversão; a proporção fica travada
    # para o campo não esticar com a janela e falsear distâncias.
    figura_.update_yaxes(
        range=[PITCH_WIDTH + MARGEM, -MARGEM],
        visible=False,
        scaleanchor="x",
        scaleratio=1,
        constrain="domain",
    )
    return figura_
