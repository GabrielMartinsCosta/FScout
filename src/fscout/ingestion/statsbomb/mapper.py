"""Tradução de uma partida da StatsBomb para linhas do schema do FScout.

Funções puras: recebem o JSON da fonte e devolvem dicionários prontos para inserção.
Nenhuma toca o banco, então o mapeamento inteiro é testável com um arquivo de exemplo.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from fscout.domain.enums import (
    BodyPart,
    CardType,
    CompetitionType,
    DefensiveActionType,
    DribbleOutcome,
    DuelOutcome,
    DuelType,
    EventType,
    GoalkeeperActionType,
    GoalkeeperOutcome,
    GoalkeeperTechnique,
    HomeAway,
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
from fscout.domain.pitch import (
    GOAL_CROSSBAR_Z,
    GOAL_LEFT_POST_Y,
    GOAL_RIGHT_POST_Y,
    PITCH_LENGTH,
    GoalMouthZone,
    classify_direction,
    classify_length,
    distance_m,
    distance_to_goal_m,
    enters_penalty_area,
    enters_six_yard_box,
    goal_mouth_zone,
    grid_cell,
    in_own_penalty_area,
    in_penalty_area,
    in_six_yard_box,
    is_progressive,
    lane,
    near_own_penalty_area,
    pass_direction_deg,
    shot_angle_deg,
    vertical_third,
)
from fscout.ingestion.bundle import GoalCheck, MatchBundle, Row
from fscout.ingestion.statsbomb import vocab as sb
from fscout.ingestion.statsbomb.chains import (
    DribbleConsequence,
    find_pre_assists,
    resolve_dribble_consequences,
)
from fscout.ingestion.statsbomb.clock import (
    SHOOTOUT_PERIOD,
    nominal_minutes,
    period_clocks,
    time_on_pitch,
)
from fscout.ingestion.statsbomb.vocab import Vocabulary

SOURCE = "statsbomb"

RawEvent = Mapping[str, Any]

# Chaves de topo que viram colunas de `events`; o resto vai para `qualifiers`.
COMMON_EVENT_KEYS = frozenset(
    {
        "id",
        "index",
        "period",
        "timestamp",
        "minute",
        "second",
        "type",
        "possession",
        "possession_team",
        "play_pattern",
        "team",
        "player",
        "position",
        "location",
        "duration",
        "under_pressure",
    }
)

ON_TARGET_OUTCOMES = frozenset({ShotOutcome.GOAL, ShotOutcome.SAVED, ShotOutcome.SAVED_TO_POST})
OFF_TARGET_OUTCOMES = frozenset(
    {ShotOutcome.OFF_TARGET, ShotOutcome.WAYWARD, ShotOutcome.SAVED_OFF_TARGET}
)

SAVE_TYPES = frozenset(
    {
        GoalkeeperActionType.SHOT_SAVED,
        GoalkeeperActionType.SHOT_SAVED_TO_POST,
        GoalkeeperActionType.SHOT_SAVED_OFF_TARGET,
        GoalkeeperActionType.SAVE,
        GoalkeeperActionType.PENALTY_SAVED,
    }
)
CONCEDED_TYPES = frozenset(
    {GoalkeeperActionType.GOAL_CONCEDED, GoalkeeperActionType.PENALTY_CONCEDED}
)
REBOUND_OUTCOMES = frozenset({GoalkeeperOutcome.IN_PLAY_DANGER, GoalkeeperOutcome.SAVED_TWICE})

# Tipos de evento que podem carregar a marca `aerial_won`, e a chave onde ela fica.
AERIAL_WON_FAMILIES: Mapping[str, str] = {
    "Pass": "pass",
    "Shot": "shot",
    "Clearance": "clearance",
    "Miscontrol": "miscontrol",
}

CONTINENTAL_CLUB_KEYWORDS = (
    "Champions League",
    "Europa League",
    "Conference League",
    "Libertadores",
    "Sudamericana",
)
NATIONAL_CUP_KEYWORDS = ("Cup", "Copa del Rey", "Coppa", "Pokal", "Coupe")


# =========================================================================================
# Utilitários
# =========================================================================================


def _name(obj: Mapping[str, Any] | None) -> str | None:
    return obj.get("name") if obj else None


def _ref(obj: Mapping[str, Any] | None) -> str | None:
    if not obj or obj.get("id") is None:
        return None
    return str(obj["id"])


def _location(event: RawEvent) -> tuple[float, float] | None:
    location = event.get("location")
    if not location or len(location) < 2:
        return None
    return float(location[0]), float(location[1])


def _kind(event: RawEvent) -> str:
    return event["type"]["name"]


# =========================================================================================
# Competição e temporada
# =========================================================================================


def competition_type(record: Mapping[str, Any]) -> CompetitionType:
    """Classifica a competição para os recortes nacional, continental, seleção e base.

    A StatsBomb só informa se é internacional e se é de base; o restante é inferido do nome.
    """
    name = record["competition_name"]
    if record.get("competition_youth"):
        return CompetitionType.YOUTH
    if record.get("competition_international"):
        return CompetitionType.INTERNATIONAL_NATIONAL_TEAM
    if any(keyword in name for keyword in CONTINENTAL_CLUB_KEYWORDS):
        return CompetitionType.CONTINENTAL_CLUB
    if any(keyword in name for keyword in NATIONAL_CUP_KEYWORDS):
        return CompetitionType.NATIONAL_CUP
    return CompetitionType.NATIONAL_LEAGUE


def season_source_id(competition_id: int, season_id: int) -> str:
    """Identificador da temporada na fonte.

    O `season_id` da StatsBomb não é único entre competições: 282 é tanto a Copa América
    2024 quanto a Euro 2024. Usá-lo sozinho faria a segunda carga sobrescrever a primeira.
    """
    return f"{competition_id}-{season_id}"


def competition_row(record: Mapping[str, Any]) -> Row:
    country = record.get("country_name")
    return {
        "source_id": str(record["competition_id"]),
        "name": record["competition_name"],
        "country_ref": None if country in sb.NON_COUNTRY_REGIONS else country,
        "type": competition_type(record),
        "gender": record.get("competition_gender"),
        "is_youth": bool(record.get("competition_youth")),
    }


def season_row(record: Mapping[str, Any]) -> Row:
    return {
        "source_id": season_source_id(record["competition_id"], record["season_id"]),
        "name": record["season_name"],
    }


# =========================================================================================
# Partida completa
# =========================================================================================


def build_match_bundle(
    match: Mapping[str, Any],
    events: Sequence[RawEvent],
    lineups: Sequence[Mapping[str, Any]],
    *,
    is_international: bool,
    vocab: Vocabulary,
) -> MatchBundle:
    """Traduz uma partida inteira: dimensões, participações, eventos e projeções."""
    ordered = sorted(events, key=lambda event: event["index"])
    by_id = {event["id"]: event for event in ordered}

    home_ref = str(match["home_team"]["home_team_id"])
    away_ref = str(match["away_team"]["away_team_id"])
    neutral = is_neutral_venue(match)

    players = _players_from_events(ordered)
    appearances: list[Row] = []
    clocks = period_clocks(ordered)

    for team in lineups:
        team_ref = str(team["team_id"])
        is_home = team_ref == home_ref
        goals_for, goals_against = (
            (match.get("home_score"), match.get("away_score"))
            if is_home
            else (match.get("away_score"), match.get("home_score"))
        )
        home_away = HomeAway.NEUTRAL if neutral else (HomeAway.HOME if is_home else HomeAway.AWAY)

        for lineup_player in team["lineup"]:
            player = player_row(lineup_player)
            players[player["source_id"]] = player
            appearance = appearance_row(lineup_player, clocks, vocab)
            if appearance is None:
                continue
            appearance.update(
                team_ref=team_ref,
                opponent_team_ref=away_ref if is_home else home_ref,
                home_away=home_away,
                goals_for=goals_for,
                goals_against=goals_against,
            )
            appearances.append(appearance)

    bundle = MatchBundle(
        match=match_row(match, neutral),
        teams={
            home_ref: _team_row(match["home_team"], "home", is_international),
            away_ref: _team_row(match["away_team"], "away", is_international),
        },
        players=players,
        appearances=appearances,
        goal_check=goal_check(match, ordered),
    )

    pre_assists = find_pre_assists(ordered)
    consequences = resolve_dribble_consequences(ordered, pre_assists)

    for event in ordered:
        kind = _kind(event)
        bundle.events.append(event_row(event, vocab))
        if kind == "Shot":
            bundle.shots.append(shot_row(event, vocab))
        elif kind == "Pass":
            bundle.passes.append(pass_row(event, vocab, pre_assists))
        elif kind == "Dribble":
            bundle.dribbles.append(dribble_row(event, vocab, consequences[event["id"]]))
        elif kind == "Goal Keeper":
            bundle.goalkeeper_actions.append(goalkeeper_row(event, vocab, by_id))

        disciplinary = disciplinary_row(event, vocab)
        if disciplinary is not None:
            bundle.disciplinary_actions.append(disciplinary)
        bundle.defensive_actions.extend(defensive_rows(event, vocab))

    return bundle


def is_neutral_venue(match: Mapping[str, Any]) -> bool:
    """Campo neutro: o estádio fica fora do país do mandante.

    A StatsBomb não marca campo neutro. A inferência resolve os casos que importam para o
    recorte casa/fora: seleções em Copa do Mundo e finais continentais em sede única.
    Decisão em estádio de terceiro dentro do mesmo país não é detectada.
    """
    stadium_country = _name((match.get("stadium") or {}).get("country"))
    home_country = _name(match["home_team"].get("country"))
    return (
        stadium_country is not None and home_country is not None and stadium_country != home_country
    )


def match_row(match: Mapping[str, Any], neutral: bool) -> Row:
    competition, season = match["competition"], match["season"]
    kick_off = match.get("kick_off")
    return {
        "source_id": str(match["match_id"]),
        "season_ref": season_source_id(competition["competition_id"], season["season_id"]),
        "match_date": date.fromisoformat(match["match_date"]),
        "kickoff": datetime.fromisoformat(f"{match['match_date']}T{kick_off}")
        if kick_off
        else None,
        "home_team_ref": str(match["home_team"]["home_team_id"]),
        "away_team_ref": str(match["away_team"]["away_team_id"]),
        "home_score": match.get("home_score"),
        "away_score": match.get("away_score"),
        "stage": _name(match.get("competition_stage")),
        "stadium": _name(match.get("stadium")),
        "venue_country": _name((match.get("stadium") or {}).get("country")),
        "referee": _name(match.get("referee")),
        "is_neutral_venue": neutral,
    }


def goal_check(match: Mapping[str, Any], events: Iterable[RawEvent]) -> GoalCheck:
    """Gols por equipe reconstruídos dos eventos, sem a disputa de pênaltis."""
    goals: Counter[str | None] = Counter()
    for event in events:
        if event["period"] == SHOOTOUT_PERIOD:
            continue
        kind = _kind(event)
        is_goal = kind == "Shot" and _name(event["shot"].get("outcome")) == "Goal"
        if is_goal or kind == "Own Goal For":
            goals[_ref(event.get("team"))] += 1

    home_ref = str(match["home_team"]["home_team_id"])
    away_ref = str(match["away_team"]["away_team_id"])
    return GoalCheck(
        expected=(match.get("home_score"), match.get("away_score")),
        from_events=(goals[home_ref], goals[away_ref]),
    )


def _team_row(side: Mapping[str, Any], prefix: str, is_international: bool) -> Row:
    return {
        "source_id": str(side[f"{prefix}_team_id"]),
        "name": side[f"{prefix}_team_name"],
        "gender": side.get(f"{prefix}_team_gender"),
        "country_ref": _name(side.get("country")),
        "is_national_team": is_international,
    }


# =========================================================================================
# Atletas e participações
# =========================================================================================


def player_row(lineup_player: Mapping[str, Any]) -> Row:
    """Atleta a partir da escalação. O apelido, quando existe, é o nome de exibição."""
    nickname = lineup_player.get("player_nickname")
    return {
        "source_id": str(lineup_player["player_id"]),
        "name": nickname or lineup_player["player_name"],
        "full_name": lineup_player["player_name"],
        "nickname": nickname,
        "nationality_ref": _name(lineup_player.get("country")),
    }


def _players_from_events(events: Iterable[RawEvent]) -> dict[str, Row]:
    """Atletas citados nos eventos, como garantia contra escalações incompletas.

    Todo atleta referenciado precisa existir antes da gravação dos eventos. A escalação,
    processada depois, sobrescreve estas entradas com dados completos.
    """
    players: dict[str, Row] = {}

    def add(obj: Mapping[str, Any] | None) -> None:
        ref = _ref(obj)
        if ref is not None and obj is not None and ref not in players:
            players[ref] = {"source_id": ref, "name": obj.get("name"), "full_name": obj.get("name")}

    for event in events:
        add(event.get("player"))
        add((event.get("pass") or {}).get("recipient"))
        add((event.get("substitution") or {}).get("replacement"))
        for entry in (event.get("tactics") or {}).get("lineup", []):
            add(entry.get("player"))
    return players


def appearance_row(
    lineup_player: Mapping[str, Any],
    clocks: Mapping[int, Any],
    vocab: Vocabulary,
) -> Row | None:
    """Participação na partida. Atleta que não entrou em campo não gera participação."""
    positions = lineup_player.get("positions") or []
    if not positions:
        return None

    time = time_on_pitch(positions, clocks)
    if time.by_position_s:
        main_position = max(time.by_position_s.items(), key=lambda item: item[1])[0]
    else:
        main_position = positions[0]["position"]

    is_starter = any(position.get("start_reason") == "Starting XI" for position in positions)
    return {
        "player_ref": str(lineup_player["player_id"]),
        "position": main_position,
        "position_group": vocab.lookup(
            sb.POSITION_GROUP,
            {"name": main_position},
            field_name="position",
            unknown=PositionGroup.UNKNOWN,
        ),
        "jersey_number": lineup_player.get("jersey_number"),
        "is_starter": is_starter,
        "minute_on": _clock_minute(None if is_starter else time.entered_clock_s),
        "minute_off": _clock_minute(time.exited_clock_s),
        "minutes_played": nominal_minutes(time),
        "seconds_on_pitch": time.actual_s,
    }


def _clock_minute(clock_s: int | None) -> int | None:
    return None if clock_s is None else clock_s // 60


# =========================================================================================
# Eventos
# =========================================================================================


def event_row(event: RawEvent, vocab: Vocabulary) -> Row:
    location = _location(event)
    x, y = location if location else (None, None)
    grid_col, grid_row = grid_cell(*location) if location else (None, None)
    return {
        "source_id": event["id"],
        "sequence": event["index"],
        "period": event["period"],
        "minute": event["minute"],
        "second": event["second"],
        "type": vocab.lookup(
            sb.EVENT_TYPE, event["type"], field_name="type", unknown=EventType.UNKNOWN
        ),
        "team_ref": _ref(event.get("team")),
        "player_ref": _ref(event.get("player")),
        "position": _name(event.get("position")),
        "x": x,
        "y": y,
        "third": vertical_third(location[0]) if location else None,
        "lane": lane(location[1]) if location else None,
        "grid_col": grid_col,
        "grid_row": grid_row,
        "play_pattern": vocab.lookup(
            sb.PLAY_PATTERN,
            event.get("play_pattern"),
            field_name="play_pattern",
            unknown=PlayPattern.UNKNOWN,
        ),
        "possession": event.get("possession"),
        "possession_team_ref": _ref(event.get("possession_team")),
        "duration": event.get("duration"),
        "under_pressure": bool(event.get("under_pressure", False)),
        "qualifiers": _qualifiers(event),
    }


def _qualifiers(event: RawEvent) -> dict[str, Any] | None:
    """Atributos sem coluna própria, sem os freeze frames de chute."""
    qualifiers: dict[str, Any] = {}
    for key, value in event.items():
        if key in COMMON_EVENT_KEYS:
            continue
        if key == "shot" and isinstance(value, Mapping):
            value = {k: v for k, v in value.items() if k != "freeze_frame"}
        qualifiers[key] = value
    return qualifiers or None


def shot_goal_zone(shot: Mapping[str, Any], outcome: ShotOutcome | None) -> GoalMouthZone | None:
    """Zona da boca do gol atingida pela finalização.

    O desfecho manda sobre a coordenada. Chute para fora é `OFF_TARGET` mesmo que o ponto
    final registrado caia entre as traves (chute por cima sem altura anotada). Chute no
    alvo é trazido para dentro da moldura, para que ruído de coordenada não o jogue para
    fora. Chute bloqueado não tem zona: seu ponto final é onde bateu no defensor.
    """
    if outcome in OFF_TARGET_OUTCOMES:
        return GoalMouthZone.OFF_TARGET
    if outcome is None or outcome in (ShotOutcome.BLOCKED, ShotOutcome.UNKNOWN):
        return None

    end = shot.get("end_location") or []
    if len(end) < 2:
        return None
    end_y = float(end[1])
    end_z = float(end[2]) if len(end) > 2 else None
    if outcome in ON_TARGET_OUTCOMES:
        end_y = min(max(end_y, GOAL_LEFT_POST_Y), GOAL_RIGHT_POST_Y)
        end_z = None if end_z is None else min(max(end_z, 0.0), GOAL_CROSSBAR_Z)
    return goal_mouth_zone(end_y, end_z)


def shot_row(event: RawEvent, vocab: Vocabulary) -> Row:
    shot = event["shot"]
    location = _location(event)
    outcome = vocab.lookup(
        sb.SHOT_OUTCOME, shot.get("outcome"), field_name="shot.outcome", unknown=ShotOutcome.UNKNOWN
    )
    end = [*shot.get("end_location", []), None, None, None]
    return {
        "event_ref": event["id"],
        "player_ref": _ref(event.get("player")),
        "shot_type": vocab.lookup(
            sb.SHOT_TYPE, shot.get("type"), field_name="shot.type", unknown=ShotType.UNKNOWN
        )
        or ShotType.UNKNOWN,
        "outcome": outcome or ShotOutcome.UNKNOWN,
        "technique": vocab.lookup(
            sb.SHOT_TECHNIQUE,
            shot.get("technique"),
            field_name="shot.technique",
            unknown=ShotTechnique.UNKNOWN,
        ),
        "body_part": vocab.lookup(
            sb.BODY_PART,
            shot.get("body_part"),
            field_name="shot.body_part",
            unknown=BodyPart.UNKNOWN,
        ),
        "is_goal": outcome is ShotOutcome.GOAL,
        "is_on_target": outcome in ON_TARGET_OUTCOMES,
        "hit_post": outcome in (ShotOutcome.POST, ShotOutcome.SAVED_TO_POST),
        "was_blocked": outcome is ShotOutcome.BLOCKED,
        "is_shootout": event["period"] == SHOOTOUT_PERIOD,
        "distance_m": distance_to_goal_m(*location) if location else None,
        "angle_deg": shot_angle_deg(*location) if location else None,
        "in_penalty_area": bool(location and in_penalty_area(*location)),
        "in_six_yard_box": bool(location and in_six_yard_box(*location)),
        "end_x": end[0],
        "end_y": end[1],
        "end_z": end[2],
        "goal_mouth_zone": shot_goal_zone(shot, outcome),
        "first_time": bool(shot.get("first_time")),
        "follows_dribble": bool(shot.get("follows_dribble")),
        "open_goal": bool(shot.get("open_goal")),
        "deflected": bool(shot.get("deflected")),
        "one_on_one": bool(shot.get("one_on_one")),
        "xg": shot.get("statsbomb_xg"),
        "key_pass_ref": shot.get("key_pass_id"),
    }


def pass_row(event: RawEvent, vocab: Vocabulary, pre_assists: frozenset[str]) -> Row:
    pass_ = event["pass"]
    start = _location(event)
    end_location = pass_.get("end_location") or []
    end = (float(end_location[0]), float(end_location[1])) if len(end_location) >= 2 else None

    raw_outcome = pass_.get("outcome")
    outcome = (
        PassOutcome.COMPLETE
        if raw_outcome is None
        else vocab.lookup(
            sb.PASS_OUTCOME, raw_outcome, field_name="pass.outcome", unknown=PassOutcome.UNKNOWN
        )
    )
    technique = vocab.lookup(
        sb.PASS_TECHNIQUE,
        pass_.get("technique"),
        field_name="pass.technique",
        unknown=PassTechnique.UNKNOWN,
    )
    pass_type = (
        PassType.OPEN_PLAY
        if pass_.get("type") is None
        else vocab.lookup(
            sb.PASS_TYPE, pass_.get("type"), field_name="pass.type", unknown=PassType.UNKNOWN
        )
    )

    geometry: Row = {
        "length_m": None,
        "angle_deg": None,
        "length_bucket": None,
        "direction": None,
        "is_progressive": False,
        "into_penalty_area": False,
        "into_six_yard_box": False,
    }
    if start and end:
        length_m = distance_m(*start, *end)
        geometry = {
            "length_m": length_m,
            "angle_deg": pass_direction_deg(*start, *end),
            "length_bucket": classify_length(length_m),
            "direction": classify_direction(*start, *end),
            "is_progressive": is_progressive(*start, *end),
            "into_penalty_area": enters_penalty_area(*start, *end),
            "into_six_yard_box": enters_six_yard_box(*start, *end),
        }

    return {
        "event_ref": event["id"],
        "player_ref": _ref(event.get("player")),
        "recipient_ref": _ref(pass_.get("recipient")),
        "end_x": end[0] if end else None,
        "end_y": end[1] if end else None,
        **geometry,
        "height": vocab.lookup(
            sb.PASS_HEIGHT,
            pass_.get("height"),
            field_name="pass.height",
            unknown=PassHeight.UNKNOWN,
        ),
        "pass_type": pass_type,
        "technique": technique,
        "body_part": vocab.lookup(
            sb.BODY_PART,
            pass_.get("body_part"),
            field_name="pass.body_part",
            unknown=BodyPart.UNKNOWN,
        ),
        "outcome": outcome,
        "is_complete": raw_outcome is None,
        "is_cross": bool(pass_.get("cross")),
        "is_switch": bool(pass_.get("switch")),
        "is_through_ball": bool(pass_.get("through_ball"))
        or technique is PassTechnique.THROUGH_BALL,
        "is_cutback": bool(pass_.get("cut_back")),
        "is_shot_assist": bool(pass_.get("shot_assist") or pass_.get("goal_assist")),
        "is_goal_assist": bool(pass_.get("goal_assist")),
        "is_pre_assist": event["id"] in pre_assists,
    }


def dribble_row(event: RawEvent, vocab: Vocabulary, consequence: DribbleConsequence) -> Row:
    dribble = event.get("dribble") or {}
    location = _location(event)
    outcome = (
        vocab.lookup(
            sb.DRIBBLE_OUTCOME,
            dribble.get("outcome"),
            field_name="dribble.outcome",
            unknown=DribbleOutcome.UNKNOWN,
        )
        or DribbleOutcome.UNKNOWN
    )
    return {
        "event_ref": event["id"],
        "player_ref": _ref(event.get("player")),
        "outcome": outcome,
        "is_complete": outcome is DribbleOutcome.COMPLETE,
        "nutmeg": bool(dribble.get("nutmeg")),
        "overrun": bool(dribble.get("overrun")),
        "in_penalty_area": bool(location and in_penalty_area(*location)),
        **asdict(consequence),
    }


def defensive_rows(event: RawEvent, vocab: Vocabulary) -> list[Row]:
    """Ações defensivas do evento. Um evento pode gerar zero, uma ou duas linhas."""
    kind = _kind(event)
    location = _location(event)
    rows: list[Row] = []

    def add(
        action: DefensiveActionType,
        successful: bool | None,
        *,
        duel_type: DuelType | None = None,
        duel_outcome: DuelOutcome | None = None,
        aerial: bool = False,
    ) -> None:
        rows.append(
            {
                "event_ref": event["id"],
                "player_ref": _ref(event.get("player")),
                "action_type": action,
                "duel_type": duel_type,
                "duel_outcome": duel_outcome,
                "is_successful": successful,
                "is_aerial": aerial,
                "in_own_penalty_area": bool(location and in_own_penalty_area(*location)),
            }
        )

    if kind == "Duel":
        duel = event.get("duel") or {}
        duel_type = vocab.lookup(
            sb.DUEL_TYPE, duel.get("type"), field_name="duel.type", unknown=DuelType.UNKNOWN
        )
        if duel_type is DuelType.AERIAL:
            add(
                DefensiveActionType.AERIAL_DUEL,
                False,
                duel_type=DuelType.AERIAL,
                duel_outcome=DuelOutcome.LOST,
                aerial=True,
            )
        else:
            outcome = vocab.lookup(
                sb.DUEL_OUTCOME,
                duel.get("outcome"),
                field_name="duel.outcome",
                unknown=DuelOutcome.UNKNOWN,
            )
            add(
                DefensiveActionType.TACKLE,
                outcome is DuelOutcome.WON,
                duel_type=duel_type,
                duel_outcome=outcome,
            )
    elif kind == "Interception":
        outcome = vocab.lookup(
            sb.DUEL_OUTCOME,
            (event.get("interception") or {}).get("outcome"),
            field_name="interception.outcome",
            unknown=DuelOutcome.UNKNOWN,
        )
        add(DefensiveActionType.INTERCEPTION, outcome is DuelOutcome.WON, duel_outcome=outcome)
    elif kind == "Clearance":
        add(DefensiveActionType.CLEARANCE, True)
    elif kind == "Block":
        add(DefensiveActionType.BLOCK, True)
    elif kind == "Ball Recovery":
        failed = bool((event.get("ball_recovery") or {}).get("recovery_failure"))
        add(DefensiveActionType.BALL_RECOVERY, not failed)
    elif kind == "Pressure":
        add(DefensiveActionType.PRESSURE, None)
    elif kind == "Dribbled Past":
        add(DefensiveActionType.DRIBBLED_PAST, False)
    elif kind == "Error":
        add(DefensiveActionType.ERROR, False)
    elif kind == "50/50":
        won = vocab.lookup(
            sb.FIFTY_FIFTY_WON,
            (event.get("50_50") or {}).get("outcome"),
            field_name="50_50.outcome",
            unknown=False,
        )
        add(DefensiveActionType.FIFTY_FIFTY, bool(won))

    family = AERIAL_WON_FAMILIES.get(kind)
    if family and (event.get(family) or {}).get("aerial_won"):
        add(
            DefensiveActionType.AERIAL_DUEL,
            True,
            duel_type=DuelType.AERIAL,
            duel_outcome=DuelOutcome.WON,
            aerial=True,
        )
    return rows


def goalkeeper_row(event: RawEvent, vocab: Vocabulary, by_id: Mapping[str, RawEvent]) -> Row:
    keeper = event.get("goalkeeper") or {}
    action = (
        vocab.lookup(
            sb.GOALKEEPER_TYPE,
            keeper.get("type"),
            field_name="goalkeeper.type",
            unknown=GoalkeeperActionType.UNKNOWN,
        )
        or GoalkeeperActionType.UNKNOWN
    )
    outcome = vocab.lookup(
        sb.GOALKEEPER_OUTCOME,
        keeper.get("outcome"),
        field_name="goalkeeper.outcome",
        unknown=GoalkeeperOutcome.UNKNOWN,
    )
    is_save = action in SAVE_TYPES
    row: Row = {
        "event_ref": event["id"],
        "player_ref": _ref(event.get("player")),
        "action_type": action,
        "outcome": outcome,
        "technique": vocab.lookup(
            sb.GOALKEEPER_TECHNIQUE,
            keeper.get("technique"),
            field_name="goalkeeper.technique",
            unknown=GoalkeeperTechnique.UNKNOWN,
        ),
        "body_part": vocab.lookup(
            sb.BODY_PART,
            keeper.get("body_part"),
            field_name="goalkeeper.body_part",
            unknown=BodyPart.UNKNOWN,
        ),
        "is_save": is_save,
        "is_penalty_save": action is GoalkeeperActionType.PENALTY_SAVED,
        "conceded_goal": action in CONCEDED_TYPES,
        "gave_rebound": is_save and outcome in REBOUND_OUTCOMES,
        "is_sweeper": action is GoalkeeperActionType.KEEPER_SWEEPER,
        "is_shootout": event["period"] == SHOOTOUT_PERIOD,
        "shot_ref": None,
        "shot_distance_m": None,
        "shot_from_outside_box": False,
        "shot_goal_mouth_zone": None,
        "shot_xg": None,
    }

    shot = next(
        (
            by_id[related]
            for related in event.get("related_events", [])
            if related in by_id and _kind(by_id[related]) == "Shot"
        ),
        None,
    )
    if shot is not None:
        # A coordenada do chute está no sentido de ataque de quem finalizou, então a
        # grande área de referência é a "atacada" — que é a área defendida pelo goleiro.
        shot_location = _location(shot)
        shot_outcome = sb.SHOT_OUTCOME.get(_name(shot["shot"].get("outcome")) or "")
        row.update(
            shot_ref=shot["id"],
            shot_distance_m=distance_to_goal_m(*shot_location) if shot_location else None,
            shot_from_outside_box=bool(shot_location and not in_penalty_area(*shot_location)),
            shot_goal_mouth_zone=shot_goal_zone(shot["shot"], shot_outcome),
            shot_xg=shot["shot"].get("statsbomb_xg"),
        )
    return row


def disciplinary_row(event: RawEvent, vocab: Vocabulary) -> Row | None:
    """Falta cometida, falta sofrida ou cartão por comportamento. Outros eventos: `None`."""
    kind = _kind(event)
    if kind not in ("Foul Committed", "Foul Won", "Bad Behaviour"):
        return None

    foul_committed = event.get("foul_committed") or {}
    foul_won = event.get("foul_won") or {}
    raw_card = foul_committed.get("card") or (event.get("bad_behaviour") or {}).get("card")
    if kind == "Bad Behaviour" and raw_card is None:
        return None

    location = _location(event)
    return {
        "event_ref": event["id"],
        "player_ref": _ref(event.get("player")),
        "is_foul_committed": kind == "Foul Committed",
        "is_foul_won": kind == "Foul Won",
        "card": vocab.lookup(sb.CARD, raw_card, field_name="card", unknown=CardType.UNKNOWN),
        "foul_type": _name(foul_committed.get("type")),
        "in_own_half": location[0] < PITCH_LENGTH / 2 if location else None,
        "near_own_penalty_area": near_own_penalty_area(*location) if location else None,
        "conceded_penalty": bool(foul_committed.get("penalty")),
        "won_penalty": bool(foul_won.get("penalty")),
    }
