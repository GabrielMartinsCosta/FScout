"""Aplicação FastAPI do FScout."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fscout.api.routers import catalog, metrics, players, reference
from fscout.metrics import definitions as _definitions  # noqa: F401  (registra o catálogo)

DESCRICAO = """
Análise granular de atletas de futebol a partir de dados evento a evento.

Todo endpoint de leitura aceita o mesmo conjunto de filtros de recorte — competição,
temporada, janela de datas, adversário, mando e piso de minutagem —, de modo que
"gols em junho" e "gols contra determinado adversário" são a mesma chamada com
argumentos diferentes.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="FScout",
        description=DESCRICAO,
        version="0.1.0",
        docs_url="/docs",
    )
    # O painel roda em outra porta durante o desenvolvimento.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8050", "http://127.0.0.1:8050"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(catalog.router)
    app.include_router(reference.router)
    app.include_router(players.router)
    app.include_router(metrics.router)

    @app.get("/health", tags=["serviço"], summary="Verificação de saúde")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
