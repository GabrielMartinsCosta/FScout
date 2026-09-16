"""Mapa de passes: de onde para onde o atleta distribui, e o que deu certo.

Duas cores bastam — passe certo e passe errado — e duas séries passam folgadas em
qualquer checagem da paleta. O que este gráfico tem de difícil não é cor, é **volume**:
um meia-central pode ter dois mil passes num recorte, e dois mil objetos numa figura
travam o navegador.

A solução é desenhar cada categoria como **um traço só**, com os segmentos separados por
`None`. São dois traços de linha independentemente de haver trinta ou três mil passes.

Os marcadores de destino existem por dois motivos: eles dizem para que lado o passe foi,
e são eles que carregam o tooltip (uma linha quebrada em segmentos não tem onde
pendurar um). Mas marcador só ajuda enquanto dá para distinguir um do outro: acima de
`MARCADORES_ATE` passes eles viram confete e são omitidos. Quando isso acontece a tela
diz, e a tabela equivalente continua com todos os valores — tooltip enriquece, nunca é
o único caminho para o número.

Os recortes oferecidos não são estéticos: `progressivos`, `para a área`, `cruzamentos`,
`decisivos` e `bolas em profundidade` são as perguntas que a especificação do trabalho
faz sobre distribuição, e cada um deles é naturalmente pequeno o bastante para o mapa
ficar legível.

**Os recortes daqui filtram tentativas, e o catálogo de métricas conta outra coisa.**
As marcas `is_progressive`, `into_penalty_area` e `is_through_ball` são geométricas:
valem para o passe tentado, tenha ele chegado ou não. Já as métricas de mesmo nome no
catálogo somam só os completos — e os rótulos delas dizem isso ("Passes progressivos
*certos*", "Bolas em profundidade *certas*"). As duas leituras estão corretas e servem a
propósitos diferentes: num mapa, o passe progressivo que se perdeu é justamente o que se
quer ver, e é para isso que existe a cor por desfecho.

A consequência prática é que **quem exibe estes números precisa dizer "tentativas"**. Um
rodapé escrito "192 passes progressivos" ao lado de um cartão marcado "Passes
progressivos certos: 108" faria o leitor procurar um erro que não existe. `contagens`
devolve a separação pronta para o texto sair certo.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.domain.pitch import PITCH_LENGTH
from fscout.ui import pitch
from fscout.ui.format import TRACO
from fscout.ui.theme import LARGURA_ANEL, LARGURA_LINHA, Mode, com_alfa, tokens

Passe = dict[str, Any]

# Acima disso, marcador vira ruído: ficam só as linhas.
MARCADORES_ATE = 300
OPACIDADE_DA_LINHA = 0.55
TAMANHO_DO_DESTINO = 8
DISTANCIA_DE_ACERTO = 25

# Ordem fixa. A cor acompanha a classe, então filtrar não repinta o que sobrou.
CLASSES: tuple[tuple[str, str], ...] = (("certo", "Certo"), ("errado", "Errado"))

SUBCONJUNTOS: tuple[tuple[str, str], ...] = (
    ("todos", "Todos"),
    ("progressivos", "Progressivos"),
    ("para_area", "Para a área"),
    ("cruzamentos", "Cruzamentos"),
    ("decisivos", "Decisivos"),
    ("profundidade", "Em profundidade"),
)

_MARCAS = {
    "progressivos": "is_progressive",
    "para_area": "into_penalty_area",
    "cruzamentos": "is_cross",
    "profundidade": "is_through_ball",
}

TIPOS = {
    "open_play": "jogo corrido",
    "corner": "escanteio",
    "free_kick": "falta",
    "throw_in": "lateral",
    "goal_kick": "tiro de meta",
    "kick_off": "saída de bola",
    "interception": "interceptação",
    "recovery": "recuperação",
}


def filtrar(passes: list[Passe], subconjunto: str) -> list[Passe]:
    """Recorta os passes por uma das perguntas que a especificação faz.

    `decisivos` reúne o que gerou finalização e o que antecedeu quem gerou — é a cadeia
    de criação, e separá-la em duas opções esconderia a pré-assistência.
    """
    if subconjunto == "decisivos":
        return [
            passe for passe in passes if passe.get("is_shot_assist") or passe.get("is_pre_assist")
        ]
    marca = _MARCAS.get(subconjunto)
    return [passe for passe in passes if passe.get(marca)] if marca else passes


def com_coordenada(passes: list[Passe]) -> list[Passe]:
    """Só os passes que têm origem e destino para serem desenhados."""
    return [
        passe
        for passe in passes
        if all(passe.get(campo) is not None for campo in ("x", "y", "end_x", "end_y"))
    ]


def classificar(passe: Passe) -> str:
    return "certo" if passe.get("is_complete") else "errado"


def contagens(passes: list[Passe]) -> dict[str, int]:
    """Tentativas, acertos, erros e quantos não têm como ser desenhados.

    Separado assim porque o texto que acompanha o mapa precisa distinguir tentativa de
    acerto: é o que impede o rodapé de contradizer o cartão de métrica ao lado.
    """
    certos = sum(1 for passe in passes if passe.get("is_complete"))
    return {
        "tentativas": len(passes),
        "certos": certos,
        "errados": len(passes) - certos,
        "sem_coordenada": len(passes) - len(com_coordenada(passes)),
    }


def _virgula(texto: str) -> str:
    return texto.replace(".", ",")


def _detalhe(passe: Passe) -> str:
    partes = [TIPOS.get(str(passe.get("pass_type")), str(passe.get("pass_type")))]
    if passe.get("is_cross"):
        partes.append("cruzamento")
    if passe.get("is_through_ball"):
        partes.append("em profundidade")
    if passe.get("is_goal_assist"):
        partes.append("assistência")
    elif passe.get("is_shot_assist"):
        partes.append("gerou finalização")
    elif passe.get("is_pre_assist"):
        partes.append("pré-assistência")
    return " · ".join(partes)


def mapa_de_passes(passes: list[Passe], mode: Mode | str = "light", altura: int = 470) -> go.Figure:
    """Uma linha por passe, da origem ao destino, colorida pelo desfecho."""
    t = tokens(mode)
    figura = pitch.figura(mode, x_min=0.0, x_max=PITCH_LENGTH, altura=altura)
    desenhaveis = com_coordenada(passes)
    com_marcadores = len(desenhaveis) <= MARCADORES_ATE

    for indice, (chave, rotulo) in enumerate(CLASSES):
        do_grupo = [passe for passe in desenhaveis if classificar(passe) == chave]
        cor = t.serie(indice)

        # Um traço só por categoria: os `None` cortam a linha entre um passe e o
        # seguinte, e o navegador desenha tudo de uma vez.
        xs: list[float | None] = []
        ys: list[float | None] = []
        for passe in do_grupo:
            xs.extend([passe["x"], passe["end_x"], None])
            ys.extend([passe["y"], passe["end_y"], None])

        figura.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                name=f"{rotulo} ({len(do_grupo)})",
                line={"color": com_alfa(cor, OPACIDADE_DA_LINHA), "width": LARGURA_LINHA},
                hoverinfo="skip",  # quem responde ao ponteiro é o marcador de destino
            )
        )

        if not com_marcadores or not do_grupo:
            continue

        figura.add_trace(
            go.Scatter(
                x=[passe["end_x"] for passe in do_grupo],
                y=[passe["end_y"] for passe in do_grupo],
                mode="markers",
                name=rotulo,
                showlegend=False,  # a legenda já identificou a categoria pela linha
                marker={
                    "size": TAMANHO_DO_DESTINO,
                    "color": cor,
                    "line": {"color": t.surface, "width": LARGURA_ANEL},
                },
                customdata=[
                    [
                        _virgula(f"{passe['length_m']:.1f} m")
                        if passe.get("length_m") is not None
                        else TRACO,
                        rotulo,
                        passe.get("minute", 0),
                        passe.get("recipient") or "ninguém",
                        _detalhe(passe),
                    ]
                    for passe in do_grupo
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{customdata[1]} · %{customdata[2]}'<br>"
                    "para %{customdata[3]}<br>"
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
