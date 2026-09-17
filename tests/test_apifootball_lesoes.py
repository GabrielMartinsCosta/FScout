"""Testes do histórico de afastamentos.

Este módulo carrega o último item aberto da especificação original — "histórico de lesões
com área afetada e tempo fora" — e o entrega **parcialmente**, porque a fonte não tem o
que o nome do endpoint promete. Os testes existem para fixar exatamente onde está a
fronteira entre o que é medido e o que é inferido:

- a contagem de partidas perdidas é exata, porque é o que a fonte conta;
- o agrupamento em episódios é convenção declarada, e é a única inferência;
- suspensão não é lesão, e classificar errado seria pior que não carregar nada.
"""

from __future__ import annotations

from datetime import date

import pytest

from fscout.ingestion.apifootball.injuries import (
    AREA_POR_MOTIVO,
    CATEGORIA_POR_MOTIVO,
    JANELA_DE_EPISODIO,
    MEDICA,
    Ausencia,
    agrupar_em_episodios,
    ler_ausencias,
)


def _ausencia(dia: int, motivo: str = "Injury", atleta: str = "1") -> Ausencia:
    return Ausencia(player_ref=atleta, quando=date(2024, 6, dia), motivo=motivo)


# ----------------------------------------------------------------------------------------
# Nem toda ausência é lesão
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "motivo", ["Injury", "Knee Injury", "Concussion", "Illness", "Hamstring Injury"]
)
def test_motivo_medico_entra(motivo: str) -> None:
    assert _ausencia(1, motivo).categoria == MEDICA


@pytest.mark.parametrize("motivo", ["Yellow Cards", "Red Card", "Suspended"])
def test_suspensao_nao_e_lesao(motivo: str) -> None:
    """Gravar cartão como lesão inventaria um afastamento médico que não houve."""
    assert _ausencia(1, motivo).categoria == "disciplinar"


@pytest.mark.parametrize("motivo", ["Personal Reasons", "Loan agreement", "Coach's decision"])
def test_ausencia_administrativa_nao_e_lesao(motivo: str) -> None:
    assert _ausencia(1, motivo).categoria == "administrativa"


def test_motivo_novo_nao_e_classificado_no_chute() -> None:
    """Se a fonte inventar um motivo, ele aparece como desconhecido e é relatado — e não
    escorrega para dentro de "lesão" por parecer com uma."""
    assert _ausencia(1, "Injured hamstring maybe").categoria == "desconhecida"


def test_classificacao_ignora_caixa_e_espaco() -> None:
    assert _ausencia(1, "  KNEE INJURY ").categoria == MEDICA
    assert _ausencia(1, "  KNEE INJURY ").area == "knee"


def test_todo_motivo_com_area_e_medico() -> None:
    """Contrato entre as duas tabelas: não faz sentido nomear a área de uma suspensão."""
    assert all(CATEGORIA_POR_MOTIVO.get(motivo) == MEDICA for motivo in AREA_POR_MOTIVO)


def test_motivo_generico_nao_inventa_area() -> None:
    """1.172 das linhas dizem só "Injury". Atribuir uma área a elas seria inventar
    diagnóstico."""
    assert _ausencia(1, "Injury").area is None


# ----------------------------------------------------------------------------------------
# Episódios: a única inferência do módulo
# ----------------------------------------------------------------------------------------


def test_ausencias_seguidas_viram_um_episodio() -> None:
    """Sem agrupar, os registros genéricos virariam uma "lesão" por partida perdida e
    qualquer contagem de afastamentos perderia o sentido."""
    episodios = agrupar_em_episodios([_ausencia(1), _ausencia(8), _ausencia(15)])
    assert len(episodios) == 1
    assert episodios[0].partidas_perdidas == 3
    assert episodios[0].inicio == date(2024, 6, 1)
    assert episodios[0].fim == date(2024, 6, 15)


def test_intervalo_longo_separa_dois_episodios() -> None:
    """Acima da janela presume-se que o atleta voltou e se machucou de novo."""
    longe = Ausencia(player_ref="1", quando=date(2024, 8, 1), motivo="Injury")
    episodios = agrupar_em_episodios([_ausencia(1), longe])
    assert len(episodios) == 2
    assert [e.partidas_perdidas for e in episodios] == [1, 1]


def test_a_janela_e_parametro_e_nao_numero_escondido() -> None:
    """A convenção precisa ser visível para poder ser discutida numa defesa."""
    ausencias = [_ausencia(1), _ausencia(20)]
    assert len(agrupar_em_episodios(ausencias, janela=30)) == 1
    assert len(agrupar_em_episodios(ausencias, janela=5)) == 2
    assert JANELA_DE_EPISODIO == 30


def test_atletas_diferentes_nunca_se_misturam() -> None:
    episodios = agrupar_em_episodios([_ausencia(1, atleta="1"), _ausencia(2, atleta="2")])
    assert len(episodios) == 2
    assert {e.player_ref for e in episodios} == {"1", "2"}


def test_suspensao_nao_entra_no_episodio() -> None:
    """Um cartão no meio de uma lesão não pode virar dia de afastamento médico."""
    episodios = agrupar_em_episodios(
        [_ausencia(1, "Injury"), _ausencia(8, "Yellow Cards"), _ausencia(15, "Injury")]
    )
    assert len(episodios) == 1
    assert episodios[0].partidas_perdidas == 2


def test_dias_fora_e_o_piso_do_afastamento() -> None:
    """Inclusivo nas duas pontas, e ainda assim um piso: a lesão começa antes da primeira
    partida perdida e termina antes da seguinte disputada."""
    episodio = agrupar_em_episodios([_ausencia(1), _ausencia(15)])[0]
    assert episodio.dias == 15


def test_uma_partida_perdida_e_um_episodio_de_um_dia() -> None:
    episodio = agrupar_em_episodios([_ausencia(10)])[0]
    assert episodio.partidas_perdidas == 1
    assert episodio.dias == 1


def test_area_nomeada_em_qualquer_linha_vale_para_o_episodio() -> None:
    """A fonte alterna "Injury" e "Thigh Injury" no mesmo afastamento — foi o caso real
    de Pablo Maia, com 25 linhas genéricas e 4 nomeando a coxa."""
    episodio = agrupar_em_episodios([_ausencia(1, "Injury"), _ausencia(8, "Thigh Injury")])[0]
    assert episodio.area == "thigh"
    assert episodio.descricao == "Thigh Injury"


def test_episodio_sem_area_guarda_o_motivo_generico() -> None:
    episodio = agrupar_em_episodios([_ausencia(1), _ausencia(8)])[0]
    assert episodio.area is None
    assert episodio.descricao == "Injury"


# ----------------------------------------------------------------------------------------
# Leitura defensiva
# ----------------------------------------------------------------------------------------


def test_leitura_ignora_registro_sem_atleta_ou_data() -> None:
    corpo = {
        "response": [
            {
                "player": {"id": 1, "reason": "Injury"},
                "fixture": {"date": "2024-06-01T19:00:00+00:00"},
            },
            {"player": {"reason": "Injury"}, "fixture": {"date": "2024-06-01T19:00:00+00:00"}},
            {"player": {"id": 2, "reason": "Injury"}, "fixture": {}},
            {"player": {"id": 3, "reason": "Injury"}, "fixture": {"date": "nao e data"}},
        ]
    }
    assert [a.player_ref for a in ler_ausencias(corpo)] == ["1"]


def test_leitura_de_resposta_vazia_nao_quebra() -> None:
    assert ler_ausencias({}) == []
    assert ler_ausencias({"response": None}) == []


def test_data_vem_do_horario_da_partida_em_utc() -> None:
    corpo = {
        "response": [
            {
                "player": {"id": 7, "reason": "Knee Injury"},
                "fixture": {"date": "2024-06-02T19:00:00+00:00"},
            }
        ]
    }
    ausencia = ler_ausencias(corpo)[0]
    assert ausencia.quando == date(2024, 6, 2)
    assert ausencia.area == "knee"
