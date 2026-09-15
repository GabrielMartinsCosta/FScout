"""Geometria do campo: converte coordenadas cruas em conceitos de futebol.

É aqui que "x=97.3, y=21.4" vira "fora da área, pela faixa esquerda, no terço ofensivo".
Todo o resto do sistema consome estas funções em vez de manipular coordenadas na mão,
o que mantém a definição de cada zona em um lugar só — e auditável na defesa do TCC.

Sistema de coordenadas (padrão StatsBomb)
-----------------------------------------
- Campo normalizado em **120 x 80 jardas**. A StatsBomb normaliza todo estádio para
  essas medidas; a dimensão real do gramado não é preservada.
- Origem `(0, 0)` no canto **superior esquerdo** do campo desenhado.
- `x` cresce **na direção do gol atacado**: `x = 0` é a linha de fundo defendida,
  `x = 120` é a linha de fundo atacada.
- `y` cresce "para baixo" no campo desenhado. Como o atacante avança no sentido `+x`,
  `y = 0` fica à **esquerda do atacante** e `y = 80` à direita.
- Em finalizações existe um terceiro eixo `z`, a altura em jardas, usado para
  localizar o ponto de entrada no gol.

Toda coordenada armazenada no banco já está orientada no sentido de ataque da equipe
que executou a ação, então não há necessidade de espelhar nada na hora da consulta.
"""

from __future__ import annotations

import math
from enum import StrEnum

# ---------------------------------------------------------------------------------------
# Constantes do campo, em unidades StatsBomb (jardas)
# ---------------------------------------------------------------------------------------

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

# Gol atacado: linha de fundo em x = 120, traves em y = 36 e y = 44.
GOAL_LINE_X = PITCH_LENGTH
GOAL_LEFT_POST_Y = 36.0
GOAL_RIGHT_POST_Y = 44.0
GOAL_CENTER_Y = (GOAL_LEFT_POST_Y + GOAL_RIGHT_POST_Y) / 2  # 40.0
GOAL_CROSSBAR_Z = 2.67  # 8 pés ≈ 2.4384 m ≈ 2.67 jardas

# Grande área: 18 jardas de profundidade, 44 de largura.
PENALTY_AREA_MIN_X = 102.0
PENALTY_AREA_MIN_Y = 18.0
PENALTY_AREA_MAX_Y = 62.0

# Pequena área: 6 jardas de profundidade, 20 de largura.
SIX_YARD_BOX_MIN_X = 114.0
SIX_YARD_BOX_MIN_Y = 30.0
SIX_YARD_BOX_MAX_Y = 50.0

PENALTY_SPOT = (108.0, GOAL_CENTER_Y)

# Terços verticais do campo.
DEFENSIVE_THIRD_MAX_X = PITCH_LENGTH / 3  # 40.0
MIDDLE_THIRD_MAX_X = 2 * PITCH_LENGTH / 3  # 80.0

# ---------------------------------------------------------------------------------------
# Conversão para metros
# ---------------------------------------------------------------------------------------

# As unidades StatsBomb são jardas, então a conversão isotrópica preserva a largura real
# do gol (8 jd * 0.9144 = 7.32 m, exatamente a medida oficial) e mantém ângulos corretos.
#
# A alternativa comum na literatura — reescalar 120x80 para um campo de referência de
# 105x68 m — distorce os eixos em proporções diferentes (0.875 em x, 0.850 em y), o que
# deforma ângulos de chute e encolhe o gol para 6.8 m. Por isso não é o padrão aqui.
#
# Limitação a declarar no texto do TCC: como a StatsBomb normaliza todo campo para
# 120x80 jd (109.7 x 73.2 m), distâncias absolutas carregam um erro de escala de ~4%
# em relação a um gramado de 105x68 m. Comparações entre jogadores não são afetadas,
# porque o erro é sistemático e igual para todos.
METERS_PER_YARD = 0.9144


def to_meters(x: float, y: float) -> tuple[float, float]:
    """Converte coordenadas do campo de jardas para metros."""
    return x * METERS_PER_YARD, y * METERS_PER_YARD


def distance_m(x1: float, y1: float, x2: float, y2: float) -> float:
    """Distância euclidiana entre dois pontos do campo, em metros."""
    return math.hypot(x2 - x1, y2 - y1) * METERS_PER_YARD


def distance_to_goal_m(x: float, y: float) -> float:
    """Distância do ponto até o centro da linha do gol atacado, em metros."""
    return distance_m(x, y, GOAL_LINE_X, GOAL_CENTER_Y)


def shot_angle_deg(x: float, y: float) -> float:
    """Ângulo, em graus, que a boca do gol subtende a partir do ponto de finalização.

    É o segundo insumo clássico de um modelo de xG, junto com a distância: um chute a
    10 m de frente para o gol tem ângulo muito maior que um a 10 m junto à linha de
    fundo. Retorna `0.0` quando o ponto está sobre a linha do gol (ângulo degenerado).
    """
    dx = GOAL_LINE_X - x
    if dx <= 0:
        return 0.0
    angle_to_left = math.atan2(GOAL_LEFT_POST_Y - y, dx)
    angle_to_right = math.atan2(GOAL_RIGHT_POST_Y - y, dx)
    return math.degrees(abs(angle_to_right - angle_to_left))


# ---------------------------------------------------------------------------------------
# Regiões do campo
# ---------------------------------------------------------------------------------------


def in_penalty_area(x: float, y: float) -> bool:
    """Ponto dentro da grande área atacada."""
    return x >= PENALTY_AREA_MIN_X and PENALTY_AREA_MIN_Y <= y <= PENALTY_AREA_MAX_Y


def in_six_yard_box(x: float, y: float) -> bool:
    """Ponto dentro da pequena área atacada."""
    return x >= SIX_YARD_BOX_MIN_X and SIX_YARD_BOX_MIN_Y <= y <= SIX_YARD_BOX_MAX_Y


def outside_penalty_area(x: float, y: float) -> bool:
    """Complemento de `in_penalty_area`, nomeado para consultas ficarem legíveis."""
    return not in_penalty_area(x, y)


class VerticalThird(StrEnum):
    """Terço do campo no eixo de ataque."""

    DEFENSIVE = "defensive"
    MIDDLE = "middle"
    ATTACKING = "attacking"


def vertical_third(x: float) -> VerticalThird:
    """Terço vertical correspondente à coordenada `x`."""
    if x < DEFENSIVE_THIRD_MAX_X:
        return VerticalThird.DEFENSIVE
    if x < MIDDLE_THIRD_MAX_X:
        return VerticalThird.MIDDLE
    return VerticalThird.ATTACKING


class Lane(StrEnum):
    """Corredor lateral, na divisão tática de cinco faixas.

    Os limites acompanham as linhas da grande área e da pequena área estendidas, que é
    a convenção usada na análise tática de meios-espaços (halfspaces).
    Nomes na perspectiva de quem ataca.
    """

    LEFT_WING = "left_wing"
    LEFT_HALFSPACE = "left_halfspace"
    CENTER = "center"
    RIGHT_HALFSPACE = "right_halfspace"
    RIGHT_WING = "right_wing"


def lane(y: float) -> Lane:
    """Corredor correspondente à coordenada `y`."""
    if y < PENALTY_AREA_MIN_Y:
        return Lane.LEFT_WING
    if y < SIX_YARD_BOX_MIN_Y:
        return Lane.LEFT_HALFSPACE
    if y <= SIX_YARD_BOX_MAX_Y:
        return Lane.CENTER
    if y <= PENALTY_AREA_MAX_Y:
        return Lane.RIGHT_HALFSPACE
    return Lane.RIGHT_WING


DEFAULT_GRID_COLS = 6
DEFAULT_GRID_ROWS = 5


def grid_cell(
    x: float,
    y: float,
    cols: int = DEFAULT_GRID_COLS,
    rows: int = DEFAULT_GRID_ROWS,
) -> tuple[int, int]:
    """Célula `(coluna, linha)` de uma grade regular sobre o campo, base zero.

    Base do mapa de calor: contar eventos por célula é mais barato e mais estável que
    estimar densidade a cada requisição. Coluna 0 é o campo defendido, linha 0 é `y = 0`.
    """
    col = min(int(x / PITCH_LENGTH * cols), cols - 1)
    row = min(int(y / PITCH_WIDTH * rows), rows - 1)
    return max(col, 0), max(row, 0)


# ---------------------------------------------------------------------------------------
# Boca do gol: para onde o chute foi
# ---------------------------------------------------------------------------------------


class GoalMouthZone(StrEnum):
    """Nona parte da boca do gol, na perspectiva de **quem chuta**.

    Responde "em qual canto o pênalti foi batido" e "onde o goleiro é vazado".
    `OFF_TARGET` cobre finalizações cujo ponto final cai fora das traves ou do travessão.
    """

    LEFT_LOW = "left_low"
    LEFT_MID = "left_mid"
    LEFT_HIGH = "left_high"
    CENTER_LOW = "center_low"
    CENTER_MID = "center_mid"
    CENTER_HIGH = "center_high"
    RIGHT_LOW = "right_low"
    RIGHT_MID = "right_mid"
    RIGHT_HIGH = "right_high"
    OFF_TARGET = "off_target"


def goal_mouth_zone(end_y: float, end_z: float | None) -> GoalMouthZone:
    """Zona da boca do gol atingida por uma finalização.

    Args:
        end_y: coordenada lateral do ponto final do chute.
        end_z: altura do ponto final, em jardas. `None` (chute rasteiro sem altura
            registrada) é tratado como rente ao chão.
    """
    z = 0.0 if end_z is None else end_z
    if not (GOAL_LEFT_POST_Y <= end_y <= GOAL_RIGHT_POST_Y) or z > GOAL_CROSSBAR_Z:
        return GoalMouthZone.OFF_TARGET

    third_width = (GOAL_RIGHT_POST_Y - GOAL_LEFT_POST_Y) / 3
    horizontal = min(int((end_y - GOAL_LEFT_POST_Y) / third_width), 2)

    third_height = GOAL_CROSSBAR_Z / 3
    vertical = min(int(z / third_height), 2)

    names = (
        ("left_low", "left_mid", "left_high"),
        ("center_low", "center_mid", "center_high"),
        ("right_low", "right_mid", "right_high"),
    )
    return GoalMouthZone(names[horizontal][vertical])


def mirror_to_keeper_view(zone: GoalMouthZone) -> GoalMouthZone:
    """Converte a zona da perspectiva do batedor para a do goleiro.

    O canto esquerdo de quem chuta é o canto direito de quem defende. Ter as duas
    leituras evita a ambiguidade clássica em análise de pênaltis.
    """
    swap = {
        GoalMouthZone.LEFT_LOW: GoalMouthZone.RIGHT_LOW,
        GoalMouthZone.LEFT_MID: GoalMouthZone.RIGHT_MID,
        GoalMouthZone.LEFT_HIGH: GoalMouthZone.RIGHT_HIGH,
        GoalMouthZone.RIGHT_LOW: GoalMouthZone.LEFT_LOW,
        GoalMouthZone.RIGHT_MID: GoalMouthZone.LEFT_MID,
        GoalMouthZone.RIGHT_HIGH: GoalMouthZone.LEFT_HIGH,
    }
    return swap.get(zone, zone)


# ---------------------------------------------------------------------------------------
# Passes e conduções: direção, alcance e progressão
# ---------------------------------------------------------------------------------------

FORWARD_CONE_DEG = 45.0
BACKWARD_CONE_DEG = 135.0

SHORT_PASS_MAX_M = 15.0
MEDIUM_PASS_MAX_M = 30.0


def pass_direction_deg(x1: float, y1: float, x2: float, y2: float) -> float:
    """Ângulo do deslocamento em graus, medido a partir do eixo de ataque.

    `0°` aponta direto para o gol adversário, `±180°` para o próprio gol.
    """
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def classify_direction(x1: float, y1: float, x2: float, y2: float) -> str:
    """Classifica o deslocamento em `forward`, `sideways` ou `backward`.

    Os cones de 45° e 135° são a convenção usual: um passe só conta como "pra frente"
    se ganha mais terreno no eixo de ataque do que na lateral.
    """
    angle = abs(pass_direction_deg(x1, y1, x2, y2))
    if angle <= FORWARD_CONE_DEG:
        return "forward"
    if angle >= BACKWARD_CONE_DEG:
        return "backward"
    return "sideways"


def classify_length(length_m: float) -> str:
    """Classifica o alcance do passe em `short`, `medium` ou `long`."""
    if length_m <= SHORT_PASS_MAX_M:
        return "short"
    if length_m <= MEDIUM_PASS_MAX_M:
        return "medium"
    return "long"


def enters_penalty_area(x1: float, y1: float, x2: float, y2: float) -> bool:
    """Deslocamento que termina dentro da grande área tendo começado fora dela."""
    return not in_penalty_area(x1, y1) and in_penalty_area(x2, y2)


def enters_six_yard_box(x1: float, y1: float, x2: float, y2: float) -> bool:
    """Deslocamento que termina dentro da pequena área tendo começado fora dela."""
    return not in_six_yard_box(x1, y1) and in_six_yard_box(x2, y2)


# Limiares de progressão (critério Wyscout), em metros de aproximação ao gol.
# O ganho exigido cai conforme a bola avança, porque perto da área cada metro custa mais.
PROGRESSIVE_GAIN_OWN_HALF_M = 30.0
PROGRESSIVE_GAIN_CROSSING_HALF_M = 15.0
PROGRESSIVE_GAIN_OPPONENT_HALF_M = 10.0


def is_progressive(x1: float, y1: float, x2: float, y2: float) -> bool:
    """Indica se o deslocamento é progressivo pelo critério Wyscout.

    A bola precisa se aproximar do gol adversário em pelo menos:
    30 m se começa e termina no campo de defesa, 15 m se cruza o meio-campo,
    10 m se começa e termina no campo de ataque.

    Passes que terminam no campo de defesa tendo começado no de ataque nunca são
    progressivos, independentemente do ganho.
    """
    gain = distance_to_goal_m(x1, y1) - distance_to_goal_m(x2, y2)
    if gain <= 0:
        return False

    midfield = PITCH_LENGTH / 2
    starts_own_half = x1 < midfield
    ends_own_half = x2 < midfield

    if starts_own_half and ends_own_half:
        return gain >= PROGRESSIVE_GAIN_OWN_HALF_M
    if starts_own_half and not ends_own_half:
        return gain >= PROGRESSIVE_GAIN_CROSSING_HALF_M
    if not starts_own_half and not ends_own_half:
        return gain >= PROGRESSIVE_GAIN_OPPONENT_HALF_M
    return False
