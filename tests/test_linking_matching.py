"""Testes das regras de ligação entre fontes."""

from __future__ import annotations

from datetime import date

import pytest

from fscout.linking.countries import country_key
from fscout.linking.matching import (
    MatchRecord,
    PlayerLink,
    PlayerRecord,
    ResolvedLink,
    assign_players,
    best_candidate,
    enforce_one_to_one,
    link_matches,
    resolve_votes,
    team_words,
    teams_match,
)

# ----------------------------------------------------------------------------------------
# Países e equipes
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statsbomb", "transfermarkt"),
    [
        ("United States of America", "United States"),
        ("Venezuela\xa0(Bolivarian Republic)", "Venezuela"),
        ("Korea Republic", "Korea, South"),
        ("Bosnia and Herzegovina", "Bosnia-Herzegovina"),
        ("Iran, Islamic Republic of", "Iran"),
        ("Congo, (Kinshasa)", "DR Congo"),
        ("Macedonia, Republic of", "North Macedonia"),
        ("Brazil", "Brazil"),
    ],
)
def test_grafias_de_pais_com_mesma_chave(statsbomb: str, transfermarkt: str) -> None:
    assert country_key(statsbomb) == country_key(transfermarkt)


def test_siglas_de_clube_sao_ignoradas() -> None:
    assert team_words("FC Barcelona") == team_words("Barcelona")
    assert teams_match("Real Madrid CF", "Real Madrid")


def test_clubes_diferentes_nao_correspondem() -> None:
    assert not teams_match("Real Madrid", "Atlético Madrid")
    assert not teams_match("Barcelona", "Barcelona B")
    assert not teams_match("Brazil", "Argentina")


@pytest.mark.parametrize(
    ("statsbomb", "transfermarkt"),
    [
        ("Celta Vigo", "Celta de Vigo"),
        ("Atlético Madrid", "Atlético de Madrid"),
        ("Real Betis", "Real Betis Balompié"),
        ("Athletic Club", "Athletic Bilbao"),
        ("Levante UD", "Levante UD"),
    ],
)
def test_grafias_de_clubes_da_la_liga(statsbomb: str, transfermarkt: str) -> None:
    assert teams_match(statsbomb, transfermarkt)


# ----------------------------------------------------------------------------------------
# Partidas
# ----------------------------------------------------------------------------------------


def _match(key: str, day: int, home: str, away: str) -> MatchRecord:
    return MatchRecord(key, date(2024, 6, day), home, away)


def test_partida_com_data_e_equipes_iguais() -> None:
    links = link_matches(
        [_match("sb1", 25, "Brazil", "Costa Rica")],
        [_match("tm9", 25, "Uruguay", "Panama"), _match("tm1", 25, "Brazil", "Costa Rica")],
    )
    assert [(link.left_key, link.right_key, link.swapped) for link in links] == [
        ("sb1", "tm1", False)
    ]


def test_mando_invertido_e_data_vizinha_por_fuso() -> None:
    links = link_matches(
        [_match("sb1", 25, "United States of America", "Bolivia")],
        [_match("tm1", 24, "Bolivia", "United States")],
    )
    assert len(links) == 1
    assert links[0].swapped
    assert links[0].date_offset_days == 1


def test_data_exata_tem_prioridade_sobre_a_vizinha() -> None:
    links = link_matches(
        [_match("sb1", 25, "Brazil", "Colombia")],
        [
            _match("tm_vizinha", 24, "Brazil", "Colombia"),
            _match("tm_exata", 25, "Brazil", "Colombia"),
        ],
    )
    assert links[0].right_key == "tm_exata"


def test_partida_da_outra_fonte_nao_e_reutilizada() -> None:
    links = link_matches(
        [_match("sb1", 25, "Brazil", "Colombia"), _match("sb2", 25, "Brazil", "Colombia")],
        [_match("tm1", 25, "Brazil", "Colombia")],
    )
    assert len(links) == 1


# ----------------------------------------------------------------------------------------
# Atletas dentro da partida
# ----------------------------------------------------------------------------------------


def test_homonimos_da_argentina_separados_por_nome_e_camisa() -> None:
    ours = [
        PlayerRecord("sb_lautaro", ("Lautaro Martínez", "Lautaro Javier Martínez"), 22),
        PlayerRecord("sb_lisandro", ("Lisandro Martínez",), 25),
    ]
    theirs = [
        PlayerRecord("tm_lautaro", ("Lautaro Martínez",), 22),
        PlayerRecord("tm_lisandro", ("Lisandro Martínez",), 25),
        PlayerRecord("tm_emiliano", ("Emiliano Martínez",), 23),
    ]
    links, ambiguous = assign_players(ours, theirs)
    assert {(link.left_key, link.right_key) for link in links} == {
        ("sb_lautaro", "tm_lautaro"),
        ("sb_lisandro", "tm_lisandro"),
    }
    assert ambiguous == []


def test_camisa_confirma_nome_parcial() -> None:
    """ "Gomes" contra "João Gomes" não passa sozinho; com a mesma camisa, passa."""
    theirs = [PlayerRecord("tm_gomes", ("João Gomes",), 15)]

    sem_camisa, _ = assign_players([PlayerRecord("sb", ("Gomes",), None)], theirs)
    com_camisa, _ = assign_players([PlayerRecord("sb", ("Gomes",), 15)], theirs)

    assert sem_camisa == []
    assert [link.right_key for link in com_camisa] == ["tm_gomes"]
    assert com_camisa[0].same_jersey


def test_camisa_desempata_nomes_iguais() -> None:
    ours = [PlayerRecord("sb", ("Marquinhos",), 4)]
    theirs = [
        PlayerRecord("tm_psg", ("Marquinhos",), 4),
        PlayerRecord("tm_outro", ("Marquinhos",), 19),
    ]
    links, ambiguous = assign_players(ours, theirs)
    assert [link.right_key for link in links] == ["tm_psg"]
    assert ambiguous == []


def test_empate_sem_evidencia_extra_fica_ambiguo() -> None:
    ours = [PlayerRecord("sb", ("Lucas Silva",), None)]
    theirs = [PlayerRecord("tm1", ("Lucas Silva",), 5), PlayerRecord("tm2", ("Lucas Silva",), 8)]
    links, ambiguous = assign_players(ours, theirs)
    assert links == []
    assert ambiguous == ["sb"]


def test_registro_da_outra_fonte_nao_liga_dois_atletas() -> None:
    """Os dois são candidatos válidos ao mesmo registro; fica o de evidência mais forte."""
    ours = [PlayerRecord("sb1", ("Danilo",), 2), PlayerRecord("sb2", ("Danilo",), None)]
    theirs = [PlayerRecord("tm", ("Danilo",), 2)]
    links, ambiguous = assign_players(ours, theirs)
    assert [(link.left_key, link.right_key) for link in links] == [("sb1", "tm")]
    assert ambiguous == ["sb2"]


# ----------------------------------------------------------------------------------------
# Votação entre partidas
# ----------------------------------------------------------------------------------------


def _link(left: str, right: str, similarity: float = 1.0, jersey: bool = True) -> PlayerLink:
    return PlayerLink(left, right, similarity + (0.3 if jersey else 0.0), similarity, jersey)


def test_votacao_unanime_com_nome_exato_tem_confianca_maxima() -> None:
    resolved = resolve_votes([_link("sb", "tm") for _ in range(4)])
    assert resolved["sb"] == ResolvedLink("sb", "tm", 1.0, 4, 4)
    assert not resolved["sb"].conflicting


def test_votacao_dividida_reduz_confianca() -> None:
    resolved = resolve_votes(
        [_link("sb", "tm"), _link("sb", "tm"), _link("sb", "tm"), _link("sb", "x")]
    )
    assert resolved["sb"].right_key == "tm"
    assert resolved["sb"].confidence == pytest.approx(0.75)
    assert resolved["sb"].conflicting


def test_um_para_um_mantem_a_ligacao_mais_confiavel() -> None:
    resolved = {
        "sb1": ResolvedLink("sb1", "tm", 0.9, 3, 3),
        "sb2": ResolvedLink("sb2", "tm", 0.6, 1, 1),
    }
    assert set(enforce_one_to_one(resolved)) == {"sb1"}


# ----------------------------------------------------------------------------------------
# Reserva por nome
# ----------------------------------------------------------------------------------------


def test_reserva_exige_folga_sobre_o_segundo_candidato() -> None:
    player = PlayerRecord("sb", ("Lionel Andrés Messi Cuccittini",))
    unico = [PlayerRecord("tm_messi", ("Lionel Messi",)), PlayerRecord("tm_x", ("Lionel Scaloni",))]
    empate = [PlayerRecord("tm1", ("Lionel Messi",)), PlayerRecord("tm2", ("Lionel Messi",))]

    escolhido = best_candidate(player, unico)
    assert escolhido is not None and escolhido[0].key == "tm_messi"
    assert best_candidate(player, empate) is None
    assert best_candidate(player, []) is None


def test_nome_identico_unico_vence_grafia_vizinha() -> None:
    """Bastoni x Bastrini: 0,92 de similaridade por letras não derruba o nome exato."""
    player = PlayerRecord("sb", ("Alessandro Bastoni",))
    candidates = [
        PlayerRecord("tm_bastoni", ("Alessandro Bastoni",)),
        PlayerRecord("tm_bastrini", ("Alessandro Bastrini",)),
    ]
    escolhido = best_candidate(player, candidates)
    assert escolhido is not None and escolhido[0].key == "tm_bastoni"


def test_nome_identico_nao_se_confunde_com_contencao() -> None:
    """ "Alex da Silva" contém as palavras de "Alex Sandro Lobo Silva", mas é outro nome."""
    player = PlayerRecord("sb", ("Alex Sandro", "Alex Sandro Lobo Silva"))
    candidates = [
        PlayerRecord("tm_alex_sandro", ("Alex Sandro",)),
        PlayerRecord("tm_alex_da_silva", ("Alex da Silva",)),
    ]
    escolhido = best_candidate(player, candidates)
    assert escolhido is not None and escolhido[0].key == "tm_alex_sandro"


def test_homonimos_exatos_desempatados_por_jogos_pela_selecao() -> None:
    player = PlayerRecord("sb", ("Antony", "Antony Matheus dos Santos"))
    candidates = [PlayerRecord("tm_selecao", ("Antony",)), PlayerRecord("tm_outro", ("Antony",))]

    assert best_candidate(player, candidates) is None
    escolhido = best_candidate(player, candidates, frozenset({"tm_selecao"}))
    assert escolhido is not None and escolhido[0].key == "tm_selecao"
