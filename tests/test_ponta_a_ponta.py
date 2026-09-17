"""Testes de ponta a ponta: o número sobrevive à travessia?

Cada elo da cadeia já tem teste próprio — ingestão, motor, API e figuras. O que faltava
era a **costura**: um número calculado pelo motor tem que ser o mesmo que a API serve e o
mesmo que a figura desenha. Nenhum teste de unidade pega uma divergência aí, porque cada
lado passa sozinho.

O caso concreto que isto protege: renomear um campo em `ShotOut` não quebra nenhum teste
de API nem de figura — a API continua respondendo e a figura continua desenhando, só que
sem os pontos. Aqui ela quebra.

O banco é pequeno e montado à mão, com as **duas camadas de dado**, porque o outro risco
que só aparece na travessia é uma vazar para dentro da outra.
"""

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
    Event,
    Match,
    Player,
    PlayerMatchStat,
    Season,
    Shot,
    Team,
)
from fscout.db.session import build_engine, create_all
from fscout.domain.enums import (
    BodyPart,
    CompetitionType,
    DataTier,
    EventType,
    HomeAway,
    PositionGroup,
    ShotOutcome,
    ShotType,
)
from fscout.metrics import definitions  # noqa: F401  (registra o catálogo)
from fscout.metrics.context import Slice
from fscout.metrics.engine import evaluate
from fscout.metrics.registry import REGISTRY
from fscout.ui.figures import shot_map
from fscout.ui.pages import perfil

JUNHO = date(2024, 6, 20)
JULHO = date(2024, 7, 10)


@pytest.fixture
def ambiente(tmp_path: Path) -> Iterator[tuple[TestClient, Session, dict[str, int]]]:
    """Banco com as duas camadas, a API por cima dele e uma sessão para o motor."""
    engine = build_engine(f"sqlite:///{tmp_path / 'ponta.db'}")
    create_all(engine)
    ids: dict[str, int] = {}

    with Session(engine) as session:
        liga = Competition(name="Liga", type=CompetitionType.NATIONAL_LEAGUE)
        session.add(liga)
        session.flush()
        temporada = Season(competition_id=liga.id, name="2024")
        casa, fora = Team(name="Casa"), Team(name="Fora")
        artilheiro = Player(name="Artilheiro", primary_position_group=PositionGroup.FORWARD)
        parceiro = Player(name="Parceiro", primary_position_group=PositionGroup.FORWARD)
        brasileiro = Player(name="Brasileiro", primary_position_group=PositionGroup.MIDFIELDER)
        session.add_all([temporada, casa, fora, artilheiro, parceiro, brasileiro])
        session.flush()
        ids |= {
            "liga": liga.id,
            "artilheiro": artilheiro.id,
            "parceiro": parceiro.id,
            "brasileiro": brasileiro.id,
        }

        # Camada de evento: duas partidas, em meses diferentes, para o recorte por data
        # ter o que separar.
        sequencia = 0
        for rodada, gols_do_artilheiro in ((JUNHO, 2), (JULHO, 1)):
            partida = Match(
                season_id=temporada.id,
                match_date=rodada,
                kickoff=datetime(rodada.year, rodada.month, rodada.day, 20),
                home_team_id=casa.id,
                away_team_id=fora.id,
                data_tier=DataTier.EVENT,
            )
            session.add(partida)
            session.flush()
            for jogador in (artilheiro, parceiro):
                session.add(
                    Appearance(
                        match_id=partida.id,
                        player_id=jogador.id,
                        team_id=casa.id,
                        opponent_team_id=fora.id,
                        home_away=HomeAway.HOME,
                        position_group=jogador.primary_position_group,
                        minutes_played=90,
                    )
                )
            # O artilheiro marca; o parceiro finaliza e não marca, para a classe "no
            # alvo" do mapa ter conteúdo.
            for indice in range(gols_do_artilheiro + 1):
                gol = indice < gols_do_artilheiro
                jogador = artilheiro if gol else parceiro
                sequencia += 1
                evento = Event(
                    source="teste",
                    source_id=f"e{sequencia}",
                    match_id=partida.id,
                    sequence=sequencia,
                    period=1,
                    minute=10 + indice,
                    second=0,
                    type=EventType.SHOT,
                    team_id=casa.id,
                    player_id=jogador.id,
                    x=108.0,
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
                        body_part=BodyPart.RIGHT_FOOT,
                        is_goal=gol,
                        is_on_target=True,
                        in_penalty_area=True,
                        distance_m=11.0,
                        xg=0.25,
                    )
                )

        # Camada agregada: uma partida, com totais por atleta e nenhuma coordenada.
        partida_ag = Match(
            season_id=temporada.id,
            match_date=JULHO,
            home_team_id=casa.id,
            away_team_id=fora.id,
            data_tier=DataTier.AGGREGATE,
        )
        session.add(partida_ag)
        session.flush()
        session.add(
            Appearance(
                match_id=partida_ag.id,
                player_id=brasileiro.id,
                team_id=casa.id,
                opponent_team_id=fora.id,
                home_away=HomeAway.HOME,
                position_group=PositionGroup.MIDFIELDER,
                minutes_played=90,
            )
        )
        session.add(
            PlayerMatchStat(
                match_id=partida_ag.id,
                player_id=brasileiro.id,
                team_id=casa.id,
                source="teste",
                source_id="ag-1",
                goals=1,
                shots_total=4,
                shots_on_target=2,
                passes_total=50,
                passes_accurate=40,
            )
        )
        session.commit()

    app = create_app()

    def sessao_de_teste() -> Iterator[Session]:
        with Session(engine) as sessao:
            yield sessao

    app.dependency_overrides[get_session] = sessao_de_teste
    with TestClient(app) as client, Session(engine) as sessao_do_motor:
        yield client, sessao_do_motor, ids
    engine.dispose()


# ----------------------------------------------------------------------------------------
# O número atravessa motor, API e figura sem mudar
# ----------------------------------------------------------------------------------------


def test_gols_sao_os_mesmos_no_motor_na_api_e_no_grafico(ambiente) -> None:
    """A invariante central do projeto. Três caminhos independentes, um número.

    Se um campo de `ShotOut` for renomeado, a API continua respondendo e a figura
    continua desenhando — vazia. É esta asserção que percebe.
    """
    client, sessao, ids = ambiente
    recorte = Slice(player_ids=(ids["artilheiro"],))

    do_motor = evaluate(sessao, REGISTRY.select(["gols"]), recorte)[ids["artilheiro"]]["gols"]

    chutes = client.get(f"/players/{ids['artilheiro']}/shots").json()
    da_api = sum(1 for chute in chutes if chute["is_goal"])

    figura = shot_map.mapa_de_chutes(chutes)
    trace_de_gol = next(t for t in figura.data if t.name == "Gol")
    do_grafico = len(trace_de_gol.x)

    assert do_motor.value == 3
    assert da_api == 3
    assert do_grafico == 3


def test_a_tabela_do_perfil_traz_uma_linha_por_ponto_do_mapa(ambiente) -> None:
    """A tabela equivalente sai da mesma resposta da API, então não pode divergir."""
    client, _, ids = ambiente
    chutes = client.get(f"/players/{ids['artilheiro']}/shots").json()
    figura = shot_map.mapa_de_chutes(chutes)

    pontos = sum(len(traco.x) for traco in figura.data)
    assert len(perfil._linhas_de_chutes(chutes)) == pontos == len(chutes)


def test_o_recorte_por_data_significa_o_mesmo_nos_dois_caminhos(ambiente) -> None:
    """ "Gols em junho" tem que dar o mesmo número pedido ao motor ou à API."""
    client, sessao, ids = ambiente
    junho = {"date_from": "2024-06-01", "date_to": "2024-06-30"}

    do_motor = evaluate(
        sessao,
        REGISTRY.select(["gols"]),
        Slice(
            player_ids=(ids["artilheiro"],), date_from=date(2024, 6, 1), date_to=date(2024, 6, 30)
        ),
    )[ids["artilheiro"]]["gols"]
    chutes = client.get(f"/players/{ids['artilheiro']}/shots", params=junho).json()

    assert do_motor.value == 2
    assert sum(1 for chute in chutes if chute["is_goal"]) == 2


def test_avaliar_pela_api_concorda_com_o_motor(ambiente) -> None:
    client, sessao, ids = ambiente
    do_motor = evaluate(sessao, REGISTRY.select(["gols"]), Slice())[ids["artilheiro"]]["gols"]

    resposta = client.post(
        "/metrics/evaluate",
        json={"metrics": ["gols"], "slice": {}, "player_ids": [ids["artilheiro"]]},
    ).json()

    assert resposta[0]["values"]["gols"]["value"] == do_motor.value
    assert resposta[0]["values"]["gols"]["percentile"] == do_motor.percentile


# ----------------------------------------------------------------------------------------
# As camadas não vazam uma para a outra
# ----------------------------------------------------------------------------------------


def test_a_camada_de_evento_nao_enxerga_o_atleta_da_agregada(ambiente) -> None:
    client, _, ids = ambiente
    atletas = client.get("/players", params={"data_tier": "event"}).json()
    assert ids["brasileiro"] not in {atleta["id"] for atleta in atletas}
    assert ids["artilheiro"] in {atleta["id"] for atleta in atletas}


def test_a_camada_agregada_nao_enxerga_o_atleta_de_evento(ambiente) -> None:
    client, _, ids = ambiente
    atletas = client.get("/players", params={"data_tier": "aggregate"}).json()
    assert {atleta["id"] for atleta in atletas} == {ids["brasileiro"]}


def test_metrica_de_evento_nao_e_calculada_sobre_dado_agregado(ambiente) -> None:
    """Pedir "gols" na camada agregada não devolve zero: devolve nada, porque a métrica
    não existe ali. Zero seria uma afirmação sobre o atleta."""
    client, _, ids = ambiente
    resposta = client.post(
        "/metrics/evaluate",
        json={
            "metrics": ["gols"],
            "slice": {"data_tier": "aggregate"},
            "player_ids": [ids["brasileiro"]],
        },
    ).json()
    assert resposta == [] or "gols" not in resposta[0]["values"]


def test_metrica_agregada_atravessa_a_cadeia(ambiente) -> None:
    """O mesmo percurso do teste central, na outra camada."""
    client, sessao, ids = ambiente
    recorte = Slice(player_ids=(ids["brasileiro"],), data_tier=DataTier.AGGREGATE)

    do_motor = evaluate(sessao, REGISTRY.select(["gols_ag", "finalizacoes_ag"]), recorte)
    medidas = do_motor[ids["brasileiro"]]
    assert medidas["gols_ag"].value == 1
    assert medidas["finalizacoes_ag"].value == 4

    resposta = client.post(
        "/metrics/evaluate",
        json={
            "metrics": ["gols_ag", "finalizacoes_ag"],
            "slice": {"data_tier": "aggregate"},
            "player_ids": [ids["brasileiro"]],
        },
    ).json()
    assert resposta[0]["values"]["gols_ag"]["value"] == 1


def test_mapa_de_campo_fica_vazio_na_camada_agregada(ambiente) -> None:
    """Não há coordenada ali. A tela troca o gráfico por uma explicação, e é isso que
    impede o campo vazio de parecer "o atleta não finalizou"."""
    client, _, ids = ambiente
    chutes = client.get(
        f"/players/{ids['brasileiro']}/shots", params={"data_tier": "aggregate"}
    ).json()
    assert chutes == []


def test_catalogo_separa_as_camadas_pela_api(ambiente) -> None:
    client, _, _ = ambiente
    evento = client.get("/catalog", params={"data_tier": "event"}).json()
    agregado = client.get("/catalog", params={"data_tier": "aggregate"}).json()

    chaves_de_evento = {definicao["key"] for definicao in evento}
    chaves_agregadas = {definicao["key"] for definicao in agregado}
    assert chaves_de_evento and chaves_agregadas
    assert not chaves_de_evento & chaves_agregadas


# ----------------------------------------------------------------------------------------
# Comparação com dois recortes
# ----------------------------------------------------------------------------------------


def test_comparar_dois_periodos_do_mesmo_atleta(ambiente) -> None:
    """O caso que o brief pediu: "2024 contra 2025", aqui como junho contra julho."""
    client, _, ids = ambiente
    resposta = client.post(
        "/compare",
        json={
            "player_ids": [ids["artilheiro"]],
            "metrics": ["gols"],
            "slices": [
                {"date_from": "2024-06-01", "date_to": "2024-06-30", "label": "junho"},
                {"date_from": "2024-07-01", "date_to": "2024-07-31", "label": "julho"},
            ],
        },
    ).json()

    por_recorte = {
        celula["slice_label"]: celula["values"]["gols"]["value"] for celula in resposta["cells"]
    }
    assert por_recorte == {"junho": 2.0, "julho": 1.0}


def test_percentil_e_calculado_entre_quem_esta_no_recorte(ambiente) -> None:
    """A população do percentil é a do recorte, e a tela mostra qual é — sem isso,
    "percentil 100" não diria se é entre dois ou entre duzentos."""
    client, _, ids = ambiente
    resposta = client.post("/metrics/evaluate", json={"metrics": ["gols"], "slice": {}}).json()

    do_artilheiro = next(r for r in resposta if r["player"]["id"] == ids["artilheiro"])
    assert do_artilheiro["values"]["gols"]["population"] == 2
    assert do_artilheiro["values"]["gols"]["percentile"] == 75.0
