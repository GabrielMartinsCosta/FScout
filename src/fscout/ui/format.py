"""Como um número do motor vira texto na tela.

Existe por um motivo de correção, não de estética. O motor calcula o percentil sobre o
valor **por 90 minutos** quando a métrica admite normalização, e sobre o valor bruto
quando não admite (`_ranquear`, em `metrics/engine.py`). Se a tela escolhesse por conta
própria qual dos dois exibir, apareceria um cartão com "12 gols" ao lado de "percentil
84" em que o 84 se refere a outro número — o de gols por 90 minutos. A regra fica
escrita **uma vez**, aqui, e todas as telas a consultam.

Ausência também é informação e tem tratamentos diferentes: uma razão sem amostra
suficiente não é zero, é desconhecida, e aparece como travessão com o motivo ao lado.
"""

from __future__ import annotations

from typing import Any

TRACO = "—"  # travessão: o valor não existe, e isso é diferente de valer zero

Definicao = dict[str, Any]
Medida = dict[str, Any]


def usou_por_90(definicao: Definicao, medida: Medida) -> bool:
    """Mesma condição do motor ao ranquear. Não altere uma sem a outra."""
    return bool(definicao.get("per_90")) and medida.get("per_90") is not None


def numero_exibido(definicao: Definicao, medida: Medida) -> float | None:
    """O número que a tela mostra: o mesmo sobre o qual o percentil foi calculado."""
    if usou_por_90(definicao, medida):
        return medida.get("per_90")
    return medida.get("value")


def _milhar(valor: float) -> str:
    return f"{round(valor):,}".replace(",", ".")


def formatar_valor(definicao: Definicao, medida: Medida) -> str:
    """Texto do valor, com a unidade que a definição declara."""
    valor = numero_exibido(definicao, medida)
    if valor is None:
        return TRACO

    unidade = str(definicao.get("unit", "count"))
    if unidade == "percent":
        # Razões saem do motor como fração de 0 a 1.
        return f"{valor * 100:.1f}%".replace(".", ",")
    if unidade == "meters":
        return f"{valor:.1f} m".replace(".", ",")
    if unidade == "minutes":
        return f"{_milhar(valor)} min"
    if unidade == "xg":
        return f"{valor:.2f}".replace(".", ",")
    # Contagem: por 90 minutos é fracionária; bruta é inteira.
    if usou_por_90(definicao, medida):
        return f"{valor:.2f}".replace(".", ",")
    return _milhar(valor)


def rotulo(definicao: Definicao, medida: Medida | None = None) -> str:
    """Nome da métrica, dizendo quando o número está normalizado por 90 minutos."""
    nome = str(definicao.get("label", definicao.get("key", "")))
    if medida is not None and usou_por_90(definicao, medida):
        return f"{nome} (por 90 min)"
    return nome


def formatar_percentil(medida: Medida) -> str:
    """Percentil com a população que o gerou.

    A população vai junto porque "percentil 90" entre dez atletas e entre duzentos são
    afirmações de forças muito diferentes.
    """
    percentil = medida.get("percentile")
    if percentil is None:
        return TRACO
    populacao = medida.get("population") or 0
    return f"{percentil:.0f}º entre {populacao}" if populacao else f"{percentil:.0f}º"


def motivo_da_ausencia(definicao: Definicao, medida: Medida) -> str:
    """Por que não há número. Dito em português, não como célula vazia."""
    if numero_exibido(definicao, medida) is not None:
        return ""
    minimo = int(definicao.get("min_sample") or 0)
    amostra = int(medida.get("sample") or 0)
    if minimo and amostra < minimo:
        return f"amostra insuficiente ({amostra} de {minimo} mínimos)"
    if not amostra:
        return "nenhuma ação no recorte"
    return "sem valor no recorte"


def texto_de_amostra(medida: Medida) -> str:
    amostra = int(medida.get("sample") or 0)
    minutos = int(medida.get("minutes") or 0)
    partes = []
    if amostra:
        partes.append(f"{_milhar(amostra)} ações")
    if minutos:
        partes.append(f"{_milhar(minutos)} min")
    return " · ".join(partes)


def quebrar(texto: str, largura: int = 18) -> str:
    """Quebra rótulo longo em linhas, para o eixo não cortar o texto.

    Rótulo cortado é pior que rótulo ausente: o leitor não sabe o que está faltando.
    """
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        candidata = f"{atual} {palavra}".strip()
        if len(candidata) > largura and atual:
            linhas.append(atual)
            atual = palavra
        else:
            atual = candidata
    if atual:
        linhas.append(atual)
    return "<br>".join(linhas)
