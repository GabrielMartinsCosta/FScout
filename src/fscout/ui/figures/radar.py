"""Radar comparativo: percentis dentro do grupo de posição.

O radar mostra **percentil**, não valor bruto, e isso é o que o torna comparável: "12
gols" não diz se é muito sem saber contra quem; "percentil 91 entre 36 atacantes" diz.
O eixo vai de 0 a 100 porque é essa a escala que o motor devolve, e o sentido já vem
resolvido de lá — em métrica onde menos é melhor, como gols sofridos, o motor inverte o
percentil antes de entregá-lo, de modo que **mais longe do centro é sempre melhor**.

Duas regras de honestidade estão embutidas:

**Teto de três atletas.** No radar todo polígono cruza todos os outros, então a paleta
precisa separar todos os pares — e, medido, ela separa três (ΔE 9.2 no claro, 9.4 no
escuro) e falha no quarto (13.7, abaixo do piso de 15). Passar de três não é questão de
caber na tela; é questão de o leitor não conseguir dizer de quem é cada linha.

**Métrica sem percentil sai do gráfico, não vira zero.** O motor devolve valor nulo
quando a amostra é menor que o mínimo da métrica, quando o grupo de posição tem menos
de dois atletas, ou quando a métrica não se aplica àquela posição. Desenhar isso como
zero afirmaria "é péssimo nesse quesito" onde o correto é "não sei". As métricas
descartadas voltam na lista de excluídas, para a tela dizer quais foram e por quê.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from fscout.ui.figures import aviso_no_lugar_do_grafico
from fscout.ui.format import formatar_valor, quebrar, rotulo
from fscout.ui.theme import (
    LARGURA_ANEL,
    LARGURA_LINHA,
    MAX_SERIES_TODOS_OS_PARES,
    TAMANHO_MARCADOR,
    Mode,
    com_alfa,
    tokens,
)

Entrada = dict[str, Any]  # {"player": {...}, "values": {chave: medida}}
Definicao = dict[str, Any]

MIN_EIXOS = 3  # com menos de três eixos não há polígono: é linha, e engana
OPACIDADE_DA_AREA = 0.10  # lavagem, não bloco saturado


def _sem_dados(mensagem: str, mode: Mode | str, altura: int) -> go.Figure:
    return aviso_no_lugar_do_grafico(mensagem, mode, altura)


def radar(
    dados: list[Entrada],
    definicoes: list[Definicao],
    mode: Mode | str = "light",
    altura: int = 480,
) -> tuple[go.Figure, list[str]]:
    """Monta o radar e devolve, junto, as métricas que precisaram ficar de fora.

    Raises:
        ValueError: com mais atletas do que a paleta separa com segurança.
    """
    if len(dados) > MAX_SERIES_TODOS_OS_PARES:
        raise ValueError(
            f"o radar comporta {MAX_SERIES_TODOS_OS_PARES} atletas; "
            f"foram pedidos {len(dados)}. Acima disso as cores deixam de ser "
            "distinguíveis sob daltonismo — compare em duas telas ou use a tabela."
        )
    t = tokens(mode)

    def tem_percentil(definicao: Definicao) -> bool:
        chave = definicao["key"]
        return all(
            entrada.get("values", {}).get(chave, {}).get("percentile") is not None
            for entrada in dados
        )

    incluidas = [definicao for definicao in definicoes if tem_percentil(definicao)]
    excluidas = [
        str(definicao.get("label", definicao["key"]))
        for definicao in definicoes
        if not tem_percentil(definicao)
    ]

    if not dados:
        return _sem_dados("Selecione ao menos um atleta.", mode, altura), excluidas
    if len(incluidas) < MIN_EIXOS:
        return (
            _sem_dados(
                f"Só {len(incluidas)} das {len(definicoes)} métricas têm percentil neste "
                "recorte. Amplie o recorte ou escolha outras métricas.",
                mode,
                altura,
            ),
            excluidas,
        )

    eixos = [quebrar(str(definicao.get("label", definicao["key"]))) for definicao in incluidas]
    figura = go.Figure()

    for indice, entrada in enumerate(dados):
        cor = t.serie(indice)
        medidas = entrada.get("values", {})
        percentis = [medidas[definicao["key"]]["percentile"] for definicao in incluidas]
        detalhes = [
            [
                formatar_valor(definicao, medidas[definicao["key"]]),
                rotulo(definicao, medidas[definicao["key"]]),
                medidas[definicao["key"]].get("population") or 0,
            ]
            for definicao in incluidas
        ]
        nome = str(entrada.get("player", {}).get("name", f"atleta {indice + 1}"))

        figura.add_trace(
            go.Scatterpolar(
                # O primeiro ponto se repete no fim para fechar o polígono.
                r=[*percentis, percentis[0]],
                theta=[*eixos, eixos[0]],
                customdata=[*detalhes, detalhes[0]],
                name=nome,
                mode="lines+markers",
                line={"color": cor, "width": LARGURA_LINHA},
                fill="toself",
                fillcolor=com_alfa(cor, OPACIDADE_DA_AREA),
                marker={
                    "size": TAMANHO_MARCADOR,
                    "color": cor,
                    "line": {"color": t.surface, "width": LARGURA_ANEL},
                },
                hovertemplate=(
                    "<b>%{r:.0f}º percentil</b> entre %{customdata[2]}<br>"
                    "%{customdata[0]} · %{customdata[1]}"
                    f"<extra>{nome}</extra>"
                ),
            )
        )

    figura.update_layout(
        height=altura,
        paper_bgcolor=t.surface,
        plot_bgcolor=t.surface,
        polar={
            "bgcolor": t.surface,
            "radialaxis": {
                "range": [0, 100],
                "tickvals": [25, 50, 75, 100],
                "gridcolor": t.grid,
                "linecolor": t.grid,
                "tickfont": {"color": t.muted, "size": 10},
                "angle": 90,
                "tickangle": 90,
            },
            "angularaxis": {
                "gridcolor": t.grid,
                "linecolor": t.axis,
                # Texto nunca veste a cor da série: quem identifica é a linha colorida.
                "tickfont": {"color": t.ink_secondary, "size": 11},
                "direction": "clockwise",
                "rotation": 90,
            },
        },
        # Legenda sempre presente com duas ou mais séries: identidade não pode depender
        # só de o leitor casar cores de memória.
        showlegend=len(dados) >= 2,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.04,
            "x": 0,
            "font": {"color": t.ink_secondary, "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        margin={"l": 72, "r": 72, "t": 64, "b": 40},
        hoverlabel={
            "bgcolor": t.surface,
            "bordercolor": t.border,
            "font": {"color": t.ink, "size": 12},
        },
    )
    return figura, excluidas
