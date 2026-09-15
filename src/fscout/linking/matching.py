"""Ligação de registros entre duas fontes: partidas e atletas.

Funções puras, sem banco e sem formato de fonte: recebem registros mínimos e devolvem
decisões com a evidência que as sustentou. É aqui que ficam as regras que precisam ser
defendidas no texto do TCC, então os limiares são constantes nomeadas.

A estratégia é ancorar a comparação de nomes num contexto pequeno:

1. **Partida:** mesma data (tolerância de um dia, por fuso horário) e as duas equipes
   correspondentes, em qualquer ordem de mando.
2. **Atleta dentro da partida:** entre os ~25 inscritos de uma equipe numa partida, nome
   parecido e mesmo número de camisa praticamente identificam a pessoa.
3. **Votação entre partidas:** um atleta que joga várias partidas recebe um voto por
   partida. A ligação final é a mais votada, e a concordância entra na confiança.
4. **Reserva por nome e nacionalidade:** para quem não tem escalação disponível, com
   limiar mais alto e confiança reduzida.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean

from fscout.linking.countries import country_key
from fscout.linking.names import best_similarity, name_similarity, same_name, tokens

# ---------------------------------------------------------------------------------------
# Equipes e partidas
# ---------------------------------------------------------------------------------------

# Siglas societárias que variam entre fontes sem distinguir clubes ("FC Barcelona" x
# "Barcelona"). Letras isoladas como "B" não entram: distinguem a equipe reserva.
CLUB_NOISE_TOKENS = frozenset(
    {
        "fc",
        "cf",
        "cd",
        "sc",
        "ac",
        "afc",
        "club",
        "futbol",
        "football",
        "calcio",
        "balompie",
        "ssc",
        "ud",
        "sd",
        "rc",
        "rcd",
        "sv",
        "vfb",
        "vfl",
        "tsg",
        "bsc",
        "fk",
        "sk",
        "nk",
        "as",
        "ca",
    }
)
TEAM_SIMILARITY_MIN = 0.85

# Nomes que nenhuma regra de grafia aproxima: o nome oficial contra o nome pela cidade.
TEAM_ALIASES: dict[str, str] = {
    "athletic bilbao": "athletic club",
}
MAX_DATE_OFFSET_DAYS = 1


@dataclass(frozen=True)
class MatchRecord:
    key: str
    match_date: date
    home: str
    away: str


@dataclass(frozen=True)
class MatchLink:
    left_key: str
    right_key: str
    swapped: bool
    date_offset_days: int


def team_words(name: str) -> tuple[str, ...]:
    """Palavras que identificam a equipe: sem acento, partículas nem siglas societárias."""
    key = country_key(name)
    return tuple(
        word for word in tokens(TEAM_ALIASES.get(key, key)) if word not in CLUB_NOISE_TOKENS
    )


def teams_match(first: str, second: str) -> bool:
    """Duas grafias descrevem a mesma equipe."""
    first_words, second_words = team_words(first), team_words(second)
    if not first_words or not second_words:
        return False
    if "".join(first_words) == "".join(second_words):
        return True
    # Uma palavra a mais distingue equipes ("Barcelona B", "Brazil U23"): a similaridade só
    # compara grafias com o mesmo número de palavras, para absorver acento e erro de digitação.
    if len(first_words) != len(second_words):
        return False
    return name_similarity(" ".join(first_words), " ".join(second_words)) >= TEAM_SIMILARITY_MIN


def link_matches(left: Sequence[MatchRecord], right: Sequence[MatchRecord]) -> list[MatchLink]:
    """Liga partidas das duas fontes, uma para uma.

    A data exata tem prioridade sobre a vizinha, e o mando original sobre o invertido.
    """
    by_date: dict[date, list[MatchRecord]] = defaultdict(list)
    for record in right:
        by_date[record.match_date].append(record)

    links: list[MatchLink] = []
    used: set[str] = set()
    offsets = sorted(range(-MAX_DATE_OFFSET_DAYS, MAX_DATE_OFFSET_DAYS + 1), key=abs)

    for match in left:
        candidates: list[MatchLink] = []
        for offset in offsets:
            for other in by_date.get(match.match_date + timedelta(days=offset), []):
                if other.key in used:
                    continue
                if teams_match(match.home, other.home) and teams_match(match.away, other.away):
                    candidates.append(MatchLink(match.key, other.key, False, abs(offset)))
                elif teams_match(match.home, other.away) and teams_match(match.away, other.home):
                    candidates.append(MatchLink(match.key, other.key, True, abs(offset)))
        if candidates:
            best = min(candidates, key=lambda link: (link.date_offset_days, link.swapped))
            links.append(best)
            used.add(best.right_key)
    return links


# ---------------------------------------------------------------------------------------
# Atletas dentro de uma partida
# ---------------------------------------------------------------------------------------

JERSEY_BONUS = 0.3
ACCEPT_NAME_ALONE = 0.85
ACCEPT_NAME_WITH_JERSEY = 0.5
AMBIGUITY_MARGIN = 0.1
MIN_ACCEPTED_CONFIDENCE = 0.6


@dataclass(frozen=True)
class PlayerRecord:
    key: str
    names: tuple[str | None, ...]
    jersey: int | None = None


@dataclass(frozen=True)
class PlayerLink:
    left_key: str
    right_key: str
    score: float
    name_similarity: float
    same_jersey: bool


@dataclass(frozen=True)
class ResolvedLink:
    left_key: str
    right_key: str
    confidence: float
    votes: int
    total_votes: int

    @property
    def conflicting(self) -> bool:
        return self.votes < self.total_votes


def assign_players(
    left: Sequence[PlayerRecord], right: Sequence[PlayerRecord]
) -> tuple[list[PlayerLink], list[str]]:
    """Liga os atletas de uma equipe numa partida. Devolve ligações e casos ambíguos.

    Um par é aceito com nome muito parecido, ou com nome razoável e mesmo número de
    camisa — o número resolve "Gomes" contra "João Gomes". Se duas opções aceitas ficam a
    menos de `AMBIGUITY_MARGIN` uma da outra, o atleta é marcado como ambíguo em vez de
    ligado por sorteio.
    """
    best_by_left: list[PlayerLink] = []
    ambiguous: list[str] = []

    for player in left:
        options: list[PlayerLink] = []
        for other in right:
            similarity = best_similarity(player.names, other.names)
            same_jersey = player.jersey is not None and player.jersey == other.jersey
            accepted = similarity >= ACCEPT_NAME_ALONE or (
                same_jersey and similarity >= ACCEPT_NAME_WITH_JERSEY
            )
            if accepted:
                score = similarity + (JERSEY_BONUS if same_jersey else 0.0)
                options.append(PlayerLink(player.key, other.key, score, similarity, same_jersey))
        if not options:
            continue
        options.sort(key=lambda link: link.score, reverse=True)
        if len(options) > 1 and options[0].score - options[1].score < AMBIGUITY_MARGIN:
            ambiguous.append(player.key)
            continue
        best_by_left.append(options[0])

    links: list[PlayerLink] = []
    taken: set[str] = set()
    for link in sorted(best_by_left, key=lambda item: item.score, reverse=True):
        if link.right_key in taken:
            ambiguous.append(link.left_key)
            continue
        taken.add(link.right_key)
        links.append(link)
    return links, ambiguous


def resolve_votes(links: Iterable[PlayerLink]) -> dict[str, ResolvedLink]:
    """Consolida as ligações de várias partidas numa por atleta.

    Confiança = concordância entre partidas x força média da evidência (nome mais bônus de
    camisa, limitada a 1). Um atleta ligado ao mesmo registro em todas as partidas, com nome
    exato, tem confiança 1.
    """
    grouped: dict[str, list[PlayerLink]] = defaultdict(list)
    for link in links:
        grouped[link.left_key].append(link)

    resolved: dict[str, ResolvedLink] = {}
    for left_key, group in grouped.items():
        votes = Counter(link.right_key for link in group)
        right_key, count = votes.most_common(1)[0]
        agreeing = [link for link in group if link.right_key == right_key]
        strength = min(1.0, fmean(link.score for link in agreeing))
        confidence = round(count / len(group) * strength, 3)
        resolved[left_key] = ResolvedLink(left_key, right_key, confidence, count, len(group))
    return resolved


def enforce_one_to_one(resolved: dict[str, ResolvedLink]) -> dict[str, ResolvedLink]:
    """Garante que um registro da outra fonte não fique ligado a dois atletas."""
    winners: dict[str, ResolvedLink] = {}
    for link in sorted(resolved.values(), key=lambda item: item.confidence, reverse=True):
        winners.setdefault(link.right_key, link)
    return {link.left_key: link for link in winners.values()}


# ---------------------------------------------------------------------------------------
# Reserva: nome dentro de um grupo de candidatos
# ---------------------------------------------------------------------------------------

FALLBACK_MIN_SIMILARITY = 0.9
FALLBACK_MARGIN = 0.15


def best_candidate(
    player: PlayerRecord,
    candidates: Sequence[PlayerRecord],
    preferred: frozenset[str] = frozenset(),
) -> tuple[PlayerRecord, float] | None:
    """Melhor candidato por nome, em dois níveis de evidência.

    1. **Nome idêntico**, depois de normalizado. Um único candidato com o mesmo nome é
       escolhido mesmo havendo grafias vizinhas: "Alessandro Bastoni" não perde para
       "Alessandro Bastrini" só porque as letras se parecem. Homônimos exatos são
       desempatados por `preferred` (atletas com jogos por seleção); sem desempate, nenhum.
    2. **Nome aproximado**, quando não há idêntico: similaridade alta e folga sobre o segundo
       colocado, porque sem escalação não há número de camisa para confirmar.
    """
    identical = [candidate for candidate in candidates if same_name(player.names, candidate.names)]
    if len(identical) > 1:
        identical = [candidate for candidate in identical if candidate.key in preferred]
        return (identical[0], 1.0) if len(identical) == 1 else None
    if len(identical) == 1:
        return identical[0], 1.0

    scored = sorted(
        ((candidate, best_similarity(player.names, candidate.names)) for candidate in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    if not scored or scored[0][1] < FALLBACK_MIN_SIMILARITY:
        return None
    if len(scored) > 1 and scored[0][1] - scored[1][1] < FALLBACK_MARGIN:
        return None
    return scored[0]
