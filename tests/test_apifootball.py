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

import pytest

from fscout.ingestion.apifootball import (
    GRUPOS_MINIMOS,
    ChaveAusente,
    Competicao,
    Sondagem,
    _achatar,
    _cliente,
    _competicoes_de,
    _intervalo_do_plano,
    avaliar,
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
    assert _achatar({"shots": {"total": 3, "on": 1}}) == ["shots.on", "shots.total"]


def test_achatar_aguenta_valor_solto_no_lugar_de_grupo() -> None:
    """Se a fonte mudar e mandar um escalar, o código relata em vez de quebrar."""
    assert _achatar({"rating": "7.2", "shots": {"total": 2}}) == ["rating", "shots.total"]


def test_competicoes_de_resposta_vazia_nao_quebra() -> None:
    assert _competicoes_de({}) == []
    assert _competicoes_de({"response": None}) == []


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
    competicao = _competicoes_de(corpo)[0]
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
    assert _intervalo_do_plano(mensagem) == (2022, 2024)


def test_recusa_sem_intervalo_nao_inventa_um() -> None:
    """Outra recusa real: a do parâmetro `last`, que não traz intervalo nenhum."""
    assert _intervalo_do_plano("Free plans do not have access to the Last parameter.") is None


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
        _cliente()
