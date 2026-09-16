"""Testes da API, sobre um banco pequeno criado na hora."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fscout.api.deps import get_session
from fscout.api.main import create_app
from fscout.db.models import (
    Appearance,
    Competition,
    Country,
    Event,
    Match,
    Player,
    PlayerNationality,
    PlayerValuation,
    Season,
    Shot,
    Team,
)
from fscout.db.session import build_engine, create_all
from fscout.domain.enums import (
    BodyPart,
    CompetitionType,
    EventType,
    Foot,
    HomeAway,
    PositionGroup,
    ShotOutcome,
    ShotType,
)

RODADA = date(2024, 6, 20)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = build_engine(f"sqlite:///{tmp_path / 'api.db'}")
    create_all(engine)

    with Session(engine) as session:
        brasil = Country(name="Brazil")
        competicao = Competition(name="Liga", type=CompetitionType.NATIONAL_LEAGUE)
        session.add_all([brasil, competicao])
        session.flush()
        temporada = Season(competition_id=competicao.id, name="2024")
        casa, visitante = Team(name="Casa"), Team(name="Visita")
        atacante = Player(
            name="Atacante",
            full_name="Atacante da Silva",
            birth_date=date(1999, 5, 4),
            height_cm=180,
            preferred_foot=Foot.LEFT,
            primary_position_group=PositionGroup.FORWARD,
        )
        meia = Player(name="Meia", primary_position_group=PositionGroup.MIDFIELDER)
        session.add_all([temporada, casa, visitante, atacante, meia])
        session.flush()

        session.add(PlayerNationality(player_id=atacante.id, country_id=brasil.id, is_primary=True))
        session.add(
            PlayerValuation(
                player_id=atacante.id,
                valuation_date=date(2024, 1, 1),
                market_value=1_000_000,
                contract_until=date(2027, 6, 30),
            )
        )
        partida = Match(
            season_id=temporada.id,
            match_date=RODADA,
            kickoff=datetime(2024, 6, 20, 20),
            home_team_id=casa.id,
            away_team_id=visitante.id,
        )
        session.add(partida)
        session.flush()

        for jogador in (atacante, meia):
            session.add(
                Appearance(
                    match_id=partida.id,
                    player_id=jogador.id,
                    team_id=casa.id,
                    opponent_team_id=visitante.id,
                    home_away=HomeAway.HOME,
                    position_group=jogador.primary_position_group,
                    minutes_played=90,
                )
            )
        session.flush()

        for indice, (jogador, gol) in enumerate(((atacante, True), (atacante, False)), start=1):
            evento = Event(
                source="teste",
                source_id=f"e{indice}",
                match_id=partida.id,
                sequence=indice,
                period=1,
                minute=10 + indice,
                second=0,
                type=EventType.SHOT,
                team_id=casa.id,
                player_id=jogador.id,
                x=110.0,
                y=40.0,
                grid_col=5,
                grid_row=2,
            )
            session.add(evento)
            session.flush()
            session.add(
                Shot(
                    event_id=evento.id,
                    player_id=jogador.id,
                    match_id=partida.id,
                    shot_type=ShotType.OPEN_PLAY,
                    outcome=ShotOutcome.GOAL if gol else ShotOutcome.SAVED,
                    body_part=BodyPart.LEFT_FOOT,
                    is_goal=gol,
                    is_on_target=True,
                    in_penalty_area=True,
                    distance_m=10.0,
                    xg=0.3,
                )
            )
        session.commit()

    app = create_app()

    def sessao_de_teste() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessao_de_teste
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_saude(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_catalogo_lista_definicoes(client: TestClient) -> None:
    resposta = client.get("/catalog", params={"family": "finalizacao"})
    assert resposta.status_code == 200
    chaves = {item["key"] for item in resposta.json()}
    assert {"gols", "finalizacoes"} <= chaves

    familias = client.get("/catalog/families").json()
    assert familias["finalizacao"] > 0
    assert client.get("/catalog", params={"family": "inexistente"}).status_code == 404


def test_catalogo_filtra_por_posicao(client: TestClient) -> None:
    de_goleiro = client.get("/catalog", params={"position": "goalkeeper"}).json()
    de_atacante = client.get("/catalog", params={"position": "forward"}).json()
    chaves_goleiro = {item["key"] for item in de_goleiro}
    chaves_atacante = {item["key"] for item in de_atacante}

    assert "defesas" in chaves_goleiro
    assert "defesas" not in chaves_atacante


def test_competicoes_e_equipes(client: TestClient) -> None:
    competicoes = client.get("/competitions").json()
    assert competicoes[0]["name"] == "Liga"
    assert competicoes[0]["seasons"][0]["matches"] == 1

    equipes = client.get("/teams").json()
    assert {equipe["name"] for equipe in equipes} == {"Casa", "Visita"}


def test_busca_e_ficha_do_atleta(client: TestClient) -> None:
    encontrados = client.get("/players", params={"search": "Atac"}).json()
    assert [jogador["name"] for jogador in encontrados] == ["Atacante"]
    assert encontrados[0]["minutes"] == 90

    ficha = client.get(f"/players/{encontrados[0]['id']}").json()
    assert ficha["height_cm"] == 180
    assert ficha["preferred_foot"] == "left"
    assert ficha["nationalities"] == ["Brazil"]
    assert ficha["market_value_eur"] == 1_000_000
    assert ficha["contract_until"] == "2027-06-30"

    assert client.get("/players/9999").status_code == 404


def test_finalizacoes_e_mapa_de_calor(client: TestClient) -> None:
    jogador = client.get("/players", params={"search": "Atacante"}).json()[0]["id"]

    chutes = client.get(f"/players/{jogador}/shots").json()
    assert len(chutes) == 2
    assert sum(1 for chute in chutes if chute["is_goal"]) == 1
    assert chutes[0]["opponent"] == "Visita"

    celulas = client.get(f"/players/{jogador}/heatmap").json()
    assert celulas == [{"grid_col": 5, "grid_row": 2, "actions": 2}]


def test_avaliacao_de_metricas(client: TestClient) -> None:
    resposta = client.post(
        "/metrics/evaluate",
        json={"metrics": ["gols", "finalizacoes"], "slice": {"label": "2024"}},
    )
    assert resposta.status_code == 200

    por_nome = {item["player"]["name"]: item["values"] for item in resposta.json()}
    assert por_nome["Atacante"]["gols"]["value"] == 1
    assert por_nome["Atacante"]["finalizacoes"]["value"] == 2
    assert por_nome["Meia"]["gols"]["value"] == 0

    assert client.post("/metrics/evaluate", json={"metrics": ["inexistente"]}).status_code == 404
    assert client.post("/metrics/evaluate", json={"metrics": []}).status_code == 422


def test_comparacao_em_dois_recortes(client: TestClient) -> None:
    jogador = client.get("/players", params={"search": "Atacante"}).json()[0]["id"]
    resposta = client.post(
        "/compare",
        json={
            "player_ids": [jogador],
            "metrics": ["gols"],
            "slices": [
                {"label": "junho", "date_from": "2024-06-01", "date_to": "2024-06-30"},
                {"label": "julho", "date_from": "2024-07-01", "date_to": "2024-07-31"},
            ],
        },
    )
    assert resposta.status_code == 200
    corpo = resposta.json()

    assert [definicao["key"] for definicao in corpo["definitions"]] == ["gols"]
    por_recorte = {
        celula["slice_label"]: celula["values"]["gols"]["value"] for celula in corpo["cells"]
    }
    assert por_recorte["junho"] == 1
    assert "julho" not in por_recorte  # sem partidas no recorte
