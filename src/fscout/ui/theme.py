"""Tokens de cor e template de gráfico — a única fonte de verdade visual da interface.

Nenhum módulo de gráfico escreve hexadecimal. Todos pedem a cor pelo papel que ela
exerce (série 1, tinta secundária, grade), de modo que trocar o tema é trocar este
arquivo, e não vinte figuras.

**As cores não foram escolhidas no olho.** São a paleta de referência do método de
visualização, e os subconjuntos que o FScout usa foram verificados por cálculo com
`scripts/validate_palette.py` (porte fiel do validador original, já que esta máquina
não tem Node). O que a verificação devolveu, em ΔE OKLab multiplicado por 100:

| Subconjunto | Modo | CVD (pior par) | Visão normal | Veredito |
|---|---|---|---|---|
| 3 séries, todos os pares | claro | 9.2 (deutan) | 24.0 | passa |
| 3 séries, todos os pares | escuro | 9.4 (deutan) | 20.9 | passa |
| 4 séries, adjacente | claro | 9.1 (protan) | 22.9 | passa |
| 4 séries, adjacente | escuro | 8.4 (protan) | 19.8 | passa |
| 4 séries, todos os pares | claro | 9.1 | **13.7** | **reprova** |

Daí a regra que governa o desenho das telas: **formas em que qualquer série pode
encostar em qualquer outra — dispersão, bolha, radar — param em três séries.** A
quarta coloca amarelo ao lado de laranja e o par fica indistinguível até para quem
enxerga todas as cores (13.7, abaixo do piso de 15). Não é preferência estética; é o
motivo pelo qual o mapa de chutes tem três classes de desfecho e o radar aceita no
máximo três atletas.

Duas cores do modo claro ficam abaixo de 3:1 contra a superfície (`#1baf7a` em 2.74 e
`#eda100` em 2.11). A regra permite usá-las **desde que** o valor esteja legível sem
depender da cor: por isso toda figura aqui vem acompanhada de rótulo direto e de uma
tabela equivalente.

O modo escuro não é uma inversão automática do claro: são degraus próprios dos mesmos
matizes, escolhidos para a superfície escura e verificados contra ela.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import plotly.graph_objects as go

Mode = Literal["light", "dark"]

# Pilha do sistema: nenhuma fonte de display ou serifada, nem no número de destaque.
FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'


@dataclass(frozen=True)
class Tokens:
    """Os papéis de cor de um modo. Gráficos pedem por papel, nunca por hexadecimal."""

    mode: Mode
    surface: str  # superfície do gráfico
    page: str  # plano da página, atrás dos cartões
    ink: str  # tinta primária: títulos, valores
    ink_secondary: str  # tinta secundária: rótulos
    muted: str  # eixos e marcações
    grid: str  # linha de grade, um passo fora da superfície
    axis: str  # linha de base
    border: str  # anel de um fio
    series: tuple[str, ...]  # slots categóricos, em ordem fixa
    sequential: tuple[str, ...]  # rampa de um matiz, claro -> escuro
    good: str
    critical: str

    def serie(self, indice: int) -> str:
        """Cor do slot `indice` (base zero), sem reciclar.

        Estourar os oito slots é erro de composição, não de cor: a resposta é agrupar
        em "outros" ou facetar, nunca gerar um nono matiz — um matiz gerado é
        indistinguível de algum já em uso sob daltonismo.
        """
        if not 0 <= indice < len(self.series):
            raise IndexError(
                f"slot {indice} fora da paleta de {len(self.series)}: agrupe em 'outros' ou facete"
            )
        return self.series[indice]


# Escala sequencial azul, degraus 100->700 da paleta de referência.
_SEQUENCIAL = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)  # fmt: skip

LIGHT = Tokens(
    mode="light",
    surface="#fcfcfb",
    page="#f9f9f7",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    border="rgba(11,11,11,0.10)",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    sequential=_SEQUENCIAL,
    good="#0ca30c",
    critical="#d03b3b",
)

DARK = Tokens(
    mode="dark",
    surface="#1a1a19",
    page="#0d0d0d",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    border="rgba(255,255,255,0.10)",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    sequential=_SEQUENCIAL,
    good="#0ca30c",
    critical="#d03b3b",
)

TEMAS: dict[str, Tokens] = {"light": LIGHT, "dark": DARK}

# Teto de séries para formas em que qualquer série encosta em qualquer outra
# (dispersão, bolha, radar). Medido, não estimado: ver a tabela no topo do módulo.
MAX_SERIES_TODOS_OS_PARES = 3

# Especificações de marca, fixas em todos os gráficos.
LARGURA_LINHA = 2
TAMANHO_MARCADOR = 9  # >= 8px
LARGURA_ANEL = 2  # anel na cor da superfície, para marcas que se sobrepõem
ALVO_MINIMO_PX = 24  # área de acerto do ponteiro, bem maior que a marca


def tokens(mode: Mode | str) -> Tokens:
    return TEMAS.get(str(mode), LIGHT)


def template(mode: Mode | str) -> go.layout.Template:
    """Template do Plotly com as marcas finas e a grade recessiva do método."""
    t = tokens(mode)
    eixo = {
        "gridcolor": t.grid,
        "gridwidth": 1,
        "griddash": "solid",  # grade tracejada lê como limiar; aqui é só grade
        "zeroline": False,
        "linecolor": t.axis,
        "linewidth": 1,
        "ticks": "outside",
        "ticklen": 4,
        "tickcolor": t.axis,
        "tickfont": {"color": t.muted, "size": 11},
        "title": {"font": {"color": t.ink_secondary, "size": 12}},
        "automargin": True,
    }
    return go.layout.Template(
        layout={
            "paper_bgcolor": t.surface,
            "plot_bgcolor": t.surface,
            "font": {"family": FONT_FAMILY, "color": t.ink_secondary, "size": 12},
            "title": {"font": {"family": FONT_FAMILY, "color": t.ink, "size": 15}, "x": 0},
            "colorway": list(t.series),
            "xaxis": eixo,
            "yaxis": eixo,
            "margin": {"l": 56, "r": 24, "t": 48, "b": 48},
            "hoverlabel": {
                "bgcolor": t.surface,
                "bordercolor": t.border,
                "font": {"family": FONT_FAMILY, "color": t.ink, "size": 12},
            },
            "legend": {
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "x": 0,
                "font": {"color": t.ink_secondary, "size": 12},
                "bgcolor": "rgba(0,0,0,0)",
            },
            "bargap": 0.45,  # barra fina: a folga da faixa é ar, não tinta
            "colorscale": {"sequential": [[i / 12, cor] for i, cor in enumerate(_SEQUENCIAL)]},
        }
    )


def escala_sequencial() -> list[list[object]]:
    """Rampa contínua de um matiz, para magnitude (mapa de calor, boca do gol)."""
    return [[i / (len(_SEQUENCIAL) - 1), cor] for i, cor in enumerate(_SEQUENCIAL)]


def com_alfa(cor: str, alfa: float) -> str:
    """Versão translúcida de uma cor do tema, para preenchimento de área.

    Preenchimento é lavagem, não bloco saturado: quem carrega a identidade da série é a
    linha de 2px, e a área só sugere a extensão dela.
    """
    limpa = cor.lstrip("#")
    r, g, b = (int(limpa[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alfa})"


def tinta_sobre(fundo_normalizado: float) -> str:
    """Tinta de um rótulo escrito *dentro* de um preenchimento colorido.

    Única exceção à regra de que texto não veste a cor da série: aqui o texto fica
    sobre a marca, então a cor sai da luminosidade do fundo para sempre ter contraste.
    """
    return "#ffffff" if fundo_normalizado >= 0.55 else "#0b0b0b"
