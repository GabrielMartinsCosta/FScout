"""Definições das métricas, uma família por módulo.

Importar este pacote registra o catálogo inteiro em `fscout.metrics.registry.REGISTRY`.
As compostas vêm por último, porque dependem das métricas já registradas.
"""

from fscout.metrics.definitions import (
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
    "composites",
    "defending",
    "discipline",
    "dribbling",
    "general",
    "goalkeeping",
    "passing",
    "shooting",
]
