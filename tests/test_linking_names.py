"""Testes da comparação de nomes, com pares reais de StatsBomb e Transfermarkt."""

from __future__ import annotations

import pytest

from fscout.linking.names import best_similarity, compact, name_similarity, normalize, tokens


def test_normalizacao_remove_acentos_e_letras_sem_decomposicao() -> None:
    assert normalize("Ángel Fabián Di María") == "angel fabian di maria"
    assert normalize("Martin Ødegaard") == "martin odegaard"
    assert normalize("Kylian Mbappé-Lottin") == "kylian mbappe lottin"
    assert normalize("  N'Golo   Kanté ") == "n golo kante"


def test_particulas_sao_ignoradas() -> None:
    assert tokens("Giorgian De Arrascaeta") == ("giorgian", "arrascaeta")
    assert compact("Alexis Mac Allister") == compact("Alexis MacAllister")


@pytest.mark.parametrize(
    ("statsbomb", "transfermarkt"),
    [
        ("Lionel Andrés Messi Cuccittini", "Lionel Messi"),
        ("Alexis MacAllister", "Alexis Mac Allister"),
        ("Enzo Fernandez", "Enzo Fernández"),
        ("Telasco José Segovia Pérez", "Telasco Segovia"),
        ("Giorgian De Arrascaeta", "Giorgian de Arrascaeta"),
        ("Raphinha", "Raphinha"),
    ],
)
def test_pares_reais_correspondem_completamente(statsbomb: str, transfermarkt: str) -> None:
    assert name_similarity(statsbomb, transfermarkt) == 1.0


def test_homonimo_parcial_fica_bem_abaixo_do_nome_certo() -> None:
    """Lautaro e Lisandro Martínez jogaram juntos pela Argentina na Copa América 2024."""
    correto = name_similarity("Lautaro Javier Martínez", "Lautaro Martínez")
    homonimo = name_similarity("Lautaro Javier Martínez", "Lisandro Martínez")
    assert correto == 1.0
    assert correto - homonimo >= 0.2


def test_nome_de_uma_palavra_contido_em_outro_e_indicio_fraco() -> None:
    assert name_similarity("Gomes", "Tiago Gomes") == pytest.approx(0.8)
    assert name_similarity("Gomes", "Tiago Gomes") < name_similarity("Gomes", "Gomes")


def test_nomes_sem_relacao() -> None:
    assert name_similarity("Alisson Becker", "Lionel Messi") < 0.5


def test_nome_vazio() -> None:
    assert name_similarity("", "Lionel Messi") == 0.0
    assert name_similarity("de la", "Lionel Messi") == 0.0


def test_melhor_similaridade_entre_variantes() -> None:
    """Basta uma variante de cada lado corresponder; nulos são ignorados."""
    statsbomb = ["Gomes", "João Victor Gomes da Silva", None]
    transfermarkt = ["João Gomes", None]
    assert best_similarity(statsbomb, transfermarkt) == 1.0
    assert best_similarity([None], ["João Gomes"]) == 0.0


def test_ausencia_vinda_do_pandas_e_ignorada() -> None:
    """Valor ausente numa tabela chega como NaN, que é um float verdadeiro em Python."""
    assert best_similarity([float("nan"), "Raphinha"], ["Raphinha", float("nan")]) == 1.0
    assert best_similarity([float("nan")], ["Raphinha"]) == 0.0
