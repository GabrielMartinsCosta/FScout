"""Testes da formatação, dos tokens de cor e da montagem dos recortes.

O teste central deste arquivo é o de que a tela exibe **o mesmo número sobre o qual o
percentil foi calculado**. O motor ranqueia pelo valor por 90 minutos quando a métrica
admite normalização e pelo bruto quando não admite; se a tela escolhesse por conta
própria, apareceria "12 gols" ao lado de "percentil 84" com o 84 se referindo a outra
coisa. É o tipo de erro que nunca levanta exceção e sobrevive até a defesa.
"""

from __future__ import annotations

from typing import Any

import pytest

from fscout.ui.components import filters
from fscout.ui.format import (
    TRACO,
    formatar_percentil,
    formatar_valor,
    motivo_da_ausencia,
    numero_exibido,
    quebrar,
    rotulo,
    usou_por_90,
)
from fscout.ui.pages.comparar import ROTULO_BASE, montar_recortes
from fscout.ui.theme import DARK, LIGHT, com_alfa, tokens

CONTAGEM = {"key": "gols", "label": "Gols", "unit": "count", "per_90": True, "min_sample": 0}
RAZAO = {
    "key": "aprov",
    "label": "Aproveitamento de passes",
    "unit": "percent",
    "per_90": False,
    "min_sample": 20,
}


# ----------------------------------------------------------------------------------------
# A regra que precisa espelhar o motor
# ----------------------------------------------------------------------------------------


def test_metrica_normalizavel_exibe_o_valor_por_90() -> None:
    """É sobre o por 90 que o motor calcula o percentil de uma métrica com `per_90`."""
    medida = {"value": 5.0, "per_90": 2.24, "percentile": 97.2}
    assert usou_por_90(CONTAGEM, medida)
    assert numero_exibido(CONTAGEM, medida) == 2.24


def test_metrica_normalizavel_sem_por_90_cai_no_bruto() -> None:
    """Sem minutagem não há por 90, e o motor ranqueia pelo bruto. A tela segue junto."""
    medida = {"value": 5.0, "per_90": None, "percentile": 80.0}
    assert not usou_por_90(CONTAGEM, medida)
    assert numero_exibido(CONTAGEM, medida) == 5.0


def test_razao_nunca_se_normaliza_por_90() -> None:
    """Aproveitamento por 90 minutos não significa nada; o motor proíbe a combinação."""
    medida = {"value": 0.87, "per_90": None, "percentile": 60.0}
    assert not usou_por_90(RAZAO, medida)
    assert numero_exibido(RAZAO, medida) == 0.87


def test_rotulo_avisa_quando_o_numero_esta_normalizado() -> None:
    """Sem o aviso, "0,60 gols" parece erro de quem lê."""
    assert "por 90" in rotulo(CONTAGEM, {"value": 5.0, "per_90": 0.6})
    assert "por 90" not in rotulo(CONTAGEM, {"value": 5.0, "per_90": None})


# ----------------------------------------------------------------------------------------
# Unidades
# ----------------------------------------------------------------------------------------


def test_razao_sai_como_porcentagem() -> None:
    """O motor devolve fração de 0 a 1; quem lê espera por cento."""
    assert formatar_valor(RAZAO, {"value": 0.8734, "per_90": None}) == "87,3%"


def test_contagem_bruta_sai_inteira() -> None:
    assert formatar_valor(CONTAGEM, {"value": 12.0, "per_90": None}) == "12"


def test_contagem_por_90_sai_fracionada() -> None:
    assert formatar_valor(CONTAGEM, {"value": 5.0, "per_90": 2.2388}) == "2,24"


def test_milhar_usa_separador_brasileiro() -> None:
    minutos = {"key": "m", "label": "Minutos", "unit": "minutes", "per_90": False}
    assert formatar_valor(minutos, {"value": 4136.0, "per_90": None}) == "4.136 min"


# ----------------------------------------------------------------------------------------
# Ausência: diferente de zero, e com motivo
# ----------------------------------------------------------------------------------------


def test_valor_ausente_vira_travessao_e_nao_zero() -> None:
    assert formatar_valor(RAZAO, {"value": None, "per_90": None}) == TRACO


def test_motivo_da_ausencia_cita_a_amostra_minima() -> None:
    """100% de aproveitamento em um duelo não é informação — e a tela diz por quê."""
    motivo = motivo_da_ausencia(RAZAO, {"value": None, "per_90": None, "sample": 3})
    assert "3" in motivo and "20" in motivo


def test_percentil_traz_a_populacao_que_o_gerou() -> None:
    """Percentil 90 entre dez e entre duzentos são afirmações de forças diferentes."""
    assert formatar_percentil({"percentile": 88.0, "population": 36}) == "88º entre 36"


def test_percentil_ausente_vira_travessao() -> None:
    assert formatar_percentil({"percentile": None, "population": 0}) == TRACO


def test_rotulo_longo_quebra_em_linhas_em_vez_de_ser_cortado() -> None:
    """Rótulo cortado é pior que ausente: o leitor não sabe o que está faltando."""
    assert "<br>" in quebrar("Aproveitamento de passes longos", largura=12)


# ----------------------------------------------------------------------------------------
# Tokens de cor
# ----------------------------------------------------------------------------------------


def test_nono_slot_e_recusado() -> None:
    """Um matiz gerado é indistinguível de algum já em uso sob daltonismo."""
    with pytest.raises(IndexError, match="outros"):
        LIGHT.serie(8)


def test_os_dois_modos_tem_oito_slots() -> None:
    assert len(LIGHT.series) == len(DARK.series) == 8


def test_modo_escuro_nao_e_inversao_do_claro() -> None:
    """São degraus próprios, escolhidos e verificados para a superfície escura."""
    assert LIGHT.series[0] != DARK.series[0]
    assert LIGHT.surface != DARK.surface


def test_modo_desconhecido_cai_no_claro() -> None:
    assert tokens("roxo") is LIGHT


def test_preenchimento_de_area_e_lavagem_e_nao_bloco() -> None:
    assert com_alfa("#2a78d6", 0.10) == "rgba(42,120,214,0.1)"


# ----------------------------------------------------------------------------------------
# Recortes
# ----------------------------------------------------------------------------------------


def test_campo_vazio_nao_vira_filtro() -> None:
    """Ausência e "tudo" são a mesma coisa para o `Slice`."""
    assert filters.montar_recorte() == {}
    assert filters.montar_recorte(competition_ids=[], season_ids=None) == {}


def test_mando_todos_nao_restringe() -> None:
    assert "home_away" not in filters.montar_recorte(home_away="todos")
    assert filters.montar_recorte(home_away="home")["home_away"] == "home"


def test_recorte_reune_os_campos_preenchidos() -> None:
    recorte = filters.montar_recorte(competition_ids=[1], date_from="2024-06-20", min_minutes=270)
    assert recorte == {
        "competition_ids": [1],
        "date_from": "2024-06-20",
        "min_minutes": 270,
    }


def test_sem_segunda_janela_ha_um_recorte_so() -> None:
    recortes = montar_recortes({"competition_ids": [1]}, None, None)
    assert len(recortes) == 1
    assert recortes[0]["label"] == ROTULO_BASE


def test_segundo_recorte_herda_tudo_e_troca_so_as_datas() -> None:
    """É o que isola o período: comparar 2024 com 2025 sem mudar mais nada junto."""
    base: dict[str, Any] = {"competition_ids": [1], "min_minutes": 90}
    primeiro, segundo = montar_recortes(base, "2024-06-20", "2024-06-30")
    assert segundo["competition_ids"] == [1]
    assert segundo["min_minutes"] == 90
    assert segundo["date_from"] == "2024-06-20"
    assert segundo["date_to"] == "2024-06-30"
    assert "date_from" not in primeiro


def test_montar_recortes_nao_altera_o_recorte_recebido() -> None:
    """Efeito colateral aqui contaminaria o recorte guardado no armazém da tela."""
    base: dict[str, Any] = {"competition_ids": [1]}
    montar_recortes(base, "2024-06-20", "2024-06-30")
    assert base == {"competition_ids": [1]}
