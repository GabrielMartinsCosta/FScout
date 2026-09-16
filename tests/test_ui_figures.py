"""Testes das figuras do painel.

Gráfico errado não levanta exceção: ele desenha algo plausível e falso, que vai parar na
defesa. As asserções abaixo miram nas decisões que mudariam a leitura de quem olha — a
definição de "no alvo", o teto de séries que a paleta comporta, a escala de tamanho ser
absoluta, e a métrica sem percentil sair do radar em vez de virar zero.
"""

from __future__ import annotations

from typing import Any

import pytest

from fscout.ui import pitch
from fscout.ui.figures import heatmap, radar, shot_map

# ----------------------------------------------------------------------------------------
# Mapa de chutes
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("desfecho", "gol", "esperado"),
    [
        ("goal", True, "gol"),
        ("saved", False, "no_alvo"),
        ("saved_to_post", False, "no_alvo"),
        # Bola na trave sem defesa não é chute no gol, e bloqueio de jogador de linha
        # também não: é a definição corrente de *shots on target*.
        ("post", False, "fora"),
        ("blocked", False, "fora"),
        ("saved_off_target", False, "fora"),
        ("off_target", False, "fora"),
        ("wayward", False, "fora"),
    ],
)
def test_classificacao_do_desfecho(desfecho: str, gol: bool, esperado: str) -> None:
    """A fronteira entre as três classes é o critério mais perguntado numa banca."""
    assert shot_map.classificar({"outcome": desfecho, "is_goal": gol}) == esperado


def test_chute_sem_coordenada_fica_fora_do_mapa() -> None:
    """Ele conta nas métricas; só não tem onde ser desenhado."""
    chutes: list[dict[str, Any]] = [
        {"x": 100, "y": 40},
        {"x": None, "y": None},
        {"x": 110, "y": None},
    ]
    assert len(shot_map.com_coordenada(chutes)) == 1


def test_mapa_tem_exatamente_as_tres_classes_validadas() -> None:
    """Três séries é o que a paleta separa em todos os pares. Nunca uma quarta."""
    figura = shot_map.mapa_de_chutes([])
    assert [traco.name for traco in figura.data] == [rotulo for _, rotulo in shot_map.CLASSES]
    assert len(figura.data) == 3


def test_tamanho_do_marcador_segue_escala_absoluta_de_xg() -> None:
    """Régua fixa de 0 a 1: se ela se ajustasse ao melhor chute de cada atleta, dois
    mapas lado a lado ficariam incomparáveis."""
    chutes = [
        {"x": 100, "y": 40, "xg": 0.0, "is_goal": True, "outcome": "goal"},
        {"x": 105, "y": 40, "xg": 1.0, "is_goal": True, "outcome": "goal"},
    ]
    tamanhos = list(shot_map.mapa_de_chutes(chutes).data[0].marker.size)
    assert tamanhos[0] == pytest.approx(shot_map.DIAMETRO_MINIMO)
    assert tamanhos[1] == pytest.approx(shot_map.DIAMETRO_MAXIMO)


def test_marcador_nunca_fica_menor_que_o_minimo_legivel() -> None:
    """xG ausente vira o menor diâmetro, e não um ponto invisível."""
    chutes = [{"x": 100, "y": 40, "xg": None, "is_goal": False, "outcome": "blocked"}]
    tamanhos = list(shot_map.mapa_de_chutes(chutes).data[2].marker.size)
    assert tamanhos[0] >= 8


def test_alvo_do_ponteiro_e_maior_que_a_marca() -> None:
    """Ponto de 9px é impossível de acertar no centro; o ponteiro só precisa chegar perto."""
    assert shot_map.mapa_de_chutes([]).layout.hoverdistance >= 24


# ----------------------------------------------------------------------------------------
# Mapa de calor
# ----------------------------------------------------------------------------------------


def test_matriz_preenche_com_zero_onde_nao_houve_acao() -> None:
    """Célula ausente é zero ação, não buraco: o campo inteiro precisa ser desenhado."""
    grade = heatmap.matriz([{"grid_col": 2, "grid_row": 1, "actions": 7}])
    assert len(grade) == 5
    assert all(len(linha) == 6 for linha in grade)
    assert grade[1][2] == 7
    assert sum(sum(linha) for linha in grade) == 7


def test_matriz_ignora_celula_fora_da_grade() -> None:
    """Índice inválido não deve derrubar a tela nem deslocar a contagem."""
    grade = heatmap.matriz(
        [
            {"grid_col": 99, "grid_row": 0, "actions": 5},
            {"grid_col": 0, "grid_row": 0, "actions": 3},
        ]
    )
    assert grade[0][0] == 3
    assert sum(sum(linha) for linha in grade) == 3


def test_celulas_sao_separadas_por_vao_da_superficie() -> None:
    """Quem separa marcas é a superfície, não um traço desenhado em volta delas."""
    traco = heatmap.mapa_de_calor([]).data[0]
    assert traco.xgap == 2
    assert traco.ygap == 2


def test_linhas_do_campo_ficam_sobre_as_celulas() -> None:
    """Por baixo, os degraus escuros da rampa engoliriam a referência do campo."""
    figura = heatmap.mapa_de_calor([{"grid_col": 5, "grid_row": 4, "actions": 100}])
    assert {forma.layer for forma in figura.layout.shapes} == {"above"}


def test_descricao_da_celula_usa_termos_de_futebol() -> None:
    """Índice de grade não diz nada ao leitor; terço e faixa dizem."""
    assert "defesa" in heatmap.descrever(0, 0, 6, 5)
    assert "ataque" in heatmap.descrever(5, 0, 6, 5)


# ----------------------------------------------------------------------------------------
# Radar
# ----------------------------------------------------------------------------------------


def _medida(percentil: float | None, valor: float = 1.0) -> dict[str, Any]:
    return {
        "value": valor,
        "per_90": valor,
        "percentile": percentil,
        "population": 30,
        "sample": 10,
        "minutes": 900,
    }


def _definicoes(quantidade: int) -> list[dict[str, Any]]:
    return [
        {
            "key": f"m{indice}",
            "label": f"Métrica {indice}",
            "unit": "count",
            "per_90": True,
            "min_sample": 0,
        }
        for indice in range(quantidade)
    ]


def _entrada(nome: str, percentis: list[float | None]) -> dict[str, Any]:
    return {
        "player": {"name": nome},
        "values": {f"m{indice}": _medida(p) for indice, p in enumerate(percentis)},
    }


def test_radar_recusa_mais_series_do_que_a_paleta_separa() -> None:
    """O teto não é de espaço na tela: acima dele o leitor não distingue as linhas."""
    dados = [_entrada(f"Atleta {i}", [50, 60, 70]) for i in range(4)]
    with pytest.raises(ValueError, match="comporta"):
        radar.radar(dados, _definicoes(3))


def test_radar_aceita_o_teto_exato() -> None:
    dados = [_entrada(f"Atleta {i}", [50, 60, 70]) for i in range(radar.MAX_SERIES_TODOS_OS_PARES)]
    figura, excluidas = radar.radar(dados, _definicoes(3))
    assert len(figura.data) == radar.MAX_SERIES_TODOS_OS_PARES
    assert excluidas == []


def test_metrica_sem_percentil_sai_do_radar_em_vez_de_virar_zero() -> None:
    """Desenhar nulo como zero afirmaria "é péssimo" onde o correto é "não sei"."""
    dados = [_entrada("Atleta A", [50, 60, 70, None])]
    figura, excluidas = radar.radar(dados, _definicoes(4))
    assert excluidas == ["Métrica 3"]
    # Três eixos mais o ponto que fecha o polígono.
    assert len(figura.data[0].r) == 4


def test_radar_fecha_o_poligono() -> None:
    """Sem repetir o primeiro vértice, sobra um lado aberto que parece dado faltando."""
    figura, _ = radar.radar([_entrada("Atleta A", [10, 20, 30])], _definicoes(3))
    valores = list(figura.data[0].r)
    assert valores[0] == valores[-1]


def test_radar_avisa_quando_faltam_eixos() -> None:
    """Com menos de três eixos não há polígono, e duas hastes enganam mais que informam."""
    figura, excluidas = radar.radar([_entrada("Atleta A", [10, None, None])], _definicoes(3))
    assert not figura.data
    assert len(excluidas) == 2


# ----------------------------------------------------------------------------------------
# Desenho do campo
# ----------------------------------------------------------------------------------------


def test_campo_inteiro_tem_mais_formas_que_a_metade_atacada() -> None:
    """Recortar evita o Plotly reservar espaço para o que está fora da vista."""
    from fscout.ui.theme import LIGHT

    inteiro = pitch.formas(LIGHT)
    ataque = pitch.formas(LIGHT, x_min=60.0)
    assert len(inteiro) > len(ataque)


def test_campo_fica_por_baixo_das_marcas() -> None:
    """O campo é cenário: quem tem que saltar aos olhos é o chute."""
    from fscout.ui.theme import LIGHT

    assert {forma["layer"] for forma in pitch.formas(LIGHT)} == {"below"}


def test_proporcao_do_campo_fica_travada() -> None:
    """Sem travar, o campo estica com a janela e as distâncias mentem."""
    figura = pitch.figura("light")
    assert figura.layout.yaxis.scaleanchor == "x"
    assert figura.layout.yaxis.scaleratio == 1


def test_eixo_vertical_e_invertido() -> None:
    """`y` cresce para baixo no campo desenhado: y=0 é a esquerda de quem ataca."""
    inicio, fim = pitch.figura("light").layout.yaxis.range
    assert inicio > fim
