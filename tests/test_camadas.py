"""Testes da camada de dado: o que impede somar granularidades incompatíveis.

O projeto passa a ter duas origens com granularidades diferentes — evento a evento, com
coordenada, e totais por jogador e partida. Elas respondem perguntas diferentes e não se
somam: "finalizações fora da área" existe numa e não existe na outra, e um total que
misturasse as duas subcontaria sem avisar.

O que se testa aqui é justamente a impossibilidade dessa mistura. São as regras mais
baratas de quebrar por descuido e as mais caras de descobrir depois, porque o sintoma é
um número plausível e errado.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from fscout.db.migrations import COLUNAS_ESPERADAS, colunas_faltantes, garantir_colunas
from fscout.db.models import Pass, Shot
from fscout.db.session import build_engine, create_all
from fscout.domain.enums import DataTier
from fscout.metrics.context import Slice, appearance_conditions
from fscout.metrics.engine import metricas_fora_da_camada
from fscout.metrics.registry import AMBAS_AS_CAMADAS, Aggregation, MetricSpec, Unit


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    motor = build_engine(f"sqlite:///{tmp_path / 'camadas.db'}")
    yield motor
    motor.dispose()


# ----------------------------------------------------------------------------------------
# O recorte nomeia uma camada, sempre
# ----------------------------------------------------------------------------------------


def test_recorte_novo_fica_na_camada_de_evento() -> None:
    """Padrão seguro: quem não escolhe recebe a granularidade sobre a qual as 108
    métricas do catálogo foram definidas."""
    assert Slice().data_tier is DataTier.EVENT


def test_todo_recorte_filtra_por_camada_mesmo_sem_ninguem_pedir() -> None:
    """Sem esta condição, minutagem e métrica poderiam vir de granularidades
    diferentes e o valor por 90 minutos sairia errado sem nenhum sinal."""
    condicoes = [str(condicao) for condicao in appearance_conditions(Slice())]
    assert any("data_tier" in condicao for condicao in condicoes)


def test_camada_e_uma_so_e_nao_um_conjunto() -> None:
    """Deliberado: aceitar várias reabriria a porta para somar o que não se soma."""
    recorte = Slice(data_tier=DataTier.AGGREGATE)
    assert isinstance(recorte.data_tier, DataTier)
    condicoes = [str(condicao) for condicao in appearance_conditions(recorte)]
    assert sum("data_tier" in condicao for condicao in condicoes) == 1


def test_trocar_a_camada_gera_outro_recorte() -> None:
    """`Slice` é imutável, então derivar não contamina o original."""
    original = Slice(competition_ids=(1,))
    derivado = original.with_(data_tier=DataTier.AGGREGATE)
    assert original.data_tier is DataTier.EVENT
    assert derivado.data_tier is DataTier.AGGREGATE
    assert derivado.competition_ids == (1,)


# ----------------------------------------------------------------------------------------
# A métrica declara onde pode ser calculada
# ----------------------------------------------------------------------------------------


def _metrica(chave: str, camadas: tuple[DataTier, ...]) -> MetricSpec:
    return MetricSpec(
        key=chave,
        label=chave,
        family="teste",
        table=Shot,
        aggregation=Aggregation.COUNT,
        unit=Unit.COUNT,
        data_tiers=camadas,
    )


def test_metrica_do_catalogo_e_de_evento_por_padrao() -> None:
    """As 108 métricas existentes são consultas sobre eventos: o padrão reflete isso."""
    metrica = MetricSpec(key="x", label="x", family="teste", table=Pass)
    assert metrica.applies_to_tier(DataTier.EVENT)
    assert not metrica.applies_to_tier(DataTier.AGGREGATE)


def test_metrica_pode_valer_nas_duas_camadas() -> None:
    """Gol é gol nas duas: a contagem significa a mesma coisa."""
    metrica = _metrica("gols", AMBAS_AS_CAMADAS)
    assert metrica.applies_to_tier(DataTier.EVENT)
    assert metrica.applies_to_tier(DataTier.AGGREGATE)


def test_metrica_fora_da_camada_e_nomeada_e_nao_some() -> None:
    """Sumir calado faria o leitor concluir que o atleta não tem aquela ação, quando o
    caso é que a fonte não registra aquilo."""
    specs = [_metrica("gols", AMBAS_AS_CAMADAS), _metrica("chutes_de_fora", (DataTier.EVENT,))]
    assert metricas_fora_da_camada(specs, DataTier.AGGREGATE) == ["chutes_de_fora"]
    assert metricas_fora_da_camada(specs, DataTier.EVENT) == []


# ----------------------------------------------------------------------------------------
# Acréscimo de coluna em banco já carregado
# ----------------------------------------------------------------------------------------


def test_banco_recem_criado_nao_precisa_de_acrescimo(engine: Engine) -> None:
    """`create_all` já traz a coluna; a migração não deve ter o que fazer."""
    create_all(engine)
    assert colunas_faltantes(engine) == []
    assert garantir_colunas(engine) == []


def test_coluna_que_falta_e_detectada_e_acrescentada(engine: Engine) -> None:
    """Simula o banco anterior à coluna, que é o caso real: 182 partidas já carregadas."""
    with engine.begin() as conexao:
        conexao.execute(text("CREATE TABLE matches (id INTEGER PRIMARY KEY)"))

    assert colunas_faltantes(engine) == ["matches.data_tier"]
    assert garantir_colunas(engine) == ["matches.data_tier"]
    assert colunas_faltantes(engine) == []


def test_acrescimo_e_idempotente(engine: Engine) -> None:
    """Rodar de novo não pode quebrar: o comando é chamado a cada `init-db`."""
    with engine.begin() as conexao:
        conexao.execute(text("CREATE TABLE matches (id INTEGER PRIMARY KEY)"))
    garantir_colunas(engine)
    assert garantir_colunas(engine) == []


def test_linha_antiga_recebe_a_camada_de_evento(engine: Engine) -> None:
    """O padrão da coluna não é detalhe: toda partida carregada antes dela veio da
    StatsBomb, que é dado de evento. Errar isso reclassificaria o banco inteiro."""
    with engine.begin() as conexao:
        conexao.execute(text("CREATE TABLE matches (id INTEGER PRIMARY KEY)"))
        conexao.execute(text("INSERT INTO matches (id) VALUES (1)"))

    garantir_colunas(engine)
    with Session(engine) as sessao:
        assert (
            sessao.execute(text("SELECT data_tier FROM matches WHERE id = 1")).scalar() == "event"
        )


def test_tabela_inexistente_e_ignorada(engine: Engine) -> None:
    """Banco vazio é trabalho de `create_all`, não da migração."""
    assert colunas_faltantes(engine) == []


def test_o_que_a_migracao_promete_esta_declarado() -> None:
    """A lista é o contrato: é ela que diz o que muda num banco já carregado."""
    assert "matches" in COLUNAS_ESPERADAS
    assert "data_tier" in COLUNAS_ESPERADAS["matches"]
    assert "DEFAULT 'event'" in COLUNAS_ESPERADAS["matches"]["data_tier"]
