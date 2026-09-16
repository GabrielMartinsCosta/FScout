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
from fscout.ui.figures import goal_mouth, heatmap, pass_map, radar, shot_map

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


# ----------------------------------------------------------------------------------------
# Boca do gol
# ----------------------------------------------------------------------------------------


def _chute_na_zona(zona: str | None) -> dict[str, Any]:
    return {"goal_mouth_zone": zona, "is_goal": True, "outcome": "goal"}


@pytest.mark.parametrize(
    ("zona", "linha", "coluna"),
    [
        ("left_high", 0, 0),
        ("center_mid", 1, 1),
        ("right_low", 2, 2),
        ("left_low", 2, 0),
        ("right_high", 0, 2),
    ],
)
def test_zona_cai_na_celula_certa(zona: str, linha: int, coluna: int) -> None:
    """Alto fica em cima e a esquerda de quem bate fica à esquerda na tela."""
    grade = goal_mouth.matriz([_chute_na_zona(zona)])
    assert grade[linha][coluna] == 1
    assert sum(sum(linha) for linha in grade) == 1


def test_fora_do_alvo_nao_entra_na_grade() -> None:
    """Não é uma parte do gol; espalhá-la pelas bordas inflaria zonas não acertadas."""
    grade = goal_mouth.matriz([_chute_na_zona("off_target")])
    assert sum(sum(linha) for linha in grade) == 0


def test_perspectiva_do_goleiro_espelha_os_cantos() -> None:
    """O canto esquerdo de quem bate é o direito de quem defende — a ambiguidade
    clássica da análise de pênaltis."""
    chutes = [_chute_na_zona("left_low")]
    assert goal_mouth.matriz(chutes, "batedor")[2][0] == 1
    assert goal_mouth.matriz(chutes, "goleiro")[2][2] == 1


def test_perspectiva_nao_espelha_o_meio() -> None:
    chutes = [_chute_na_zona("center_high")]
    assert goal_mouth.matriz(chutes, "batedor") == goal_mouth.matriz(chutes, "goleiro")


def test_contagens_separam_grade_fora_e_ausente() -> None:
    """Sem zona registrada é diferente de para fora, e a tela precisa dizer os dois."""
    chutes = [
        _chute_na_zona("center_mid"),
        _chute_na_zona("left_high"),
        _chute_na_zona("off_target"),
        _chute_na_zona(None),
    ]
    assert goal_mouth.contagens(chutes) == {"na_grade": 2, "fora": 1, "sem_zona": 1}


def test_cada_zona_tem_a_contagem_escrita() -> None:
    """Nove rótulos: é o que torna o valor legível sem depender de cor nem do mouse."""
    figura = goal_mouth.boca_do_gol([_chute_na_zona("center_mid")])
    assert len(figura.layout.annotations) == 9
    assert {anotacao.text for anotacao in figura.layout.annotations} == {"0", "1"}


def test_rotulo_troca_de_tinta_conforme_o_preenchimento() -> None:
    """No degrau escuro da rampa, tinta escura sumiria."""
    chutes = [_chute_na_zona("center_mid")] * 5
    figura = goal_mouth.boca_do_gol(chutes)
    cores = {anotacao.font.color for anotacao in figura.layout.annotations}
    assert len(cores) == 2  # a célula cheia e as vazias não usam a mesma tinta


def test_boca_do_gol_dispensa_barra_de_cor() -> None:
    """A contagem já está escrita na célula; a barra seria tinta repetindo o que se lê."""
    assert goal_mouth.boca_do_gol([]).data[0].showscale is False


# ----------------------------------------------------------------------------------------
# Mapa de passes
# ----------------------------------------------------------------------------------------


def _passe(**marcas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "x": 40.0,
        "y": 40.0,
        "end_x": 80.0,
        "end_y": 40.0,
        "is_complete": True,
        "pass_type": "open_play",
        "length_m": 36.6,
        "minute": 10,
    }
    base.update(marcas)
    return base


@pytest.mark.parametrize(
    ("subconjunto", "marca"),
    [
        ("progressivos", "is_progressive"),
        ("para_area", "into_penalty_area"),
        ("cruzamentos", "is_cross"),
        ("profundidade", "is_through_ball"),
    ],
)
def test_cada_recorte_de_passe_usa_a_sua_marca(subconjunto: str, marca: str) -> None:
    passes = [_passe(**{marca: True}), _passe()]
    assert len(pass_map.filtrar(passes, subconjunto)) == 1


def test_decisivos_reunem_assistencia_e_pre_assistencia() -> None:
    """Separar as duas esconderia a pré-assistência, que é o elo anterior da jogada."""
    passes = [_passe(is_shot_assist=True), _passe(is_pre_assist=True), _passe()]
    assert len(pass_map.filtrar(passes, "decisivos")) == 2


def test_todos_nao_recorta_nada() -> None:
    passes = [_passe(), _passe(is_cross=True)]
    assert pass_map.filtrar(passes, "todos") == passes


def test_recorte_do_mapa_inclui_a_tentativa_que_falhou() -> None:
    """O mapa filtra **tentativas**; o catálogo, nas métricas de mesmo nome, conta só as
    completas — e os rótulos dele dizem "certos".

    Ver o passe progressivo que se perdeu é o motivo de existir cor por desfecho, então
    as duas leituras estão certas. O que não pode é o texto da tela chamar tentativa de
    passe certo: foi assim que 192 no rodapé apareceu ao lado de 108 no cartão.
    """
    passes = [_passe(is_progressive=True), _passe(is_progressive=True, is_complete=False)]
    assert len(pass_map.filtrar(passes, "progressivos")) == 2


def test_contagens_separam_tentativa_de_acerto() -> None:
    """É essa separação que o rodapé usa para não contradizer o cartão de métrica."""
    passes = [_passe(), _passe(), _passe(is_complete=False), _passe(end_x=None)]
    assert pass_map.contagens(passes) == {
        "tentativas": 4,
        "certos": 3,
        "errados": 1,
        "sem_coordenada": 1,
    }


def test_passe_sem_origem_ou_destino_fica_fora_do_mapa() -> None:
    """Ele conta nas métricas de passe; só não tem como virar uma linha."""
    passes = [_passe(), _passe(end_x=None), _passe(y=None)]
    assert len(pass_map.com_coordenada(passes)) == 1


def test_passe_incompleto_muda_de_classe() -> None:
    assert pass_map.classificar(_passe(is_complete=True)) == "certo"
    assert pass_map.classificar(_passe(is_complete=False)) == "errado"


def test_cada_categoria_vira_um_traco_so() -> None:
    """Mil passes não podem virar mil objetos: os `None` cortam a linha entre eles."""
    passes = [_passe() for _ in range(5)]
    tracos_de_linha = [
        traco for traco in pass_map.mapa_de_passes(passes).data if traco.mode == "lines"
    ]
    assert len(tracos_de_linha) == len(pass_map.CLASSES)
    certos = tracos_de_linha[0]
    # Três posições por passe: origem, destino e o separador.
    assert len(certos.x) == 15
    assert certos.x[2] is None


def test_marcadores_somem_quando_viram_confete() -> None:
    """Acima do teto o mapa fica só com as linhas, e a tela avisa."""
    muitos = [_passe() for _ in range(pass_map.MARCADORES_ATE + 1)]
    modos = {traco.mode for traco in pass_map.mapa_de_passes(muitos).data}
    assert modos == {"lines"}


def test_marcadores_aparecem_quando_cabem() -> None:
    poucos = [_passe(), _passe(is_complete=False)]
    modos = [traco.mode for traco in pass_map.mapa_de_passes(poucos).data]
    assert modos.count("markers") == 2


def test_legenda_traz_a_contagem_de_cada_categoria() -> None:
    """Saber que foram 12 certos e 3 errados sem precisar contar linha na tela."""
    passes = [_passe(), _passe(), _passe(is_complete=False)]
    nomes = [traco.name for traco in pass_map.mapa_de_passes(passes).data if traco.mode == "lines"]
    assert nomes == ["Certo (2)", "Errado (1)"]
