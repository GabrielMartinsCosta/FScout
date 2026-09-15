"""Testes dos encadeamentos: pré-assistência e consequência do drible."""

from __future__ import annotations

from typing import Any

from fscout.ingestion.statsbomb.chains import find_pre_assists, resolve_dribble_consequences


def _event(
    index: int,
    kind: str,
    *,
    player: int,
    team: int = 1,
    possession: int = 1,
    seconds: float = 0.0,
    period: int = 1,
    **payload: Any,
) -> dict[str, Any]:
    minutes, rest = divmod(seconds, 60)
    return {
        "id": f"e{index}",
        "index": index,
        "type": {"name": kind},
        "player": {"id": player},
        "team": {"id": team},
        "possession": possession,
        "period": period,
        "timestamp": f"00:{int(minutes):02d}:{rest:06.3f}",
        **payload,
    }


def _pass(recipient: int, **flags: Any) -> dict[str, Any]:
    return {"pass": {"recipient": {"id": recipient}, **flags}}


GOAL = {"shot": {"outcome": {"name": "Goal"}}}
SAVED = {"shot": {"outcome": {"name": "Saved"}}}

# ----------------------------------------------------------------------------------------
# Pré-assistência
# ----------------------------------------------------------------------------------------


def test_pre_assistencia_e_o_passe_para_quem_assistiu() -> None:
    events = [
        _event(1, "Pass", player=7, **_pass(8)),
        _event(2, "Carry", player=8),
        _event(3, "Pass", player=8, **_pass(9, goal_assist=True)),
        _event(4, "Shot", player=9, **GOAL),
    ]
    assert find_pre_assists(events) == {"e1"}


def test_sem_pre_assistencia_quando_o_ultimo_passe_foi_para_outro() -> None:
    """O assistente recuperou a bola sozinho: o passe anterior da equipe não foi para ele."""
    events = [
        _event(1, "Pass", player=7, **_pass(5)),
        _event(2, "Ball Recovery", player=8),
        _event(3, "Pass", player=8, **_pass(9, goal_assist=True)),
    ]
    assert find_pre_assists(events) == frozenset()


def test_passe_incompleto_nao_e_pre_assistencia() -> None:
    events = [
        _event(1, "Pass", player=7, **_pass(8, outcome={"name": "Out"})),
        _event(2, "Pass", player=8, **_pass(9, goal_assist=True)),
    ]
    assert find_pre_assists(events) == frozenset()


def test_pre_assistencia_nao_atravessa_posses() -> None:
    events = [
        _event(1, "Pass", player=7, possession=1, **_pass(8)),
        _event(2, "Pass", player=8, possession=2, **_pass(9, goal_assist=True)),
    ]
    assert find_pre_assists(events) == frozenset()


# ----------------------------------------------------------------------------------------
# Consequência do drible
# ----------------------------------------------------------------------------------------


def test_drible_passe_e_gol_de_companheiro() -> None:
    events = [
        _event(1, "Dribble", player=10, seconds=0),
        _event(2, "Pass", player=10, seconds=2, **_pass(11, goal_assist=True)),
        _event(3, "Shot", player=11, seconds=3, **GOAL),
    ]
    result = resolve_dribble_consequences(events, frozenset())["e1"]

    assert result.led_to_shot
    assert result.led_to_goal
    assert result.led_to_key_pass
    assert result.led_to_assist
    assert not result.drew_foul


def test_drible_chute_rebote_e_gol() -> None:
    """A mesma posse continua depois da defesa, e o gol no rebote conta."""
    events = [
        _event(1, "Dribble", player=10, seconds=0),
        _event(2, "Shot", player=10, seconds=2, **SAVED),
        _event(3, "Goal Keeper", player=99, team=2, seconds=2.5),
        _event(4, "Shot", player=12, seconds=4, **GOAL),
    ]
    result = resolve_dribble_consequences(events, frozenset())["e1"]
    assert result.led_to_shot
    assert result.led_to_goal


def test_chute_fora_da_janela_nao_conta() -> None:
    events = [
        _event(1, "Dribble", player=10, seconds=0),
        _event(2, "Shot", player=10, seconds=12, **GOAL),
    ]
    result = resolve_dribble_consequences(events, frozenset())["e1"]
    assert not result.led_to_shot
    assert not result.led_to_goal


def test_chute_do_adversario_ou_em_outra_posse_nao_conta() -> None:
    events = [
        _event(1, "Dribble", player=10, possession=1, seconds=0),
        _event(2, "Shot", player=50, team=2, possession=2, seconds=3, **GOAL),
        _event(3, "Shot", player=11, possession=3, seconds=6, **GOAL),
    ]
    result = resolve_dribble_consequences(events, frozenset())["e1"]
    assert not result.led_to_shot


def test_passe_decisivo_de_outro_jogador_nao_e_do_driblador() -> None:
    events = [
        _event(1, "Dribble", player=10, seconds=0),
        _event(2, "Pass", player=10, seconds=1, **_pass(11)),
        _event(3, "Pass", player=11, seconds=2, **_pass(12, goal_assist=True)),
        _event(4, "Shot", player=12, seconds=3, **GOAL),
    ]
    result = resolve_dribble_consequences(events, frozenset({"e2"}))["e1"]

    assert result.led_to_goal
    assert result.led_to_pre_assist
    assert not result.led_to_assist
    assert not result.led_to_key_pass


def test_falta_sofrida_logo_apos_o_drible() -> None:
    """A falta encerra a posse, mas ainda é consequência do drible."""
    events = [
        _event(1, "Dribble", player=10, possession=1, seconds=0),
        _event(2, "Foul Committed", player=50, team=2, possession=2, seconds=1),
        _event(3, "Foul Won", player=10, possession=2, seconds=1),
    ]
    assert resolve_dribble_consequences(events, frozenset())["e1"].drew_foul


def test_falta_muito_depois_do_drible_nao_conta() -> None:
    events = [
        _event(1, "Dribble", player=10, seconds=0),
        _event(2, "Foul Won", player=10, seconds=5),
    ]
    assert not resolve_dribble_consequences(events, frozenset())["e1"].drew_foul
