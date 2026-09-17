"""Definições das métricas, uma família por módulo.

Importar este pacote registra o catálogo inteiro em `fscout.metrics.registry.REGISTRY`.
As compostas vêm por último, porque dependem das métricas já registradas.

`aggregate` é o módulo da segunda camada de dado: mesmas famílias, chaves com sufixo
`_ag`, calculadas sobre totais por partida em vez de sobre eventos. Métrica de uma camada
nunca aparece numa avaliação da outra — quem garante isso é o motor, não a organização
dos arquivos.
"""

from fscout.metrics.definitions import (
    aggregate,
    defending,
    discipline,
    dribbling,
    general,
    goalkeeping,
    passing,
    shooting,
)

from fscout.metrics.definitions import composites  # isort: skip  (depende das anteriores)

__all__ = [
    "aggregate",
    "composites",
    "defending",
    "discipline",
    "dribbling",
    "general",
    "goalkeeping",
    "passing",
    "shooting",
]
