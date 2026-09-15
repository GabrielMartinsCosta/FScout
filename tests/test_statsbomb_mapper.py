"""Testes do mapeamento StatsBomb para o schema.

O primeiro evento é copiado literalmente do arquivo da final da Copa de 2022: o pênalti
convertido por Messi aos 22 minutos.
"""

from __future__ import annotations

from typing import Any

import pytest

from fscout.domain.enums import (
    BodyPart,
    CardType,
    CompetitionType,
    DefensiveActionType,
    GoalkeeperActionType,
    PassOutcome,
    PassType,
    ShotOutcome,
    ShotType,
)
from fscout.domain.pitch import GoalMouthZone
from fscout.ingestion.statsbomb.mapper import (
    competition_type,
    defensive_rows,
    disciplinary_row,
    goal_check,
    goalkeeper_row,
    is_neutral_venue,
    pass_row,
    season_source_id,
    shot_row,
)
from fscout.ingestion.statsbomb.vocab import Vocabulary

MESSI_PENALTY: dict[str, Any] = {
    "id": "6d527ebc-a948-4cd8-ac82-daced35bb715",
    "index": 771,
    "period": 1,
    "timestamp": "00:22:24.114",
    "minute": 22,
    "second": 24,
    "type": {"id": 16, "name": "Shot"},
    "possession": 32,
    "possession_team": {"id": 779, "name": "Argentina"},
    "play_pattern": {"id": 5, "name": "Other"},
    "team": {"id": 779, "name": "Argentina"},
    "player": {"id": 5503, "name": "Lionel Andrés Messi Cuccittini"},
    "position": {"id": 17, "name": "Right Wing"},
    "location": [108.0, 40.0],
    "duration": 0.625635,
    "related_events": ["c9b8e568-dcdc-4302-9683-0e9e9a55a42a"],
    "shot": {
        "statsbomb_xg": 0.7835,
        "end_location": [120.0, 41.8, 0.2],
        "outcome": {"id": 97, "name": "Goal"},
        "technique": {"id": 93, "name": "Normal"},
        "body_part": {"id": 38, "name": "Left Foot"},
        "type": {"id": 88, "name": "Penalty"},
    },
}


def _event(kind: str, family: str | None = None, payload: Any = None, **extra: Any) -> dict:
    event = {
        "id": extra.pop("id", "ev"),
        "index": 1,
        "period": extra.pop("period", 1),
        "type": {"name": kind},
        "player": {"id": 1},
        "team": {"id": 1},
        **extra,
    }
    if family is not None:
        event[family] = payload
    return event


# ----------------------------------------------------------------------------------------
# Finalização
# ----------------------------------------------------------------------------------------


def test_penalti_do_messi() -> None:
    vocab = Vocabulary()
    row = shot_row(MESSI_PENALTY, vocab)

    assert row["shot_type"] is ShotType.PENALTY
    assert row["outcome"] is ShotOutcome.GOAL
    assert row["is_goal"] and row["is_on_target"]
    assert row["body_part"] is BodyPart.LEFT_FOOT
    assert row["in_penalty_area"] and not row["in_six_yard_box"]
    assert row["distance_m"] == pytest.approx(10.97, abs=0.02)
    # y=41.8 cai no terço direito do gol, visto por quem chuta; z=0.2 é rasteiro.
    assert row["goal_mouth_zone"] is GoalMouthZone.RIGHT_LOW
    assert row["xg"] == pytest.approx(0.7835)
    assert not row["is_shootout"]
    assert not vocab.misses


def test_off_t_da_statsbomb_e_chute_para_fora() -> None:
    """Chute por cima sem altura anotada: a coordenada cai entre as traves, mas foi para fora."""
    event = {**MESSI_PENALTY, "shot": {"outcome": {"name": "Off T"}, "end_location": [120, 40]}}
    row = shot_row(event, Vocabulary())
    assert row["outcome"] is ShotOutcome.OFF_TARGET
    assert row["goal_mouth_zone"] is GoalMouthZone.OFF_TARGET
    assert not row["is_on_target"]


def test_defesa_com_coordenada_ruidosa_fica_dentro_da_moldura() -> None:
    event = {
        **MESSI_PENALTY,
        "shot": {"outcome": {"name": "Saved"}, "end_location": [119.0, 35.8, 0.3]},
    }
    assert shot_row(event, Vocabulary())["goal_mouth_zone"] is GoalMouthZone.LEFT_LOW


def test_cobranca_na_disputa_de_penaltis_fica_marcada() -> None:
    row = shot_row({**MESSI_PENALTY, "period": 5}, Vocabulary())
    assert row["is_shootout"]


def test_valor_desconhecido_e_contabilizado() -> None:
    vocab = Vocabulary()
    event = {**MESSI_PENALTY, "shot": {**MESSI_PENALTY["shot"], "technique": {"name": "Rabona"}}}
    shot_row(event, vocab)
    assert vocab.misses[("shot.technique", "Rabona")] == 1


# ----------------------------------------------------------------------------------------
# Passe
# ----------------------------------------------------------------------------------------


def test_passe_sem_outcome_e_completo_e_sem_type_e_jogo_corrido() -> None:
    event = _event("Pass", "pass", {"recipient": {"id": 2}, "end_location": [70.0, 40.0]})
    event["location"] = [50.0, 40.0]
    row = pass_row(event, Vocabulary(), frozenset())

    assert row["is_complete"]
    assert row["outcome"] is PassOutcome.COMPLETE
    assert row["pass_type"] is PassType.OPEN_PLAY
    assert row["length_m"] == pytest.approx(20 * 0.9144)
    assert row["direction"] == "forward"
    assert row["is_progressive"]  # cruza o meio-campo ganhando ~18 m


# ----------------------------------------------------------------------------------------
# Defesa
# ----------------------------------------------------------------------------------------


def test_corte_de_cabeca_que_venceu_pelo_alto_gera_duas_linhas() -> None:
    event = _event("Clearance", "clearance", {"aerial_won": True, "head": True})
    event["location"] = [10.0, 40.0]
    rows = defensive_rows(event, Vocabulary())

    assert [row["action_type"] for row in rows] == [
        DefensiveActionType.CLEARANCE,
        DefensiveActionType.AERIAL_DUEL,
    ]
    assert rows[1]["is_successful"] and rows[1]["is_aerial"]
    assert rows[0]["in_own_penalty_area"]


def test_duelo_aereo_perdido() -> None:
    rows = defensive_rows(_event("Duel", "duel", {"type": {"name": "Aerial Lost"}}), Vocabulary())
    assert len(rows) == 1
    assert rows[0]["action_type"] is DefensiveActionType.AERIAL_DUEL
    assert rows[0]["is_successful"] is False


def test_desarme_com_sucesso_em_jogo() -> None:
    payload = {"type": {"name": "Tackle"}, "outcome": {"name": "Success In Play"}}
    rows = defensive_rows(_event("Duel", "duel", payload), Vocabulary())
    assert rows[0]["action_type"] is DefensiveActionType.TACKLE
    assert rows[0]["is_successful"] is True


def test_pressao_nao_tem_desfecho() -> None:
    rows = defensive_rows(_event("Pressure"), Vocabulary())
    assert rows[0]["is_successful"] is None


def test_evento_sem_acao_defensiva() -> None:
    assert defensive_rows(_event("Carry"), Vocabulary()) == []


# ----------------------------------------------------------------------------------------
# Goleiro e disciplina
# ----------------------------------------------------------------------------------------


def test_defesa_que_da_rebote_ligada_ao_chute_de_fora_da_area() -> None:
    shot = {
        **MESSI_PENALTY,
        "id": "chute",
        "location": [90.0, 40.0],
        "shot": {
            "outcome": {"name": "Saved"},
            "end_location": [120, 38, 2.5],
            "statsbomb_xg": 0.04,
        },
    }
    keeper = _event(
        "Goal Keeper",
        "goalkeeper",
        {"type": {"name": "Shot Saved"}, "outcome": {"name": "In Play Danger"}},
        related_events=["chute"],
    )
    row = goalkeeper_row(keeper, Vocabulary(), {"chute": shot})

    assert row["action_type"] is GoalkeeperActionType.SHOT_SAVED
    assert row["is_save"] and row["gave_rebound"]
    assert row["shot_ref"] == "chute"
    assert row["shot_from_outside_box"]
    assert row["shot_goal_mouth_zone"] is GoalMouthZone.LEFT_HIGH
    assert row["shot_xg"] == pytest.approx(0.04)


def test_cartao_por_comportamento_nao_tem_localizacao() -> None:
    event = _event("Bad Behaviour", "bad_behaviour", {"card": {"name": "Yellow Card"}})
    row = disciplinary_row(event, Vocabulary())
    assert row is not None
    assert row["card"] is CardType.YELLOW
    assert row["in_own_half"] is None


def test_falta_no_campo_de_ataque() -> None:
    event = _event("Foul Committed", "foul_committed", {"card": {"name": "Second Yellow"}})
    event["location"] = [100.0, 30.0]
    row = disciplinary_row(event, Vocabulary())
    assert row is not None
    assert row["in_own_half"] is False
    assert row["near_own_penalty_area"] is False
    assert row["card"] is CardType.SECOND_YELLOW


def test_eventos_sem_disciplina() -> None:
    assert disciplinary_row(_event("Pass", "pass", {}), Vocabulary()) is None
    assert disciplinary_row(_event("Bad Behaviour", "bad_behaviour", {}), Vocabulary()) is None


# ----------------------------------------------------------------------------------------
# Partida, competição e temporada
# ----------------------------------------------------------------------------------------


def _match(home_score: int = 1, away_score: int = 0) -> dict[str, Any]:
    return {
        "home_team": {"home_team_id": 1, "country": {"name": "Argentina"}},
        "away_team": {"away_team_id": 2, "country": {"name": "France"}},
        "home_score": home_score,
        "away_score": away_score,
        "stadium": {"name": "Lusail Stadium", "country": {"name": "Qatar"}},
    }


def test_conferencia_de_placar_ignora_disputa_de_penaltis_e_conta_gol_contra() -> None:
    goal = {"outcome": {"name": "Goal"}}
    events = [
        _event("Shot", "shot", goal, team={"id": 1}),
        _event("Own Goal For", team={"id": 1}),
        _event("Shot", "shot", goal, team={"id": 2}, period=5),
    ]
    check = goal_check(_match(2, 0), events)
    assert check.from_events == (2, 0)
    assert check.ok


def test_campo_neutro_quando_o_estadio_fica_fora_do_pais_do_mandante() -> None:
    assert is_neutral_venue(_match())
    local = _match()
    local["stadium"]["country"]["name"] = "Argentina"
    assert not is_neutral_venue(local)


@pytest.mark.parametrize(
    ("name", "international", "youth", "expected"),
    [
        ("Copa America", True, False, CompetitionType.INTERNATIONAL_NATIONAL_TEAM),
        ("FIFA World Cup", True, False, CompetitionType.INTERNATIONAL_NATIONAL_TEAM),
        ("La Liga", False, False, CompetitionType.NATIONAL_LEAGUE),
        ("Champions League", False, False, CompetitionType.CONTINENTAL_CLUB),
        ("Copa del Rey", False, False, CompetitionType.NATIONAL_CUP),
        ("FIFA U20 World Cup", True, True, CompetitionType.YOUTH),
    ],
)
def test_tipo_de_competicao(
    name: str, international: bool, youth: bool, expected: CompetitionType
) -> None:
    record = {
        "competition_name": name,
        "competition_international": international,
        "competition_youth": youth,
    }
    assert competition_type(record) is expected


def test_temporadas_com_mesmo_id_em_competicoes_diferentes_nao_colidem() -> None:
    """282 é Copa América 2024 (223) e Euro 2024 (55) na StatsBomb."""
    assert season_source_id(223, 282) != season_source_id(55, 282)
