"""Mapa de chutes: de onde o atleta finaliza, com que probabilidade e com que desfecho.

Três decisões deste gráfico precisam estar escritas, porque são exatamente o que se
pergunta numa defesa.

**Por que só três classes de desfecho.** Dispersão é uma forma em que qualquer ponto
pode acabar encostado em qualquer outro, então a paleta tem que separar *todos* os
pares, não só os vizinhos. Medido com `scripts/validate_palette.py`, três séries passam
com folga (ΔE 9.2 no claro, 9.4 no escuro sob daltonismo) e a quarta reprova: amarelo e
laranja ficam a ΔE 13.7, abaixo do piso de 15 exigido para quem enxerga todas as cores.
O limite é medido, não estimado.

**O que conta como "no alvo".** Chute defendido pelo goleiro, inclusive o que ele manda
na trave (`saved`, `saved_to_post`). Bola na trave sem defesa **não** conta, nem chute
bloqueado por jogador de linha — é a definição corrente de *shots on target*, e a
diferença aparece em qualquer comparação com fonte externa.

**O tamanho é escala absoluta, não relativa.** O diâmetro sai do xG entre 0 e 1 sempre
pela mesma régua. Se a régua se ajustasse ao melhor chute de cada atleta, dois mapas
lado a lado ficariam incomparáveis: o mesmo tamanho significaria coisas diferentes.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.domain.pitch import PITCH_LENGTH
from fscout.ui import pitch
from fscout.ui.format import TRACO
from fscout.ui.theme import LARGURA_ANEL, Mode, tokens

Chute = dict[str, Any]

# Defendido pelo goleiro — inclusive quando ele espalma na trave.
NO_ALVO = frozenset({"saved", "saved_to_post"})

# Ordem fixa dos slots categóricos. Nunca reciclada, nunca reatribuída por quantidade:
# a cor acompanha a classe, então filtrar não repinta o que sobrou.
CLASSES: tuple[tuple[str, str], ...] = (
    ("gol", "Gol"),
    ("no_alvo", "No alvo"),
    ("fora", "Para fora ou bloqueado"),
)

DIAMETRO_MINIMO = 9.0  # >= 8px mesmo com xG perto de zero
DIAMETRO_MAXIMO = 30.0
X_MINIMO = 60.0  # o campo de ataque basta: não há finalização do próprio campo que valha a escala
DISTANCIA_DE_ACERTO = 25  # o ponteiro só precisa chegar perto, não acertar o ponto

DESFECHOS = {
    "goal": "Gol",
    "saved": "Defendido",
    "saved_to_post": "Defendido na trave",
    "saved_off_target": "Defendido, ia para fora",
    "blocked": "Bloqueado",
    "off_target": "Para fora",
    "post": "Na trave",
    "wayward": "Muito errado",
    "offside": "Impedido",
}

PARTES_DO_CORPO = {
    "left_foot": "pé esquerdo",
    "right_foot": "pé direito",
    "head": "cabeça",
    "chest": "peito",
    "other": "outra parte",
}


def classificar(chute: Chute) -> str:
    """Classe de desfecho do chute, entre as três que a paleta comporta."""
    if chute.get("is_goal"):
        return "gol"
    return "no_alvo" if str(chute.get("outcome")) in NO_ALVO else "fora"


def com_coordenada(chutes: list[Chute]) -> list[Chute]:
    """Só os chutes que têm onde ser desenhados.

    Finalização sem coordenada existe no banco e conta nas métricas; ela apenas não
    aparece no mapa. Quem chama deve dizer ao leitor quantas ficaram de fora.
    """
    return [chute for chute in chutes if chute.get("x") is not None and chute.get("y") is not None]


def _diametro(xg: float | None) -> float:
    valor = 0.0 if xg is None else max(0.0, min(1.0, float(xg)))
    return DIAMETRO_MINIMO + valor * (DIAMETRO_MAXIMO - DIAMETRO_MINIMO)


def _virgula(texto: str) -> str:
    return texto.replace(".", ",")


def _detalhe(chute: Chute) -> str:
    partes = []
    distancia = chute.get("distance_m")
    if distancia is not None:
        partes.append(_virgula(f"{float(distancia):.1f} m"))
    parte = PARTES_DO_CORPO.get(str(chute.get("body_part")), "")
    if parte:
        partes.append(parte)
    return " · ".join(partes)


def mapa_de_chutes(chutes: list[Chute], mode: Mode | str = "light", altura: int = 470) -> go.Figure:
    """Um ponto por finalização: posição no campo, tamanho por xG, cor por desfecho."""
    t = tokens(mode)
    figura = pitch.figura(mode, x_min=X_MINIMO, x_max=PITCH_LENGTH, altura=altura)
    desenhaveis = com_coordenada(chutes)

    for indice, (chave, rotulo) in enumerate(CLASSES):
        do_grupo = [chute for chute in desenhaveis if classificar(chute) == chave]
        figura.add_trace(
            go.Scatter(
                x=[chute["x"] for chute in do_grupo],
                y=[chute["y"] for chute in do_grupo],
                mode="markers",
                name=rotulo,
                marker={
                    "size": [_diametro(chute.get("xg")) for chute in do_grupo],
                    "color": t.serie(indice),
                    # Anel na cor da superfície: é o que mantém legível o ponto que
                    # cai em cima de outro. Contorno colorido seria tinta sem dado.
                    "line": {"color": t.surface, "width": LARGURA_ANEL},
                },
                customdata=[
                    [
                        _virgula(f"{chute['xg']:.2f}") if chute.get("xg") is not None else TRACO,
                        DESFECHOS.get(str(chute.get("outcome")), str(chute.get("outcome"))),
                        chute.get("minute", 0),
                        chute.get("opponent") or "",
                        _detalhe(chute),
                    ]
                    for chute in do_grupo
                ],
                hovertemplate=(
                    "<b>xG %{customdata[0]}</b><br>"
                    "%{customdata[1]} · %{customdata[2]}'<br>"
                    "contra %{customdata[3]}<br>"
                    "%{customdata[4]}<extra></extra>"
                ),
            )
        )

    figura.update_layout(
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "x": 0,
            "font": {"color": t.ink_secondary, "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        hoverdistance=DISTANCIA_DE_ACERTO,
        hoverlabel={
            "bgcolor": t.surface,
            "bordercolor": t.border,
            "font": {"color": t.ink, "size": 12},
        },
    )
    return figura
