"""Testes das regras internas do ligador do Transfermarkt, sem banco nem rede."""

from __future__ import annotations

from datetime import date

from fscout.ingestion.transfermarkt.linker import (
    MATCHED_BY_EXACT_NAME,
    _Candidates,
    _plausible_age,
    _propose_by_exact_name,
)
from fscout.linking.matching import PlayerRecord
from fscout.linking.names import compact

JOGO = date(2022, 11, 24)


def _candidates(*entries: tuple[str, str, date | None]) -> _Candidates:
    candidates = _Candidates()
    for key, name, birth in entries:
        record = PlayerRecord(key, (name,))
        candidates.records[key] = record
        candidates.birth_dates[key] = birth
        candidates.by_exact_name[compact(name)].add(key)
    return candidates


def test_nome_unico_no_dataset_liga_quem_nao_tem_pais() -> None:
    """Haris Seferovic e Atiba Hutchinson não têm cidadania registrada na fonte."""
    candidates = _candidates(
        ("109256", "Haris Seferovic", date(1992, 2, 22)),
        ("957139", "Tarik Seferovic", date(2006, 12, 31)),
    )
    proposal = _propose_by_exact_name(PlayerRecord("sb", ("Haris Seferović",)), JOGO, candidates)

    assert proposal is not None
    record, similarity, method = proposal
    assert (record.key, similarity, method) == ("109256", 1.0, MATCHED_BY_EXACT_NAME)


def test_homonimos_no_dataset_inteiro_nao_ligam() -> None:
    """Fabinho tem oito registros no Transfermarkt; nenhum pode ser escolhido pelo nome."""
    candidates = _candidates(
        ("1", "Fabinho", date(1993, 10, 23)),
        ("2", "Fabinho", date(1995, 5, 1)),
    )
    assert _propose_by_exact_name(PlayerRecord("sb", ("Fabinho",)), JOGO, candidates) is None


def test_nome_parecido_nao_basta_neste_nivel() -> None:
    """ "Daniel Olmo" (StatsBomb) e "Dani Olmo" (Transfermarkt) não são idênticos."""
    candidates = _candidates(("293385", "Dani Olmo", date(1998, 5, 7)))
    record = PlayerRecord("sb", ("Daniel Olmo", "Daniel Olmo Carvajal"))
    assert _propose_by_exact_name(record, JOGO, candidates) is None


def test_idade_implausivel_descarta_homonimo_de_outra_geracao() -> None:
    """O mesmo registro serve para uma partida e não serve para outra, 25 anos depois."""
    candidates = _candidates(("veterano", "Ali Karimi", date(1970, 11, 8)))
    record = PlayerRecord("sb", ("Ali Karimi",))

    assert _propose_by_exact_name(record, date(1998, 6, 10), candidates) is not None
    assert _propose_by_exact_name(record, date(2022, 11, 21), candidates) is None


def test_idade_plausivel() -> None:
    assert _plausible_age(date(1996, 5, 4), JOGO)
    assert _plausible_age(None, JOGO)  # sem data de nascimento, não descarta
    assert not _plausible_age(date(1960, 1, 1), JOGO)
    assert not _plausible_age(date(2015, 1, 1), JOGO)
