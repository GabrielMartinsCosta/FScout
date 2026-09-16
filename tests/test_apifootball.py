"""Testes da sondagem do API-Football.

A sondagem existe para uma decisão de escopo: escrever ou não o adaptador. O critério
dessa decisão precisa estar escrito e testado, e não ser impressão de quem olhou a saída
— é ele que justifica, no texto do TCC, ter feito ou não o último item da especificação.

Nada aqui toca a rede. O que se testa é o julgamento sobre um relatório já obtido.
"""

from __future__ import annotations

import pytest

from fscout.ingestion.apifootball import ChaveAusente, Sondagem, _cliente, vale_a_pena


def _relatorio(temporadas: list[int], lesoes: int | None = 12) -> Sondagem:
    return Sondagem(
        plano="Free",
        temporadas_do_brasileirao=temporadas,
        lesoes_encontradas=lesoes,
        temporada_testada=max(temporadas) if temporadas else None,
    )


def test_sem_temporada_nao_compensa() -> None:
    """Sem Brasileirão liberado, o item perde o objeto."""
    viavel, motivo = vale_a_pena(_relatorio([]))
    assert not viavel
    assert "nenhuma temporada" in motivo


def test_uma_temporada_so_nao_e_historico() -> None:
    """A especificação pede histórico de lesões; com um ano não há o que comparar."""
    viavel, motivo = vale_a_pena(_relatorio([2025]))
    assert not viavel
    assert "sem histórico" in motivo


def test_sem_lesoes_nao_compensa() -> None:
    """Temporada liberada mas endpoint vazio entrega metade do que o item prometia."""
    viavel, _ = vale_a_pena(_relatorio([2023, 2024, 2025], lesoes=0))
    assert not viavel


def test_varias_temporadas_com_lesoes_compensa() -> None:
    viavel, motivo = vale_a_pena(_relatorio([2023, 2024, 2025]))
    assert viavel
    assert "3 temporadas" in motivo


def test_limite_de_temporadas_e_ajustavel() -> None:
    """O critério é um parâmetro, não um número escondido no meio do código."""
    assert vale_a_pena(_relatorio([2024, 2025]), minimo_de_temporadas=2)[0]
    assert not vale_a_pena(_relatorio([2024, 2025]), minimo_de_temporadas=3)[0]


def test_sem_chave_a_mensagem_diz_o_que_fazer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: a chave é credencial pessoal e pode simplesmente não existir ainda."""
    from fscout import config

    monkeypatch.setattr(config.get_settings(), "api_football_key", "", raising=False)
    with pytest.raises(ChaveAusente, match="FSCOUT_API_FOOTBALL_KEY"):
        _cliente()
