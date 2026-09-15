"""Definições das métricas, uma família por módulo.

Importar este pacote registra o catálogo inteiro em `fscout.metrics.registry.REGISTRY`.
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

__all__ = [
    "defending",
    "discipline",
    "dribbling",
    "general",
    "goalkeeping",
    "passing",
    "shooting",
]
