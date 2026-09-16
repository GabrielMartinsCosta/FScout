"""Testes do porte do validador de paleta.

O porte existe porque esta máquina não tem Node e a regra manda **calcular** a segurança
da paleta para daltonismo, não estimá-la. Um porte que devolve números diferentes do
original é pior que nenhum: ele daria um aval falso.

Por isso as asserções não espelham a implementação — elas se ancoram nos valores
**publicados na referência da paleta**, que foram medidos com o script original em
JavaScript. Se alguém alterar a conversão de cor, a simulação de daltonismo ou a
definição de ΔE, estes testes apontam o desvio.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# O validador é um script de linha de comando, fora do pacote instalável: ele precisa
# rodar num clone recém-baixado, antes de qualquer instalação.
_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "validate_palette.py"
_spec = importlib.util.spec_from_file_location("validate_palette", _CAMINHO)
assert _spec and _spec.loader
validador = importlib.util.module_from_spec(_spec)
sys.modules["validate_palette"] = validador
_spec.loader.exec_module(validador)

CLARO = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
)  # fmt: skip
ESCURO = (
    "#3987e5", "#d95926", "#199e70", "#c98500",
    "#d55181", "#008300", "#9085e9", "#e66767",
)  # fmt: skip
SUPERFICIE_CLARA = "#fcfcfb"
SUPERFICIE_ESCURA = "#1a1a19"


# ----------------------------------------------------------------------------------------
# Fidelidade ao original, aferida contra os números publicados
# ----------------------------------------------------------------------------------------


def test_pior_par_adjacente_no_modo_claro() -> None:
    """A referência publica ΔE 9.1 sob protanopia entre amarelo e verde-água."""
    assert validador.delta_e("#eda100", "#1baf7a", "protan") == pytest.approx(9.1, abs=0.05)


def test_pior_par_adjacente_no_modo_escuro() -> None:
    """A referência publica ΔE 8.4 sob protanopia nos degraus escuros."""
    assert validador.delta_e("#c98500", "#199e70", "protan") == pytest.approx(8.4, abs=0.05)


def test_par_que_reprova_o_quarto_slot_em_todos_os_pares() -> None:
    """Amarelo e laranja ficam a ΔE 13.7 na visão normal — abaixo do piso de 15.

    É exatamente esse número que limita a três séries as formas em que qualquer marca
    pode encostar em qualquer outra (dispersão, bolha, radar).
    """
    assert validador.delta_e("#eda100", "#eb6834") == pytest.approx(13.7, abs=0.05)
    assert validador.delta_e("#eda100", "#eb6834") < validador.NORMAL_FLOOR


def test_contraste_publicado_das_cores_de_alivio() -> None:
    """Verde-água a 2.74:1 e amarelo a 2.11:1 contra a superfície clara."""
    assert validador.contrast("#1baf7a", SUPERFICIE_CLARA) == pytest.approx(2.74, abs=0.01)
    assert validador.contrast("#eda100", SUPERFICIE_CLARA) == pytest.approx(2.11, abs=0.01)


def test_contraste_do_degrau_mais_claro_da_rampa_ordinal() -> None:
    """O degrau 250 marca 2.06:1, o mínimo que a rampa ordinal admite no claro."""
    assert validador.contrast("#86b6ef", SUPERFICIE_CLARA) == pytest.approx(2.06, abs=0.01)


# ----------------------------------------------------------------------------------------
# As checagens, no conjunto
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("paleta", "modo", "superficie"),
    [(CLARO, "light", SUPERFICIE_CLARA), (ESCURO, "dark", SUPERFICIE_ESCURA)],
)
def test_os_oito_slots_passam_na_lista_adjacente(
    paleta: tuple[str, ...], modo: str, superficie: str
) -> None:
    """Barras, linhas e pilhas comparam só vizinhos, e aí os oito slots servem."""
    _, ok = validador.validate(paleta, mode=modo, surface=superficie, pairs="adjacent")
    assert ok


@pytest.mark.parametrize(
    ("paleta", "modo", "superficie"),
    [(CLARO, "light", SUPERFICIE_CLARA), (ESCURO, "dark", SUPERFICIE_ESCURA)],
)
def test_tres_slots_passam_com_todos_os_pares(
    paleta: tuple[str, ...], modo: str, superficie: str
) -> None:
    """O teto de três séries do FScout é medido, e é este o teste que o mede."""
    _, ok = validador.validate(paleta[:3], mode=modo, surface=superficie, pairs="all")
    assert ok


def test_o_quarto_slot_reprova_com_todos_os_pares() -> None:
    """Sentinela do teto: se algum dia passar, a regra das três séries mudou."""
    relatorio, ok = validador.validate(
        CLARO[:4], mode="light", surface=SUPERFICIE_CLARA, pairs="all"
    )
    assert not ok
    estados = {nome: estado for nome, estado, _ in relatorio}
    assert estados["Normal-vision floor"] == "fail"


def test_luminosidade_dentro_da_faixa_do_modo() -> None:
    """Fora da faixa, a cor deixa de funcionar como marca sobre aquela superfície."""
    minimo, maximo = validador.BAND["light"]
    assert all(minimo <= validador.oklch(cor)[0] <= maximo for cor in CLARO)


def test_rampa_sequencial_e_de_um_matiz_so() -> None:
    """Magnitude pede um matiz do claro ao escuro; salto de matiz viraria arco-íris."""
    _, ok = validador.validate_ordinal(
        ["#86b6ef", "#5598e7", "#256abf", "#104281"], mode="light", surface=SUPERFICIE_CLARA
    )
    assert ok


def test_rampa_fora_de_ordem_reprova() -> None:
    """Rampa não monotônica mente sobre a magnitude que representa."""
    _, ok = validador.validate_ordinal(
        ["#256abf", "#86b6ef", "#104281"], mode="light", surface=SUPERFICIE_CLARA
    )
    assert not ok


# ----------------------------------------------------------------------------------------
# Fronteira de entrada: sem ela a validação falharia ABERTA
# ----------------------------------------------------------------------------------------


def test_hexadecimal_invalido_e_recusado() -> None:
    """Sem a checagem, o valor vira NaN e todas as comparações passam por engano."""
    assert not validador.is_hex_color("#12345")
    assert not validador.is_hex_color("azul")
    assert validador.is_hex_color("#2a78d6")
    assert validador.is_hex_color("2a78d6")


def test_espacos_unicode_sao_removidos() -> None:
    """Colar uma lista de cores de uma página traz espaços que não são o espaço comum."""
    assert validador.split_colors(" #2a78d6 , #eb6834　") == ["#2a78d6", "#eb6834"]


def test_linha_de_comando_recusa_entrada_invalida() -> None:
    """Código 2 é erro de uso — distinto de 1, que é paleta reprovada."""
    assert validador.main(["#2a78d6,#naoehcor"]) == 2


def test_linha_de_comando_reprova_paleta_ruim() -> None:
    assert validador.main([",".join(CLARO[:4]), "--pairs", "all"]) == 1


def test_linha_de_comando_aprova_paleta_boa() -> None:
    assert validador.main([",".join(CLARO[:3]), "--pairs", "all"]) == 0


# ----------------------------------------------------------------------------------------
# Propriedades da métrica de cor
# ----------------------------------------------------------------------------------------


def test_distancia_de_cor_para_si_mesma_e_zero() -> None:
    assert validador.delta_e("#2a78d6", "#2a78d6") == pytest.approx(0.0, abs=1e-9)


def test_distancia_de_cor_e_simetrica() -> None:
    ida = validador.delta_e("#2a78d6", "#eb6834", "deutan")
    volta = validador.delta_e("#eb6834", "#2a78d6", "deutan")
    assert ida == pytest.approx(volta, abs=1e-9)


def test_daltonismo_aproxima_cores_que_a_visao_normal_separa() -> None:
    """Verde e vermelho é o par clássico: sob deuteranopia a distância despenca."""
    normal = validador.delta_e("#008300", "#e34948")
    simulado = validador.delta_e("#008300", "#e34948", "deutan")
    assert simulado < normal
