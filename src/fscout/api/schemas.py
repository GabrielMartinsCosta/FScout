"""Formatos de entrada e saída da API.

Separados dos modelos do banco de propósito: o que a interface consome não deve mudar
porque uma coluna mudou de nome.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from fscout.domain.enums import CompetitionType, HomeAway, PositionGroup
from fscout.metrics.context import Slice


class SliceIn(BaseModel):
    """Recorte de análise, no corpo de requisições POST."""

    competition_ids: list[int] = Field(default_factory=list)
    season_ids: list[int] = Field(default_factory=list)
    competition_types: list[CompetitionType] = Field(default_factory=list)
    team_ids: list[int] = Field(default_factory=list)
    opponent_team_ids: list[int] = Field(default_factory=list)
    position_groups: list[PositionGroup] = Field(default_factory=list)
    player_ids: list[int] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    home_away: HomeAway | None = None
    min_minutes: int | None = None
    label: str | None = None

    def to_slice(self) -> Slice:
        return Slice(
            player_ids=tuple(self.player_ids),
            team_ids=tuple(self.team_ids),
            opponent_team_ids=tuple(self.opponent_team_ids),
            competition_ids=tuple(self.competition_ids),
            competition_types=tuple(self.competition_types),
            season_ids=tuple(self.season_ids),
            position_groups=tuple(self.position_groups),
            date_from=self.date_from,
            date_to=self.date_to,
            home_away=self.home_away,
            min_minutes=self.min_minutes,
            label=self.label,
        )


class MetricDefinitionOut(BaseModel):
    """Uma linha do catálogo: a definição operacional da métrica."""

    key: str
    label: str
    family: str
    unit: str
    kind: str
    per_90: bool
    higher_is_better: bool
    positions: list[PositionGroup]
    min_sample: int = 0
    inputs: list[str] = Field(default_factory=list)
    description: str = ""


class MetricValueOut(BaseModel):
    """Valor de uma métrica para um atleta, com o que permite interpretá-lo."""

    key: str
    value: float | None
    per_90: float | None = None
    percentile: float | None = None
    population: int = 0
    sample: int = 0
    minutes: int = 0


class PlayerSummaryOut(BaseModel):
    id: int
    name: str
    full_name: str | None = None
    position_group: PositionGroup | None = None
    nationality: str | None = None
    age: int | None = None
    matches: int = 0
    minutes: int = 0


class ClubSpellOut(BaseModel):
    team: str
    start_date: date | None = None
    end_date: date | None = None


class PlayerProfileOut(PlayerSummaryOut):
    """Ficha do atleta, incluindo o que veio de fontes fora dos eventos."""

    birth_date: date | None = None
    height_cm: int | None = None
    preferred_foot: str | None = None
    birth_country: str | None = None
    nationalities: list[str] = Field(default_factory=list)
    market_value_eur: float | None = None
    market_value_date: date | None = None
    contract_until: date | None = None
    club_spells: list[ClubSpellOut] = Field(default_factory=list)


class SeasonOut(BaseModel):
    id: int
    name: str
    start_date: date | None = None
    end_date: date | None = None
    matches: int = 0


class CompetitionOut(BaseModel):
    id: int
    name: str
    type: CompetitionType
    country: str | None = None
    seasons: list[SeasonOut] = Field(default_factory=list)


class TeamOut(BaseModel):
    id: int
    name: str
    country: str | None = None
    is_national_team: bool = False


class ShotOut(BaseModel):
    """Uma finalização, com o que o mapa de chutes precisa desenhar."""

    match_date: date
    minute: int
    opponent: str | None = None
    x: float | None = None
    y: float | None = None
    end_y: float | None = None
    end_z: float | None = None
    outcome: str
    is_goal: bool
    shot_type: str
    body_part: str | None = None
    play_pattern: str | None = None
    distance_m: float | None = None
    xg: float | None = None
    goal_mouth_zone: str | None = None


class HeatmapCellOut(BaseModel):
    """Célula da grade do campo, base do mapa de calor."""

    grid_col: int
    grid_row: int
    actions: int


class EvaluateRequest(BaseModel):
    metrics: list[str]
    slice: SliceIn = Field(default_factory=SliceIn)
    player_ids: list[int] = Field(default_factory=list)


class PlayerMetricsOut(BaseModel):
    player: PlayerSummaryOut
    values: dict[str, MetricValueOut]


class CompareRequest(BaseModel):
    """Comparação de N atletas em M métricas sob K recortes.

    Recortes diferentes para os mesmos atletas é o que permite "2024 contra 2025".
    """

    player_ids: list[int]
    metrics: list[str]
    slices: list[SliceIn] = Field(default_factory=lambda: [SliceIn()])


class ComparisonCellOut(BaseModel):
    slice_label: str
    player: PlayerSummaryOut
    values: dict[str, MetricValueOut]


class CompareOut(BaseModel):
    definitions: list[MetricDefinitionOut]
    cells: list[ComparisonCellOut]
