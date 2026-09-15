"""Schema do FScout.

Organização em quatro partes:

1. **Dimensões** — país, competição, temporada, clube, atleta, partida, participação.
   Respondem "quem, onde, quando" e sustentam todos os recortes pedidos
   (por campeonato, por janela de datas, por adversário, casa/fora).

2. **Identidade entre fontes** — `external_ids`. Uma entidade canônica (o atleta Messi)
   tem um id em cada fonte que a descreve. As dimensões não guardam origem; a tabela de
   ligação guarda, junto com a forma como cada ligação foi estabelecida.

3. **Fato** — `events`, uma linha por ação registrada em campo. É a tabela canônica de
   ações: nada é apagado dela, e o JSON `qualifiers` guarda tudo que ainda não foi
   traduzido para coluna. Isso permite criar métricas novas depois sem reingerir nada.

4. **Projeções** — `shots`, `passes`, `dribbles`, `defensive_actions`,
   `goalkeeper_actions`, `disciplinary_actions`. Cada uma é uma visão tipada e indexada
   de uma família de eventos.

Por que projeções em vez de consultar o JSON direto? Porque quase toda métrica pedida é
um filtro sobre poucos atributos de uma família ("gol de canhota, de fora da área, vindo
de escanteio" são três colunas de `shots` mais uma de `events`). Em colunas tipadas e
indexadas isso é um WHERE trivial; dentro de um blob JSON, em SQLite, é varredura completa.
O custo é um mapeamento mecânico na ingestão, pago uma vez.

O que deliberadamente **não** existe aqui: colunas do tipo `gols_canhota_fora_da_area`.
Estatística derivada não é coluna — é consulta. O catálogo dessas consultas vive em
`fscout.metrics`.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fscout.db.base import Base, SourceRefMixin, TimestampMixin, enum_column
from fscout.domain.enums import (
    BodyPart,
    CardType,
    CompetitionType,
    DefensiveActionType,
    DribbleOutcome,
    DuelOutcome,
    DuelType,
    EventType,
    Foot,
    GoalkeeperActionType,
    GoalkeeperOutcome,
    GoalkeeperTechnique,
    HomeAway,
    PassHeight,
    PassOutcome,
    PassTechnique,
    PassType,
    PlayPattern,
    PositionGroup,
    ShotOutcome,
    ShotTechnique,
    ShotType,
)
from fscout.domain.pitch import GoalMouthZone, Lane, VerticalThird

# =========================================================================================
# Dimensões
# =========================================================================================


class Country(Base):
    """País, usado para nacionalidade do atleta e sede da competição.

    Guarda o centroide geográfico porque a visão de mapa-múndi precisa posicionar um
    marcador por país sem depender de serviço externo de geocodificação em tempo real.
    """

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    iso3: Mapped[str | None] = mapped_column(String(3), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class Competition(Base):
    """Competição. O campo `type` sustenta os recortes nacional/estadual/continental."""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id"))
    type: Mapped[CompetitionType] = enum_column(
        CompetitionType, default=CompetitionType.UNKNOWN, index=True
    )
    gender: Mapped[str | None] = mapped_column(String(16))
    is_youth: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    country: Mapped[Country | None] = relationship()
    seasons: Mapped[list[Season]] = relationship(back_populates="competition")


class Season(Base):
    """Temporada de uma competição."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    competition: Mapped[Competition] = relationship(back_populates="seasons")


class Team(Base):
    """Clube ou seleção."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    short_name: Mapped[str | None] = mapped_column(String(48))
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id"))
    gender: Mapped[str | None] = mapped_column(String(16))
    is_national_team: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    country: Mapped[Country | None] = relationship()


class Player(Base):
    """Atleta.

    Só os atributos estáveis da pessoa ficam aqui. Tudo que varia no tempo — clube,
    posição jogada, valor de mercado — vive em tabelas próprias com vigência.

    Cada fonte preenche o que tem: a StatsBomb traz nome e nacionalidade, mas não data de
    nascimento, altura, peso nem pé preferencial. Esses campos ficam nulos até que uma
    fonte biográfica seja ligada ao mesmo atleta via `external_ids`.
    """

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    full_name: Mapped[str | None] = mapped_column(String(192), index=True)
    nickname: Mapped[str | None] = mapped_column(String(96))
    birth_date: Mapped[date | None] = mapped_column(Date)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[int | None] = mapped_column(Integer)
    # Nascer num país não é ter cidadania dele: fica separado de `nationalities`.
    birth_country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id"))
    preferred_foot: Mapped[Foot | None] = enum_column(Foot, nullable=True)
    primary_position_group: Mapped[PositionGroup | None] = enum_column(
        PositionGroup, nullable=True, index=True
    )

    nationalities: Mapped[list[PlayerNationality]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    club_spells: Mapped[list[PlayerClubSpell]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )

    @property
    def age(self) -> int | None:
        """Idade em anos completos na data de hoje."""
        if self.birth_date is None:
            return None
        today = date.today()
        had_birthday = (today.month, today.day) >= (self.birth_date.month, self.birth_date.day)
        return today.year - self.birth_date.year - (0 if had_birthday else 1)


class PlayerNationality(Base):
    """Nacionalidade do atleta. Tabela separada porque dupla cidadania é comum."""

    __tablename__ = "player_nationalities"
    __table_args__ = (UniqueConstraint("player_id", "country_id", name="uq_player_nationality"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)

    player: Mapped[Player] = relationship(back_populates="nationalities")
    country: Mapped[Country] = relationship()


class PlayerClubSpell(Base):
    """Passagem do atleta por um clube: o histórico de clubes pedido.

    Com `source = "derived"`, as datas são a primeira e a última partida observada nos
    dados carregados, não as datas contratuais. Fontes de transferências gravam com a
    própria origem, e aí `end_date` nulo significa vínculo vigente.
    """

    __tablename__ = "player_club_spells"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_loan: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32), default="derived", index=True)

    player: Mapped[Player] = relationship(back_populates="club_spells")
    team: Mapped[Team] = relationship()


class Venue(Base):
    """Estádio.

    Entidade própria, e não um texto na partida, porque a coordenada é obtida uma vez por
    estádio e compartilhada por todas as partidas disputadas nele.
    """

    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(192), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id"))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Proveniência da coordenada: busca automática ou correção manual.
    geocode_source: Mapped[str | None] = mapped_column(String(32))
    geocode_query: Mapped[str | None] = mapped_column(String(256))
    osm_type: Mapped[str | None] = mapped_column(String(16))
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    geocoded_as_stadium: Mapped[bool] = mapped_column(Boolean, default=False)

    country: Mapped[Country | None] = relationship()


class MatchWeather(Base):
    """Condição meteorológica durante a partida (definição em `fscout.ingestion.weather`)."""

    __tablename__ = "match_weather"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity_pct: Mapped[float | None] = mapped_column(Float)
    precipitation_mm: Mapped[float | None] = mapped_column(Float)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class Match(Base):
    """Partida."""

    __tablename__ = "matches"
    __table_args__ = (Index("ix_match_season_date", "season_id", "match_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    match_date: Mapped[date] = mapped_column(Date, index=True)
    # Início em UTC: conferido contra horários oficiais de Copa do Mundo 2022, Copa América
    # 2024 e Euro 2024. `match_date` também é a data em UTC.
    kickoff: Mapped[datetime | None] = mapped_column(DateTime)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str | None] = mapped_column(String(64))
    stadium: Mapped[str | None] = mapped_column(String(128))
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"), index=True)
    referee: Mapped[str | None] = mapped_column(String(96))
    attendance: Mapped[int | None] = mapped_column(Integer)
    is_neutral_venue: Mapped[bool] = mapped_column(Boolean, default=False)

    season: Mapped[Season] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class Appearance(Base):
    """Participação de um atleta numa partida.

    `opponent_team_id` e `home_away` são desnormalizados de propósito. Sem eles, "estatísticas
    contra o time X" e "desempenho fora de casa" exigiriam dois JOINs em `matches` com
    CASE para descobrir de que lado o jogador estava — em toda consulta do sistema.
    Com eles, viram um WHERE indexado. A duplicação é segura porque o valor é derivado
    na ingestão e nunca editado depois.

    `minutes_played` é nominal (um jogo inteiro vale 90) e é a base de toda normalização
    por 90 minutos. `seconds_on_pitch` é o tempo efetivo, com acréscimos.
    """

    __tablename__ = "appearances"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_appearance"),
        Index("ix_appearance_player_opponent", "player_id", "opponent_team_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    opponent_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    home_away: Mapped[HomeAway] = enum_column(HomeAway, default=HomeAway.UNKNOWN, index=True)

    position: Mapped[str | None] = mapped_column(String(48))
    position_group: Mapped[PositionGroup | None] = enum_column(
        PositionGroup, nullable=True, index=True
    )
    jersey_number: Mapped[int | None] = mapped_column(Integer)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False)
    minute_on: Mapped[int | None] = mapped_column(Integer)
    minute_off: Mapped[int | None] = mapped_column(Integer)
    minutes_played: Mapped[int] = mapped_column(Integer, default=0)
    seconds_on_pitch: Mapped[int] = mapped_column(Integer, default=0)

    # Placar do ponto de vista do jogador: evita recalcular clean sheet a cada consulta.
    goals_for: Mapped[int | None] = mapped_column(Integer)
    goals_against: Mapped[int | None] = mapped_column(Integer)

    match: Mapped[Match] = relationship()
    player: Mapped[Player] = relationship()
    team: Mapped[Team] = relationship(foreign_keys=[team_id])
    opponent_team: Mapped[Team] = relationship(foreign_keys=[opponent_team_id])


# =========================================================================================
# Identidade entre fontes
# =========================================================================================


class ExternalId(Base, TimestampMixin):
    """Identificador de uma entidade canônica numa fonte de dados.

    Cada fonte numera atletas, clubes e partidas do seu jeito. Esta tabela liga cada
    número externo à entidade do FScout, o que permite combinar fontes sem duplicar
    ninguém: a StatsBomb cria o atleta, e uma fonte biográfica carregada depois se liga
    ao mesmo registro e preenche data de nascimento e altura.

    `matched_by` registra como a ligação foi estabelecida — `created` (a fonte criou o
    registro), `exact_id`, `name_birthdate`, `manual` —, e `confidence` quantifica
    ligações inferidas. Isso torna o cruzamento entre fontes auditável: para qualquer
    atleta é possível mostrar de onde veio cada dado e por que dois registros foram
    considerados a mesma pessoa.

    `entity` é o nome da tabela. Não há chave estrangeira real porque a tabela serve a
    várias entidades; a integridade é garantida pela camada de carga.
    """

    __tablename__ = "external_ids"
    __table_args__ = (
        UniqueConstraint("entity", "source", "source_id", name="uq_external_id"),
        Index("ix_external_id_entity", "entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    matched_by: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


# =========================================================================================
# Fato: eventos
# =========================================================================================


class Event(Base, SourceRefMixin):
    """Uma ação registrada em campo. Tabela canônica de ações.

    Campos comuns a todo tipo de evento ficam em colunas; o que é específico de um tipo
    vai para a projeção correspondente, e o restante permanece em `qualifiers`. Nada
    vindo da fonte é descartado, então uma métrica pensada daqui a seis meses pode ser
    calculada sobre os dados já carregados.

    Os índices são poucos de propósito: cada índice encarece a carga de centenas de
    milhares de linhas, e as consultas analíticas partem quase sempre de atleta ou de
    partida, que os índices compostos já cobrem pelo prefixo.
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_event_source"),
        Index("ix_event_match_sequence", "match_id", "period", "sequence"),
        Index("ix_event_player_type", "player_id", "type"),
        Index("ix_event_team_type", "team_id", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))

    sequence: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    minute: Mapped[int] = mapped_column(Integer)
    second: Mapped[int] = mapped_column(Integer, default=0)

    type: Mapped[EventType] = enum_column(EventType, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    position: Mapped[str | None] = mapped_column(String(48))

    # Localização de origem. Nula em eventos sem posição (substituição, fim de tempo).
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)

    # Zonas pré-calculadas a partir de (x, y). Gravadas na ingestão porque mapa de calor
    # e recorte por setor de campo são consultados o tempo todo e a derivação é imutável.
    third: Mapped[VerticalThird | None] = enum_column(VerticalThird, nullable=True)
    lane: Mapped[Lane | None] = enum_column(Lane, nullable=True)
    grid_col: Mapped[int | None] = mapped_column(Integer)
    grid_row: Mapped[int | None] = mapped_column(Integer)

    play_pattern: Mapped[PlayPattern | None] = enum_column(PlayPattern, nullable=True, index=True)
    possession: Mapped[int | None] = mapped_column(Integer)
    possession_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))

    duration: Mapped[float | None] = mapped_column(Float)
    under_pressure: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tudo que a fonte trouxe e ainda não virou coluna, exceto os freeze frames de chute
    # (posição dos 22 jogadores no momento da finalização). Eles multiplicam o tamanho do
    # banco e continuam disponíveis no cache bruto em data/raw.
    qualifiers: Mapped[dict | None] = mapped_column(JSON)

    match: Mapped[Match] = relationship()
    player: Mapped[Player | None] = relationship()
    team: Mapped[Team | None] = relationship(foreign_keys=[team_id])


# =========================================================================================
# Projeções tipadas por família de evento
# =========================================================================================


class Shot(Base):
    """Finalização.

    Cobre a lista de recortes de gol pedida: pé usado, cabeça, dentro ou fora da área,
    pequena área, pênalti, falta, acrobacia, origem em escanteio ou cruzamento, canto
    do gol atingido, e o aproveitamento derivado de `outcome`.

    Cobranças da disputa de pênaltis ficam marcadas com `is_shootout`: são finalizações
    reais, úteis para a análise de cobrança, mas não são gols do atleta.
    """

    __tablename__ = "shots"
    __table_args__ = (
        Index("ix_shot_goal_bodypart", "is_goal", "body_part"),
        Index("ix_shot_type_outcome", "shot_type", "outcome"),
    )

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    shot_type: Mapped[ShotType] = enum_column(ShotType, default=ShotType.UNKNOWN, index=True)
    outcome: Mapped[ShotOutcome] = enum_column(ShotOutcome, default=ShotOutcome.UNKNOWN, index=True)
    technique: Mapped[ShotTechnique | None] = enum_column(ShotTechnique, nullable=True)
    body_part: Mapped[BodyPart | None] = enum_column(BodyPart, nullable=True, index=True)

    # Desfechos derivados de `outcome`, materializados porque aparecem em quase toda métrica.
    is_goal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_on_target: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    hit_post: Mapped[bool] = mapped_column(Boolean, default=False)
    was_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shootout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Geometria da finalização.
    distance_m: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float | None] = mapped_column(Float)
    in_penalty_area: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    in_six_yard_box: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Ponto de chegada e o canto do gol correspondente.
    end_x: Mapped[float | None] = mapped_column(Float)
    end_y: Mapped[float | None] = mapped_column(Float)
    end_z: Mapped[float | None] = mapped_column(Float)
    goal_mouth_zone: Mapped[GoalMouthZone | None] = enum_column(GoalMouthZone, nullable=True)

    first_time: Mapped[bool] = mapped_column(Boolean, default=False)
    follows_dribble: Mapped[bool] = mapped_column(Boolean, default=False)
    open_goal: Mapped[bool] = mapped_column(Boolean, default=False)
    deflected: Mapped[bool] = mapped_column(Boolean, default=False)
    one_on_one: Mapped[bool] = mapped_column(Boolean, default=False)

    xg: Mapped[float | None] = mapped_column(Float)

    # Passe que gerou a finalização; liga assistência a gol e origem em cruzamento.
    key_pass_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


class Pass(Base):
    """Passe, incluindo cruzamentos e cobranças de bola parada.

    `is_progressive`, `into_penalty_area` e `into_six_yard_box` são geométricos: valem
    para a tentativa. O recorte "passes progressivos certos" combina com `is_complete`.
    """

    __tablename__ = "passes"
    __table_args__ = (
        Index("ix_pass_player_complete", "player_id", "is_complete"),
        Index("ix_pass_assist", "is_goal_assist"),
    )

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    recipient_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)

    end_x: Mapped[float | None] = mapped_column(Float)
    end_y: Mapped[float | None] = mapped_column(Float)
    length_m: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float | None] = mapped_column(Float)
    length_bucket: Mapped[str | None] = mapped_column(String(16), index=True)
    direction: Mapped[str | None] = mapped_column(String(16), index=True)

    height: Mapped[PassHeight | None] = enum_column(PassHeight, nullable=True)
    pass_type: Mapped[PassType] = enum_column(PassType, default=PassType.OPEN_PLAY, index=True)
    technique: Mapped[PassTechnique | None] = enum_column(PassTechnique, nullable=True)
    body_part: Mapped[BodyPart | None] = enum_column(BodyPart, nullable=True, index=True)
    outcome: Mapped[PassOutcome] = enum_column(PassOutcome, default=PassOutcome.COMPLETE)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    is_cross: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    is_through_ball: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cutback: Mapped[bool] = mapped_column(Boolean, default=False)
    is_progressive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    into_penalty_area: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    into_six_yard_box: Mapped[bool] = mapped_column(Boolean, default=False)

    # Cadeia de criação. `is_shot_assist` inclui o passe que virou gol.
    is_shot_assist: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_goal_assist: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pre_assist: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


class Dribble(Base):
    """Drible (um contra um com a bola dominada)."""

    __tablename__ = "dribbles"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    outcome: Mapped[DribbleOutcome] = enum_column(
        DribbleOutcome, default=DribbleOutcome.UNKNOWN, index=True
    )
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    nutmeg: Mapped[bool] = mapped_column(Boolean, default=False)
    overrun: Mapped[bool] = mapped_column(Boolean, default=False)
    in_penalty_area: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Consequência do drible na mesma posse, resolvida na ingestão (ver `chains.py`).
    # Materializa "quantas grandes jogadas nasceram de um drible" sem recursão em consulta.
    led_to_shot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    led_to_goal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    led_to_key_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    led_to_assist: Mapped[bool] = mapped_column(Boolean, default=False)
    led_to_pre_assist: Mapped[bool] = mapped_column(Boolean, default=False)
    drew_foul: Mapped[bool] = mapped_column(Boolean, default=False)

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


class DefensiveAction(Base):
    """Ação defensiva ou duelo, normalizados num eixo único.

    Desarme, interceptação, corte, bloqueio, recuperação, pressão e duelo aéreo chegam
    como tipos distintos na fonte. Unificá-los aqui permite compor índices defensivos
    agregados sem uma UNION de seis tabelas.

    Um evento pode gerar mais de uma linha: um corte de cabeça que venceu a disputa pelo
    alto é, ao mesmo tempo, um corte e um duelo aéreo ganho. Daí a chave própria e a
    unicidade por `(event_id, action_type)`.

    `is_successful` é nulo quando a ação não tem desfecho (pressão).
    """

    __tablename__ = "defensive_actions"
    __table_args__ = (
        UniqueConstraint("event_id", "action_type", name="uq_defensive_event_action"),
        Index("ix_defensive_player_type", "player_id", "action_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    action_type: Mapped[DefensiveActionType] = enum_column(DefensiveActionType, index=True)
    duel_type: Mapped[DuelType | None] = enum_column(DuelType, nullable=True)
    duel_outcome: Mapped[DuelOutcome | None] = enum_column(DuelOutcome, nullable=True)
    is_successful: Mapped[bool | None] = mapped_column(Boolean, index=True)
    is_aerial: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    in_own_penalty_area: Mapped[bool] = mapped_column(Boolean, default=False)

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


class GoalkeeperAction(Base):
    """Ação de goleiro: defesa, saída, encaixe, soco, defesa de pênalti."""

    __tablename__ = "goalkeeper_actions"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    action_type: Mapped[GoalkeeperActionType] = enum_column(GoalkeeperActionType, index=True)
    outcome: Mapped[GoalkeeperOutcome | None] = enum_column(GoalkeeperOutcome, nullable=True)
    technique: Mapped[GoalkeeperTechnique | None] = enum_column(GoalkeeperTechnique, nullable=True)
    body_part: Mapped[BodyPart | None] = enum_column(BodyPart, nullable=True)

    is_save: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_penalty_save: Mapped[bool] = mapped_column(Boolean, default=False)
    conceded_goal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    gave_rebound: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sweeper: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shootout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Atributos do chute enfrentado, copiados do evento de finalização correspondente.
    # Sustentam "defesas de fora da área" e "gols evitados" (soma de xG menos gols sofridos).
    shot_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    shot_distance_m: Mapped[float | None] = mapped_column(Float)
    shot_from_outside_box: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    shot_goal_mouth_zone: Mapped[GoalMouthZone | None] = enum_column(GoalMouthZone, nullable=True)
    shot_xg: Mapped[float | None] = mapped_column(Float)

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


class DisciplinaryAction(Base):
    """Falta cometida, falta sofrida e cartão.

    Os recortes de campo são nulos quando o evento não tem localização — cartão por
    reclamação, por exemplo, é registrado sem coordenada.
    """

    __tablename__ = "disciplinary_actions"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)

    is_foul_committed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_foul_won: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    card: Mapped[CardType | None] = enum_column(CardType, nullable=True, index=True)
    foul_type: Mapped[str | None] = mapped_column(String(32))

    # Recortes pedidos: cartão no campo de ataque x de defesa, falta perto da própria área.
    in_own_half: Mapped[bool | None] = mapped_column(Boolean, index=True)
    near_own_penalty_area: Mapped[bool | None] = mapped_column(Boolean)
    conceded_penalty: Mapped[bool] = mapped_column(Boolean, default=False)
    won_penalty: Mapped[bool] = mapped_column(Boolean, default=False)

    event: Mapped[Event] = relationship(foreign_keys=[event_id])


# =========================================================================================
# Dados de fonte externa (CSV do clube, planilha manual, fontes biográficas)
# =========================================================================================


class Injury(Base):
    """Lesão do atleta.

    Nenhum provedor aberto de eventos registra lesão; a alimentação vem de outra fonte.
    A tabela existe desde já para que o histórico de disponibilidade possa ser cruzado
    com a minutagem sem alteração de schema depois.
    """

    __tablename__ = "injuries"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    description: Mapped[str | None] = mapped_column(String(192))
    body_area: Mapped[str | None] = mapped_column(String(64), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    days_out: Mapped[int | None] = mapped_column(Integer)
    matches_missed: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="manual")

    player: Mapped[Player] = relationship()


class PlayerValuation(Base):
    """Valor de mercado e situação contratual numa data.

    Série temporal em vez de campo único no atleta: valor de mercado muda e a evolução
    é mais informativa que o número corrente.
    """

    __tablename__ = "player_valuations"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    valuation_date: Mapped[date] = mapped_column(Date, index=True)
    market_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    contract_until: Mapped[date | None] = mapped_column(Date)
    annual_salary: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="manual")

    player: Mapped[Player] = relationship()


# =========================================================================================
# Auditoria de carga
# =========================================================================================


class IngestionRun(Base, TimestampMixin):
    """Registro de cada execução de ingestão.

    Num TCC é preciso responder "de onde veio este número e quando foi carregado".
    Esta tabela é a resposta. `warnings` guarda o que a carga não conseguiu reconciliar:
    placar que não bate com os eventos, valores da fonte fora do vocabulário.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    matches_ingested: Mapped[int] = mapped_column(Integer, default=0)
    events_ingested: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    warnings: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
