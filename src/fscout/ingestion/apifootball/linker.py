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
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from fscout.db.models import (
    Appearance,
    Competition,
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
    Season,
    Shot,
    Team,
)
from fscout.domain.enums import DataTier
from fscout.ingestion.loader import refresh_player_profiles
from fscout.linking.matching import (
    MatchLink,
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
    equipes_fundidas: int = 0
    temporadas_fundidas: int = 0
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


# Colunas que apontam para uma equipe. Mesma disciplina da fusão de atletas: cada uma
# precisa de destino antes de o registro sumir, senão o banco recusa a exclusão.
REFERENCIAS_DE_EQUIPE: tuple[tuple[type, str], ...] = (
    (Match, "home_team_id"),
    (Match, "away_team_id"),
    (Appearance, "team_id"),
    (Appearance, "opponent_team_id"),
    (PlayerMatchStat, "team_id"),
    (PlayerClubSpell, "team_id"),
    (Event, "team_id"),
    (Event, "possession_team_id"),
)


def _correspondencias_de_equipe(session: Session, ligacoes: list[MatchLink]) -> dict[int, int]:
    """Equipe da camada agregada -> equipe canônica, pelo lado que ocupam na partida.

    A âncora é a mesma das escalações: em partidas que as duas fontes descrevem, quem
    joga em casa numa é quem joga em casa na outra — salvo mando invertido, que
    `link_matches` já detectou.
    """
    lados = {
        match_id: (casa, fora)
        for match_id, casa, fora in session.execute(
            select(Match.id, Match.home_team_id, Match.away_team_id)
        )
    }
    votos: dict[int, Counter[int]] = defaultdict(Counter)
    for link in ligacoes:
        agregada = lados.get(int(link.left_key))
        canonica = lados.get(int(link.right_key))
        if agregada is None or canonica is None:
            continue
        if link.swapped:
            canonica = (canonica[1], canonica[0])
        for de, para in zip(agregada, canonica, strict=True):
            if de != para:
                votos[de][para] += 1
    return {de: contagem.most_common(1)[0][0] for de, contagem in votos.items() if contagem}


def mesclar_equipes(session: Session, duplicada_id: int, canonica_id: int) -> None:
    """Aponta tudo para a equipe canônica e apaga a duplicada."""
    if duplicada_id == canonica_id:
        return
    for tabela, coluna in REFERENCIAS_DE_EQUIPE:
        session.execute(
            update(tabela)
            .where(getattr(tabela, coluna) == duplicada_id)
            .values({coluna: canonica_id})
        )
    _repontar(session, Team.__tablename__, duplicada_id, canonica_id)
    session.execute(delete(Team).where(Team.id == duplicada_id))


def mesclar_temporadas(session: Session, duplicada_id: int, canonica_id: int) -> None:
    """Move as partidas para a temporada canônica e apaga a duplicada.

    A competição da duplicada some junto quando fica sem temporada nenhuma: duas linhas
    "Copa América" no filtro seriam a mesma competição vista por duas fontes, e o que
    distingue as leituras é a camada da partida, não a competição.
    """
    if duplicada_id == canonica_id:
        return
    duplicada = session.get(Season, duplicada_id)
    if duplicada is None:
        return
    competicao_orfa = duplicada.competition_id
    session.execute(
        update(Match).where(Match.season_id == duplicada_id).values(season_id=canonica_id)
    )
    _repontar(session, Season.__tablename__, duplicada_id, canonica_id)
    session.execute(delete(Season).where(Season.id == duplicada_id))
    session.flush()

    restantes = session.scalar(
        select(func.count()).select_from(Season).where(Season.competition_id == competicao_orfa)
    )
    if restantes:
        return
    canonica = session.get(Season, canonica_id)
    if canonica is not None:
        _repontar(session, Competition.__tablename__, competicao_orfa, canonica.competition_id)
    session.execute(delete(Competition).where(Competition.id == competicao_orfa))


def _repontar(session: Session, entidade: str, duplicado_id: int, canonico_id: int) -> None:
    """Faz os identificadores da fonte apontarem para o registro canônico."""
    ligacoes = session.scalars(
        select(ExternalId).where(
            ExternalId.entity == entidade, ExternalId.entity_id == duplicado_id
        )
    ).all()
    for ligacao in ligacoes:
        ja_existe = session.scalar(
            select(ExternalId).where(
                ExternalId.entity == entidade,
                ExternalId.source == ligacao.source,
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
        _repontar(session, Player.__tablename__, duplicado_id, canonico_id)
        mesclar_atletas(session, duplicado_id, canonico_id)
        fundidos.add(canonico_id)
        relatorio.atletas_fundidos += 1

    # As derivadas foram apagadas na fusão; aqui elas voltam, agora considerando as
    # participações das duas camadas de uma vez.
    refresh_player_profiles(session, fundidos)
    relatorio.atletas_ligados = len(resolvidos)

    # Atleta não é a única entidade que as duas fontes descrevem. Sem fundir equipe e
    # competição, o filtro da tela mostraria "Copa América" duas vezes e "Brasil" como
    # dois adversários diferentes.
    for duplicada, canonica in _correspondencias_de_equipe(session, ligacoes_de_partida).items():
        mesclar_equipes(session, duplicada, canonica)
        relatorio.equipes_fundidas += 1

    temporadas = {int(link.left_key): int(link.right_key) for link in ligacoes_de_partida}
    por_temporada: dict[int, int] = {}
    for agregada, canonica in temporadas.items():
        de = session.scalar(select(Match.season_id).where(Match.id == agregada))
        para = session.scalar(select(Match.season_id).where(Match.id == canonica))
        if de is not None and para is not None and de != para:
            por_temporada[de] = para
    for duplicada, canonica in por_temporada.items():
        mesclar_temporadas(session, duplicada, canonica)
        relatorio.temporadas_fundidas += 1

    session.commit()
    return relatorio
