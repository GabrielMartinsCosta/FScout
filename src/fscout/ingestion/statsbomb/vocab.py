"""Tradução do vocabulário da StatsBomb para o vocabulário do domínio.

A StatsBomb nomeia valores do seu próprio jeito: `"Off T"` para chute para fora,
`"Ground Pass"` para passe rasteiro, `"Aerial Lost"` para duelo aéreo perdido. Uma
normalização automática de texto erraria parte deles em silêncio. Por isso cada campo
tem aqui uma tabela explícita, conferida contra 129 mil eventos de quatro competições
(Copa do Mundo 2022, Copa América 2024, Euro 2024 e La Liga 2020/21).

Valor fora das tabelas não interrompe a ingestão: vira `UNKNOWN` e é contabilizado em
`Vocabulary.misses`, que o pipeline reporta ao final. Uma entrada nesse relatório é sinal
para ampliar a tabela, não para ser ignorada.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fscout.domain.enums import (
    BodyPart,
    CardType,
    DribbleOutcome,
    DuelOutcome,
    DuelType,
    EventType,
    GoalkeeperActionType,
    GoalkeeperOutcome,
    GoalkeeperTechnique,
    PassHeight,
    PassOutcome,
    PassTechnique,
    PassType,
    PlayPattern,
    PositionGroup,
    ShotOutcome,
    ShotTechnique,
    ShotType,
)

T = TypeVar("T")


@dataclass
class Vocabulary:
    """Aplica as tabelas de tradução e registra os valores não reconhecidos."""

    misses: Counter[tuple[str, str]] = field(default_factory=Counter)

    def lookup(
        self,
        table: Mapping[str, T],
        raw: Mapping[str, Any] | None,
        *,
        field_name: str,
        unknown: T,
    ) -> T | None:
        """Traduz um objeto `{"id": ..., "name": ...}` da fonte.

        Objeto ausente devolve `None`: ausência de informação é diferente de informação
        desconhecida, e a distinção importa no denominador dos aproveitamentos.
        """
        if not raw:
            return None
        name = raw.get("name")
        if name in table:
            return table[name]
        self.misses[(field_name, str(name))] += 1
        return unknown


# Regiões que a StatsBomb coloca em `country_name` de competições, mas que não são países.
NON_COUNTRY_REGIONS = frozenset(
    {"International", "Europe", "South America", "Africa", "Asia", "North and Central America"}
)

EVENT_TYPE: Mapping[str, EventType] = {
    "Pass": EventType.PASS,
    "Ball Receipt*": EventType.BALL_RECEIPT,
    "Carry": EventType.CARRY,
    "Pressure": EventType.PRESSURE,
    "Shot": EventType.SHOT,
    "Dribble": EventType.DRIBBLE,
    "Dribbled Past": EventType.DRIBBLED_PAST,
    "Duel": EventType.DUEL,
    "Interception": EventType.INTERCEPTION,
    "Clearance": EventType.CLEARANCE,
    "Block": EventType.BLOCK,
    "Ball Recovery": EventType.BALL_RECOVERY,
    "Miscontrol": EventType.MISCONTROL,
    "Dispossessed": EventType.DISPOSSESSED,
    "Foul Committed": EventType.FOUL_COMMITTED,
    "Foul Won": EventType.FOUL_WON,
    "Goal Keeper": EventType.GOALKEEPER,
    "Substitution": EventType.SUBSTITUTION,
    "Bad Behaviour": EventType.BAD_BEHAVIOUR,
    "Own Goal For": EventType.OWN_GOAL_FOR,
    "Own Goal Against": EventType.OWN_GOAL_AGAINST,
    "Offside": EventType.OFFSIDE,
    "Shield": EventType.SHIELD,
    "Error": EventType.ERROR,
    "50/50": EventType.FIFTY_FIFTY,
    "Player On": EventType.PLAYER_ON,
    "Player Off": EventType.PLAYER_OFF,
    "Injury Stoppage": EventType.INJURY_STOPPAGE,
    "Referee Ball-Drop": EventType.REFEREE_BALL_DROP,
    "Tactical Shift": EventType.TACTICAL_SHIFT,
    "Starting XI": EventType.STARTING_XI,
    "Half Start": EventType.HALF_START,
    "Half End": EventType.HALF_END,
    # Marcadores de transmissão, presentes em temporadas antigas. Sem valor analítico.
    "Camera On": EventType.UNKNOWN,
    "Camera off": EventType.UNKNOWN,
}

PLAY_PATTERN: Mapping[str, PlayPattern] = {
    "Regular Play": PlayPattern.REGULAR_PLAY,
    "From Corner": PlayPattern.FROM_CORNER,
    "From Free Kick": PlayPattern.FROM_FREE_KICK,
    "From Throw In": PlayPattern.FROM_THROW_IN,
    "From Counter": PlayPattern.FROM_COUNTER,
    "From Goal Kick": PlayPattern.FROM_GOAL_KICK,
    "From Keeper": PlayPattern.FROM_KEEPER,
    "From Kick Off": PlayPattern.FROM_KICK_OFF,
    "Other": PlayPattern.OTHER,
}

BODY_PART: Mapping[str, BodyPart] = {
    "Left Foot": BodyPart.LEFT_FOOT,
    "Right Foot": BodyPart.RIGHT_FOOT,
    "Head": BodyPart.HEAD,
    "Chest": BodyPart.CHEST,
    "Other": BodyPart.OTHER,
    "No Touch": BodyPart.NO_TOUCH,
    "Both Hands": BodyPart.BOTH_HANDS,
    "Left Hand": BodyPart.LEFT_HAND,
    "Right Hand": BodyPart.RIGHT_HAND,
    "Keeper Arm": BodyPart.KEEPER_ARM,
    "Drop Kick": BodyPart.DROP_KICK,
}

SHOT_TYPE: Mapping[str, ShotType] = {
    "Open Play": ShotType.OPEN_PLAY,
    "Penalty": ShotType.PENALTY,
    "Free Kick": ShotType.FREE_KICK,
    "Corner": ShotType.CORNER,
    "Kick Off": ShotType.KICK_OFF,
}

SHOT_OUTCOME: Mapping[str, ShotOutcome] = {
    "Goal": ShotOutcome.GOAL,
    "Saved": ShotOutcome.SAVED,
    "Saved to Post": ShotOutcome.SAVED_TO_POST,
    "Saved Off Target": ShotOutcome.SAVED_OFF_TARGET,
    "Blocked": ShotOutcome.BLOCKED,
    "Off T": ShotOutcome.OFF_TARGET,
    "Post": ShotOutcome.POST,
    "Wayward": ShotOutcome.WAYWARD,
}

SHOT_TECHNIQUE: Mapping[str, ShotTechnique] = {
    "Normal": ShotTechnique.NORMAL,
    "Volley": ShotTechnique.VOLLEY,
    "Half Volley": ShotTechnique.HALF_VOLLEY,
    "Lob": ShotTechnique.LOB,
    "Overhead Kick": ShotTechnique.OVERHEAD_KICK,
    "Backheel": ShotTechnique.BACKHEEL,
    "Diving Header": ShotTechnique.DIVING_HEADER,
}

PASS_HEIGHT: Mapping[str, PassHeight] = {
    "Ground Pass": PassHeight.GROUND,
    "Low Pass": PassHeight.LOW,
    "High Pass": PassHeight.HIGH,
}

# A ausência de `type` num passe significa jogo corrido; por isso não há "Open Play" aqui.
PASS_TYPE: Mapping[str, PassType] = {
    "Corner": PassType.CORNER,
    "Free Kick": PassType.FREE_KICK,
    "Throw-in": PassType.THROW_IN,
    "Goal Kick": PassType.GOAL_KICK,
    "Kick Off": PassType.KICK_OFF,
    "Interception": PassType.INTERCEPTION,
    "Recovery": PassType.RECOVERY,
}

PASS_TECHNIQUE: Mapping[str, PassTechnique] = {
    "Through Ball": PassTechnique.THROUGH_BALL,
    "Inswinging": PassTechnique.INSWINGING,
    "Outswinging": PassTechnique.OUTSWINGING,
    "Straight": PassTechnique.STRAIGHT,
}

# A ausência de `outcome` num passe significa passe completo.
PASS_OUTCOME: Mapping[str, PassOutcome] = {
    "Incomplete": PassOutcome.INCOMPLETE,
    "Out": PassOutcome.OUT,
    "Pass Offside": PassOutcome.OFFSIDE,
    "Injury Clearance": PassOutcome.INJURY_CLEARANCE,
    "Unknown": PassOutcome.UNKNOWN,
}

DRIBBLE_OUTCOME: Mapping[str, DribbleOutcome] = {
    "Complete": DribbleOutcome.COMPLETE,
    "Incomplete": DribbleOutcome.INCOMPLETE,
}

# A StatsBomb só registra o duelo aéreo *perdido* como evento `Duel`. O vencido aparece
# como a marca `aerial_won` em passes, chutes, cortes e domínios errados.
DUEL_TYPE: Mapping[str, DuelType] = {
    "Aerial Lost": DuelType.AERIAL,
    "Tackle": DuelType.TACKLE,
}

# Usada em desarmes e interceptações. "In Play" e "Out" dizem se a bola seguiu em jogo,
# distinção que não altera quem venceu a disputa.
DUEL_OUTCOME: Mapping[str, DuelOutcome] = {
    "Won": DuelOutcome.WON,
    "Success": DuelOutcome.WON,
    "Success In Play": DuelOutcome.WON,
    "Success Out": DuelOutcome.WON,
    "Lost": DuelOutcome.LOST,
    "Lost In Play": DuelOutcome.LOST,
    "Lost Out": DuelOutcome.LOST,
}

FIFTY_FIFTY_WON: Mapping[str, bool] = {
    "Won": True,
    "Success To Team": True,
    "Lost": False,
    "Success To Opposition": False,
}

GOALKEEPER_TYPE: Mapping[str, GoalkeeperActionType] = {
    "Shot Faced": GoalkeeperActionType.SHOT_FACED,
    "Shot Saved": GoalkeeperActionType.SHOT_SAVED,
    "Shot Saved to Post": GoalkeeperActionType.SHOT_SAVED_TO_POST,
    "Shot Saved Off Target": GoalkeeperActionType.SHOT_SAVED_OFF_TARGET,
    "Save": GoalkeeperActionType.SAVE,
    "Penalty Saved": GoalkeeperActionType.PENALTY_SAVED,
    "Penalty Saved to Post": GoalkeeperActionType.PENALTY_SAVED,
    "Goal Conceded": GoalkeeperActionType.GOAL_CONCEDED,
    "Penalty Conceded": GoalkeeperActionType.PENALTY_CONCEDED,
    "Keeper Sweeper": GoalkeeperActionType.KEEPER_SWEEPER,
    "Collected": GoalkeeperActionType.COLLECTED,
    "Punch": GoalkeeperActionType.PUNCH,
    "Smother": GoalkeeperActionType.SMOTHER,
}

GOALKEEPER_OUTCOME: Mapping[str, GoalkeeperOutcome] = {
    "Success": GoalkeeperOutcome.SUCCESS,
    "Fail": GoalkeeperOutcome.FAIL,
    "No Touch": GoalkeeperOutcome.NO_TOUCH,
    "In Play Safe": GoalkeeperOutcome.IN_PLAY_SAFE,
    "In Play Danger": GoalkeeperOutcome.IN_PLAY_DANGER,
    "Touched In": GoalkeeperOutcome.TOUCHED_IN,
    "Touched Out": GoalkeeperOutcome.TOUCHED_OUT,
    "Claim": GoalkeeperOutcome.CLAIM,
    "Clear": GoalkeeperOutcome.CLEAR,
    "Punched out": GoalkeeperOutcome.PUNCHED_OUT,
    "Saved Twice": GoalkeeperOutcome.SAVED_TWICE,
    "Collected Twice": GoalkeeperOutcome.COLLECTED_TWICE,
    "Won": GoalkeeperOutcome.WON,
    "Success In Play": GoalkeeperOutcome.SUCCESS_IN_PLAY,
    "Success Out": GoalkeeperOutcome.SUCCESS_OUT,
    "Lost In Play": GoalkeeperOutcome.LOST_IN_PLAY,
    "Lost Out": GoalkeeperOutcome.LOST_OUT,
}

GOALKEEPER_TECHNIQUE: Mapping[str, GoalkeeperTechnique] = {
    "Diving": GoalkeeperTechnique.DIVING,
    "Standing": GoalkeeperTechnique.STANDING,
}

CARD: Mapping[str, CardType] = {
    "Yellow Card": CardType.YELLOW,
    "Second Yellow": CardType.SECOND_YELLOW,
    "Red Card": CardType.RED,
}

# Alas (wing backs) são defensores; pontas (wings) são atacantes. É a convenção que
# mantém laterais ofensivos no mesmo grupo de comparação que os laterais tradicionais.
POSITION_GROUP: Mapping[str, PositionGroup] = {
    "Goalkeeper": PositionGroup.GOALKEEPER,
    "Right Back": PositionGroup.DEFENDER,
    "Right Center Back": PositionGroup.DEFENDER,
    "Center Back": PositionGroup.DEFENDER,
    "Left Center Back": PositionGroup.DEFENDER,
    "Left Back": PositionGroup.DEFENDER,
    "Right Wing Back": PositionGroup.DEFENDER,
    "Left Wing Back": PositionGroup.DEFENDER,
    "Right Defensive Midfield": PositionGroup.MIDFIELDER,
    "Center Defensive Midfield": PositionGroup.MIDFIELDER,
    "Left Defensive Midfield": PositionGroup.MIDFIELDER,
    "Right Midfield": PositionGroup.MIDFIELDER,
    "Right Center Midfield": PositionGroup.MIDFIELDER,
    "Center Midfield": PositionGroup.MIDFIELDER,
    "Left Center Midfield": PositionGroup.MIDFIELDER,
    "Left Midfield": PositionGroup.MIDFIELDER,
    "Right Attacking Midfield": PositionGroup.MIDFIELDER,
    "Center Attacking Midfield": PositionGroup.MIDFIELDER,
    "Left Attacking Midfield": PositionGroup.MIDFIELDER,
    "Right Wing": PositionGroup.FORWARD,
    "Left Wing": PositionGroup.FORWARD,
    "Right Center Forward": PositionGroup.FORWARD,
    "Center Forward": PositionGroup.FORWARD,
    "Left Center Forward": PositionGroup.FORWARD,
    "Striker": PositionGroup.FORWARD,
    "Secondary Striker": PositionGroup.FORWARD,
}
