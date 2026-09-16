"""Testes da sondagem do API-Football.

A sondagem existe para uma decisão de escopo: construir ou não a camada de dado
agregado, que é o que daria cobertura ao futebol de clubes sul-americano — onde não
existe dado de evento aberto. O critério dessa decisão precisa estar escrito e testado,
e não ser impressão de quem olhou a saída: é ele que justifica, no texto do TCC, ter
feito ou não a cobertura do Brasileirão, e por quê.

Nada aqui toca a rede. O que se testa é o julgamento sobre um relatório já obtido, e o
achatamento defensivo das respostas — o serviço bloqueia leitura automatizada da
documentação, então o código não pode supor o formato do que chega.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fscout.ingestion.apifootball.client import (
    ChaveAusente,
    ClienteApiFootball,
    intervalo_do_plano,
)
from fscout.ingestion.apifootball.download import Progresso
from fscout.ingestion.apifootball.probe import (
    GRUPOS_MINIMOS,
    Competicao,
    Sondagem,
    achatar,
    avaliar,
    competicoes_de,
    partidas_encerradas,
)

ESTATISTICAS_COMPLETAS = [
    "shots.total",
    "shots.on",
    "passes.total",
    "passes.key",
    "duels.total",
    "duels.won",
]


def _sondagem(
    temporadas_serie_a: list[int],
    temporadas_libertadores: list[int] | None = None,
    estatisticas: list[str] | None = None,
    lesoes: int | None = 40,
) -> Sondagem:
    competicoes = [
        Competicao(
            id=71, nome="Serie A", pais="Brazil", tipo="League", temporadas=temporadas_serie_a
        )
    ]
    if temporadas_libertadores:
        competicoes.append(
            Competicao(
                id=13,
                nome="CONMEBOL Libertadores",
                pais="World",
                tipo="Cup",
                temporadas=temporadas_libertadores,
            )
        )
    campos = ESTATISTICAS_COMPLETAS if estatisticas is None else estatisticas
    return Sondagem(
        plano="Free",
        competicoes=competicoes,
        estatisticas_do_jogador=campos,
        grupos_encontrados={chave.split(".", 1)[0] for chave in campos},
        lesoes_encontradas=lesoes,
        temporada_testada=max(temporadas_serie_a) if temporadas_serie_a else None,
    )


# ----------------------------------------------------------------------------------------
# O critério de decisão
# ----------------------------------------------------------------------------------------


def test_competicao_sem_estatistica_nao_sustenta_a_camada() -> None:
    """Sem finalização, passe e duelo sobra uma tabela de gols e cartões, que qualquer
    site já mostra — não é ferramenta de scouting."""
    veredito = avaliar(_sondagem([2023, 2024, 2025], estatisticas=[]))
    assert veredito.cobre_brasileirao
    assert not veredito.tem_estatistica_util
    assert not veredito.vale_a_camada_2


def test_estatistica_sem_competicao_nao_sustenta_a_camada() -> None:
    """Com uma temporada só não há histórico, que é metade do que a ferramenta faz."""
    veredito = avaliar(_sondagem([2025]))
    assert not veredito.cobre_brasileirao
    assert veredito.tem_estatistica_util
    assert not veredito.vale_a_camada_2


def test_competicao_e_estatistica_juntas_sustentam() -> None:
    veredito = avaliar(_sondagem([2023, 2024, 2025], temporadas_libertadores=[2024, 2025]))
    assert veredito.vale_a_camada_2
    assert veredito.cobre_continental


def test_grupo_minimo_faltando_derruba_a_estatistica() -> None:
    """Falta o duelo: o veredito precisa dizer qual grupo faltou, não só recusar."""
    veredito = avaliar(_sondagem([2023, 2024], estatisticas=["shots.total", "passes.total"]))
    assert not veredito.tem_estatistica_util
    assert any("duels" in motivo for motivo in veredito.motivos)


def test_libertadores_ausente_nao_derruba_o_brasileirao() -> None:
    """São decisões separadas: a liga nacional sozinha já sustentaria a camada."""
    veredito = avaliar(_sondagem([2023, 2024, 2025]))
    assert veredito.vale_a_camada_2
    assert not veredito.cobre_continental


def test_lesoes_sao_relatadas_a_parte() -> None:
    """Lesão não entra no critério da camada 2: ela não depende de dado de evento e
    entra na tabela própria, que já existe no schema."""
    com = avaliar(_sondagem([2023, 2024], lesoes=120))
    sem = avaliar(_sondagem([2023, 2024], lesoes=0))
    assert com.tem_lesoes and not sem.tem_lesoes
    assert com.vale_a_camada_2 == sem.vale_a_camada_2


def test_limite_de_temporadas_e_ajustavel() -> None:
    """O critério é parâmetro, não número escondido no meio do código."""
    assert avaliar(_sondagem([2024, 2025]), minimo_de_temporadas=2).cobre_brasileirao
    assert not avaliar(_sondagem([2024, 2025]), minimo_de_temporadas=3).cobre_brasileirao


# ----------------------------------------------------------------------------------------
# Leitura defensiva: a documentação da fonte não é legível, então nada se supõe
# ----------------------------------------------------------------------------------------


def test_achatar_transforma_grupos_em_caminhos() -> None:
    assert achatar({"shots": {"total": 3, "on": 1}}) == ["shots.on", "shots.total"]


def test_achatar_aguenta_valor_solto_no_lugar_de_grupo() -> None:
    """Se a fonte mudar e mandar um escalar, o código relata em vez de quebrar."""
    assert achatar({"rating": "7.2", "shots": {"total": 2}}) == ["rating", "shots.total"]


def test_competicoes_de_resposta_vazia_nao_quebra() -> None:
    assert competicoes_de({}) == []
    assert competicoes_de({"response": None}) == []


def test_competicao_pega_a_cobertura_da_temporada_mais_recente() -> None:
    corpo = {
        "response": [
            {
                "league": {"id": 71, "name": "Serie A", "type": "League"},
                "country": {"name": "Brazil"},
                "seasons": [
                    {"year": 2023, "coverage": {"players": False}},
                    {"year": 2025, "coverage": {"players": True}},
                ],
            }
        ]
    }
    competicao = competicoes_de(corpo)[0]
    assert competicao.temporadas == [2023, 2025]
    assert competicao.cobertura == {"players": True}


def test_busca_de_competicao_ignora_caixa_e_aceita_varios_termos() -> None:
    relatorio = _sondagem([2024, 2025], temporadas_libertadores=[2025])
    assert relatorio.competicao("libertadores") is not None
    assert relatorio.competicao("CONMEBOL", "Libertadores") is not None
    assert relatorio.competicao("premier league") is None


def test_grupos_minimos_sao_os_que_viram_metrica() -> None:
    """Fixa o contrato: mudar isto muda o que a ferramenta consegue calcular."""
    assert sorted(GRUPOS_MINIMOS) == ["duels", "passes", "shots"]


# ----------------------------------------------------------------------------------------
# Restrição de plano: a recusa é informação de cobertura disfarçada de erro
# ----------------------------------------------------------------------------------------


def test_intervalo_do_plano_sai_da_mensagem_de_recusa() -> None:
    """A recusa real do serviço: "Free plans do not have access to this season,
    try from 2022 to 2024." O intervalo dentro dela é cobertura, não ruído."""
    mensagem = "Free plans do not have access to this season, try from 2022 to 2024."
    assert intervalo_do_plano(mensagem) == (2022, 2024)


def test_recusa_sem_intervalo_nao_inventa_um() -> None:
    """Outra recusa real: a do parâmetro `last`, que não traz intervalo nenhum."""
    assert intervalo_do_plano("Free plans do not have access to the Last parameter.") is None


def test_veredito_conta_temporada_acessivel_e_nao_a_listada() -> None:
    """`/leagues` lista 17 temporadas do Brasileirão; o plano gratuito serve 3.

    Julgar pela lista contaria histórico que a ingestão não conseguiria baixar — e
    prometeria no texto do TCC uma cobertura que não existe.
    """
    relatorio = _sondagem(list(range(2010, 2027)))
    relatorio.temporadas_acessiveis = [2022, 2023, 2024]
    relatorio.restricao_do_plano = "Free plans do not have access to this season"

    veredito = avaliar(relatorio)
    assert veredito.cobre_brasileirao
    assert any("3 temporadas acessíveis" in motivo for motivo in veredito.motivos)
    assert any("2022 a 2024" in motivo for motivo in veredito.motivos)


def test_janela_do_plano_tambem_corta_a_libertadores() -> None:
    """A restrição vale para a assinatura inteira, não só para a competição sondada."""
    relatorio = _sondagem([2022, 2023, 2024], temporadas_libertadores=list(range(2018, 2027)))
    relatorio.temporadas_acessiveis = [2022, 2023, 2024]

    veredito = avaliar(relatorio)
    assert veredito.cobre_continental
    assert any("Libertadores: 3 temporadas" in motivo for motivo in veredito.motivos)


def test_sem_restricao_conhecida_usa_o_que_foi_listado() -> None:
    """Num plano sem limite de temporada, listada e acessível são a mesma coisa."""
    relatorio = _sondagem([2022, 2023, 2024, 2025])
    veredito = avaliar(relatorio)
    assert veredito.cobre_brasileirao
    assert any("4 temporadas" in motivo for motivo in veredito.motivos)


def test_sem_chave_a_mensagem_diz_o_que_fazer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erro esperado: a chave é credencial pessoal e pode não existir ainda."""
    from fscout import config

    monkeypatch.setattr(config.get_settings(), "api_football_key", "", raising=False)
    with pytest.raises(ChaveAusente, match="FSCOUT_API_FOOTBALL_KEY"):
        ClienteApiFootball()


# ----------------------------------------------------------------------------------------
# Cache e orçamento: o que torna possível baixar 380 partidas a 100 por dia
# ----------------------------------------------------------------------------------------


@pytest.fixture
def configurado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chave de mentira e cache em pasta temporária. Nenhum teste aqui vai à rede."""
    from fscout import config

    ajustes = config.get_settings()
    monkeypatch.setattr(ajustes, "api_football_key", "chave-de-teste", raising=False)
    monkeypatch.setattr(ajustes, "raw_dir", tmp_path, raising=False)
    return tmp_path


def _cliente_sem_rede(orcamento: int | None) -> ClienteApiFootball:
    # Sem transporte real: se algum teste tentar ir à rede por engano, ele falha em vez
    # de silenciosamente consumir cota de verdade.
    return ClienteApiFootball(orcamento=orcamento, http=httpx.Client(base_url="http://invalido"))


def test_nome_do_cache_e_legivel(configurado: Path) -> None:
    """Conferir uma carga contra a fonte é abrir o arquivo certo; um hash puro não diria
    o que tem dentro."""
    with _cliente_sem_rede(1) as cliente:
        caminho = cliente.caminho_no_cache("fixtures/players", {"fixture": 1234567})
    assert caminho.name == "fixture-1234567.json"
    assert caminho.parent.name == "fixtures_players"


def test_resposta_em_cache_nao_gasta_cota(configurado: Path) -> None:
    """É isto que faz a carga ser retomável: o que já veio não é pedido de novo."""
    with _cliente_sem_rede(0) as cliente:
        caminho = cliente.caminho_no_cache("fixtures/players", {"fixture": 42})
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps({"response": ["ok"]}), encoding="utf-8")

        # Orçamento zero: se tentasse a rede, levantaria OrcamentoEsgotado.
        assert cliente.obter("fixtures/players", fixture=42) == {"response": ["ok"]}
        assert cliente.gastas == 0
        assert cliente.aproveitadas == 1


def test_orcamento_esgotado_para_antes_de_pedir(configurado: Path) -> None:
    """Parar ao fim do orçamento é o combinado, não falha: evita passar o resto do dia
    recebendo erro de cota."""
    from fscout.ingestion.apifootball.client import OrcamentoEsgotado

    with _cliente_sem_rede(0) as cliente, pytest.raises(OrcamentoEsgotado, match="esgotado"):
        cliente.obter("fixtures", league=71, season=2024)


def test_sem_teto_o_restante_e_desconhecido(configurado: Path) -> None:
    with _cliente_sem_rede(None) as cliente:
        assert cliente.restante is None
    with _cliente_sem_rede(5) as cliente:
        assert cliente.restante == 5


# ----------------------------------------------------------------------------------------
# Progresso da carga em várias sessões
# ----------------------------------------------------------------------------------------


def test_so_partidas_encerradas_entram_na_carga() -> None:
    """Jogo não disputado não tem estatística de jogador: pedir seria gastar cota à toa."""
    corpo = {
        "response": [
            {"fixture": {"id": 1, "status": {"short": "FT"}}},
            {"fixture": {"id": 2, "status": {"short": "NS"}}},
            {"fixture": {"id": 3, "status": {"short": "FT"}}},
        ]
    }
    assert [p["fixture"]["id"] for p in partidas_encerradas(corpo)] == [1, 3]


def test_progresso_conta_os_dias_que_ainda_faltam() -> None:
    """O número que responde "quando isso acaba", que é a pergunta de quem roda."""
    progresso = Progresso(competicao=71, temporada=2024, partidas_encerradas=380, faltam=250)
    assert progresso.dias_restantes(100) == 3
    assert not progresso.concluido
    assert progresso.por_cento == pytest.approx(34.2, abs=0.1)


def test_progresso_completo_nao_pede_mais_dias() -> None:
    progresso = Progresso(
        competicao=71, temporada=2024, partidas_encerradas=380, ja_em_cache=380, faltam=0
    )
    assert progresso.concluido
    assert progresso.dias_restantes(100) == 0
    assert progresso.por_cento == pytest.approx(100.0)


def test_temporada_vazia_nao_e_considerada_concluida() -> None:
    """Zero de zero não é "pronto": é sinal de que a temporada não veio."""
    assert not Progresso(competicao=71, temporada=2030).concluido
