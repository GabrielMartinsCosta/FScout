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
def api(
    host: Annotated[str, typer.Option(help="Endereço de escuta.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Porta.")] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Recarrega ao salvar, para desenvolvimento.")
    ] = False,
) -> None:
    """Sobe a API. A documentação interativa fica em /docs."""
    import uvicorn

    console.print(f"Documentação interativa em http://{host}:{port}/docs")
    uvicorn.run("fscout.api.main:app", host=host, port=port, reload=reload)


apifootball_app = typer.Typer(
    help="Camada de dado agregado: Brasileirão, Libertadores e o resto da Conmebol.",
    no_args_is_help=True,
)
app.add_typer(apifootball_app, name="api-football")

SERIE_A_DO_BRASIL = 71  # id da competição no API-Football


def _cobertura_declarada(cobertura: dict[str, object], limite: int = 4) -> str:
    """Lista o que a fonte afirma cobrir, achatando o objeto sem supor o formato."""
    ligados: list[str] = []
    for grupo, valor in cobertura.items():
        if isinstance(valor, dict):
            ligados.extend(f"{grupo}.{campo}" for campo, ligado in valor.items() if ligado)
        elif valor:
            ligados.append(str(grupo))
    if not ligados:
        return "-"
    mostrados = ", ".join(sorted(ligados)[:limite])
    resto = len(ligados) - limite
    return f"{mostrados} (+{resto})" if resto > 0 else mostrados


@apifootball_app.command("sondar")
def api_football_sondar() -> None:
    """Mede o que o plano cobre: competições, temporadas e profundidade da estatística."""
    from fscout.ingestion.apifootball import ChaveAusente, avaliar, sondar

    try:
        with console.status("Consultando o API-Football (gasta seis requisições)"):
            relatorio = sondar()
    except ChaveAusente as erro:
        console.print(f"[yellow]{erro}[/yellow]")
        raise typer.Exit(code=1) from erro

    conta = Table(title="Conta", show_header=False)
    conta.add_row("Plano", relatorio.plano)
    conta.add_row(
        "Requisições hoje", f"{relatorio.requisicoes_usadas} de {relatorio.requisicoes_no_dia}"
    )
    conta.add_row("Gastas nesta sondagem", str(relatorio.gastas_aqui))
    console.print(conta)

    if relatorio.competicoes:
        ligas = Table(title="Competições liberadas")
        for coluna in ("id", "competição", "país", "temporadas", "a fonte declara cobrir"):
            ligas.add_column(coluna)
        for liga in relatorio.competicoes:
            ligas.add_row(
                str(liga.id),
                liga.nome,
                liga.pais,
                liga.resumo_de_temporadas,
                _cobertura_declarada(liga.cobertura),
            )
        console.print(ligas)

    # A prova: o que veio numa partida de verdade, e não o que a fonte promete cobrir.
    if relatorio.estatisticas_do_jogador:
        amostra = Table(
            title=f"Amostra real — {relatorio.partida_de_exemplo} — {relatorio.jogador_de_exemplo}",
            show_header=False,
        )
        amostra.add_row("Estatísticas por jogador", str(len(relatorio.estatisticas_do_jogador)))
        amostra.add_row("Grupos", ", ".join(sorted(relatorio.grupos_encontrados)))
        amostra.add_row("Campos", ", ".join(relatorio.estatisticas_do_jogador))
        console.print(amostra)

    if relatorio.temporada_testada is not None:
        console.print(
            f"Lesões na temporada {relatorio.temporada_testada}: "
            f"{relatorio.lesoes_encontradas} registros"
        )
    for aviso in relatorio.avisos:
        console.print(f"[yellow]{aviso}[/yellow]")

    veredito = avaliar(relatorio)
    console.print()
    for motivo in veredito.motivos:
        console.print(f"  {motivo}")
    cor = "green" if veredito.vale_a_camada_2 else "yellow"
    frase = (
        "a camada de dado agregado se sustenta"
        if veredito.vale_a_camada_2
        else "a camada de dado agregado NÃO se sustenta"
    )
    console.print(f"\n[{cor}]Veredito: {frase}.[/{cor}]")


def _mostrar_progresso(progresso: object, titulo: str, cota_diaria: int) -> None:
    tabela = Table(title=titulo, show_header=False)
    tabela.add_row("Partidas encerradas na temporada", str(progresso.partidas_encerradas))
    tabela.add_row("Já estavam em cache", str(progresso.ja_em_cache))
    tabela.add_row("Baixadas agora", str(progresso.baixadas_agora))
    tabela.add_row("Ainda faltam", str(progresso.faltam))
    tabela.add_row("Requisições gastas", str(progresso.gastas))
    tabela.add_row("Servidas pelo cache", str(progresso.aproveitadas))
    tabela.add_row("Progresso", f"{progresso.por_cento:.1f}%")
    console.print(tabela)

    for aviso in progresso.avisos:
        console.print(f"[yellow]{aviso}[/yellow]")

    if progresso.concluido:
        console.print("[green]Temporada completa no cache.[/green]")
    elif progresso.faltam:
        recado = f"Faltam {progresso.faltam} partidas"
        # Só estima dias quando a cota diária é conhecida: dividir pelo orçamento de uma
        # sessão daria um número inventado, e grande.
        if cota_diaria > 0:
            recado += f": mais ~{progresso.dias_restantes(cota_diaria)} dia(s) de cota"
        console.print(f"{recado}. Rode o mesmo comando amanhã — o cache faz ele continuar daqui.")


@apifootball_app.command("baixar")
def api_football_baixar(
    competicao: Annotated[int, typer.Option(help="Id da competição.")] = SERIE_A_DO_BRASIL,
    temporada: Annotated[int, typer.Option(help="Ano da temporada.")] = 2024,
    requisicoes: Annotated[
        int, typer.Option(help="Teto de requisições. 0 pergunta à conta quanto ainda cabe.")
    ] = 0,
) -> None:
    """Baixa as estatísticas por jogador de cada partida, em sessões diárias.

    Uma temporada do Brasileirão tem 380 partidas e o plano gratuito dá 100 requisições
    por dia, então a carga leva alguns dias. Rodar de novo continua de onde parou: o que
    já está em cache não é pedido outra vez.
    """
    from fscout.ingestion.apifootball import ChaveAusente, baixar_partidas, orcamento_do_dia

    try:
        if requisicoes > 0:
            orcamento, cota_diaria = requisicoes, 0
        else:
            orcamento, cota_diaria = orcamento_do_dia()
        if orcamento <= 0:
            console.print(
                "[yellow]A cota de hoje acabou. O que já veio está em cache; "
                "rode de novo amanhã.[/yellow]"
            )
            raise typer.Exit(code=0)
        console.print(f"Orçamento desta sessão: {orcamento} requisições.")
        with console.status(f"Baixando {competicao}/{temporada}"):
            progresso = baixar_partidas(competicao, temporada, orcamento)
    except ChaveAusente as erro:
        console.print(f"[yellow]{erro}[/yellow]")
        raise typer.Exit(code=1) from erro

    _mostrar_progresso(progresso, f"Competição {competicao}, temporada {temporada}", cota_diaria)


@apifootball_app.command("lesoes")
def api_football_lesoes(
    competicao: Annotated[int, typer.Option(help="Id da competição.")] = SERIE_A_DO_BRASIL,
    temporada: Annotated[int, typer.Option(help="Ano da temporada.")] = 2024,
    requisicoes: Annotated[
        int, typer.Option(help="Teto de requisições. 0 pergunta à conta quanto ainda cabe.")
    ] = 0,
) -> None:
    """Baixa o histórico de lesões da temporada, que vem paginado."""
    from fscout.ingestion.apifootball import ChaveAusente, baixar_lesoes, orcamento_do_dia

    try:
        orcamento = requisicoes if requisicoes > 0 else orcamento_do_dia()[0]
        if orcamento <= 0:
            console.print("[yellow]A cota de hoje acabou. Rode de novo amanhã.[/yellow]")
            raise typer.Exit(code=0)
        with console.status(f"Baixando lesões de {competicao}/{temporada}"):
            progresso = baixar_lesoes(competicao, temporada, orcamento)
    except ChaveAusente as erro:
        console.print(f"[yellow]{erro}[/yellow]")
        raise typer.Exit(code=1) from erro

    console.print(
        f"Lesões declaradas: {progresso.partidas_encerradas} · "
        f"baixadas: {progresso.baixadas_agora} · faltam: {progresso.faltam} · "
        f"requisições gastas: {progresso.gastas}"
    )
    for aviso in progresso.avisos:
        console.print(f"[yellow]{aviso}[/yellow]")


@app.command()
def paises() -> None:
    """Preenche o código ISO de cada país, que é o que posiciona o mapa-múndi."""
    from fscout.linking.countries import preencher_iso3

    with Session(get_engine()) as session:
        preenchidos, sem_codigo = preencher_iso3(session)

    console.print(f"Códigos ISO gravados: {preenchidos}")
    if sem_codigo:
        console.print(f"[yellow]Sem código[/yellow] ({len(sem_codigo)}): {', '.join(sem_codigo)}")
        console.print("Estados extintos ou de sucessão ambígua não entram no mapa-múndi.")


@app.command()
def ui(
    host: Annotated[str, typer.Option(help="Endereço de escuta.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Porta.")] = 8050,
    debug: Annotated[
        bool, typer.Option("--debug", help="Recarrega ao salvar, para desenvolvimento.")
    ] = False,
) -> None:
    """Sobe o painel. Exige a API no ar, em outro terminal (`fscout api`)."""
    from fscout.ui.app import criar_app

    console.print(f"Painel em http://{host}:{port}")
    console.print("A API precisa estar respondendo; suba-a com [bold]fscout api[/bold].")
    criar_app().run(host=host, port=port, debug=debug)


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
