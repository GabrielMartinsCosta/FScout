"""Testes do mapeador da camada agregada.

Cada asserção aqui corresponde a uma armadilha encontrada lendo o dado real da fonte, e
não a uma hipótese sobre como ele deveria ser. As quatro que mais custariam caro:

1. `passes.accuracy` parece porcentagem pelo nome e é contagem.
2. Nulo significa zero nos campos de contagem — mas não na nota, onde zero seria uma
   afirmação de desempenho péssimo.
3. Minutos nulos significam que o atleta não entrou, e não que jogou zero minuto.
4. `penalty.commited` está escrito errado na fonte, e copiar o erro é o que faz funcionar.

Nenhum teste vai à rede: todos montam a resposta à mão, no formato observado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from fscout.domain.enums import CompetitionType, DataTier, HomeAway, PositionGroup
from fscout.ingestion.apifootball.mapper import (
    build_match_bundle,
    competition_row,
    decimal,
    inteiro,
    season_row,
    season_source_id,
)

LIGA = {"id": 71, "name": "Serie A", "country": "Brazil", "season": 2024, "round": "Rodada 1"}


def _fixture(**mudancas: Any) -> dict[str, Any]:
    base = {
        "fixture": {
            "id": 1180355,
            "referee": "Fulano de Tal",
            "date": "2024-04-13T21:30:00+00:00",
            "venue": {"id": 244, "name": "Beira-Rio", "city": "Porto Alegre"},
            "status": {"short": "FT"},
        },
        "league": dict(LIGA),
        "teams": {
            "home": {"id": 119, "name": "Internacional"},
            "away": {"id": 118, "name": "Bahia"},
        },
        "goals": {"home": 2, "away": 1},
    }
    base.update(mudancas)
    return base


def _estatistica(**mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "games": {
            "minutes": 90,
            "number": 1,
            "position": "G",
            "rating": "7.2",
            "captain": False,
            "substitute": False,
        },
        "offsides": None,
        "shots": {"total": None, "on": None},
        "goals": {"total": None, "conceded": 1, "assists": None, "saves": 3},
        "passes": {"total": 18, "key": None, "accuracy": "12"},
        "tackles": {"total": None, "blocks": None, "interceptions": None},
        "duels": {"total": 1, "won": 1},
        "dribbles": {"attempts": None, "success": None, "past": None},
        "fouls": {"drawn": 1, "committed": None},
        "cards": {"yellow": 0, "red": 0},
        "penalty": {"won": None, "commited": None, "scored": 0, "missed": 0, "saved": 0},
    }
    for grupo, valores in mudancas.items():
        if isinstance(valores, dict) and isinstance(base.get(grupo), dict):
            base[grupo] = {**base[grupo], **valores}
        else:
            base[grupo] = valores
    return base


def _jogadores(*entradas: tuple[int, int, str, dict[str, Any]]) -> dict[str, Any]:
    """Monta a resposta de `/fixtures/players`: (id do time, id do atleta, nome, stats)."""
    por_time: dict[int, list[dict[str, Any]]] = {}
    for time_id, atleta_id, nome, stats in entradas:
        por_time.setdefault(time_id, []).append(
            {"player": {"id": atleta_id, "name": nome}, "statistics": [stats]}
        )
    return {
        "response": [
            {"team": {"id": time_id, "name": str(time_id)}, "players": jogadores}
            for time_id, jogadores in por_time.items()
        ]
    }


# ----------------------------------------------------------------------------------------
# Conversão de números
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [(None, 0), ("", 0), ("12", 12), (12, 12), (12.0, 12), ("7.2", 7), ("lixo", 0)],
)
def test_contagem_aceita_nulo_e_texto(bruto: Any, esperado: int) -> None:
    """A fonte manda número como texto em alguns campos e nulo em muitos outros."""
    assert inteiro(bruto) == esperado


def test_nota_ausente_nao_vira_zero() -> None:
    """Zero na nota seria afirmar desempenho péssimo; ausência é outra coisa."""
    assert decimal(None) is None
    assert decimal("") is None
    assert decimal("7.2") == pytest.approx(7.2)


def test_chave_de_temporada_e_composta() -> None:
    """O ano se repete entre competições e sozinho não identifica nada."""
    assert season_source_id(71, 2024) == "71-2024"
    assert season_source_id(13, 2024) != season_source_id(71, 2024)


# ----------------------------------------------------------------------------------------
# Competição
# ----------------------------------------------------------------------------------------


def test_liga_nacional_guarda_o_pais() -> None:
    linha = competition_row(LIGA)
    assert linha["type"] is CompetitionType.NATIONAL_LEAGUE
    assert linha["country_ref"] == "Brazil"


def test_copa_continental_nao_e_liga_nacional() -> None:
    """O recorte por tipo de competição, que a especificação pede, depende disto."""
    linha = competition_row({"id": 13, "name": "CONMEBOL Libertadores", "country": "World"})
    assert linha["type"] is CompetitionType.CONTINENTAL_CLUB
    assert linha["country_ref"] is None


def test_temporada_leva_o_ano_como_nome() -> None:
    assert season_row(LIGA) == {"source_id": "71-2024", "name": "2024"}


# ----------------------------------------------------------------------------------------
# A partida
# ----------------------------------------------------------------------------------------


def test_partida_nasce_marcada_como_camada_agregada() -> None:
    """É esta marca que impede a partida de ser somada com as de evento."""
    bundle = build_match_bundle(_fixture(), _jogadores((119, 1, "A", _estatistica())))
    assert bundle.match["data_tier"] is DataTier.AGGREGATE


def test_horario_vem_convertido_para_utc_sem_fuso() -> None:
    """Gravar horário local como se fosse universal já custou uma correção neste
    projeto, no clima das partidas."""
    fixture = _fixture()
    fixture["fixture"]["date"] = "2024-04-13T18:30:00-03:00"
    bundle = build_match_bundle(fixture, _jogadores((119, 1, "A", _estatistica())))
    assert bundle.match["kickoff"] == datetime(2024, 4, 13, 21, 30)
    assert bundle.match["kickoff"].tzinfo is None
    assert bundle.match["match_date"] == datetime(2024, 4, 13).date()


def test_placar_confere_com_os_gols_somados_por_atleta() -> None:
    """A conferência mais barata de uma ingestão, herdada da fonte de eventos."""
    jogadores = _jogadores(
        (119, 1, "Goleiro", _estatistica()),
        (119, 2, "Artilheiro", _estatistica(goals={"total": 2})),
        (118, 3, "Visitante", _estatistica(goals={"total": 1})),
    )
    bundle = build_match_bundle(_fixture(), jogadores)
    assert bundle.goal_check.expected == (2, 1)
    assert bundle.goal_check.from_events == (2, 1)
    assert bundle.goal_check.ok


def test_placar_divergente_e_detectado() -> None:
    """Gol contra é a exceção conhecida: não é creditado a atleta do time que marcou."""
    jogadores = _jogadores((119, 1, "A", _estatistica()), (118, 3, "B", _estatistica()))
    bundle = build_match_bundle(_fixture(), jogadores)
    assert not bundle.goal_check.ok


# ----------------------------------------------------------------------------------------
# Participação e estatística
# ----------------------------------------------------------------------------------------


def test_reserva_que_nao_entrou_nao_vira_participacao() -> None:
    """Minutos nulos, com nota também nula, é reserva não utilizada — 32% das linhas."""
    jogadores = _jogadores(
        (119, 1, "Jogou", _estatistica()),
        (119, 2, "Banco", _estatistica(games={"minutes": None, "rating": None})),
    )
    bundle = build_match_bundle(_fixture(), jogadores)
    assert len(bundle.appearances) == 1
    assert len(bundle.player_match_stats) == 1
    assert "2" not in bundle.players


@pytest.mark.parametrize(
    ("letra", "grupo"),
    [
        ("G", PositionGroup.GOALKEEPER),
        ("D", PositionGroup.DEFENDER),
        ("M", PositionGroup.MIDFIELDER),
        ("F", PositionGroup.FORWARD),
    ],
)
def test_posicao_vira_grupo(letra: str, grupo: PositionGroup) -> None:
    """A fonte dá uma letra por setor, e é o grupo que o percentil usa."""
    jogadores = _jogadores((119, 1, "A", _estatistica(games={"position": letra})))
    assert build_match_bundle(_fixture(), jogadores).appearances[0]["position_group"] is grupo


def test_posicao_desconhecida_nao_inventa_grupo() -> None:
    jogadores = _jogadores((119, 1, "A", _estatistica(games={"position": "Z"})))
    assert build_match_bundle(_fixture(), jogadores).appearances[0]["position_group"] is None


def test_mando_e_adversario_saem_do_lado_do_time() -> None:
    jogadores = _jogadores((119, 1, "Casa", _estatistica()), (118, 2, "Fora", _estatistica()))
    bundle = build_match_bundle(_fixture(), jogadores)
    casa = next(a for a in bundle.appearances if a["team_ref"] == "119")
    fora = next(a for a in bundle.appearances if a["team_ref"] == "118")
    assert casa["home_away"] is HomeAway.HOME
    assert casa["opponent_team_ref"] == "118"
    assert fora["home_away"] is HomeAway.AWAY
    assert (casa["goals_for"], casa["goals_against"]) == (2, 1)
    assert (fora["goals_for"], fora["goals_against"]) == (1, 2)


def test_passes_certos_sao_contagem_e_nao_porcentagem() -> None:
    """O campo se chama "accuracy" na fonte, mas em 124 amostras nunca excedeu o total.
    Guardar com o nome errado faria alguém dividir por 100 depois."""
    jogadores = _jogadores((119, 1, "A", _estatistica()))
    estatistica = build_match_bundle(_fixture(), jogadores).player_match_stats[0]
    assert estatistica["passes_total"] == 18
    assert estatistica["passes_accurate"] == 12


def test_penalti_cometido_le_a_grafia_errada_da_fonte() -> None:
    """A fonte escreve "commited", com um "t". Corrigir faria o campo vir sempre vazio."""
    jogadores = _jogadores((119, 1, "A", _estatistica(penalty={"commited": 2})))
    assert (
        build_match_bundle(_fixture(), jogadores).player_match_stats[0]["penalties_committed"] == 2
    )


def test_nulo_de_contagem_vira_zero() -> None:
    """A fonte grava nulo onde quer dizer "nenhum" na maioria dos campos."""
    estatistica = build_match_bundle(
        _fixture(), _jogadores((119, 1, "A", _estatistica()))
    ).player_match_stats[0]
    assert estatistica["shots_total"] == 0
    assert estatistica["goals"] == 0
    assert estatistica["tackles"] == 0


def test_nota_da_fonte_e_preservada_como_ela_veio() -> None:
    """Fica gravada por completude; nenhuma métrica do catálogo se apoia nela."""
    estatistica = build_match_bundle(
        _fixture(), _jogadores((119, 1, "A", _estatistica()))
    ).player_match_stats[0]
    assert estatistica["source_rating"] == pytest.approx(7.2)


def test_cada_estatistica_tem_identidade_propria_na_fonte() -> None:
    """Sem isso, recarregar a mesma partida duplicaria linhas em vez de substituí-las."""
    jogadores = _jogadores((119, 1, "A", _estatistica()), (118, 2, "B", _estatistica()))
    bundle = build_match_bundle(_fixture(), jogadores)
    identidades = {linha["source_id"] for linha in bundle.player_match_stats}
    assert identidades == {"1180355-1", "1180355-2"}
