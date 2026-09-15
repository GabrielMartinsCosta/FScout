"""Ligação StatsBomb x Transfermarkt: partidas, equipes e atletas.

Traduz as tabelas das duas fontes para os registros mínimos de `fscout.linking.matching`,
aplica as regras e grava as decisões em `external_ids`. Toda ligação automática é refeita
a cada execução; ligações `manual` são preservadas e têm precedência.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from fscout.db.models import Appearance, Country, ExternalId, Match, Player, PlayerNationality, Team
from fscout.ingestion.transfermarkt.client import TransfermarktClient
from fscout.linking.countries import country_key
from fscout.linking.matching import (
    MIN_ACCEPTED_CONFIDENCE,
    MatchRecord,
    PlayerLink,
    PlayerRecord,
    assign_players,
    best_candidate,
    enforce_one_to_one,
    link_matches,
    resolve_votes,
)
from fscout.linking.names import compact, is_name, tokens

logger = logging.getLogger(__name__)

SOURCE = "transfermarkt"

MATCHED_BY_DATE_TEAMS = "date_teams"
MATCHED_BY_MATCH_SIDE = "match_side"
MATCHED_BY_LINEUP = "game_lineup"
MATCHED_BY_NAME_NATIONALITY = "name_nationality"
MATCHED_BY_EXACT_NAME = "exact_name_unique"
AUTOMATIC_METHODS = (
    MATCHED_BY_DATE_TEAMS,
    MATCHED_BY_MATCH_SIDE,
    MATCHED_BY_LINEUP,
    MATCHED_BY_NAME_NATIONALITY,
    MATCHED_BY_EXACT_NAME,
)

# A ligação por nome e nacionalidade não tem a evidência da escalação; a confiança é
# reduzida para que nunca empate com uma ligação por escalação.
NAME_NATIONALITY_CONFIDENCE_FACTOR = 0.8

# Idade plausível na data da partida, para descartar homônimos de outra geração.
MIN_AGE_YEARS, MAX_AGE_YEARS = 15, 45

LINEUP_CHUNK_ROWS = 500_000


@dataclass
class LinkReport:
    matches_total: int = 0
    matches_linked: int = 0
    teams_linked: int = 0
    players_total: int = 0
    players_by_lineup: int = 0
    players_by_name: int = 0
    players_by_exact_name: int = 0
    review: list[dict[str, Any]] = field(default_factory=list)
    # Avaliação do método por nome e nacionalidade contra as ligações por escalação.
    fallback_checked: int = 0
    fallback_proposed: int = 0
    fallback_agreed: int = 0

    @property
    def players_linked(self) -> int:
        return self.players_by_lineup + self.players_by_name + self.players_by_exact_name

    @property
    def fallback_precision(self) -> float | None:
        return self.fallback_agreed / self.fallback_proposed if self.fallback_proposed else None

    @property
    def fallback_recall(self) -> float | None:
        return self.fallback_agreed / self.fallback_checked if self.fallback_checked else None


def link_transfermarkt(
    session: Session, client: TransfermarktClient
) -> tuple[LinkReport, dict[int, int]]:
    """Liga os registros do banco ao Transfermarkt.

    Devolve o relatório e o mapa atleta canônico -> id do atleta no Transfermarkt.
    """
    report = LinkReport()
    session.execute(
        delete(ExternalId).where(
            ExternalId.source == SOURCE, ExternalId.matched_by.in_(AUTOMATIC_METHODS)
        )
    )
    links = _Links(session)

    matches = _statsbomb_matches(session)
    report.matches_total = len(matches)
    if matches.empty:
        return report, {}

    sides = _link_matches_and_teams(client, matches, links, report)
    lineup_links, ambiguous = _link_by_lineup(session, client, sides)

    player_links: dict[int, int] = {}
    for link in enforce_one_to_one(resolve_votes(lineup_links)).values():
        player_id, tm_id = int(link.left_key), int(link.right_key)
        if link.confidence < MIN_ACCEPTED_CONFIDENCE:
            report.review.append(
                _review(player_id, "confiança baixa na escalação", tm_id, link.confidence)
            )
            continue
        if links.add("players", player_id, tm_id, MATCHED_BY_LINEUP, link.confidence):
            player_links[player_id] = tm_id
    report.players_by_lineup = len(player_links)

    for player_key in ambiguous - {str(player_id) for player_id in player_links}:
        report.review.append(_review(int(player_key), "ambíguo na escalação"))

    _link_by_name_and_nationality(session, client, player_links, links, report)
    session.flush()
    logger.info(
        "Transfermarkt: %d/%d partidas, %d atletas ligados",
        report.matches_linked,
        report.matches_total,
        report.players_linked,
    )
    return report, player_links


# =========================================================================================
# Partidas e equipes
# =========================================================================================


@dataclass(frozen=True)
class _Side:
    match_id: int
    game_id: int
    team_id: int
    club_id: int


def _link_matches_and_teams(
    client: TransfermarktClient,
    matches: pd.DataFrame,
    links: _Links,
    report: LinkReport,
) -> list[_Side]:
    games = client.read(
        "games",
        usecols=[
            "game_id",
            "date",
            "home_club_id",
            "away_club_id",
            "home_club_name",
            "away_club_name",
        ],
        parse_dates=["date"],
    )
    first, last = min(matches.match_date), max(matches.match_date)
    games = games[
        games.date.between(
            pd.Timestamp(first - timedelta(days=1)), pd.Timestamp(last + timedelta(days=1))
        )
    ].dropna(subset=["home_club_name", "away_club_name"])

    match_links = link_matches(
        [
            MatchRecord(str(row.match_id), row.match_date, row.home, row.away)
            for row in matches.itertuples()
        ],
        [
            MatchRecord(str(row.game_id), row.date.date(), row.home_club_name, row.away_club_name)
            for row in games.itertuples()
        ],
    )

    matches_by_id = matches.set_index("match_id")
    games_by_id = games.set_index("game_id")
    sides: list[_Side] = []
    team_votes: dict[int, Counter[int]] = defaultdict(Counter)

    for link in match_links:
        match = matches_by_id.loc[int(link.left_key)]
        game = games_by_id.loc[int(link.right_key)]
        home_club, away_club = int(game.home_club_id), int(game.away_club_id)
        if link.swapped:
            home_club, away_club = away_club, home_club
        for team_id, club_id in ((match.home_team_id, home_club), (match.away_team_id, away_club)):
            sides.append(_Side(int(link.left_key), int(link.right_key), int(team_id), club_id))
            team_votes[int(team_id)][club_id] += 1
        if links.add(
            "matches", int(link.left_key), int(link.right_key), MATCHED_BY_DATE_TEAMS, 1.0
        ):
            report.matches_linked += 1

    for team_id, votes in team_votes.items():
        club_id, count = votes.most_common(1)[0]
        confidence = round(count / sum(votes.values()), 3)
        if links.add("teams", team_id, club_id, MATCHED_BY_MATCH_SIDE, confidence):
            report.teams_linked += 1
    return sides


# =========================================================================================
# Atletas por escalação
# =========================================================================================


def _link_by_lineup(
    session: Session, client: TransfermarktClient, sides: list[_Side]
) -> tuple[list[PlayerLink], set[str]]:
    if not sides:
        return [], set()

    lineups = _read_lineups(client, {side.game_id for side in sides})
    appearances = _statsbomb_appearances(session, {side.match_id for side in sides})
    lineup_groups = {key: group for key, group in lineups.groupby(["game_id", "club_id"])}
    appearance_groups = {key: group for key, group in appearances.groupby(["match_id", "team_id"])}

    all_links: list[PlayerLink] = []
    ambiguous: set[str] = set()
    for side in sides:
        ours = appearance_groups.get((side.match_id, side.team_id))
        theirs = lineup_groups.get((side.game_id, side.club_id))
        if ours is None or theirs is None:
            continue
        side_links, side_ambiguous = assign_players(
            [
                PlayerRecord(
                    str(row.player_id),
                    (row.name, row.full_name, row.nickname),
                    _as_int(row.jersey_number),
                )
                for row in ours.itertuples()
            ],
            [
                PlayerRecord(str(row.player_id), (row.player_name,), _as_int(row.number))
                for row in theirs.itertuples()
            ],
        )
        all_links.extend(side_links)
        ambiguous.update(side_ambiguous)
    return all_links, ambiguous


def _read_lineups(client: TransfermarktClient, game_ids: set[int]) -> pd.DataFrame:
    """Escalações só das partidas ligadas; a tabela inteira tem mais de 3 milhões de linhas."""
    chunks = pd.read_csv(
        client.path("game_lineups"),
        usecols=["game_id", "club_id", "player_id", "player_name", "number"],
        dtype={"number": "string"},
        chunksize=LINEUP_CHUNK_ROWS,
    )
    selected = [chunk[chunk.game_id.isin(game_ids)] for chunk in chunks]
    return pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()


# =========================================================================================
# Atletas por nome e nacionalidade
# =========================================================================================


@dataclass
class _CandidatePool:
    records: dict[str, PlayerRecord] = field(default_factory=dict)
    birth_dates: dict[str, date | None] = field(default_factory=dict)
    by_token: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # Atletas com jogos por seleção: desempatam homônimos exatos.
    capped: set[str] = field(default_factory=set)


@dataclass
class _Candidates:
    """Atletas do Transfermarkt indexados por país e, globalmente, por nome exato."""

    pools: dict[str, _CandidatePool] = field(default_factory=lambda: defaultdict(_CandidatePool))
    by_exact_name: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    records: dict[str, PlayerRecord] = field(default_factory=dict)
    birth_dates: dict[str, date | None] = field(default_factory=dict)


def _link_by_name_and_nationality(
    session: Session,
    client: TransfermarktClient,
    player_links: dict[int, int],
    links: _Links,
    report: LinkReport,
) -> None:
    """Liga por nome quem não tem escalação, e mede a precisão do método onde ela existe.

    Para os atletas já ligados por escalação, o método é aplicado como se eles não
    estivessem ligados, e a resposta é comparada com a ligação por escalação. Isso dá
    precisão e cobertura do método de reserva medidas sobre dados reais.
    """
    candidates = _read_candidates(client)
    players = _statsbomb_players(session)
    nationalities = _statsbomb_nationalities(session)
    report.players_total = len(players)
    taken = set(player_links.values())

    for row in players.itertuples():
        player_id = int(row.player_id)
        record = PlayerRecord(str(player_id), (row.name, row.full_name, row.nickname))
        proposal = _propose(record, nationalities.get(player_id, ()), row.first_match, candidates)

        if player_id in player_links:
            report.fallback_checked += 1
            if proposal is not None:
                report.fallback_proposed += 1
                report.fallback_agreed += int(int(proposal[0].key) == player_links[player_id])
            continue

        if proposal is None:
            report.review.append(_review(player_id, "sem candidato por nome e nacionalidade"))
            continue
        candidate, similarity, method = proposal
        tm_id = int(candidate.key)
        confidence = round(similarity * NAME_NATIONALITY_CONFIDENCE_FACTOR, 3)
        if tm_id in taken:
            report.review.append(
                _review(player_id, "candidato já ligado a outro atleta", tm_id, confidence)
            )
            continue
        if links.add("players", player_id, tm_id, method, confidence):
            player_links[player_id] = tm_id
            taken.add(tm_id)
            if method == MATCHED_BY_EXACT_NAME:
                report.players_by_exact_name += 1
            else:
                report.players_by_name += 1


def _propose(
    record: PlayerRecord,
    nationalities: Iterable[str],
    first_match: date,
    candidates: _Candidates,
) -> tuple[PlayerRecord, float, str] | None:
    """Candidato por nome, primeiro dentro do país e depois no dataset inteiro."""
    query_tokens = {token for name in record.names if is_name(name) for token in tokens(name)}
    by_nationality: dict[str, PlayerRecord] = {}
    preferred: set[str] = set()
    for nationality in nationalities:
        pool = candidates.pools.get(country_key(nationality))
        if pool is None:
            continue
        for key in set().union(*(pool.by_token.get(token, set()) for token in query_tokens)):
            if _plausible_age(pool.birth_dates.get(key), first_match):
                by_nationality[key] = pool.records[key]
                if key in pool.capped:
                    preferred.add(key)

    proposal = best_candidate(record, list(by_nationality.values()), frozenset(preferred))
    if proposal is not None:
        return proposal[0], proposal[1], MATCHED_BY_NAME_NATIONALITY
    return _propose_by_exact_name(record, first_match, candidates)


def _propose_by_exact_name(
    record: PlayerRecord, first_match: date, candidates: _Candidates
) -> tuple[PlayerRecord, float, str] | None:
    """Último recurso: nome idêntico e único no dataset inteiro.

    Resolve atletas que o Transfermarkt registra sem cidadania e sem país de nascimento —
    Haris Seferovic e Atiba Hutchinson não aparecem em nenhum grupo por país. A exigência de
    unicidade global segura os homônimos: "Fabinho" tem oito registros e segue sem ligação.
    """
    keys: set[str] = set()
    for name in record.names:
        if is_name(name):
            keys |= candidates.by_exact_name.get(compact(name), set())
    plausible = [
        key for key in keys if _plausible_age(candidates.birth_dates.get(key), first_match)
    ]
    if len(plausible) != 1:
        return None
    return candidates.records[plausible[0]], 1.0, MATCHED_BY_EXACT_NAME


def _read_candidates(client: TransfermarktClient) -> _Candidates:
    """Atletas do Transfermarkt agrupados por país e indexados por nome exato."""
    players = client.read(
        "players",
        usecols=[
            "player_id",
            "name",
            "first_name",
            "last_name",
            "country_of_citizenship",
            "country_of_birth",
            "date_of_birth",
            "international_caps",
        ],
        parse_dates=["date_of_birth"],
    )
    candidates = _Candidates()
    for row in players.itertuples():
        full = " ".join(part for part in (row.first_name, row.last_name) if isinstance(part, str))
        record = PlayerRecord(str(row.player_id), (_text(row.name), full or None))
        birth = None if pd.isna(row.date_of_birth) else row.date_of_birth.date()
        capped = not pd.isna(row.international_caps) and row.international_caps > 0
        candidates.records[record.key] = record
        candidates.birth_dates[record.key] = birth
        for name in record.names:
            if is_name(name):
                candidates.by_exact_name[compact(name)].add(record.key)

        countries = {
            country_key(value)
            for value in (row.country_of_citizenship, row.country_of_birth)
            if isinstance(value, str)
        }
        for country in countries:
            pool = candidates.pools[country]
            pool.records[record.key] = record
            pool.birth_dates[record.key] = birth
            if capped:
                pool.capped.add(record.key)
            for name in record.names:
                for token in tokens(name or ""):
                    pool.by_token[token].add(record.key)
    return candidates


def _plausible_age(birth: date | None, on: date) -> bool:
    if birth is None:
        return True
    age = (on - birth).days / 365.25
    return MIN_AGE_YEARS <= age <= MAX_AGE_YEARS


# =========================================================================================
# Leitura do banco
# =========================================================================================


def _statsbomb_matches(session: Session) -> pd.DataFrame:
    home, away = aliased(Team), aliased(Team)
    rows = session.execute(
        select(
            Match.id, Match.match_date, Match.home_team_id, Match.away_team_id, home.name, away.name
        )
        .join(ExternalId, (ExternalId.entity == "matches") & (ExternalId.entity_id == Match.id))
        .join(home, home.id == Match.home_team_id)
        .join(away, away.id == Match.away_team_id)
        .where(ExternalId.source == "statsbomb")
    ).all()
    return pd.DataFrame(
        rows, columns=["match_id", "match_date", "home_team_id", "away_team_id", "home", "away"]
    )


def _statsbomb_appearances(session: Session, match_ids: set[int]) -> pd.DataFrame:
    rows = session.execute(
        select(
            Appearance.match_id,
            Appearance.team_id,
            Appearance.player_id,
            Appearance.jersey_number,
            Player.name,
            Player.full_name,
            Player.nickname,
        )
        .join(Player, Player.id == Appearance.player_id)
        .where(Appearance.match_id.in_(match_ids))
    ).all()
    return pd.DataFrame(
        rows,
        columns=[
            "match_id",
            "team_id",
            "player_id",
            "jersey_number",
            "name",
            "full_name",
            "nickname",
        ],
    )


def _statsbomb_players(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            Player.id, Player.name, Player.full_name, Player.nickname, func.min(Match.match_date)
        )
        .join(Appearance, Appearance.player_id == Player.id)
        .join(Match, Match.id == Appearance.match_id)
        .group_by(Player.id)
    ).all()
    return pd.DataFrame(rows, columns=["player_id", "name", "full_name", "nickname", "first_match"])


def _statsbomb_nationalities(session: Session) -> dict[int, list[str]]:
    nationalities: dict[int, list[str]] = defaultdict(list)
    for player_id, name in session.execute(
        select(PlayerNationality.player_id, Country.name).join(
            Country, Country.id == PlayerNationality.country_id
        )
    ):
        nationalities[player_id].append(name)
    return nationalities


# =========================================================================================
# Gravação e utilitários
# =========================================================================================


class _Links:
    """Grava ligações sem sobrescrever as manuais nem duplicar entidade ou id externo."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self, entity: str, entity_id: int, source_id: int, matched_by: str, confidence: float
    ) -> bool:
        taken = self._session.scalar(
            select(func.count())
            .select_from(ExternalId)
            .where(
                ExternalId.entity == entity,
                ExternalId.source == SOURCE,
                (ExternalId.source_id == str(source_id)) | (ExternalId.entity_id == entity_id),
            )
        )
        if taken:
            return False
        self._session.add(
            ExternalId(
                entity=entity,
                entity_id=entity_id,
                source=SOURCE,
                source_id=str(source_id),
                matched_by=matched_by,
                confidence=confidence,
            )
        )
        self._session.flush()
        return True


def _review(
    player_id: int, reason: str, tm_id: int | None = None, confidence: float | None = None
) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "motivo": reason,
        "transfermarkt_player_id": tm_id,
        "confianca": confidence,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
