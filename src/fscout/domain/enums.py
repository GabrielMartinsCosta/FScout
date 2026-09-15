"""Vocabulário controlado do domínio.

Toda fonte de dados (StatsBomb, CSV de clube, provedor comercial) é traduzida para
estes enums na camada de ingestão. Assim o motor de métricas nunca conhece a origem
do dado: ele só conhece este vocabulário.

Os valores são strings para que o banco continue legível numa consulta manual
(`WHERE body_part = 'left_foot'`), o que importa bastante durante a escrita do TCC.

Qualquer valor desconhecido vindo da fonte vira `UNKNOWN` em vez de quebrar a
ingestão — um provedor novo não deve derrubar o pipeline inteiro.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class LenientStrEnum(StrEnum):
    """StrEnum que degrada valores desconhecidos para UNKNOWN em vez de levantar erro.

    Subclasses devem declarar um membro `UNKNOWN`.
    """

    @classmethod
    def _missing_(cls, value: Any) -> LenientStrEnum | None:
        if isinstance(value, str):
            normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
            for member in cls:
                if member.value == normalized:
                    return member
        return cls.__members__.get("UNKNOWN")

    @classmethod
    def parse(cls, value: Any) -> LenientStrEnum | None:
        """Converte valor bruto da fonte.

        `None` ou string vazia devolvem `None`: ausência de informação é diferente de
        informação desconhecida, e essa distinção importa no cálculo de aproveitamentos.
        """
        if value is None or value == "":
            return None
        return cls(value)


# ---------------------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------------------


class EventType(LenientStrEnum):
    """Tipo do evento. Espelha a taxonomia da StatsBomb, a mais completa disponível em aberto."""

    PASS = "pass"
    BALL_RECEIPT = "ball_receipt"
    CARRY = "carry"
    PRESSURE = "pressure"
    SHOT = "shot"
    DRIBBLE = "dribble"
    DRIBBLED_PAST = "dribbled_past"
    DUEL = "duel"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    BLOCK = "block"
    BALL_RECOVERY = "ball_recovery"
    MISCONTROL = "miscontrol"
    DISPOSSESSED = "dispossessed"
    FOUL_COMMITTED = "foul_committed"
    FOUL_WON = "foul_won"
    GOALKEEPER = "goalkeeper"
    SUBSTITUTION = "substitution"
    BAD_BEHAVIOUR = "bad_behaviour"
    OWN_GOAL_FOR = "own_goal_for"
    OWN_GOAL_AGAINST = "own_goal_against"
    OFFSIDE = "offside"
    SHIELD = "shield"
    ERROR = "error"
    FIFTY_FIFTY = "fifty_fifty"
    PLAYER_ON = "player_on"
    PLAYER_OFF = "player_off"
    INJURY_STOPPAGE = "injury_stoppage"
    REFEREE_BALL_DROP = "referee_ball_drop"
    TACTICAL_SHIFT = "tactical_shift"
    STARTING_XI = "starting_xi"
    HALF_START = "half_start"
    HALF_END = "half_end"
    UNKNOWN = "unknown"


class PlayPattern(LenientStrEnum):
    """Como começou a posse que originou o evento.

    É o campo que responde "o gol veio de escanteio?" sem precisar reconstruir a jogada.
    """

    REGULAR_PLAY = "regular_play"
    FROM_CORNER = "from_corner"
    FROM_FREE_KICK = "from_free_kick"
    FROM_THROW_IN = "from_throw_in"
    FROM_COUNTER = "from_counter"
    FROM_GOAL_KICK = "from_goal_kick"
    FROM_KEEPER = "from_keeper"
    FROM_KICK_OFF = "from_kick_off"
    OTHER = "other"
    UNKNOWN = "unknown"


class BodyPart(LenientStrEnum):
    """Parte do corpo que executou a ação."""

    LEFT_FOOT = "left_foot"
    RIGHT_FOOT = "right_foot"
    HEAD = "head"
    CHEST = "chest"
    OTHER = "other"
    NO_TOUCH = "no_touch"
    # Específicos de goleiro.
    BOTH_HANDS = "both_hands"
    LEFT_HAND = "left_hand"
    RIGHT_HAND = "right_hand"
    UNKNOWN = "unknown"


class Foot(LenientStrEnum):
    """Pé preferencial declarado do atleta."""

    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Finalização
# ---------------------------------------------------------------------------------------


class ShotType(LenientStrEnum):
    """Situação de jogo em que a finalização aconteceu."""

    OPEN_PLAY = "open_play"
    PENALTY = "penalty"
    FREE_KICK = "free_kick"
    CORNER = "corner"
    KICK_OFF = "kick_off"
    UNKNOWN = "unknown"


class ShotOutcome(LenientStrEnum):
    """Desfecho da finalização."""

    GOAL = "goal"
    SAVED = "saved"
    SAVED_TO_POST = "saved_to_post"
    SAVED_OFF_TARGET = "saved_off_target"
    BLOCKED = "blocked"
    OFF_TARGET = "off_target"
    POST = "post"
    WAYWARD = "wayward"
    OFFSIDE = "offside"
    UNKNOWN = "unknown"


class ShotTechnique(LenientStrEnum):
    """Técnica de execução. Cobre o pedido de "gols acrobáticos"."""

    NORMAL = "normal"
    VOLLEY = "volley"
    HALF_VOLLEY = "half_volley"
    LOB = "lob"
    OVERHEAD_KICK = "overhead_kick"
    BACKHEEL = "backheel"
    DIVING_HEADER = "diving_header"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Passe
# ---------------------------------------------------------------------------------------


class PassHeight(LenientStrEnum):
    GROUND = "ground"
    LOW = "low"
    HIGH = "high"
    UNKNOWN = "unknown"


class PassType(LenientStrEnum):
    """Origem do passe: bola parada, reinício ou jogo corrido."""

    OPEN_PLAY = "open_play"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    KICK_OFF = "kick_off"
    INTERCEPTION = "interception"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


class PassTechnique(LenientStrEnum):
    THROUGH_BALL = "through_ball"
    INSWINGING = "inswinging"
    OUTSWINGING = "outswinging"
    STRAIGHT = "straight"
    NO_TOUCH = "no_touch"
    UNKNOWN = "unknown"


class PassOutcome(LenientStrEnum):
    """Na fonte, ausência de outcome significa passe completo; aqui isso é explícito."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    OUT = "out"
    OFFSIDE = "offside"
    INJURY_CLEARANCE = "injury_clearance"
    UNKNOWN = "unknown"


class PassDirection(LenientStrEnum):
    """Direção derivada do ângulo do passe: "pra frente", "pro lado" ou "pra trás"."""

    FORWARD = "forward"
    SIDEWAYS = "sideways"
    BACKWARD = "backward"
    UNKNOWN = "unknown"


class PassLengthBucket(LenientStrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Drible, duelo, ação defensiva
# ---------------------------------------------------------------------------------------


class DribbleOutcome(LenientStrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class DuelType(LenientStrEnum):
    AERIAL = "aerial"
    TACKLE = "tackle"
    FIFTY_FIFTY = "fifty_fifty"
    UNKNOWN = "unknown"


class DuelOutcome(LenientStrEnum):
    WON = "won"
    LOST = "lost"
    SUCCESS = "success"
    UNKNOWN = "unknown"


class DefensiveActionType(LenientStrEnum):
    """Ações defensivas normalizadas num eixo único, para compor índices agregados."""

    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    BLOCK = "block"
    BALL_RECOVERY = "ball_recovery"
    PRESSURE = "pressure"
    AERIAL_DUEL = "aerial_duel"
    DRIBBLED_PAST = "dribbled_past"
    ERROR = "error"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Goleiro
# ---------------------------------------------------------------------------------------


class GoalkeeperActionType(LenientStrEnum):
    SHOT_SAVED = "shot_saved"
    PENALTY_SAVED = "penalty_saved"
    SMOTHER = "smother"
    COLLECTED = "collected"
    PUNCH = "punch"
    SAVE = "save"
    CLAIM = "claim"
    KEEPER_SWEEPER = "keeper_sweeper"
    GOAL_CONCEDED = "goal_conceded"
    PENALTY_CONCEDED = "penalty_conceded"
    UNKNOWN = "unknown"


class GoalkeeperOutcome(LenientStrEnum):
    SUCCESS = "success"
    FAIL = "fail"
    IN_PLAY_SAFE = "in_play_safe"
    IN_PLAY_DANGER = "in_play_danger"
    TOUCHED_IN = "touched_in"
    TOUCHED_OUT = "touched_out"
    NO_TOUCH = "no_touch"
    CLAIM = "claim"
    PUNCHED_OUT = "punched_out"
    UNKNOWN = "unknown"


class GoalkeeperTechnique(LenientStrEnum):
    DIVING = "diving"
    STANDING = "standing"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Disciplina
# ---------------------------------------------------------------------------------------


class CardType(LenientStrEnum):
    YELLOW = "yellow"
    SECOND_YELLOW = "second_yellow"
    RED = "red"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------------------
# Estrutura de competição, posição e mando
# ---------------------------------------------------------------------------------------


class CompetitionType(LenientStrEnum):
    """Recorte pedido: nacional, estadual, continental, internacional, amistoso, base."""

    NATIONAL_LEAGUE = "national_league"
    NATIONAL_CUP = "national_cup"
    REGIONAL = "regional"
    CONTINENTAL_CLUB = "continental_club"
    INTERNATIONAL_NATIONAL_TEAM = "international_national_team"
    FRIENDLY_CLUB = "friendly_club"
    FRIENDLY_NATIONAL_TEAM = "friendly_national_team"
    YOUTH = "youth"
    UNKNOWN = "unknown"


class PositionGroup(LenientStrEnum):
    """Agrupamento grosso da posição.

    Usado para escolher o conjunto de métricas comparáveis: não faz sentido comparar
    clean sheet de goleiro com drible de ponta no mesmo radar.
    """

    GOALKEEPER = "goalkeeper"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    FORWARD = "forward"
    UNKNOWN = "unknown"


class Venue(LenientStrEnum):
    HOME = "home"
    AWAY = "away"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"
