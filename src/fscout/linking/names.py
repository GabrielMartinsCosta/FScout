"""Normalização e comparação de nomes de pessoas e equipes.

Cada fonte escreve nomes do seu jeito. A StatsBomb registra "Lionel Andrés Messi
Cuccittini"; o Transfermarkt, "Lionel Messi". Uma escreve "Alexis MacAllister", a outra
"Alexis Mac Allister"; uma tem "Enzo Fernandez", a outra "Enzo Fernández". Comparar texto
exato falha em todos esses casos.

A comparação aqui é deliberadamente simples e explicável — acento removido, partículas
ignoradas, conjunto de palavras comparado —, porque cada decisão de ligação precisa poder
ser justificada. A precisão não vem de um comparador sofisticado, e sim de onde ele é
aplicado: entre os ~25 atletas de uma equipe numa mesma partida, e não entre 50 mil nomes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

# Letras que a decomposição Unicode não separa em letra-base mais acento.
_UNDECOMPOSABLE = str.maketrans(
    {
        "ø": "o",
        "Ø": "o",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "ß": "ss",
        "đ": "d",
        "Đ": "d",
        "ł": "l",
        "Ł": "l",
        "ı": "i",  # noqa: RUF001 - i sem pingo (turco), intencional
        "ð": "d",
        "þ": "th",
    }
)

# Inclui o apóstrofo tipográfico (U+2019), com que algumas fontes grafam nomes como N'Golo.
_SEPARATORS = re.compile(r"[\s\-'’`.,()/]+")  # noqa: RUF001


def is_name(value: object) -> bool:
    """Texto não vazio. Barra `None` e o `NaN` que o pandas usa para valor ausente."""
    return isinstance(value, str) and bool(value.strip())


# Partículas que variam entre fontes ("De Arrascaeta" x "Arrascaeta") sem identificar ninguém.
PARTICLES = frozenset(
    {
        "de",
        "da",
        "do",
        "dos",
        "das",
        "del",
        "della",
        "di",
        "du",
        "van",
        "von",
        "der",
        "den",
        "la",
        "le",
        "el",
        "y",
        "e",
    }
)

# Um nome de uma palavra só ("Gomes") contido num nome maior ("Tiago Gomes") é indício fraco:
# a similaridade é limitada a este teto para nunca empatar com uma correspondência completa.
SINGLE_TOKEN_CAP = 0.8


def normalize(text: str) -> str:
    """Minúsculas, sem acento, separadores unificados em espaço simples."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_UNDECOMPOSABLE))
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SEPARATORS.sub(" ", without_marks.lower()).strip()


def tokens(text: str) -> tuple[str, ...]:
    """Palavras significativas do nome, na ordem original, sem partículas."""
    return tuple(token for token in normalize(text).split() if token not in PARTICLES)


def compact(text: str) -> str:
    """Nome sem espaços, para igualar "MacAllister" e "Mac Allister"."""
    return "".join(tokens(text))


def name_similarity(first: str, second: str) -> float:
    """Similaridade entre dois nomes, de 0 a 1.

    Combina dois critérios e fica com o maior:

    - **contenção:** fração das palavras do nome mais curto presentes no mais longo. Resolve
      nome completo contra nome de uso ("Lionel Andrés Messi Cuccittini" x "Lionel Messi").
    - **sequência:** semelhança de caracteres entre as palavras ordenadas. Resolve grafias
      vizinhas que a contenção não pega.
    """
    first_tokens, second_tokens = tokens(first), tokens(second)
    if not first_tokens or not second_tokens:
        return 0.0
    if compact(first) == compact(second):
        return 1.0

    shorter, longer = sorted((set(first_tokens), set(second_tokens)), key=len)
    containment = len(shorter & longer) / len(shorter)
    if len(shorter) == 1:
        containment *= SINGLE_TOKEN_CAP

    sequence = SequenceMatcher(
        None, " ".join(sorted(first_tokens)), " ".join(sorted(second_tokens))
    ).ratio()
    return max(containment, sequence)


def best_similarity(first_names: Iterable[str | None], second_names: Iterable[str | None]) -> float:
    """Maior similaridade entre quaisquer variantes de nome dos dois lados.

    Um atleta tem nome de uso, nome completo e apelido; basta que uma variante de cada lado
    corresponda.
    """
    left = [name for name in first_names if is_name(name)]
    right = [name for name in second_names if is_name(name)]
    return max((name_similarity(a, b) for a in left for b in right), default=0.0)


def same_name(first_names: Iterable[str | None], second_names: Iterable[str | None]) -> bool:
    """Alguma variante de nome é idêntica dos dois lados, depois de normalizada.

    É evidência mais forte que similaridade 1: "Alex da Silva" contém as palavras de
    "Alex Sandro Lobo Silva" e atinge similaridade máxima por contenção, sem ser o mesmo nome.
    """
    left = {compact(name) for name in first_names if is_name(name)} - {""}
    right = {compact(name) for name in second_names if is_name(name)} - {""}
    return bool(left & right)
