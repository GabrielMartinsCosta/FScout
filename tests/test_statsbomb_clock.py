"""Testes da minutagem.

Os relógios usados são os reais da final da Copa do Mundo de 2022, que teve acréscimos
longos e prorrogação — o pior caso para quem calcula minutos subtraindo relógios.
"""

from __future__ import annotations

from typing import Any

import pytest

from fscout.ingestion.statsbomb.clock import (
    PeriodClock,
    clock_to_seconds,
    nominal_minutes,
    period_clocks,
    time_on_pitch,
    timestamp_seconds,
)


def _s(clock: str) -> int:
    return clock_to_seconds(clock)


FINAL_CLOCKS = {
    1: PeriodClock(1, _s("00:00"), _s("52:34")),
    2: PeriodClock(2, _s("45:00"), _s("98:37")),
    3: PeriodClock(3, _s("90:00"), _s("106:04")),
    4: PeriodClock(4, _s("105:00"), _s("124:07")),
    5: PeriodClock(5, _s("120:00"), _s("125:58")),
}


def _position(
    start: str,
    start_period: int,
    end: str | None,
    end_period: int | None,
    position: str = "Center Forward",
) -> dict[str, Any]:
    return {
        "position": position,
        "from": start,
        "from_period": start_period,
        "to": end,
        "to_period": end_period,
    }


def test_conversao_de_relogios() -> None:
    assert clock_to_seconds("41:01") == 2461
    assert clock_to_seconds("124:07") == 7447
    assert timestamp_seconds("00:52:34.569") == pytest.approx(3154.569)


def test_titular_do_jogo_inteiro_com_prorrogacao() -> None:
    time = time_on_pitch([_position("00:00", 1, None, None)], FINAL_CLOCKS)

    assert time.nominal_s == 120 * 60
    assert nominal_minutes(time) == 120
    esperado_efetivo = (
        _s("52:34")
        + (_s("98:37") - _s("45:00"))
        + (_s("106:04") - _s("90:00"))
        + (_s("124:07") - _s("105:00"))
    )
    assert time.actual_s == esperado_efetivo


def test_intervalo_que_atravessa_o_fim_do_primeiro_tempo() -> None:
    """Entrou aos 41:01 do 1º tempo e saiu aos 64:09 do 2º.

    A subtração direta dos relógios (23:08) perde os 7:34 de acréscimo do 1º tempo,
    porque o 2º tempo recomeça em 45:00.
    """
    time = time_on_pitch([_position("41:01", 1, "64:09", 2)], FINAL_CLOCKS)

    assert time.nominal_s == (_s("45:00") - _s("41:01")) + (_s("64:09") - _s("45:00"))
    assert time.actual_s == (_s("52:34") - _s("41:01")) + (_s("64:09") - _s("45:00"))
    assert time.actual_s - (_s("64:09") - _s("41:01")) == _s("07:34")


def test_trocas_de_posicao_nao_alteram_o_total() -> None:
    fracionado = [
        _position("41:01", 1, "41:20", 1, "Center Forward"),
        _position("41:20", 1, "64:09", 2, "Left Wing"),
        _position("64:09", 2, None, None, "Left Midfield"),
    ]
    inteiro = [_position("41:01", 1, None, None)]

    a = time_on_pitch(fracionado, FINAL_CLOCKS)
    b = time_on_pitch(inteiro, FINAL_CLOCKS)

    assert (a.nominal_s, a.actual_s) == (b.nominal_s, b.actual_s)
    assert sum(a.by_position_s.values()) == a.actual_s
    assert max(a.by_position_s, key=lambda name: a.by_position_s[name]) == "Left Midfield"


def test_disputa_de_penaltis_nao_soma_minutos() -> None:
    time = time_on_pitch([_position("120:00", 5, None, None)], FINAL_CLOCKS)
    assert time.actual_s == 0
    assert nominal_minutes(time) == 0


def test_quem_entra_nos_acrescimos_conta_um_minuto() -> None:
    clocks = {1: PeriodClock(1, 0, _s("46:00")), 2: PeriodClock(2, _s("45:00"), _s("95:00"))}
    time = time_on_pitch([_position("92:00", 2, None, None)], clocks)

    assert time.nominal_s == 0
    assert time.actual_s == 180
    assert nominal_minutes(time) == 1


def test_relogio_dos_periodos_lido_dos_eventos() -> None:
    def event(kind: str, period: int, minute: int, second: int) -> dict[str, Any]:
        return {"type": {"name": kind}, "period": period, "minute": minute, "second": second}

    events = [
        event("Half Start", 1, 0, 0),
        event("Pass", 1, 30, 0),
        event("Half End", 1, 47, 12),
        event("Half Start", 2, 45, 0),
        event("Pass", 2, 93, 59),  # 2º tempo sem Half End: usa o último evento
    ]
    clocks = period_clocks(events)

    assert clocks[1] == PeriodClock(1, 0, _s("47:12"))
    assert clocks[2] == PeriodClock(2, _s("45:00"), _s("93:59"))


# ----------------------------------------------------------------------------------------
# Escalações inconsistentes, reproduzidas da própria final de 2022
# ----------------------------------------------------------------------------------------


def _ending(position: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**position, "end_reason": reason}


def test_intervalo_invertido_da_fonte_e_descartado() -> None:
    """Messi: um intervalo vai do 115:32 do 4º período ao 28:11 do 1º."""
    positions = [
        _ending(_position("00:00", 1, "115:32", 4, "Right Wing"), "Tactical Shift"),
        _ending(_position("115:32", 4, "28:11", 1, "Right Center Forward"), "Player Off"),
        _ending(_position("28:19", 1, None, None, "Right Wing"), "Final Whistle"),
    ]
    time = time_on_pitch(positions, FINAL_CLOCKS)

    assert nominal_minutes(time) == 120
    assert time.exited_clock_s is None


def test_intervalos_sobrepostos_sao_unidos_e_cortados_na_substituicao() -> None:
    """Koundé: um intervalo fecha na substituição aos 120:35, outro fica aberto desde 41:20."""
    positions = [
        _ending(_position("00:00", 1, "120:35", 4, "Right Back"), "Substitution - Off (Tactical)"),
        _ending(_position("41:20", 1, None, None, "Right Back"), "Final Whistle"),
    ]
    time = time_on_pitch(positions, FINAL_CLOCKS)

    assert nominal_minutes(time) == 120
    esperado_efetivo = (
        _s("52:34")
        + (_s("98:37") - _s("45:00"))
        + (_s("106:04") - _s("90:00"))
        + (_s("120:35") - _s("105:00"))
    )
    assert time.actual_s == esperado_efetivo
    assert time.exited_clock_s == _s("120:35")


def test_entrada_registrada_para_quem_veio_do_banco() -> None:
    positions = [_ending(_position("64:09", 2, None, None), "Final Whistle")]
    time = time_on_pitch(positions, FINAL_CLOCKS)
    assert time.entered_clock_s == _s("64:09")
