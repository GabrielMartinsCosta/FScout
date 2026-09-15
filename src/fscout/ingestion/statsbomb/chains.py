"""Encadeamentos dentro de uma posse de bola.

Algumas estatísticas pedidas não são atributo de um evento, e sim relação entre
eventos: a pré-assistência é o passe *para* quem deu a assistência; "drible que gerou
gol" liga um drible a uma finalização alguns toques depois. A StatsBomb não traz
nenhuma das duas pronta.

Resolver isso em tempo de consulta exigiria uma CTE recursiva por lance, inviável num
painel interativo. Aqui a relação é resolvida uma vez, na ingestão, percorrendo os
eventos em memória, e o resultado vira colunas booleanas nas projeções.

As definições operacionais adotadas estão nas docstrings e nas constantes abaixo, porque
são escolhas metodológicas que precisam aparecer no texto do TCC.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fscout.ingestion.statsbomb.clock import timestamp_seconds

# Janela entre o drible e a jogada que ele gerou. Dez segundos cobrem drible, condução,
# passe e finalização, mas não uma nova construção depois de a bola circular.
DRIBBLE_CONSEQUENCE_WINDOW_S = 10.0

# Falta sofrida conta como consequência do drible apenas se vier logo em seguida.
FOUL_AFTER_DRIBBLE_WINDOW_S = 3.0

Event = Mapping[str, Any]


@dataclass(frozen=True)
class DribbleConsequence:
    led_to_shot: bool = False
    led_to_goal: bool = False
    led_to_key_pass: bool = False
    led_to_assist: bool = False
    led_to_pre_assist: bool = False
    drew_foul: bool = False


def _kind(event: Event) -> str:
    return event["type"]["name"]


def _team_id(event: Event) -> int | None:
    return (event.get("team") or {}).get("id")


def _player_id(event: Event) -> int | None:
    return (event.get("player") or {}).get("id")


def _ordered(events: Sequence[Event]) -> list[Event]:
    return sorted(events, key=lambda event: event["index"])


def find_pre_assists(events: Sequence[Event]) -> frozenset[str]:
    """Identificadores dos passes de pré-assistência.

    Definição: o último passe da mesma equipe, na mesma posse, antes da assistência, desde
    que tenha sido completo e recebido por quem deu a assistência. Se o último passe da
    equipe foi para outro jogador — quem assistiu recuperou a bola sozinho, por exemplo —
    não há pré-assistência.
    """
    ordered = _ordered(events)
    found: set[str] = set()

    for position, event in enumerate(ordered):
        if _kind(event) != "Pass" or not event["pass"].get("goal_assist"):
            continue
        assister = _player_id(event)
        for previous in reversed(ordered[:position]):
            same_possession = previous["possession"] == event["possession"]
            if not same_possession or previous["period"] != event["period"]:
                break
            if _kind(previous) != "Pass" or _team_id(previous) != _team_id(event):
                continue
            previous_pass = previous["pass"]
            completed = "outcome" not in previous_pass
            recipient = (previous_pass.get("recipient") or {}).get("id")
            if completed and recipient == assister:
                found.add(previous["id"])
            break

    return frozenset(found)


def resolve_dribble_consequences(
    events: Sequence[Event],
    pre_assists: frozenset[str],
) -> dict[str, DribbleConsequence]:
    """Consequências de cada drible, indexadas pelo identificador do evento de drible.

    Definição: uma ação conta como consequência se for da mesma equipe, na mesma posse e
    ocorrer em até `DRIBBLE_CONSEQUENCE_WINDOW_S` segundos depois do drible. Chute e gol
    podem ser de qualquer companheiro, o que cobre "drible, passe, chute, rebote e gol".
    Passe decisivo, assistência e pré-assistência precisam ser do próprio driblador.

    Falta sofrida é a exceção: basta ser do próprio driblador em até
    `FOUL_AFTER_DRIBBLE_WINDOW_S` segundos, sem exigir a mesma posse.
    """
    ordered = _ordered(events)
    consequences: dict[str, DribbleConsequence] = {}

    for position, dribble in enumerate(ordered):
        if _kind(dribble) != "Dribble":
            continue
        start = timestamp_seconds(dribble["timestamp"])
        team, player = _team_id(dribble), _player_id(dribble)
        flags = dict.fromkeys(DribbleConsequence.__dataclass_fields__, False)

        for following in ordered[position + 1 :]:
            if following["period"] != dribble["period"]:
                break
            elapsed = timestamp_seconds(following["timestamp"]) - start
            if elapsed > DRIBBLE_CONSEQUENCE_WINDOW_S:
                break

            kind = _kind(following)
            if kind == "Foul Won" and _player_id(following) == player:
                flags["drew_foul"] |= elapsed <= FOUL_AFTER_DRIBBLE_WINDOW_S
            if following["possession"] != dribble["possession"] or _team_id(following) != team:
                continue

            if kind == "Shot":
                flags["led_to_shot"] = True
                if (following["shot"].get("outcome") or {}).get("name") == "Goal":
                    flags["led_to_goal"] = True
            elif kind == "Pass" and _player_id(following) == player:
                pass_ = following["pass"]
                if pass_.get("shot_assist") or pass_.get("goal_assist"):
                    flags["led_to_key_pass"] = True
                if pass_.get("goal_assist"):
                    flags["led_to_assist"] = True
                if following["id"] in pre_assists:
                    flags["led_to_pre_assist"] = True

        consequences[dribble["id"]] = DribbleConsequence(**flags)

    return consequences
