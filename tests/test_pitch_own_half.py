"""Testes das zonas vistas do lado de quem defende."""

from __future__ import annotations

from fscout.domain.pitch import in_own_penalty_area, near_own_penalty_area


def test_propria_grande_area_fica_em_x_baixo() -> None:
    assert in_own_penalty_area(5.0, 40.0)
    assert in_own_penalty_area(18.0, 18.0)
    assert not in_own_penalty_area(18.1, 40.0)
    assert not in_own_penalty_area(110.0, 40.0)


def test_perto_da_propria_area_inclui_a_propria_area_e_a_margem() -> None:
    assert near_own_penalty_area(5.0, 40.0)
    assert near_own_penalty_area(29.0, 40.0)
    assert not near_own_penalty_area(30.0, 40.0)
    assert near_own_penalty_area(20.0, 7.0)
    assert not near_own_penalty_area(20.0, 6.0)
