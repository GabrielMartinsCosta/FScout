"""Gravação de partidas no banco.

Três garantias sustentam o resto do sistema:

- **Idempotência.** Recarregar uma partida apaga e regrava seus fatos na mesma transação.
  O banco nunca fica com metade de uma partida, nem com uma partida em dobro.
- **Identidade entre fontes.** Atleta, clube, competição e partida são resolvidos via
  `external_ids`. A mesma fonte sempre cai no mesmo registro canônico.
- **Fonte dona do registro.** A fonte que criou um registro pode atualizá-lo. Uma fonte
  ligada depois só preenche campos vazios, para não sobrescrever dado de outra origem.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from fscout.db.base import Base
from fscout.db.models import (
    Appearance,
    Competition,
    DefensiveAction,
    DisciplinaryAction,
    Dribble,
    Event,
    ExternalId,
    GoalkeeperAction,
    Match,
    Pass,
    Player,
    PlayerClubSpell,
    PlayerNationality,
    Season,
    Shot,
    Team,
)
from fscout.domain.enums import PositionGroup
from fscout.ingestion.bundle import MatchBundle, Row
from fscout.linking.countries import CountryResolver
from fscout.linking.venues import VenueResolver

MATCHED_BY_CREATED = "created"
DERIVED_SOURCE = "derived"
PROJECTIONS = (Shot, Pass, Dribble, DefensiveAction, GoalkeeperAction, DisciplinaryAction)

# SQLite limita variáveis por consulta; lotes de 500 ficam longe do limite.
IN_CLAUSE_CHUNK = 500

T = TypeVar("T")
RefMap = Mapping[str, tuple[str, Mapping[str, int]]]


@dataclass(frozen=True)
class MatchLoadResult:
    match_id: int
    events: int
    player_ids: frozenset[int]


class Loader:
    """Grava as linhas de uma fonte, resolvendo identidades e referências."""

    def __init__(self, session: Session, source: str) -> None:
        self._session = session
        self._source = source
        self._entity_ids: dict[tuple[str, str], int] = {}
        self._countries = CountryResolver(session)
        self._venues = VenueResolver(session, self._countries)
        self._nationalities: set[tuple[int, int]] = set()

    # ------------------------------------------------------------------------------------
    # Identidade
    # ------------------------------------------------------------------------------------

    def resolve(self, model: type[Base], row: Row) -> int:
        """Id canônico da entidade descrita por `row`, criando-a na primeira vez."""
        source_id = row["source_id"]
        attributes = {key: value for key, value in row.items() if key != "source_id"}
        entity = model.__tablename__
        cache_key = (entity, source_id)
        if cache_key in self._entity_ids:
            return self._entity_ids[cache_key]

        link = self._session.scalar(
            select(ExternalId).where(
                ExternalId.entity == entity,
                ExternalId.source == self._source,
                ExternalId.source_id == source_id,
            )
        )
        if link is None:
            instance = model(**attributes)
            self._session.add(instance)
            self._session.flush()
            entity_id: int = instance.id  # type: ignore[attr-defined]
            self._session.add(
                ExternalId(
                    entity=entity,
                    entity_id=entity_id,
                    source=self._source,
                    source_id=source_id,
                    matched_by=MATCHED_BY_CREATED,
                )
            )
        else:
            entity_id = link.entity_id
            instance = self._session.get(model, entity_id)
            owns_record = link.matched_by == MATCHED_BY_CREATED
            for name, value in attributes.items():
                if value is not None and (owns_record or getattr(instance, name) is None):
                    setattr(instance, name, value)

        self._session.flush()
        self._entity_ids[cache_key] = entity_id
        return entity_id

    def existing_ids(self, model: type[Base], source_ids: Iterable[str]) -> set[str]:
        """Quais identificadores desta fonte já têm registro canônico."""
        found: set[str] = set()
        for chunk in _chunks(list(source_ids), IN_CLAUSE_CHUNK):
            found.update(
                self._session.scalars(
                    select(ExternalId.source_id).where(
                        ExternalId.entity == model.__tablename__,
                        ExternalId.source == self._source,
                        ExternalId.source_id.in_(chunk),
                    )
                )
            )
        return found

    def country_id(self, name: str | None) -> int | None:
        """Id canônico do país, unificando grafias de fontes diferentes."""
        return self._countries.resolve(name)

    # ------------------------------------------------------------------------------------
    # Dimensões de competição
    # ------------------------------------------------------------------------------------

    def load_competition(self, row: Row) -> int:
        return self.resolve(Competition, _swap(row, "country_ref", "country_id", self.country_id))

    def load_season(self, row: Row, competition_id: int) -> int:
        return self.resolve(Season, {**row, "competition_id": competition_id})

    # ------------------------------------------------------------------------------------
    # Partida
    # ------------------------------------------------------------------------------------

    def replace_match(self, bundle: MatchBundle, season_id: int) -> MatchLoadResult:
        """Grava a partida, substituindo por inteiro qualquer carga anterior dela."""
        session = self._session
        team_ids = {
            ref: self.resolve(Team, _swap(row, "country_ref", "country_id", self.country_id))
            for ref, row in bundle.teams.items()
        }

        player_ids: dict[str, int] = {}
        for ref, row in bundle.players.items():
            attributes = {key: value for key, value in row.items() if key != "nationality_ref"}
            player_id = self.resolve(Player, attributes)
            player_ids[ref] = player_id
            country_id = self.country_id(row.get("nationality_ref"))
            if country_id is not None:
                self._ensure_nationality(player_id, country_id)

        match_attributes = {
            key: value
            for key, value in bundle.match.items()
            if key not in ("season_ref", "home_team_ref", "away_team_ref", "venue_country")
        }
        match_attributes.update(
            season_id=season_id,
            venue_id=self._venues.resolve(
                bundle.match.get("stadium"), bundle.match.get("venue_country")
            ),
            home_team_id=team_ids[bundle.match["home_team_ref"]],
            away_team_id=team_ids[bundle.match["away_team_ref"]],
        )
        match_id = self.resolve(Match, match_attributes)
        self._delete_match_facts(match_id)

        match_scope = {"match_id": match_id}
        _bulk_insert(
            session,
            Appearance,
            bundle.appearances,
            match_scope,
            {
                "player_ref": ("player_id", player_ids),
                "team_ref": ("team_id", team_ids),
                "opponent_team_ref": ("opponent_team_id", team_ids),
            },
        )
        _bulk_insert(
            session,
            Event,
            bundle.events,
            {**match_scope, "source": self._source},
            {
                "team_ref": ("team_id", team_ids),
                "player_ref": ("player_id", player_ids),
                "possession_team_ref": ("possession_team_id", team_ids),
            },
        )
        event_ids: dict[str, int] = dict(
            session.execute(select(Event.source_id, Event.id).where(Event.match_id == match_id))
            .tuples()
            .all()
        )

        common: RefMap = {
            "event_ref": ("event_id", event_ids),
            "player_ref": ("player_id", player_ids),
        }
        projections: Sequence[tuple[type[Base], list[Row], RefMap]] = (
            (Shot, bundle.shots, {"key_pass_ref": ("key_pass_event_id", event_ids)}),
            (Pass, bundle.passes, {"recipient_ref": ("recipient_player_id", player_ids)}),
            (Dribble, bundle.dribbles, {}),
            (DefensiveAction, bundle.defensive_actions, {}),
            (
                GoalkeeperAction,
                bundle.goalkeeper_actions,
                {"shot_ref": ("shot_event_id", event_ids)},
            ),
            (DisciplinaryAction, bundle.disciplinary_actions, {}),
        )
        for model, rows, extra_refs in projections:
            _bulk_insert(session, model, rows, match_scope, {**common, **extra_refs})

        return MatchLoadResult(
            match_id=match_id,
            events=len(bundle.events),
            player_ids=frozenset(player_ids.values()),
        )

    def _delete_match_facts(self, match_id: int) -> None:
        for model in PROJECTIONS:
            self._session.execute(delete(model).where(model.match_id == match_id))
        self._session.execute(delete(Event).where(Event.match_id == match_id))
        self._session.execute(delete(Appearance).where(Appearance.match_id == match_id))

    def _ensure_nationality(self, player_id: int, country_id: int) -> None:
        key = (player_id, country_id)
        if key in self._nationalities:
            return
        existing = self._session.scalars(
            select(PlayerNationality.country_id).where(PlayerNationality.player_id == player_id)
        ).all()
        if country_id not in existing:
            self._session.add(
                PlayerNationality(
                    player_id=player_id, country_id=country_id, is_primary=not existing
                )
            )
        self._nationalities.add(key)


# =========================================================================================
# Derivações pós-carga
# =========================================================================================


def refresh_season_dates(session: Session, season_id: int) -> None:
    """Início e fim da temporada a partir das partidas carregadas."""
    first, last = session.execute(
        select(func.min(Match.match_date), func.max(Match.match_date)).where(
            Match.season_id == season_id
        )
    ).one()
    season = session.get(Season, season_id)
    if season is not None:
        season.start_date, season.end_date = first, last


def refresh_player_profiles(session: Session, player_ids: Iterable[int]) -> None:
    """Recalcula posição principal e histórico de clubes dos atletas afetados.

    Considera todas as participações do atleta, de qualquer competição já carregada, e
    não só as da carga atual.
    """
    for chunk in _chunks(sorted(set(player_ids)), IN_CLAUSE_CHUNK):
        _refresh_position_groups(session, chunk)
        _refresh_club_spells(session, chunk)


def _refresh_position_groups(session: Session, player_ids: Sequence[int]) -> None:
    """Posição principal: o grupo em que o atleta acumulou mais minutos."""
    totals = session.execute(
        select(Appearance.player_id, Appearance.position_group, func.sum(Appearance.minutes_played))
        .where(
            Appearance.player_id.in_(player_ids),
            Appearance.position_group.is_not(None),
            Appearance.position_group != PositionGroup.UNKNOWN,
        )
        .group_by(Appearance.player_id, Appearance.position_group)
    ).all()

    best: dict[int, tuple[int, PositionGroup]] = {}
    for player_id, group, minutes in totals:
        if player_id not in best or minutes > best[player_id][0]:
            best[player_id] = (minutes, group)
    for player_id, (_, group) in best.items():
        player = session.get(Player, player_id)
        if player is not None:
            player.primary_position_group = group


def _refresh_club_spells(session: Session, player_ids: Sequence[int]) -> None:
    """Histórico de clubes derivado: primeira e última partida observada por clube.

    Seleções ficam de fora. Duas passagens pelo mesmo clube, separadas por outro, se
    fundem numa só — limitação aceitável enquanto não houver fonte de transferências.
    """
    session.execute(
        delete(PlayerClubSpell).where(
            PlayerClubSpell.player_id.in_(player_ids), PlayerClubSpell.source == DERIVED_SOURCE
        )
    )
    spells: list[tuple[int, int, date, date]] = [
        tuple(row)  # type: ignore[misc]
        for row in session.execute(
            select(
                Appearance.player_id,
                Appearance.team_id,
                func.min(Match.match_date),
                func.max(Match.match_date),
            )
            .join(Match, Match.id == Appearance.match_id)
            .join(Team, Team.id == Appearance.team_id)
            .where(Appearance.player_id.in_(player_ids), Team.is_national_team.is_(False))
            .group_by(Appearance.player_id, Appearance.team_id)
        ).all()
    ]
    if spells:
        session.execute(
            insert(PlayerClubSpell),
            [
                {
                    "player_id": player_id,
                    "team_id": team_id,
                    "start_date": first,
                    "end_date": last,
                    "source": DERIVED_SOURCE,
                }
                for player_id, team_id, first, last in spells
            ],
        )


# =========================================================================================
# Utilitários
# =========================================================================================


def _swap(row: Row, ref_key: str, column: str, resolver: Callable[[Any], Any]) -> Row:
    swapped = {key: value for key, value in row.items() if key != ref_key}
    swapped[column] = resolver(row.get(ref_key))
    return swapped


def _resolve_refs(row: Row, fixed: Mapping[str, Any], refs: RefMap) -> Row:
    """Troca cada chave `*_ref` pelo id canônico correspondente.

    Referência sem correspondente levanta `KeyError` de propósito: significa que o
    mapeador citou algo que não entregou, e gravar `NULL` esconderia o erro.
    """
    resolved = dict(fixed)
    for key, value in row.items():
        if key in refs:
            column, ids = refs[key]
            resolved[column] = None if value is None else ids[value]
        else:
            resolved[key] = value
    return resolved


def _bulk_insert(
    session: Session,
    model: type[Base],
    rows: Sequence[Row],
    fixed: Mapping[str, Any],
    refs: RefMap,
) -> None:
    if rows:
        session.execute(insert(model), [_resolve_refs(row, fixed, refs) for row in rows])


def _chunks(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
