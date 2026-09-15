"""Relógio da partida e cálculo de minutagem.

Cada período da StatsBomb tem relógio próprio, que não zera: o 2º tempo começa em
45:00, a prorrogação em 90:00 e 105:00, a disputa de pênaltis em 120:00. Os acréscimos
fazem o relógio passar do fim nominal (o 1º tempo da final de 2022 terminou em 52:34) e
o período seguinte recomeça do valor nominal. Por isso subtrair "saída menos entrada"
diretamente dá errado sempre que o intervalo atravessa o fim de um tempo.

São produzidas duas medidas:

- **Minutagem nominal:** cada período limitado à duração regulamentar (45, 45, 15, 15).
  É a convenção de FBref, Transfermarkt e da imprensa, em que um jogo inteiro vale 90.
  É a base da normalização por 90 minutos, para que os números sejam comparáveis com
  fontes públicas.
- **Tempo efetivo em campo:** inclui os acréscimos. Mais fiel à exposição real do atleta.

A disputa de pênaltis (período 5) não conta em nenhuma das duas.

Dados sujos na escalação
------------------------
Os intervalos de posição da StatsBomb nem sempre são coerentes. Na própria final de 2022
há intervalo que termina antes de começar e intervalos sobrepostos para o mesmo atleta
(um fechado na substituição, outro aberto "até o apito final"). Somar intervalos conta o
mesmo tempo duas vezes — Messi apareceu com 207 minutos numa partida de 120. O cálculo
abaixo é robusto a isso:

1. intervalo invertido ou vazio é descartado;
2. os intervalos são **unidos** por período, não somados;
3. tudo é cortado na saída definitiva (substituição ou expulsão), porque atleta
   substituído não volta a campo. Saída temporária para atendimento ("Player Off") não
   conta como saída definitiva.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

REGULAR_PERIODS = (1, 2, 3, 4)
SHOOTOUT_PERIOD = 5

NOMINAL_START_S: Mapping[int, int] = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}
NOMINAL_END_S: Mapping[int, int] = {1: 45 * 60, 2: 90 * 60, 3: 105 * 60, 4: 120 * 60}

# Motivos de fim de intervalo que encerram a participação do atleta na partida.
FINAL_EXIT_REASONS = ("Substitution - Off", "Sent Off")

# Instante da partida: (período, relógio em segundos). A tupla ordena corretamente mesmo
# com o relógio recomeçando do nominal a cada período.
Moment = tuple[int, int]


@dataclass(frozen=True)
class PeriodClock:
    """Leitura do relógio no início e no fim efetivo de um período, em segundos."""

    period: int
    start_s: int
    end_s: int


@dataclass(frozen=True)
class TimeOnPitch:
    nominal_s: int
    actual_s: int
    by_position_s: Mapping[str, int]
    entered_clock_s: int | None = None
    exited_clock_s: int | None = None


def clock_to_seconds(clock: str) -> int:
    """Converte o relógio da escalação, `"mm:ss"`, em segundos. Minutos podem passar de 99."""
    minutes, seconds = clock.split(":")
    return int(minutes) * 60 + int(seconds)


def timestamp_seconds(timestamp: str) -> float:
    """Converte o timestamp de evento, `"hh:mm:ss.fff"` relativo ao início do período."""
    hours, minutes, seconds = timestamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def period_clocks(events: Iterable[Mapping[str, Any]]) -> dict[int, PeriodClock]:
    """Relógio de início e fim de cada período, lido dos eventos `Half Start` e `Half End`.

    Se um período não tiver `Half End` (falha de coleta), o fim é o último evento dele.
    """
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    latest: dict[int, int] = {}

    for event in events:
        period = event["period"]
        clock = event["minute"] * 60 + event["second"]
        latest[period] = max(latest.get(period, clock), clock)
        kind = event["type"]["name"]
        if kind == "Half Start":
            starts[period] = min(starts.get(period, clock), clock)
        elif kind == "Half End":
            ends[period] = max(ends.get(period, clock), clock)

    return {
        period: PeriodClock(
            period=period,
            start_s=starts.get(period, NOMINAL_START_S.get(period, 0)),
            end_s=ends.get(period, latest[period]),
        )
        for period in latest
    }


def time_on_pitch(
    positions: Sequence[Mapping[str, Any]],
    clocks: Mapping[int, PeriodClock],
) -> TimeOnPitch:
    """Tempo em campo a partir dos intervalos de posição da escalação.

    Cada intervalo é partido por período e recortado pelos limites do período. Os pedaços
    de um mesmo período são unidos antes de somar, o que neutraliza sobreposições da fonte.
    Um intervalo sem fim (`to` nulo) vai até o apito final do último período regular.
    """
    regular = [period for period in REGULAR_PERIODS if period in clocks]
    if not positions or not regular:
        return TimeOnPitch(nominal_s=0, actual_s=0, by_position_s={})

    last_period = max(regular)
    final_whistle: Moment = (last_period, clocks[last_period].end_s)
    final_exit = _final_exit(positions)
    limit = min(final_whistle, final_exit) if final_exit else final_whistle

    spans: dict[int, list[tuple[int, int]]] = defaultdict(list)
    by_position: dict[str, int] = defaultdict(int)
    entered: Moment | None = None

    for position in positions:
        start: Moment = (position["from_period"], clock_to_seconds(position["from"]))
        end: Moment = (
            final_whistle
            if position.get("to") is None
            else (position["to_period"], clock_to_seconds(position["to"]))
        )
        end = min(end, limit)
        if end <= start:
            continue

        for period in range(start[0], end[0] + 1):
            clock = clocks.get(period)
            if clock is None or period not in REGULAR_PERIODS:
                continue
            span_start = max(start[1] if period == start[0] else clock.start_s, clock.start_s)
            span_end = min(end[1] if period == end[0] else clock.end_s, clock.end_s)
            if span_end <= span_start:
                continue
            spans[period].append((span_start, span_end))
            by_position[position["position"]] += span_end - span_start
            entered = min(entered, (period, span_start)) if entered else (period, span_start)

    actual = nominal = 0
    for period, period_spans in spans.items():
        for span_start, span_end in _union(period_spans):
            actual += span_end - span_start
            nominal += _overlap(span_start, span_end, clocks[period].start_s, NOMINAL_END_S[period])

    return TimeOnPitch(
        nominal_s=nominal,
        actual_s=actual,
        by_position_s=dict(by_position),
        entered_clock_s=entered[1] if entered else None,
        exited_clock_s=final_exit[1] if final_exit and actual > 0 else None,
    )


def nominal_minutes(time: TimeOnPitch) -> int:
    """Minutos nominais arredondados.

    Quem entrou só nos acréscimos tem minutagem nominal zero, mas esteve em campo. Conta
    como 1 minuto, a mesma convenção das fontes públicas.
    """
    if time.actual_s <= 0:
        return 0
    return max(1, round(time.nominal_s / 60))


def _final_exit(positions: Sequence[Mapping[str, Any]]) -> Moment | None:
    exits = [
        (position["to_period"], clock_to_seconds(position["to"]))
        for position in positions
        if position.get("to") is not None
        and str(position.get("end_reason", "")).startswith(FINAL_EXIT_REASONS)
    ]
    return max(exits) if exits else None


def _union(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlap(start: int, end: int, lower: int, upper: int) -> int:
    return max(0, min(end, upper) - max(start, lower))
