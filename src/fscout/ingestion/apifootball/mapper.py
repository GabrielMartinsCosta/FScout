"""Tradução do JSON do API-Football para o vocabulário do domínio.

Entrega o mesmo `MatchBundle` que o adaptador da StatsBomb entrega, então o carregador
não precisa saber que existe uma segunda fonte — ele continua resolvendo identidades e
referências do mesmo jeito. A diferença aparece no conteúdo: aqui não há eventos, e sim
uma linha de totais por atleta.

Quatro decisões saíram da leitura do dado real, e nenhuma delas era óbvia antes:

1. **`passes.accuracy` é contagem, não porcentagem.** Em 124 amostras ela nunca excedeu
   `passes.total`. O nome do campo na fonte engana; a coluna aqui se chama
   `passes_accurate` para o engano não se propagar.
2. **Nulo quer dizer zero nos campos de contagem.** A fonte grava `null` em 94% dos
   `goals.total` e `0` explícito nos cartões — inconsistência dela, normalizada aqui, na
   entrada, para nenhuma métrica ter que lidar com isso depois.
3. **Minutos nulos querem dizer que o atleta não entrou.** São 59 dos 184 registros
   observados, sempre com a nota também nula: reserva não utilizada. Eles não viram
   participação, porque `appearances` é sobre quem atuou.
4. **`penalty.commited`** está escrito com um "t" só na fonte. Copiar o erro é o que faz
   a leitura funcionar; corrigi-lo silenciosamente faria o campo vir sempre vazio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fscout.domain.enums import CompetitionType, DataTier, HomeAway, PositionGroup
from fscout.ingestion.bundle import GoalCheck, MatchBundle, Row

FONTE = "apifootball"

# A fonte usa uma letra por setor. Sem meia dúzia de posições detalhadas, como na
# StatsBomb, o grupo é tudo o que se tem — e é o que o percentil usa.
POSICOES: dict[str, PositionGroup] = {
    "G": PositionGroup.GOALKEEPER,
    "D": PositionGroup.DEFENDER,
    "M": PositionGroup.MIDFIELDER,
    "F": PositionGroup.FORWARD,
}


def inteiro(valor: Any) -> int:
    """Número de contagem da fonte, com nulo e texto tratados como o que são.

    Nulo vira zero porque é assim que a fonte grava "nenhum" na maioria dos campos.
    Texto aparece em `passes.accuracy` e precisa ser convertido antes de somar.
    """
    if valor is None or valor == "":
        return 0
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


def decimal(valor: Any) -> float | None:
    """Número fracionário, preservando a ausência em vez de transformá-la em zero.

    Usado só na nota da fonte: ali zero significaria desempenho péssimo, e não ausência.
    """
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def season_source_id(league_id: Any, season: Any) -> str:
    """Chave da temporada. Composta, pela mesma razão da StatsBomb: o ano se repete
    entre competições, e sozinho não identifica nada."""
    return f"{league_id}-{season}"


# Tipo de cada competição, por id da fonte. Tabela explícita em vez de heurística, pelo
# mesmo motivo que a tradução do vocabulário da StatsBomb é explícita: adivinhar erra em
# silêncio. A primeira versão deduzia "país igual a World" como copa continental de
# clubes, e classificou a **Copa América** — torneio de seleções — como competição de
# clubes. O recorte por tipo de competição, que a especificação pede, depende disto.
TIPOS_POR_COMPETICAO: dict[int, CompetitionType] = {
    9: CompetitionType.INTERNATIONAL_NATIONAL_TEAM,  # Copa América
    71: CompetitionType.NATIONAL_LEAGUE,  # Brasileirão Série A
    72: CompetitionType.NATIONAL_LEAGUE,  # Série B
    75: CompetitionType.NATIONAL_LEAGUE,  # Série C
    76: CompetitionType.NATIONAL_LEAGUE,  # Série D
    13: CompetitionType.CONTINENTAL_CLUB,  # Libertadores
    11: CompetitionType.CONTINENTAL_CLUB,  # Sudamericana
    73: CompetitionType.NATIONAL_CUP,  # Copa do Brasil
}

# Competições de seleção não pertencem a um país, e gravar uma sede como "país da
# competição" faria o recorte por país devolver coisa errada.
SEM_PAIS = frozenset(
    {CompetitionType.INTERNATIONAL_NATIONAL_TEAM, CompetitionType.CONTINENTAL_CLUB}
)


def competition_row(league: dict[str, Any]) -> Row:
    identificador = league.get("id")
    tipo = TIPOS_POR_COMPETICAO.get(
        int(identificador) if identificador is not None else -1, CompetitionType.UNKNOWN
    )
    return {
        "source_id": str(identificador),
        "name": str(league.get("name", "")),
        "country_ref": None if tipo in SEM_PAIS else league.get("country"),
        "type": tipo,
    }


def season_row(league: dict[str, Any]) -> Row:
    return {
        "source_id": season_source_id(league.get("id"), league.get("season")),
        "name": str(league.get("season")),
    }


def _kickoff(texto: Any) -> datetime | None:
    """Horário de início em UTC e sem fuso, como o resto do schema guarda.

    A fonte manda com deslocamento explícito ("2024-04-13T21:30:00+00:00"). Converter
    para UTC antes de descartar o fuso evita o erro clássico de gravar horário local como
    se fosse universal — que já custou uma correção neste projeto, no clima das partidas.
    """
    if not texto:
        return None
    try:
        momento = datetime.fromisoformat(str(texto))
    except ValueError:
        return None
    if momento.tzinfo is None:
        return momento
    return momento.astimezone(UTC).replace(tzinfo=None)


def _time_row(time: dict[str, Any], pais: Any) -> Row:
    return {
        "source_id": str(time.get("id")),
        "name": str(time.get("name", "")),
        "country_ref": pais,
        "is_national_team": False,
    }


def _estatisticas(bruto: dict[str, Any]) -> Row:
    """As 33 medidas da fonte, nos nomes do schema."""
    jogos = bruto.get("games") or {}
    chutes = bruto.get("shots") or {}
    gols = bruto.get("goals") or {}
    passes = bruto.get("passes") or {}
    desarmes = bruto.get("tackles") or {}
    duelos = bruto.get("duels") or {}
    dribles = bruto.get("dribbles") or {}
    faltas = bruto.get("fouls") or {}
    cartoes = bruto.get("cards") or {}
    penaltis = bruto.get("penalty") or {}
    return {
        "shirt_number": inteiro(jogos.get("number")) or None,
        "is_captain": bool(jogos.get("captain")),
        "is_substitute": bool(jogos.get("substitute")),
        "source_rating": decimal(jogos.get("rating")),
        "shots_total": inteiro(chutes.get("total")),
        "shots_on_target": inteiro(chutes.get("on")),
        "goals": inteiro(gols.get("total")),
        "assists": inteiro(gols.get("assists")),
        "goals_conceded": inteiro(gols.get("conceded")),
        "saves": inteiro(gols.get("saves")),
        "passes_total": inteiro(passes.get("total")),
        "passes_key": inteiro(passes.get("key")),
        # Contagem de passes certos. A fonte chama de "accuracy"; ver o topo do módulo.
        "passes_accurate": inteiro(passes.get("accuracy")),
        "tackles": inteiro(desarmes.get("total")),
        "blocks": inteiro(desarmes.get("blocks")),
        "interceptions": inteiro(desarmes.get("interceptions")),
        "duels_total": inteiro(duelos.get("total")),
        "duels_won": inteiro(duelos.get("won")),
        "dribbles_attempted": inteiro(dribles.get("attempts")),
        "dribbles_successful": inteiro(dribles.get("success")),
        "dribbled_past": inteiro(dribles.get("past")),
        "fouls_drawn": inteiro(faltas.get("drawn")),
        "fouls_committed": inteiro(faltas.get("committed")),
        "yellow_cards": inteiro(cartoes.get("yellow")),
        "red_cards": inteiro(cartoes.get("red")),
        "penalties_won": inteiro(penaltis.get("won")),
        # "commited", com um "t", é a grafia da fonte. Ver o topo do módulo.
        "penalties_committed": inteiro(penaltis.get("commited")),
        "penalties_scored": inteiro(penaltis.get("scored")),
        "penalties_missed": inteiro(penaltis.get("missed")),
        "penalties_saved": inteiro(penaltis.get("saved")),
        "offsides": inteiro(bruto.get("offsides")),
    }


def build_match_bundle(fixture: dict[str, Any], jogadores: dict[str, Any]) -> MatchBundle:
    """Uma partida da camada agregada, pronta para o carregador.

    Args:
        fixture: um item da resposta de `/fixtures`.
        jogadores: o corpo inteiro de `/fixtures/players` daquela partida.
    """
    dados = fixture.get("fixture") or {}
    liga = fixture.get("league") or {}
    times = fixture.get("teams") or {}
    placar = fixture.get("goals") or {}
    local = dados.get("venue") or {}
    pais = liga.get("country")

    casa = times.get("home") or {}
    fora = times.get("away") or {}
    ref_casa, ref_fora = str(casa.get("id")), str(fora.get("id"))
    gols_casa, gols_fora = placar.get("home"), placar.get("away")
    kickoff = _kickoff(dados.get("date"))

    match: Row = {
        "source_id": str(dados.get("id")),
        "season_ref": season_source_id(liga.get("id"), liga.get("season")),
        "match_date": kickoff.date() if kickoff else None,
        "kickoff": kickoff,
        "home_team_ref": ref_casa,
        "away_team_ref": ref_fora,
        "home_score": gols_casa,
        "away_score": gols_fora,
        "stage": liga.get("round"),
        "stadium": local.get("name"),
        "referee": dados.get("referee"),
        "venue_country": pais,
        # A marca que impede esta partida de ser somada com as de evento.
        "data_tier": DataTier.AGGREGATE,
    }

    equipes = {ref_casa: _time_row(casa, pais), ref_fora: _time_row(fora, pais)}
    atletas: dict[str, Row] = {}
    participacoes: list[Row] = []
    estatisticas: list[Row] = []
    gols_por_lado = {ref_casa: 0, ref_fora: 0}
    avisos: list[str] = []
    ja_vistos: set[str] = set()

    for time in jogadores.get("response") or []:
        ref_time = str((time.get("team") or {}).get("id"))
        ref_adversario = ref_fora if ref_time == ref_casa else ref_casa
        mando = HomeAway.HOME if ref_time == ref_casa else HomeAway.AWAY

        for entrada in time.get("players") or []:
            atleta = entrada.get("player") or {}
            bruto_lista = entrada.get("statistics") or []
            if not bruto_lista or not isinstance(bruto_lista[0], dict):
                continue
            bruto = bruto_lista[0]
            jogos = bruto.get("games") or {}
            minutos = jogos.get("minutes")
            if not minutos:
                continue  # reserva que não entrou: não é participação

            ref_atleta = str(atleta.get("id"))
            if ref_atleta in ja_vistos:
                # Defeito observado na fonte: o id 65657 aparece duas vezes na mesma
                # partida da Copa América, como "Jesús Sagredo" e "José Sagredo". Um
                # identificador para duas pessoas. Fica a primeira ocorrência, porque
                # duas participações do mesmo atleta canônico numa partida não existem —
                # e o aviso sobe junto com o dado, para o defeito não sumir calado.
                avisos.append(
                    f"atleta {ref_atleta} repetido na partida {dados.get('id')} "
                    f"(segundo nome: {atleta.get('name')!r}); ficou a primeira ocorrência"
                )
                continue
            ja_vistos.add(ref_atleta)
            atletas[ref_atleta] = {"source_id": ref_atleta, "name": str(atleta.get("name", ""))}
            medidas = _estatisticas(bruto)
            gols_por_lado[ref_time] = gols_por_lado.get(ref_time, 0) + medidas["goals"]

            participacoes.append(
                {
                    "player_ref": ref_atleta,
                    "team_ref": ref_time,
                    "opponent_team_ref": ref_adversario,
                    "home_away": mando,
                    "position": jogos.get("position"),
                    "position_group": POSICOES.get(str(jogos.get("position"))),
                    "jersey_number": medidas["shirt_number"],
                    "is_starter": not medidas["is_substitute"],
                    "minutes_played": inteiro(minutos),
                    # A fonte não mede tempo efetivo com acréscimos. Zero aqui significa
                    # "não medido", e não "não jogou" — quem não jogou nem chega aqui.
                    "seconds_on_pitch": 0,
                    "goals_for": gols_casa if ref_time == ref_casa else gols_fora,
                    "goals_against": gols_fora if ref_time == ref_casa else gols_casa,
                }
            )
            estatisticas.append(
                {
                    "source": FONTE,
                    "source_id": f"{dados.get('id')}-{ref_atleta}",
                    "player_ref": ref_atleta,
                    "team_ref": ref_time,
                    **medidas,
                }
            )

    return MatchBundle(
        match=match,
        teams=equipes,
        players=atletas,
        appearances=participacoes,
        # Mesma conferência barata da ingestão de eventos: se os gols somados por atleta
        # não batem com o placar, algo no mapeamento está errado. Gol contra é a exceção
        # conhecida — ele não é creditado a nenhum atleta do time que marcou.
        goal_check=GoalCheck(
            expected=(gols_casa, gols_fora),
            from_events=(gols_por_lado.get(ref_casa, 0), gols_por_lado.get(ref_fora, 0)),
        ),
        player_match_stats=estatisticas,
        avisos=avisos,
    )
