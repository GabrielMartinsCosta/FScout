"""Interface de linha de comando do FScout."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
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
from fscout.ingestion.transfermarkt.pipeline import enrich_from_transfermarkt
from fscout.ingestion.weather import enrich_weather
from fscout.metrics import definitions as metric_definitions  # noqa: F401
from fscout.metrics.registry import REGISTRY

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
    models.Venue,
    models.MatchWeather,
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
def transfermarkt() -> None:
    """Liga os atletas ao Transfermarkt e preenche biografia e valor de mercado."""
    with console.status("Ligando StatsBomb e Transfermarkt (a primeira vez baixa ~190 MB)"):
        report = enrich_from_transfermarkt()
    link, bio = report.linking, report.enrichment

    table = Table(title="Ligação StatsBomb x Transfermarkt", show_header=False)
    table.add_row("Partidas ligadas", f"{link.matches_linked} de {link.matches_total}")
    table.add_row("Equipes ligadas", str(link.teams_linked))
    table.add_row(
        "Atletas ligados",
        f"{link.players_linked} de {link.players_total} "
        f"({_percent(link.players_linked, link.players_total)})",
    )
    table.add_row("  por escalação da partida", str(link.players_by_lineup))
    table.add_row("  por nome e nacionalidade", str(link.players_by_name))
    table.add_row("  por nome único no dataset", str(link.players_by_exact_name))
    table.add_row("Casos para revisão manual", str(len(link.review)))
    if link.fallback_precision is not None and link.fallback_recall is not None:
        table.add_row(
            "Nome+nacionalidade: precisão",
            f"{link.fallback_precision:.1%} ({link.fallback_agreed}/{link.fallback_proposed})",
        )
        table.add_row(
            "Nome+nacionalidade: cobertura",
            f"{link.fallback_recall:.1%} ({link.fallback_agreed}/{link.fallback_checked})",
        )
    console.print(table)

    filled = Table(title="Biografia preenchida", show_header=False)
    for label, value in (
        ("Data de nascimento", bio.birth_date),
        ("Altura", bio.height),
        ("Pé preferencial", bio.foot),
        ("País de nascimento", bio.birth_country),
        ("Nacionalidades acrescentadas", bio.nationalities_added),
        ("Registros de valor de mercado", bio.valuations),
        ("Fins de contrato", bio.contracts),
    ):
        filled.add_row(label, f"{value:,}".replace(",", "."))
    console.print(filled)
    console.print(f"Casos para revisão: {report.review_path}")


def _percent(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "-"


@app.command()
def weather() -> None:
    """Localiza os estádios e busca o clima de cada partida no horário do jogo."""
    with console.status("Localizando estádios (1 consulta/s no OpenStreetMap) e buscando clima"):
        report = enrich_weather()

    table = Table(title="Clima das partidas", show_header=False)
    table.add_row("Estádios localizados", f"{report.venues_located} de {report.venues_total}")
    table.add_row("  por coordenada manual", str(report.venues_manual))
    table.add_row("Partidas com clima", f"{report.matches_with_weather} de {report.matches_total}")
    table.add_row("Partidas sem horário de início", str(report.matches_without_kickoff))
    table.add_row("Partidas sem estádio localizado", str(report.matches_without_location))
    table.add_row("Climas refeitos após correção", str(report.weather_discarded))
    console.print(table)
    for name in report.venues_unresolved:
        console.print(
            f"[yellow]não localizado[/yellow] {name}: informe em data/reference/venues.csv"
        )
    for name in report.venues_to_check:
        console.print(f"[yellow]conferir[/yellow] {name}: resultado não marcado como estádio")


@app.command()
def catalogo(
    familia: Annotated[str | None, typer.Argument(help="Filtra por família de métricas.")] = None,
    csv_path: Annotated[
        Path | None, typer.Option("--csv", help="Exporta o catálogo para um arquivo CSV.")
    ] = None,
) -> None:
    """Lista o catálogo de métricas: a tabela de definições operacionais do projeto."""
    metricas = REGISTRY.by_family(familia) if familia else tuple(REGISTRY)
    if not metricas:
        console.print(f"[yellow]nenhuma métrica na família {familia!r}[/yellow]")
        console.print(f"famílias: {', '.join(REGISTRY.families())}")
        raise typer.Exit(code=1)

    table = Table(title=f"Catálogo de métricas ({len(metricas)} de {len(REGISTRY)})")
    for coluna in ("chave", "métrica", "família", "unidade", "tipo", "por 90", "sentido"):
        table.add_column(coluna)
    for spec in metricas:
        table.add_row(
            spec.key,
            spec.label,
            spec.family,
            str(spec.unit),
            str(getattr(spec, "aggregation", "composta")),
            "sim" if spec.per_90 else "não",
            "maior é melhor" if spec.higher_is_better else "menor é melhor",
        )
    console.print(table)

    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(
                [
                    "chave",
                    "metrica",
                    "familia",
                    "unidade",
                    "agregacao",
                    "por_90",
                    "sentido",
                    "posicoes",
                    "definicao",
                ]
            )
            for spec in metricas:
                escritor.writerow(
                    [
                        spec.key,
                        spec.label,
                        spec.family,
                        str(spec.unit),
                        str(getattr(spec, "aggregation", "composta")),
                        "sim" if spec.per_90 else "nao",
                        "maior e melhor" if spec.higher_is_better else "menor e melhor",
                        " ".join(str(posicao) for posicao in spec.positions),
                        spec.description,
                    ]
                )
        console.print(f"Catálogo exportado para {csv_path}")


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
