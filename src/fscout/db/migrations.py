"""Acréscimo de colunas em banco já carregado, sem framework de migração.

O projeto decidiu não adotar Alembic enquanto recarregar for barato, e recarregar
continua barato. Mas "barato" não é "gratuito": o banco atual tem 662 mil eventos, e
refazer a carga inteira para ganhar uma coluna com valor padrão é desperdício de tempo
de quem está trabalhando.

Este módulo é o meio-termo honesto: uma lista explícita de colunas que precisam existir,
conferida contra o que o banco tem, e um `ALTER TABLE` para o que faltar. Trinta linhas,
nenhuma dependência nova, e nenhuma pretensão de ser um sistema de migração — não há
versionamento, não há reversão, e coluna que muda de tipo continua exigindo recarga.

O dia em que isto não bastar é o dia de adotar Alembic, e não o de crescer este arquivo.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text

from fscout.db.session import get_engine

logger = logging.getLogger(__name__)

# Tabela -> coluna -> definição SQL. O padrão precisa estar aqui porque `ALTER TABLE ADD
# COLUMN NOT NULL` exige um: é ele que preenche as linhas que já existem.
COLUNAS_ESPERADAS: dict[str, dict[str, str]] = {
    # Toda partida carregada antes desta coluna veio da StatsBomb, que é dado de evento.
    "matches": {"data_tier": "VARCHAR(48) NOT NULL DEFAULT 'event'"},
}


def colunas_faltantes(engine: Engine | None = None) -> list[str]:
    """Colunas esperadas que o banco ainda não tem, como `tabela.coluna`."""
    engine = engine or get_engine()
    inspetor = inspect(engine)
    existentes_por_tabela = set(inspetor.get_table_names())

    faltantes = []
    for tabela, colunas in COLUNAS_ESPERADAS.items():
        if tabela not in existentes_por_tabela:
            continue  # tabela ainda não criada; `create_all` cuida dela
        presentes = {coluna["name"] for coluna in inspetor.get_columns(tabela)}
        faltantes.extend(f"{tabela}.{nome}" for nome in colunas if nome not in presentes)
    return faltantes


def garantir_colunas(engine: Engine | None = None) -> list[str]:
    """Acrescenta as colunas que faltarem. Devolve o que foi acrescentado.

    Idempotente: com o banco em dia, não faz nada e devolve lista vazia.
    """
    engine = engine or get_engine()
    faltantes = colunas_faltantes(engine)
    if not faltantes:
        return []

    acrescentadas = []
    with engine.begin() as conexao:
        for qualificado in faltantes:
            tabela, _, nome = qualificado.partition(".")
            definicao = COLUNAS_ESPERADAS[tabela][nome]
            logger.info("Acrescentando coluna %s", qualificado)
            conexao.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {definicao}"))
            acrescentadas.append(qualificado)
    return acrescentadas
