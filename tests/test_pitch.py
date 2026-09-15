"""Testes da geometria do campo.

Erro em `pitch.py` não quebra nada: ele só produz números plausíveis e errados, que
depois viram gráfico e vão parar no texto do TCC. Por isso as asserções abaixo se
ancoram em medidas oficiais verificáveis (pênalti a 12 jd, gol de 7.32 m, travessão a
2.44 m) em vez de espelharem a implementação.
"""

from __future__ import annotations

import math

import pytest

from fscout.domain.pitch import (
    GOAL_CROSSBAR_Z,
    GOAL_LEFT_POST_Y,
    GOAL_RIGHT_POST_Y,
    METERS_PER_YARD,
    PENALTY_SPOT,
    GoalMouthZone,
    Lane,
    VerticalThird,
    classify_direction,
    classify_length,
    distance_m,
    distance_to_goal_m,
    enters_penalty_area,
    goal_mouth_zone,
    grid_cell,
    in_penalty_area,
    in_six_yard_box,
    is_progressive,
    lane,
    mirror_to_keeper_view,
    shot_angle_deg,
    vertical_third,
)

# ----------------------------------------------------------------------------------------
# Conversão de unidades, aferida contra medidas oficiais
# ----------------------------------------------------------------------------------------


def test_largura_do_gol_corresponde_a_medida_oficial() -> None:
    """As traves distam 7.32 m, a medida da regra 1 da IFAB."""
    largura = distance_m(120.0, GOAL_LEFT_POST_Y, 120.0, GOAL_RIGHT_POST_Y)
    assert largura == pytest.approx(7.32, abs=0.01)


def test_altura_do_travessao_corresponde_a_medida_oficial() -> None:
    """O travessão está a 2.44 m do chão."""
    assert GOAL_CROSSBAR_Z * METERS_PER_YARD == pytest.approx(2.44, abs=0.01)  # noqa: SIM300


def test_marca_do_penalti_esta_a_onze_metros() -> None:
    """A marca do pênalti fica a 12 jd (10.97 m) da linha do gol."""
    assert distance_to_goal_m(*PENALTY_SPOT) == pytest.approx(10.97, abs=0.02)


# ----------------------------------------------------------------------------------------
# Ângulo de finalização
# ----------------------------------------------------------------------------------------


def test_angulo_da_marca_do_penalti() -> None:
    """Da marca do pênalti o gol subtende 2·atan(4/12) ≈ 36.87°."""
    esperado = math.degrees(2 * math.atan(4 / 12))
    assert shot_angle_deg(*PENALTY_SPOT) == pytest.approx(esperado, abs=0.01)


def test_angulo_diminui_com_a_distancia() -> None:
    """Chute de frente, mais longe, enxerga um gol menor."""
    assert shot_angle_deg(110, 40) > shot_angle_deg(90, 40) > shot_angle_deg(60, 40)


def test_angulo_diminui_ao_abrir_para_a_linha_de_fundo() -> None:
    """À mesma distância da linha de fundo, o ângulo fecha na direção da lateral."""
    assert shot_angle_deg(110, 40) > shot_angle_deg(110, 20) > shot_angle_deg(110, 2)


def test_angulo_sobre_a_linha_do_gol_e_degenerado() -> None:
    """Sobre a própria linha de fundo o ângulo não é definido; a função devolve zero."""
    assert shot_angle_deg(120, 40) == 0.0


# ----------------------------------------------------------------------------------------
# Regiões
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "y", "dentro"),
    [
        (110.0, 40.0, True),  # centro da grande área
        (102.0, 18.0, True),  # quina exata: os limites são inclusivos
        (101.9, 40.0, False),  # um passo antes da linha da área
        (110.0, 17.9, False),  # fora pela lateral da área
        (60.0, 40.0, False),  # meio-campo
    ],
)
def test_limites_da_grande_area(x: float, y: float, dentro: bool) -> None:
    assert in_penalty_area(x, y) is dentro


@pytest.mark.parametrize(
    ("x", "y", "dentro"),
    [
        (117.0, 40.0, True),
        (114.0, 30.0, True),
        (113.9, 40.0, False),
        (117.0, 29.9, False),
    ],
)
def test_limites_da_pequena_area(x: float, y: float, dentro: bool) -> None:
    assert in_six_yard_box(x, y) is dentro


def test_pequena_area_esta_contida_na_grande_area() -> None:
    """Invariante geométrico: todo ponto da pequena área também está na grande."""
    for x in (114.0, 117.0, 120.0):
        for y in (30.0, 40.0, 50.0):
            assert in_penalty_area(x, y)


def test_tercos_verticais() -> None:
    assert vertical_third(10) is VerticalThird.DEFENSIVE
    assert vertical_third(39.9) is VerticalThird.DEFENSIVE
    assert vertical_third(40) is VerticalThird.MIDDLE
    assert vertical_third(79.9) is VerticalThird.MIDDLE
    assert vertical_third(80) is VerticalThird.ATTACKING
    assert vertical_third(119) is VerticalThird.ATTACKING


def test_corredores_seguem_as_linhas_da_area() -> None:
    """As faixas acompanham as linhas da grande e da pequena área, e y=0 é a esquerda."""
    assert lane(5) is Lane.LEFT_WING
    assert lane(17.9) is Lane.LEFT_WING
    assert lane(18) is Lane.LEFT_HALFSPACE
    assert lane(29.9) is Lane.LEFT_HALFSPACE
    assert lane(40) is Lane.CENTER
    assert lane(50) is Lane.CENTER
    assert lane(50.1) is Lane.RIGHT_HALFSPACE
    assert lane(62) is Lane.RIGHT_HALFSPACE
    assert lane(62.1) is Lane.RIGHT_WING
    assert lane(79) is Lane.RIGHT_WING


def test_grade_nao_estoura_nas_bordas() -> None:
    """Coordenada na borda máxima cai na última célula, não numa célula inexistente."""
    assert grid_cell(0.0, 0.0) == (0, 0)
    assert grid_cell(120.0, 80.0) == (5, 4)
    assert grid_cell(119.99, 79.99) == (5, 4)


# ----------------------------------------------------------------------------------------
# Boca do gol
# ----------------------------------------------------------------------------------------


def test_chute_no_meio_do_gol_rente_ao_chao() -> None:
    assert goal_mouth_zone(40.0, 0.1) is GoalMouthZone.CENTER_LOW


def test_cantos_do_gol() -> None:
    """y=36 é o lado esquerdo de quem chuta, porque y cresce para a direita do atacante."""
    assert goal_mouth_zone(36.5, 0.2) is GoalMouthZone.LEFT_LOW
    assert goal_mouth_zone(43.5, 2.5) is GoalMouthZone.RIGHT_HIGH
    assert goal_mouth_zone(36.5, 2.5) is GoalMouthZone.LEFT_HIGH
    assert goal_mouth_zone(43.5, 0.2) is GoalMouthZone.RIGHT_LOW


def test_chute_fora_das_traves_ou_por_cima() -> None:
    assert goal_mouth_zone(35.0, 1.0) is GoalMouthZone.OFF_TARGET
    assert goal_mouth_zone(45.0, 1.0) is GoalMouthZone.OFF_TARGET
    assert goal_mouth_zone(40.0, 3.0) is GoalMouthZone.OFF_TARGET


def test_altura_ausente_e_tratada_como_rasteira() -> None:
    """Fonte sem eixo z não deve virar 'fora do gol' por omissão."""
    assert goal_mouth_zone(40.0, None) is GoalMouthZone.CENTER_LOW


def test_espelhamento_para_a_visao_do_goleiro_e_involutivo() -> None:
    """Espelhar duas vezes volta ao original; o centro e o 'fora' não se alteram."""
    for zona in GoalMouthZone:
        assert mirror_to_keeper_view(mirror_to_keeper_view(zona)) is zona
    assert mirror_to_keeper_view(GoalMouthZone.LEFT_LOW) is GoalMouthZone.RIGHT_LOW
    assert mirror_to_keeper_view(GoalMouthZone.CENTER_MID) is GoalMouthZone.CENTER_MID
    assert mirror_to_keeper_view(GoalMouthZone.OFF_TARGET) is GoalMouthZone.OFF_TARGET


# ----------------------------------------------------------------------------------------
# Passes: direção, alcance, progressão
# ----------------------------------------------------------------------------------------


def test_classificacao_de_direcao() -> None:
    assert classify_direction(60, 40, 80, 40) == "forward"
    assert classify_direction(60, 40, 40, 40) == "backward"
    assert classify_direction(60, 40, 60, 60) == "sideways"
    # Diagonal de 45° ainda conta como para frente; além disso, vira lateral.
    assert classify_direction(60, 40, 70, 50) == "forward"
    assert classify_direction(60, 40, 65, 50) == "sideways"


def test_classificacao_de_alcance() -> None:
    assert classify_length(8.0) == "short"
    assert classify_length(15.0) == "short"
    assert classify_length(15.1) == "medium"
    assert classify_length(30.0) == "medium"
    assert classify_length(45.0) == "long"


def test_entrada_na_area_exige_comecar_fora() -> None:
    assert enters_penalty_area(95, 40, 110, 40) is True
    # Passe inteiramente dentro da área não é "entrada na área".
    assert enters_penalty_area(105, 40, 112, 40) is False
    # Saída da área tampouco.
    assert enters_penalty_area(110, 40, 95, 40) is False


def test_progressao_exige_ganho_maior_no_proprio_campo() -> None:
    """No campo de defesa o critério Wyscout pede 30 m de aproximação."""
    assert is_progressive(10, 40, 30, 40) is False  # ~18 m de ganho
    assert is_progressive(5, 40, 45, 40) is True  # ~37 m de ganho, cruza o meio? não
    # 5 -> 45 cruza o meio-campo (60)? não: 45 < 60, segue no campo de defesa.


def test_progressao_cruzando_o_meio_campo_exige_quinze_metros() -> None:
    assert is_progressive(50, 40, 62, 40) is False  # ~11 m
    assert is_progressive(50, 40, 70, 40) is True  # ~18 m


def test_progressao_no_campo_de_ataque_exige_dez_metros() -> None:
    assert is_progressive(70, 40, 78, 40) is False  # ~7 m
    assert is_progressive(70, 40, 85, 40) is True  # ~14 m


def test_passe_para_tras_nunca_e_progressivo() -> None:
    assert is_progressive(100, 40, 40, 40) is False
    assert is_progressive(70, 40, 69, 40) is False


def test_passe_que_recua_para_o_proprio_campo_nunca_e_progressivo() -> None:
    """Sair do campo de ataque para o de defesa é regressão, qualquer que seja o ganho."""
    assert is_progressive(70, 40, 50, 40) is False
