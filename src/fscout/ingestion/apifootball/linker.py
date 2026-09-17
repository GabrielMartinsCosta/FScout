"""Ligação da quarta fonte ao elenco canônico.

O problema: o carregador cria um atleta canônico novo para cada id que ainda não
conhece. Sem ligação, um brasileiro que jogou a Copa América de 2024 (fonte de eventos)
e o Brasileirão de 2024 (fonte agregada) vira **duas pessoas** no banco, e nenhuma
comparação entre camadas faria sentido.

A solução reaproveita o método já validado no Transfermarkt, em vez de inventar outro, e
o gancho é uma coincidência de catálogo que vale ouro: **a Copa América de 2024 existe
nas duas fontes**. As mesmas 32 partidas, as mesmas escalações. Isso dá o nível mais
forte do método — âncora por partida, com número de camisa — em vez de obrigar a adivinhar
por nome solto entre 1.984 candidatos.

E o efeito vai além da medição. Ligados os ids da Copa América, os mesmos identificadores
reaparecem nas partidas do Brasileirão, onde não há âncora nenhuma: o carregador encontra
a ligação pronta em `external_ids` e reaproveita o atleta canônico sozinho. A competição
compartilhada não serve só para conferir — ela **é** o mecanismo.

Quando a ligação encontra um atleta que a carga já havia criado em duplicata, os dois
registros são fundidos: participações e estatísticas passam para o canônico, e o
duplicado, que não tem identidade em nenhuma outra fonte, é removido.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from fscout.db.models import (
    Appearance,
    DefensiveAction,
    DisciplinaryAction,
    Dribble,
    Event,
    ExternalId,
    GoalkeeperAction,
    Injury,
    Match,
    Pass,
    Player,
    PlayerClubSpell,
    PlayerMatchStat,
    PlayerNationality,
    PlayerValuation,
    Shot,
    Team,
)
from fscout.domain.enums import DataTier
from fscout.ingestion.apifootball.mapper import FONTE
from fscout.ingestion.loader import refresh_player_profiles
from fscout.linking.matching import (
    MatchRecord,
    PlayerRecord,
    ResolvedLink,
    assign_players,
    enforce_one_to_one,
    link_matches,
    resolve_votes,
)

logger = logging.getLogger(__name__)

MATCHED_BY = "lineup"


@dataclass
class RelatorioDeLigacao:
    """O que foi ligado, o que foi recusado e com que confiança."""

    partidas_agregadas: int = 0
    partidas_de_evento: int = 0
    partidas_ligadas: int = 0
    atletas_na_sobreposicao: int = 0
    atletas_ligados: int = 0
    atletas_fundidos: int = 0
    ambiguos: list[str] = field(default_factory=list)
    conflitantes: list[str] = field(default_factory=list)

    @property
    def cobertura(self) -> float:
        if not self.atletas_na_sobreposicao:
            return 0.0
        return self.atletas_ligados / self.atletas_na_sobreposicao


@dataclass(frozen=True)
class _Escalacao:
    """Atletas de um time numa partida, do jeito que o comparador precisa."""

    por_time: dict[int, list[PlayerRecord]]


def _partidas(session: Session, camada: DataTier) -> list[MatchRecord]:
    casa, fora = Team.__table__.alias("casa"), Team.__table__.alias("fora")
    linhas = session.execute(
        select(Match.id, Match.match_date, casa.c.name, fora.c.name)
        .join(casa, casa.c.id == Match.home_team_id)
        .join(fora, fora.c.id == Match.away_team_id)
        .where(Match.data_tier == camada)
    ).all()
    return [
        MatchRecord(key=str(match_id), match_date=data, home=nome_casa, away=nome_fora)
        for match_id, data, nome_casa, nome_fora in linhas
    ]


def _escalacoes(session: Session, match_ids: list[int]) -> dict[int, _Escalacao]:
    """Escalação de cada partida, agrupada por equipe."""
    if not match_ids:
        return {}
    linhas = session.execute(
        select(
            Appearance.match_id,
            Appearance.team_id,
            Appearance.player_id,
            Appearance.jersey_number,
            Player.name,
            Player.full_name,
        )
        .join(Player, Player.id == Appearance.player_id)
        .where(Appearance.match_id.in_(match_ids))
    ).all()

    por_partida: dict[int, dict[int, list[PlayerRecord]]] = defaultdict(lambda: defaultdict(list))
    for match_id, team_id, player_id, camisa, nome, nome_completo in linhas:
        por_partida[match_id][team_id].append(
            PlayerRecord(key=str(player_id), names=(nome, nome_completo), jersey=camisa)
        )
    return {match_id: _Escalacao(dict(times)) for match_id, times in por_partida.items()}


def _lados(
    esquerda: _Escalacao, direita: _Escalacao, invertido: bool
) -> list[tuple[list[PlayerRecord], list[PlayerRecord]]]:
    """Casa com casa e fora com fora, respeitando o mando invertido entre as fontes.

    Comparar os 22 atletas de uma vez dobraria as chances de casar homônimos de times
    diferentes; separar por equipe é o que torna a camisa um sinal confiável.
    """
    times_esquerda = sorted(esquerda.por_time)
    times_direita = sorted(direita.por_time)
    if len(times_esquerda) != len(times_direita):
        return []
    if invertido:
        times_direita = list(reversed(times_direita))
    return [
        (esquerda.por_time[a], direita.por_time[b])
        for a, b in zip(times_esquerda, times_direita, strict=True)
    ]


# Toda tabela que aponta para `players` precisa de uma decisão explícita antes de um
# atleta sumir, e a decisão não é a mesma para todas.
#
# **Movidas:** carregam dado medido, que pertence à pessoa e não ao registro duplicado.
MOVIDAS = (
    Appearance,
    PlayerMatchStat,
    Event,
    Shot,
    Pass,
    Dribble,
    DefensiveAction,
    GoalkeeperAction,
    DisciplinaryAction,
    PlayerValuation,
    Injury,
)
# **Apagadas:** são derivadas das participações, e o `refresh_player_profiles` as
# reconstrói depois da fusão. Movê-las duplicaria o que o canônico já tem — foi
# exatamente uma passagem por clube derivada que fez a primeira tentativa de fusão
# falhar com violação de chave estrangeira.
DERIVADAS = (PlayerNationality, PlayerClubSpell)


def mesclar_atletas(session: Session, duplicado_id: int, canonico_id: int) -> None:
    """Move o dado do duplicado para o canônico e apaga o duplicado.

    O duplicado existe porque a carga rodou antes da ligação e não tem identidade em
    nenhuma outra fonte, então pode sumir — mas só depois que tudo que apontava para ele
    tiver destino. Deixar uma tabela de fora não corrompe nada: o banco recusa a exclusão
    e a transação inteira volta atrás.
    """
    if duplicado_id == canonico_id:
        return
    for tabela in MOVIDAS:
        session.execute(
            update(tabela).where(tabela.player_id == duplicado_id).values(player_id=canonico_id)
        )
    # Quem recebeu o passe também é uma referência ao atleta, e some junto com ele.
    session.execute(
        update(Pass)
        .where(Pass.recipient_player_id == duplicado_id)
        .values(recipient_player_id=canonico_id)
    )
    for tabela in DERIVADAS:
        session.execute(delete(tabela).where(tabela.player_id == duplicado_id))
    session.execute(
        delete(ExternalId).where(
            ExternalId.entity == Player.__tablename__, ExternalId.entity_id == duplicado_id
        )
    )
    session.execute(delete(Player).where(Player.id == duplicado_id))


def ligar_atletas(session: Session) -> RelatorioDeLigacao:
    """Liga os atletas da camada agregada aos canônicos, pela competição compartilhada."""
    relatorio = RelatorioDeLigacao()

    agregadas = _partidas(session, DataTier.AGGREGATE)
    de_evento = _partidas(session, DataTier.EVENT)
    relatorio.partidas_agregadas = len(agregadas)
    relatorio.partidas_de_evento = len(de_evento)

    ligacoes_de_partida = link_matches(agregadas, de_evento)
    relatorio.partidas_ligadas = len(ligacoes_de_partida)
    if not ligacoes_de_partida:
        return relatorio

    escalacoes_agregadas = _escalacoes(
        session, [int(link.left_key) for link in ligacoes_de_partida]
    )
    escalacoes_de_evento = _escalacoes(
        session, [int(link.right_key) for link in ligacoes_de_partida]
    )

    votos = []
    ambiguos: set[str] = set()
    envolvidos: set[str] = set()
    for link in ligacoes_de_partida:
        esquerda = escalacoes_agregadas.get(int(link.left_key))
        direita = escalacoes_de_evento.get(int(link.right_key))
        if esquerda is None or direita is None:
            continue
        for atletas_agregados, atletas_de_evento in _lados(esquerda, direita, link.swapped):
            envolvidos.update(atleta.key for atleta in atletas_agregados)
            encontrados, duvidosos = assign_players(atletas_agregados, atletas_de_evento)
            votos.extend(encontrados)
            ambiguos.update(duvidosos)

    relatorio.atletas_na_sobreposicao = len(envolvidos)
    resolvidos: dict[str, ResolvedLink] = enforce_one_to_one(resolve_votes(votos))
    relatorio.ambiguos = sorted(ambiguos - set(resolvidos))
    relatorio.conflitantes = sorted(
        chave for chave, ligacao in resolvidos.items() if ligacao.conflicting
    )

    fundidos: set[int] = set()
    for chave, ligacao in resolvidos.items():
        duplicado_id, canonico_id = int(chave), int(ligacao.right_key)
        if duplicado_id == canonico_id:
            continue
        _repontar_identidade(session, duplicado_id, canonico_id)
        mesclar_atletas(session, duplicado_id, canonico_id)
        fundidos.add(canonico_id)
        relatorio.atletas_fundidos += 1

    # As derivadas foram apagadas na fusão; aqui elas voltam, agora considerando as
    # participações das duas camadas de uma vez.
    refresh_player_profiles(session, fundidos)

    relatorio.atletas_ligados = len(resolvidos)
    session.commit()
    return relatorio


def _repontar_identidade(session: Session, duplicado_id: int, canonico_id: int) -> None:
    """Faz o id da fonte apontar para o canônico, antes de o duplicado sumir.

    É esta linha que faz o Brasileirão carregar ligado: o carregador procura o id da
    fonte em `external_ids` e, encontrando, reaproveita o atleta em vez de criar outro.
    """
    ligacoes = session.scalars(
        select(ExternalId).where(
            ExternalId.entity == Player.__tablename__,
            ExternalId.source == FONTE,
            ExternalId.entity_id == duplicado_id,
        )
    ).all()
    for ligacao in ligacoes:
        ja_existe = session.scalar(
            select(ExternalId).where(
                ExternalId.entity == Player.__tablename__,
                ExternalId.source == FONTE,
                ExternalId.source_id == ligacao.source_id,
                ExternalId.entity_id == canonico_id,
            )
        )
        if ja_existe is not None:
            session.delete(ligacao)
            continue
        ligacao.entity_id = canonico_id
        ligacao.matched_by = MATCHED_BY
    session.flush()
