"""Histórico de lesões: o último item aberto da especificação, e o que ele realmente é.

A tabela `injuries` existe desde a Fase 0, vazia, com o comentário de que nenhum provedor
aberto de eventos registra lesão. A fonte agregada registra — mas **não** no formato que
o nome do endpoint sugere, e a diferença precisa estar declarada antes de qualquer número
sair daqui.

**O que a fonte entrega:** uma linha por *partida perdida*, com o motivo da ausência.
Não há data de início, data de fim nem dias fora. São 1.668 linhas para 383 atletas numa
temporada do Brasileirão.

**O que isso obriga a fazer, e o que cada coisa vale:**

| Campo | Como sai | Confiabilidade |
|---|---|---|
| `matches_missed` | ausências do episódio | **exato** — é o que a fonte conta |
| `start_date`, `end_date` | primeira e última partida perdida | limites, não diagnóstico |
| `days_out` | intervalo entre as duas | **piso**, não medida |
| `body_area` | só quando o motivo nomeia | ausente na maioria |

`days_out` é piso porque o afastamento começa antes da primeira partida perdida e termina
antes da seguinte disputada — a fonte só marca os jogos, não o calendário médico.

**Nem toda ausência é lesão.** Das 22 razões observadas, cinco são disciplinares ou
administrativas — cartões, suspensão, empréstimo, decisão técnica, motivo pessoal. Gravar
uma suspensão como lesão seria simplesmente errado, então a classificação é explícita e
auditável, no mesmo padrão da tradução do vocabulário da StatsBomb.

**Episódio.** Ausências médicas seguidas do mesmo atleta viram um episódio. O corte é um
intervalo de `JANELA_DE_EPISODIO` dias entre partidas perdidas: acima disso, presume-se
que o atleta voltou e se machucou de novo. É uma convenção declarada, não uma medida — e
é a única inferência deste módulo.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from fscout.db.models import ExternalId, Injury, Player
from fscout.db.session import get_engine
from fscout.ingestion.apifootball.client import ClienteApiFootball
from fscout.ingestion.apifootball.download import ENDPOINT_DE_LESOES
from fscout.ingestion.apifootball.mapper import FONTE

logger = logging.getLogger(__name__)

# Dias entre partidas perdidas acima dos quais se presume um episódio novo. Convenção
# declarada: com só a data das partidas não há como distinguir uma lesão longa de duas
# curtas com retorno no meio.
JANELA_DE_EPISODIO = 30

MEDICA = "medica"

# Classificação de cada motivo observado na fonte. Explícita, e não por palavra-chave,
# pelo mesmo motivo que a tradução do vocabulário da StatsBomb é explícita: "Suspended"
# e "Loan agreement" não contêm "injury", mas "Personal Reasons" também não, e uma regra
# por substring classificaria mal o dia em que a fonte escrever "Injured".
CATEGORIA_POR_MOTIVO: dict[str, str] = {
    "injury": MEDICA,
    "knee injury": MEDICA,
    "muscle injury": MEDICA,
    "thigh injury": MEDICA,
    "achilles tendon injury": MEDICA,
    "ankle injury": MEDICA,
    "groin injury": MEDICA,
    "leg injury": MEDICA,
    "back injury": MEDICA,
    "calf injury": MEDICA,
    "hip injury": MEDICA,
    "hamstring injury": MEDICA,
    "finger injury": MEDICA,
    "hand injury": MEDICA,
    "concussion": MEDICA,
    "illness": MEDICA,
    "yellow cards": "disciplinar",
    "red card": "disciplinar",
    "suspended": "disciplinar",
    "personal reasons": "administrativa",
    "loan agreement": "administrativa",
    "coach's decision": "administrativa",
}

# Área do corpo, quando o motivo a nomeia. Em inglês e minúsculo, como o resto do
# vocabulário gravado no banco (`body_part` guarda "left_foot", "head").
AREA_POR_MOTIVO: dict[str, str] = {
    "knee injury": "knee",
    "muscle injury": "muscle",
    "thigh injury": "thigh",
    "achilles tendon injury": "achilles",
    "ankle injury": "ankle",
    "groin injury": "groin",
    "leg injury": "leg",
    "back injury": "back",
    "calf injury": "calf",
    "hip injury": "hip",
    "hamstring injury": "hamstring",
    "finger injury": "finger",
    "hand injury": "hand",
    "concussion": "head",
}


@dataclass(frozen=True)
class Ausencia:
    """Uma partida que o atleta não disputou, com o motivo que a fonte deu."""

    player_ref: str
    quando: date
    motivo: str

    @property
    def categoria(self) -> str:
        return CATEGORIA_POR_MOTIVO.get(self.motivo.strip().lower(), "desconhecida")

    @property
    def area(self) -> str | None:
        return AREA_POR_MOTIVO.get(self.motivo.strip().lower())


@dataclass
class RelatorioDeLesoes:
    """O que entrou, o que ficou de fora e por quê."""

    ausencias_na_fonte: int = 0
    medicas: int = 0
    disciplinares: int = 0
    administrativas: int = 0
    motivos_desconhecidos: list[str] = field(default_factory=list)
    episodios: int = 0
    atletas: int = 0
    sem_area: int = 0
    atletas_fora_do_elenco: int = 0
    gastas: int = 0


def ler_ausencias(corpo: dict) -> list[Ausencia]:
    """Lê a resposta de `/injuries` sem supor o formato dela."""
    ausencias = []
    for item in corpo.get("response") or []:
        atleta = item.get("player") or {}
        partida = item.get("fixture") or {}
        identificador, quando = atleta.get("id"), partida.get("date")
        if identificador is None or not quando:
            continue
        try:
            momento = datetime.fromisoformat(str(quando))
        except ValueError:
            continue
        ausencias.append(
            Ausencia(
                player_ref=str(identificador),
                quando=momento.date(),
                motivo=str(atleta.get("reason") or ""),
            )
        )
    return ausencias


@dataclass
class Episodio:
    """Ausências médicas seguidas de um mesmo atleta, tratadas como um afastamento."""

    player_ref: str
    inicio: date
    fim: date
    partidas_perdidas: int
    motivos: list[str]

    @property
    def dias(self) -> int:
        """Piso do afastamento: ele começa antes da primeira partida perdida."""
        return (self.fim - self.inicio).days + 1

    @property
    def area(self) -> str | None:
        """A primeira área nomeada no episódio.

        A fonte alterna "Injury" e "Knee Injury" no mesmo afastamento; quando qualquer
        uma das linhas nomeia a área, ela vale para o episódio inteiro.
        """
        for motivo in self.motivos:
            area = AREA_POR_MOTIVO.get(motivo.strip().lower())
            if area:
                return area
        return None

    @property
    def descricao(self) -> str:
        """O motivo mais específico que a fonte deu, para o registro ser auditável."""
        nomeados = [m for m in self.motivos if AREA_POR_MOTIVO.get(m.strip().lower())]
        return (nomeados or self.motivos or ["Injury"])[0]


def agrupar_em_episodios(
    ausencias: list[Ausencia], janela: int = JANELA_DE_EPISODIO
) -> list[Episodio]:
    """Junta ausências médicas seguidas num episódio por atleta.

    Uma partida perdida isolada é um episódio de um jogo; sem agrupar, os 1.172 registros
    genéricos virariam 1.172 "lesões" e qualquer contagem de afastamentos ficaria sem
    sentido.
    """
    por_atleta: dict[str, list[Ausencia]] = defaultdict(list)
    for ausencia in ausencias:
        if ausencia.categoria == MEDICA:
            por_atleta[ausencia.player_ref].append(ausencia)

    episodios: list[Episodio] = []
    for player_ref, lista in por_atleta.items():
        lista.sort(key=lambda a: a.quando)
        atual: list[Ausencia] = []
        for ausencia in lista:
            if atual and ausencia.quando - atual[-1].quando > timedelta(days=janela):
                episodios.append(_fechar(player_ref, atual))
                atual = []
            atual.append(ausencia)
        if atual:
            episodios.append(_fechar(player_ref, atual))
    return episodios


def _fechar(player_ref: str, ausencias: list[Ausencia]) -> Episodio:
    return Episodio(
        player_ref=player_ref,
        inicio=ausencias[0].quando,
        fim=ausencias[-1].quando,
        partidas_perdidas=len(ausencias),
        motivos=[a.motivo for a in ausencias],
    )


def carregar_lesoes(competicao: int, temporada: int) -> RelatorioDeLesoes:
    """Baixa (uma requisição) e grava o histórico de afastamentos da temporada.

    Só entram atletas que já existem no elenco canônico. Criar um atleta a partir de uma
    lesão encheria a base de nomes sem partida nenhuma, e a ligação entre fontes perderia
    o sentido.
    """
    relatorio = RelatorioDeLesoes()

    with ClienteApiFootball(orcamento=2) as cliente:
        corpo = cliente.obter(ENDPOINT_DE_LESOES, league=competicao, season=temporada)
        relatorio.gastas = cliente.gastas

    ausencias = ler_ausencias(corpo)
    relatorio.ausencias_na_fonte = len(ausencias)
    desconhecidos: set[str] = set()
    for ausencia in ausencias:
        categoria = ausencia.categoria
        if categoria == MEDICA:
            relatorio.medicas += 1
        elif categoria == "disciplinar":
            relatorio.disciplinares += 1
        elif categoria == "administrativa":
            relatorio.administrativas += 1
        else:
            desconhecidos.add(ausencia.motivo)
    relatorio.motivos_desconhecidos = sorted(desconhecidos)

    episodios = agrupar_em_episodios(ausencias)

    with Session(get_engine()) as session:
        conhecidos = dict(
            session.execute(
                select(ExternalId.source_id, ExternalId.entity_id).where(
                    ExternalId.entity == Player.__tablename__, ExternalId.source == FONTE
                )
            ).all()
        )
        gravados: set[int] = set()
        for episodio in episodios:
            player_id = conhecidos.get(episodio.player_ref)
            if player_id is None:
                relatorio.atletas_fora_do_elenco += 1
                continue
            if player_id not in gravados:
                # Recarregar substitui: a fonte é a mesma e o episódio pode ter crescido
                # desde a última carga.
                session.execute(
                    delete(Injury).where(Injury.player_id == player_id, Injury.source == FONTE)
                )
                gravados.add(player_id)
            area = episodio.area
            if area is None:
                relatorio.sem_area += 1
            session.add(
                Injury(
                    player_id=player_id,
                    description=episodio.descricao,
                    body_area=area,
                    start_date=episodio.inicio,
                    end_date=episodio.fim,
                    days_out=episodio.dias,
                    matches_missed=episodio.partidas_perdidas,
                    source=FONTE,
                )
            )
            relatorio.episodios += 1
        session.commit()
        relatorio.atletas = len(gravados)

    return relatorio
