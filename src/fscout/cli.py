"""Interface de linha de comando do FScout."""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fscout.db import models
from fscout.db.session import create_all, get_engine
from fscout.ingestion.pipeline import ingest_season
from fscout.ingestion.statsbomb.client import StatsBombClient

app = typer.Typer(
    help="FScout: scouting de atletas a partir de dados evento a evento.",
    no_args_is_help=True,
)
console = Console()

STATUS_TABLES = (
    models.Competition,
    models.Season,
    models.Match,
    models.Team,
    models.Player,
    models.Appearance,
    models.Event,
    models.Shot,
    models.Pass,
    models.Dribble,
    models.DefensiveAction,
    models.GoalkeeperAction,
    models.DisciplinaryAction,
    models.ExternalId,
)


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log detalhado.")] = False,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, show_time=False)],
    )
    # Uma linha por arquivo baixado polui a barra de progresso sem informar nada.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command("init-db")
def init_db() -> None:
    """Cria as tabelas que ainda não existem."""
    create_all()
    console.print("[green]Banco pronto.[/green]")


@app.command()
def competitions(
    search: Annotated[
        str | None, typer.Argument(help="Filtra por competição, temporada ou país.")
    ] = None,
) -> None:
    """Lista as temporadas disponíveis na StatsBomb Open Data."""
    with StatsBombClient() as client:
        records = client.competitions()

    if search:
        term = search.lower()
        records = [
            record
            for record in records
            if term
            in f"{record['competition_name']} {record['season_name']} "
            f"{record['country_name']}".lower()
        ]

    table = Table(title="StatsBomb Open Data")
    for column in ("competição", "temporada", "id", "país", "gênero", "360"):
        table.add_column(column)
    for record in sorted(records, key=lambda r: (r["competition_name"], r["season_name"])):
        table.add_row(
            record["competition_name"],
            record["season_name"],
            f"{record['competition_id']} {record['season_id']}",
            record["country_name"],
            record["competition_gender"],
            "sim" if record.get("match_available_360") else "",
        )
    console.print(table)


@app.command()
def ingest(
    competition_id: Annotated[int, typer.Argument(help="Id da competição na StatsBomb.")],
    season_id: Annotated[int, typer.Argument(help="Id da temporada na StatsBomb.")],
    limit: Annotated[int | None, typer.Option(help="Carrega só as N primeiras partidas.")] = None,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Recarrega partidas já presentes no banco.")
    ] = False,
) -> None:
    """Carrega uma temporada da StatsBomb no banco."""
    columns = (
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console) as progress:
        task = progress.add_task("Preparando", total=None)

        def on_progress(position: int, total: int, label: str) -> None:
            progress.update(task, total=total, completed=position - 1, description=label)

        report = ingest_season(
            competition_id, season_id, limit=limit, refresh=refresh, progress=on_progress
        )
        done = max(report.matches_loaded, 1)
        progress.update(task, total=done, completed=done, description="Concluído")

    summary = Table(title=f"{report.competition} {report.season}", show_header=False)
    summary.add_row("Partidas selecionadas", str(report.matches_selected))
    summary.add_row("Carregadas", str(report.matches_loaded))
    summary.add_row("Já estavam no banco", str(report.matches_skipped))
    summary.add_row("Eventos gravados", f"{report.events_loaded:,}".replace(",", "."))
    summary.add_row("Placares divergentes", str(len(report.goal_mismatches)))
    summary.add_row("Valores não mapeados", str(len(report.unmapped_values)))
    console.print(summary)

    for message in report.goal_mismatches:
        console.print(f"[yellow]placar divergente[/yellow] {message}")
    for (field_name, value), count in report.unmapped_values.most_common(15):
        console.print(f"[yellow]não mapeado[/yellow] {field_name} = {value!r} ({count}x)")


@app.command()
def status() -> None:
    """Quantidade de registros por tabela."""
    create_all()
    table = Table(title="Banco FScout")
    table.add_column("tabela")
    table.add_column("registros", justify="right")
    with Session(get_engine()) as session:
        for model in STATUS_TABLES:
            count = session.scalar(select(func.count()).select_from(model))
            table.add_row(model.__tablename__, f"{count:,}".replace(",", "."))
    console.print(table)


if __name__ == "__main__":
    app()
