"""Mapa-múndi: contra quem o atleta produz, com o raio pelo volume de gols e assistências.

Esta é a visão que originou o projeto — abrir a ficha de um atleta e ver, num mapa, onde
a produção dele se concentra.

**O país é o do adversário.** "Contra quem ele produz" e "de onde ele é" são perguntas
diferentes e dariam mapas diferentes; esta é a que anda junto com a minutagem, e por isso
é a que o mapa responde. Em torneio de seleções o adversário é a própria seleção; em liga
nacional todos os adversários dividem o país da liga, e o mapa concentra tudo num marcador
— o que é o dado dizendo a verdade, não defeito do gráfico.

**Um código, um marcador.** Inglaterra, Escócia e País de Gales são seleções distintas e
o mesmo Estado soberano. Sem agrupar, sairiam três bolhas empilhadas no mesmo ponto, e a
de cima esconderia as de baixo — o leitor veria um número onde há três. Elas são somadas
num marcador só, rotulado com os três nomes, e a tabela equivalente mantém a separação.

**Forma antes de cor.** O volume vai no raio, que é o canal que a especificação pediu, e
a cor faz o trabalho de ênfase: um matiz para quem participou de gols, cinza para quem só
enfrentou. Duas séries, e a segunda existe para dar contexto à primeira — sem ela, "não
marcou contra a Alemanha" e "nunca enfrentou a Alemanha" ficariam idênticos: ausentes.

O raio usa **escala absoluta**. Se a régua se ajustasse ao melhor país de cada atleta,
dois mapas lado a lado ficariam incomparáveis.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.ui.theme import LARGURA_ANEL, Mode, tokens

Pais = dict[str, Any]

# Escala absoluta: 10 participações equivalem a um marcador de 44px de diâmetro.
# Em `sizemode="area"`, sizeref = 2 * valor_de_referencia / diametro^2.
REFERENCIA_DE_PARTICIPACOES = 10
DIAMETRO_DA_REFERENCIA = 44
SIZEREF = 2 * REFERENCIA_DE_PARTICIPACOES / (DIAMETRO_DA_REFERENCIA**2)
TAMANHO_MINIMO = 5
TAMANHO_SEM_PRODUCAO = 8
DISTANCIA_DE_ACERTO = 25


def agrupar_por_codigo(paises: list[Pais]) -> list[Pais]:
    """Soma os países que dividem o mesmo código ISO, preservando os nomes.

    Só acontece com as seleções britânicas, mas a regra é geral: dois registros no mesmo
    ponto do mapa precisam virar um marcador, senão um esconde o outro.
    """
    agrupados: dict[str, Pais] = {}
    for pais in paises:
        codigo = pais.get("iso3")
        if not codigo:
            continue
        atual = agrupados.setdefault(
            codigo,
            {
                "iso3": codigo,
                "nomes": [],
                "matches": 0,
                "minutes": 0,
                "goals": 0,
                "assists": 0,
                "contributions": 0,
            },
        )
        atual["nomes"].append(pais.get("country", ""))
        for campo in ("matches", "minutes", "goals", "assists", "contributions"):
            atual[campo] += int(pais.get(campo) or 0)
    for pais in agrupados.values():
        pais["rotulo"] = " / ".join(sorted(nome for nome in pais["nomes"] if nome))
    return sorted(agrupados.values(), key=lambda pais: (-pais["contributions"], pais["rotulo"]))


def sem_posicao(paises: list[Pais]) -> list[str]:
    """Países sem código ISO, que existem na tabela e não têm onde ser desenhados.

    São Estados extintos de sucessão ambígua. Declarar a ausência é melhor que escolher
    um sucessor arbitrário e plantar um marcador onde ninguém jogou.
    """
    return sorted(str(pais.get("country", "")) for pais in paises if not pais.get("iso3"))


def _texto(pais: Pais) -> str:
    partes = [f"{pais['goals']} gols", f"{pais['assists']} assistências"]
    partes.append(f"{pais['matches']} partidas")
    return " · ".join(partes)


def mapa_mundi(paises: list[Pais], mode: Mode | str = "light", altura: int = 470) -> go.Figure:
    """Um marcador por país do adversário, com o raio pelo volume de gols e assistências."""
    t = tokens(mode)
    agrupados = agrupar_por_codigo(paises)
    com_producao = [pais for pais in agrupados if pais["contributions"] > 0]
    sem_producao = [pais for pais in agrupados if pais["contributions"] == 0]

    figura = go.Figure()

    # O cinza entra primeiro para ficar por baixo: contexto não disputa com o dado.
    if sem_producao:
        figura.add_trace(
            go.Scattergeo(
                locations=[pais["iso3"] for pais in sem_producao],
                locationmode="ISO-3",
                mode="markers",
                name="Enfrentou, sem participação",
                marker={
                    "size": TAMANHO_SEM_PRODUCAO,
                    "color": t.muted,
                    "line": {"color": t.surface, "width": LARGURA_ANEL},
                },
                customdata=[[pais["rotulo"], _texto(pais)] for pais in sem_producao],
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
            )
        )

    if com_producao:
        figura.add_trace(
            go.Scattergeo(
                locations=[pais["iso3"] for pais in com_producao],
                locationmode="ISO-3",
                mode="markers",
                name="Participação em gols",
                marker={
                    "size": [pais["contributions"] for pais in com_producao],
                    "sizemode": "area",
                    "sizeref": SIZEREF,
                    "sizemin": TAMANHO_MINIMO,
                    "color": t.serie(0),
                    "line": {"color": t.surface, "width": LARGURA_ANEL},
                },
                customdata=[
                    [pais["rotulo"], pais["contributions"], _texto(pais)] for pais in com_producao
                ],
                hovertemplate=(
                    "<b>%{customdata[1]} participações em gols</b><br>"
                    "%{customdata[0]}<br>%{customdata[2]}<extra></extra>"
                ),
            )
        )

    figura.update_layout(
        height=altura,
        paper_bgcolor=t.surface,
        plot_bgcolor=t.surface,
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        showlegend=len(figura.data) >= 2,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "x": 0,
            "font": {"color": t.ink_secondary, "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverdistance=DISTANCIA_DE_ACERTO,
        hoverlabel={
            "bgcolor": t.surface,
            "bordercolor": t.border,
            "font": {"color": t.ink, "size": 12},
        },
        geo={
            "projection": {"type": "natural earth"},
            "bgcolor": t.surface,
            "showland": True,
            "landcolor": t.grid,
            "showocean": True,
            "oceancolor": t.surface,
            "showcountries": True,
            "countrycolor": t.axis,
            "countrywidth": 1,
            "showcoastlines": False,
            "showframe": False,
            "lataxis": {"range": [-58, 82]},  # corta a Antártida, onde ninguém joga
        },
    )
    return figura
