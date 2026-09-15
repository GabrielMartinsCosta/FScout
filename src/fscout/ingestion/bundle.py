"""Contrato entre adaptadores de fonte e a camada de carga.

Todo adaptador — StatsBomb hoje, outras fontes de eventos depois — entrega uma partida
como um `MatchBundle`. O carregador só conhece este formato, então acrescentar uma fonte
significa escrever um mapeador, não mexer na gravação.

Referências entre registros usam identificadores *da fonte* em chaves terminadas em
`_ref`. O carregador troca cada uma pelo id canônico depois de resolver as entidades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Row = dict[str, Any]


@dataclass(frozen=True)
class GoalCheck:
    """Conferência entre o placar oficial e os gols encontrados nos eventos.

    É o teste de sanidade mais barato de uma ingestão: se os gols reconstruídos a partir
    das finalizações não batem com o placar, algo no mapeamento está errado.
    """

    expected: tuple[int | None, int | None]
    from_events: tuple[int, int]

    @property
    def ok(self) -> bool:
        return all(
            expected is None or expected == found
            for expected, found in zip(self.expected, self.from_events, strict=True)
        )


@dataclass
class MatchBundle:
    """Uma partida inteira, já traduzida para o vocabulário do domínio."""

    match: Row
    teams: dict[str, Row]
    players: dict[str, Row]
    appearances: list[Row]
    goal_check: GoalCheck
    events: list[Row] = field(default_factory=list)
    shots: list[Row] = field(default_factory=list)
    passes: list[Row] = field(default_factory=list)
    dribbles: list[Row] = field(default_factory=list)
    defensive_actions: list[Row] = field(default_factory=list)
    goalkeeper_actions: list[Row] = field(default_factory=list)
    disciplinary_actions: list[Row] = field(default_factory=list)
