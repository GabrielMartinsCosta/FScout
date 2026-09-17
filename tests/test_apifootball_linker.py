"""Testes da ligação e da fusão de atletas duplicados.

A fusão é a única operação destrutiva do projeto: ela apaga um registro. Por isso os
testes aqui cobrem menos o caminho feliz e mais as bordas em que apagar seria errado —
e a garantia de que nada que apontava para o duplicado fica órfão.

O defeito que motivou metade deste arquivo foi real: a primeira tentativa de fusão
falhou com violação de chave estrangeira porque uma passagem por clube, **derivada** das
participações pelo próprio pipeline, ainda apontava para o duplicado. O banco recusou a
exclusão e a transação inteira voltou atrás — que é o comportamento correto, mas só
apareceu ao rodar contra dado real.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from fscout.db.models import (
    Appearance,
    Competition,
    Country,
    ExternalId,
    Match,
    Player,
    PlayerClubSpell,
    PlayerMatchStat,
    PlayerNationality,
    Season,
    Team,
)
from fscout.db.session import build_engine, create_all
from fscout.domain.enums import DataTier, HomeAway
from fscout.ingestion.apifootball.linker import (
    DERIVADAS,
    MOVIDAS,
    RelatorioDeLigacao,
    _lados,
    ligar_atletas,
    mesclar_atletas,
)
from fscout.linking.matching import PlayerRecord


@pytest.fixture
def sessao(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = build_engine(f"sqlite:///{tmp_path / 'ligacao.db'}")
    create_all(engine)
    with Session(engine) as sessao:
        yield sessao
    engine.dispose()


def _cenario(sessao: Session) -> tuple[int, int, int]:
    """Um duplicado com dado e derivadas, e o canônico para onde ele deve ir."""
    casa, fora = Team(name="Internacional"), Team(name="Bahia")
    competicao = Competition(name="Serie A")
    sessao.add_all([casa, fora, competicao])
    sessao.flush()
    temporada = Season(competition_id=competicao.id, name="2024")
    sessao.add(temporada)
    sessao.flush()
    partida = Match(
        season_id=temporada.id,
        match_date=date(2024, 4, 13),
        home_team_id=casa.id,
        away_team_id=fora.id,
        data_tier=DataTier.AGGREGATE,
    )
    canonico, duplicado = Player(name="Sergio Rochet"), Player(name="Sergio Rochet")
    sessao.add_all([partida, canonico, duplicado])
    sessao.flush()

    sessao.add_all(
        [
            Appearance(
                match_id=partida.id,
                player_id=duplicado.id,
                team_id=casa.id,
                opponent_team_id=fora.id,
                home_away=HomeAway.HOME,
                minutes_played=90,
            ),
            PlayerMatchStat(
                match_id=partida.id,
                player_id=duplicado.id,
                team_id=casa.id,
                source="apifootball",
                source_id="1-2",
                passes_total=18,
            ),
            # A derivada que fez a primeira tentativa falhar.
            PlayerClubSpell(player_id=duplicado.id, team_id=casa.id, start_date=date(2024, 1, 1)),
            ExternalId(
                entity="players",
                entity_id=duplicado.id,
                source="apifootball",
                source_id="19599",
                matched_by="created",
            ),
        ]
    )
    sessao.flush()
    return duplicado.id, canonico.id, partida.id


def test_fusao_move_o_dado_medido(sessao: Session) -> None:
    """Participação e estatística pertencem à pessoa, não ao registro duplicado."""
    duplicado, canonico, _ = _cenario(sessao)
    mesclar_atletas(sessao, duplicado, canonico)

    assert (
        sessao.scalar(
            select(func.count()).select_from(Appearance).where(Appearance.player_id == canonico)
        )
        == 1
    )
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(PlayerMatchStat)
            .where(PlayerMatchStat.player_id == canonico)
        )
        == 1
    )


def test_fusao_apaga_o_que_e_derivado(sessao: Session) -> None:
    """Passagem por clube se recalcula das participações; movê-la duplicaria o que o
    canônico já tem."""
    duplicado, canonico, _ = _cenario(sessao)
    mesclar_atletas(sessao, duplicado, canonico)

    assert sessao.scalar(select(func.count()).select_from(PlayerClubSpell)) == 0


def test_duplicado_some_e_nao_deixa_orfao(sessao: Session) -> None:
    """Se alguma tabela ficasse de fora, o banco recusaria a exclusão — e é isso que
    aconteceu na primeira tentativa, contra dado real."""
    duplicado, canonico, _ = _cenario(sessao)
    mesclar_atletas(sessao, duplicado, canonico)
    sessao.flush()

    assert sessao.get(Player, duplicado) is None
    assert sessao.get(Player, canonico) is not None
    assert (
        sessao.scalar(
            select(func.count()).select_from(Appearance).where(Appearance.player_id == duplicado)
        )
        == 0
    )


def test_fusao_de_um_atleta_com_ele_mesmo_nao_faz_nada(sessao: Session) -> None:
    """Guarda contra o caso em que a ligação aponta para o próprio registro: sem isto,
    o atleta apagaria a si mesmo depois de mover os dados para si mesmo."""
    duplicado, _, _ = _cenario(sessao)
    mesclar_atletas(sessao, duplicado, duplicado)
    sessao.flush()

    assert sessao.get(Player, duplicado) is not None
    assert (
        sessao.scalar(
            select(func.count()).select_from(Appearance).where(Appearance.player_id == duplicado)
        )
        == 1
    )


def test_identidade_do_duplicado_e_removida(sessao: Session) -> None:
    """Quem repontou a identidade para o canônico é `_repontar_identidade`, antes da
    fusão; o que sobrar aqui apontaria para um id que não existe mais."""
    duplicado, canonico, _ = _cenario(sessao)
    mesclar_atletas(sessao, duplicado, canonico)

    restantes = sessao.scalars(
        select(ExternalId).where(ExternalId.entity == "players", ExternalId.entity_id == duplicado)
    ).all()
    assert restantes == []


def test_toda_tabela_que_aponta_para_atleta_tem_destino() -> None:
    """Contrato explícito: cada tabela é movida ou apagada, e nenhuma fica esquecida.

    Esquecer uma não corrompe o banco — ele recusa a exclusão —, mas trava a ligação
    inteira, que foi exatamente o sintoma na primeira execução.
    """
    decididas = {tabela.__tablename__ for tabela in (*MOVIDAS, *DERIVADAS)}
    apontam_para_atleta = {
        tabela.__tablename__ for tabela in (*MOVIDAS, *DERIVADAS) if hasattr(tabela, "player_id")
    }
    assert apontam_para_atleta == decididas
    assert "player_club_spells" in {tabela.__tablename__ for tabela in DERIVADAS}
    assert "appearances" in {tabela.__tablename__ for tabela in MOVIDAS}


def test_nacionalidade_do_duplicado_nao_sobrescreve_a_do_canonico(sessao: Session) -> None:
    """A do duplicado viria de uma fonte mais pobre, que só tem o nome do atleta."""
    duplicado, canonico, _ = _cenario(sessao)
    pais = Country(name="Uruguay")
    sessao.add(pais)
    sessao.flush()
    sessao.add(PlayerNationality(player_id=duplicado, country_id=pais.id, is_primary=True))
    sessao.flush()

    mesclar_atletas(sessao, duplicado, canonico)
    assert sessao.scalar(select(func.count()).select_from(PlayerNationality)) == 0


# ----------------------------------------------------------------------------------------
# Emparelhamento das equipes dentro da partida
# ----------------------------------------------------------------------------------------


def _escalacao(por_time: dict[int, list[str]]) -> object:
    from fscout.ingestion.apifootball.linker import _Escalacao

    return _Escalacao(
        {
            time: [PlayerRecord(key=nome, names=(nome,), jersey=None) for nome in nomes]
            for time, nomes in por_time.items()
        }
    )


def test_lados_emparelham_time_com_time() -> None:
    """Comparar os 22 de uma vez dobraria a chance de casar homônimos de times
    diferentes; a camisa só é sinal confiável dentro de uma equipe."""
    esquerda = _escalacao({1: ["A"], 2: ["B"]})
    direita = _escalacao({10: ["A"], 20: ["B"]})
    pares = _lados(esquerda, direita, invertido=False)
    assert [(p[0][0].key, p[1][0].key) for p in pares] == [("A", "A"), ("B", "B")]


def test_mando_invertido_inverte_o_emparelhamento() -> None:
    """As fontes discordam sobre quem é o mandante em jogo de campo neutro."""
    esquerda = _escalacao({1: ["A"], 2: ["B"]})
    direita = _escalacao({10: ["B"], 20: ["A"]})
    pares = _lados(esquerda, direita, invertido=True)
    assert [(p[0][0].key, p[1][0].key) for p in pares] == [("A", "A"), ("B", "B")]


def test_escalacao_incompleta_nao_emparelha_no_chute() -> None:
    """Uma fonte com um time só não permite dizer qual lado é qual."""
    assert _lados(_escalacao({1: ["A"]}), _escalacao({10: ["A"], 20: ["B"]}), False) == []


# ----------------------------------------------------------------------------------------
# Relatório
# ----------------------------------------------------------------------------------------


def test_sem_partida_em_comum_a_ligacao_nao_acontece(sessao: Session) -> None:
    """O caso do Brasileirão sozinho: sem competição compartilhada não há âncora, e
    inventar ligação por nome solto entre milhares de candidatos seria pior que não ligar.
    """
    relatorio = ligar_atletas(sessao)
    assert relatorio.partidas_ligadas == 0
    assert relatorio.atletas_ligados == 0
    assert relatorio.cobertura == 0.0


def test_cobertura_sem_sobreposicao_nao_divide_por_zero() -> None:
    assert RelatorioDeLigacao().cobertura == 0.0
    assert RelatorioDeLigacao(atletas_na_sobreposicao=4, atletas_ligados=3).cobertura == 0.75
