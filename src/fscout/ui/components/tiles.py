"""Cartões de resumo e ficha de identificação.

Quando o dado é um número só, a forma certa não é um gráfico de uma barra — é o
número, grande, com o rótulo do que ele mede e o contexto que permite interpretá-lo.
Daí o cartão trazer três coisas e não uma: o valor, o percentil com a população que o
gerou, e o tamanho da amostra. "12 gols" sozinho não diz se é muito.

Números grandes usam os algarismos proporcionais da fonte. Algarismos de largura fixa
(`tabular-nums`) existem para alinhar colunas; num valor solto em corpo grande eles
deixam o número frouxo. Nas tabelas, o contrário — lá a largura fixa é o que faz as
casas decimais se alinharem.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dash import html

from fscout.ui.format import (
    TRACO,
    formatar_percentil,
    formatar_valor,
    motivo_da_ausencia,
    rotulo,
    texto_de_amostra,
)
from fscout.ui.theme import FONT_FAMILY, Mode, Tokens, tokens

POSICOES = {
    "goalkeeper": "Goleiro",
    "defender": "Defensor",
    "midfielder": "Meio-campista",
    "forward": "Atacante",
    "unknown": "Não identificada",
}

PES = {"left": "Esquerdo", "right": "Direito", "both": "Ambos", "unknown": TRACO}


def estilos_de_tabela(t: Tokens) -> dict[str, Any]:
    """Estilo das tabelas equivalentes aos gráficos, igual em todas as telas.

    Ao contrário dos números grandes, aqui os algarismos têm largura fixa: é o que
    alinha as casas decimais de uma coluna para o olho comparar sem esforço.
    """
    return {
        "style_table": {"overflowX": "auto", "maxHeight": "320px", "overflowY": "auto"},
        "style_header": {
            "backgroundColor": t.surface,
            "color": t.ink_secondary,
            "fontWeight": 600,
            "fontSize": "12px",
            "border": "none",
            "borderBottom": f"1px solid {t.axis}",
        },
        "style_cell": {
            "backgroundColor": t.surface,
            "color": t.ink,
            "fontFamily": FONT_FAMILY,
            "fontSize": "12px",
            "padding": "7px 10px",
            "border": "none",
            "borderBottom": f"1px solid {t.grid}",
            "textAlign": "left",
            "fontVariantNumeric": "tabular-nums",
        },
    }


def _estilo_de_cartao(t: Tokens) -> dict[str, Any]:
    return {
        "backgroundColor": t.surface,
        "border": f"1px solid {t.border}",
        "borderRadius": "10px",
        "padding": "14px 16px",
        "minWidth": "170px",
        "flex": "1 1 170px",
        "fontFamily": FONT_FAMILY,
    }


def cartao(
    rotulo_texto: str,
    valor_texto: str,
    apoio: str = "",
    percentil: str = "",
    mode: Mode | str = "light",
) -> html.Div:
    """Um número, o que ele mede e o que permite interpretá-lo."""
    t = tokens(mode)
    filhos: list[Any] = [
        html.Div(
            rotulo_texto,
            style={"color": t.ink_secondary, "fontSize": "12px", "lineHeight": "1.3"},
        ),
        html.Div(
            valor_texto,
            style={
                "color": t.ink,
                "fontSize": "28px",
                "fontWeight": 600,
                "lineHeight": "1.15",
                "marginTop": "6px",
                # Algarismos proporcionais: largura fixa afrouxa número em corpo grande.
                "fontVariantNumeric": "normal",
            },
        ),
    ]
    if percentil:
        filhos.append(
            html.Div(
                f"percentil {percentil}",
                style={"color": t.ink_secondary, "fontSize": "12px", "marginTop": "6px"},
            )
        )
    if apoio:
        filhos.append(
            html.Div(apoio, style={"color": t.muted, "fontSize": "11px", "marginTop": "4px"})
        )
    return html.Div(filhos, style=_estilo_de_cartao(t))


def cartao_de_metrica(
    definicao: dict[str, Any], medida: dict[str, Any], mode: Mode | str = "light"
) -> html.Div:
    """Cartão montado a partir do catálogo e de uma medida da API."""
    ausencia = motivo_da_ausencia(definicao, medida)
    return cartao(
        rotulo_texto=rotulo(definicao, medida),
        valor_texto=formatar_valor(definicao, medida),
        apoio=ausencia or texto_de_amostra(medida),
        percentil="" if ausencia else formatar_percentil(medida),
        mode=mode,
    )


def linha_de_cartoes(cartoes: list[Any], mode: Mode | str = "light") -> html.Div:
    return html.Div(
        cartoes,
        style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "width": "100%"},
    )


def _data(valor: Any) -> str:
    if not valor:
        return TRACO
    try:
        return date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except ValueError:
        return str(valor)


def _valor_de_mercado(euros: float | None) -> str:
    if not euros:
        return TRACO
    if euros >= 1_000_000:
        return f"€ {euros / 1_000_000:.1f} mi".replace(".", ",")
    return f"€ {euros / 1_000:.0f} mil"


def _dado(titulo: str, valor: str, t: Tokens) -> html.Div:
    return html.Div(
        [
            html.Div(titulo, style={"color": t.muted, "fontSize": "11px"}),
            html.Div(valor, style={"color": t.ink, "fontSize": "14px", "marginTop": "2px"}),
        ],
        style={"minWidth": "120px"},
    )


def ficha(perfil: dict[str, Any], mode: Mode | str = "light") -> html.Div:
    """Identificação do atleta: o que a especificação pede como dados básicos.

    A dupla nacionalidade aparece por extenso quando existe — é um dos itens pedidos, e
    some se a tela mostrar só a principal.
    """
    t = tokens(mode)
    nacionalidades = perfil.get("nationalities") or []
    if not nacionalidades and perfil.get("nationality"):
        nacionalidades = [perfil["nationality"]]

    altura = perfil.get("height_cm")
    idade = perfil.get("age")

    return html.Div(
        [
            html.Div(
                perfil.get("name", TRACO),
                style={
                    "color": t.ink,
                    "fontSize": "26px",
                    "fontWeight": 600,
                    "lineHeight": "1.2",
                },
            ),
            html.Div(
                perfil.get("full_name") or "",
                style={"color": t.muted, "fontSize": "12px", "marginTop": "2px"},
            ),
            html.Div(
                [
                    _dado("Posição", POSICOES.get(str(perfil.get("position_group")), TRACO), t),
                    _dado("Idade", f"{idade} anos" if idade else TRACO, t),
                    _dado("Nascimento", _data(perfil.get("birth_date")), t),
                    _dado("Nacionalidade", " · ".join(nacionalidades) or TRACO, t),
                    _dado("País de nascimento", perfil.get("birth_country") or TRACO, t),
                    _dado("Altura", f"{altura} cm" if altura else TRACO, t),
                    _dado("Pé preferencial", PES.get(str(perfil.get("preferred_foot")), TRACO), t),
                    _dado("Valor de mercado", _valor_de_mercado(perfil.get("market_value_eur")), t),
                    _dado("Contrato até", _data(perfil.get("contract_until")), t),
                    _dado("Partidas", str(perfil.get("matches", 0)), t),
                    _dado("Minutos", f"{int(perfil.get('minutes', 0)):,}".replace(",", "."), t),
                ],
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": "18px 26px",
                    "marginTop": "14px",
                },
            ),
        ],
        style={
            "backgroundColor": t.surface,
            "border": f"1px solid {t.border}",
            "borderRadius": "10px",
            "padding": "18px 20px",
            "fontFamily": FONT_FAMILY,
        },
    )
