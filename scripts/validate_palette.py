"""Validação computável da paleta categórica usada nos gráficos do FScout.

Porte fiel de ``scripts/validate_palette.js`` (skill dataviz) para Python, feito
porque esta máquina não tem Node e a regra é explícita: a segurança da paleta
para daltonismo se **calcula**, não se estima a olho.

Mantém do original, sem reinterpretação:

* as matrizes de Machado, Oliveira & Fernandes (2009) em severidade 1.0, sobre
  RGB linear — os limiares de CVD são calibrados para *este* modelo de simulação;
* ΔE como distância euclidiana em OKLab multiplicada por 100;
* os seis limiares (faixa de luminosidade, piso de croma, separação CVD, piso de
  visão normal, contraste, e as checagens ordinais).

Checagens 1 (ordem fixa de matizes) e 6 (as cores vêm da paleta documentada) são
regras estruturais, não medíveis a partir dos hexadecimais.

Uso::

    python scripts/validate_palette.py "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all
    python scripts/validate_palette.py "#86b6ef,#5598e7,#256abf,#104281" --ordinal

Código de saída 0, ou 1 se alguma checagem reprovar (FAIL); 2 para erro de uso.
WARN não reprova: CVD adjacente na faixa 6–8 e contraste abaixo de 3:1 são
legais *apenas* com codificação secundária (rótulos diretos, vãos, textura).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Iterable, Sequence

# -- limiares -----------------------------------------------------------------
BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}  # OKLCH L
CHROMA_FLOOR = 0.10  # OKLCH C
CVD_TARGET, CVD_FLOOR = 8.0, 6.0  # ΔE OKLab×100, min(protan, deutan), pares adjacentes
NORMAL_FLOOR = 15.0  # ΔE OKLab×100, pior par da lista ativa, visão não simulada
CONTRAST_MIN = 3.0  # WCAG contra a superfície
DEFAULT_SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
ORDINAL_MIN_DL = 0.06  # ΔL OKLCH mínimo entre degraus vizinhos
ORDINAL_LIGHT_FLOOR = 2.0  # degrau mais claro: contraste WCAG contra a superfície

# Machado, Oliveira & Fernandes (2009), severidade 1.0, sobre RGB linear.
MACHADO = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritan": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}

# -- fronteira de entrada ------------------------------------------------------
# Toda cor vinda de fora passa por aqui antes de qualquer conta: sem isso um
# valor inválido vira NaN e a validação falha ABERTA (passa por engano). O
# conjunto de espaços é a interseção entre o que JS trim() e Python strip()
# removem, para o porte se comportar igual ao original.
WS_RUN = "[ \t\n\v\f\r   -     　]+"
_WS_RE = re.compile(f"^{WS_RUN}|{WS_RUN}$")
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def strip_ws(value: str) -> str:
    return _WS_RE.sub("", value)


def split_colors(raw: str | None) -> list[str]:
    return [c for c in (strip_ws(p) for p in (raw or "").split(",")) if c]


def is_hex_color(value: str) -> bool:
    return bool(_HEX_RE.match(value))


# -- conversões de cor ---------------------------------------------------------
def hex_to_srgb(h: str) -> tuple[float, float, float]:
    h = strip_ws(h).lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _s2lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lin(h: str) -> tuple[float, float, float]:
    r, g, b = hex_to_srgb(h)
    return _s2lin(r), _s2lin(g), _s2lin(b)


def _rel_lum(h: str) -> float:
    r, g, b = lin(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_rel_lum(a), _rel_lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _cbrt(x: float) -> float:
    # Math.cbrt do JS aceita negativos; x ** (1/3) em Python não.
    return math.copysign(abs(x) ** (1 / 3), x)


def oklab_from_lin(rgb: Sequence[float]) -> tuple[float, float, float]:
    r, g, b = rgb
    # Nomes do espaco LMS da definicao original do OKLab (long, medium, short),
    # prefixados porque "l" sozinho se confunde com o algarismo 1.
    lms_l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    lms_m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    lms_s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * lms_l + 0.7936177850 * lms_m - 0.0040720468 * lms_s,  # L
        1.9779984951 * lms_l - 2.4285922050 * lms_m + 0.4505937099 * lms_s,  # a
        0.0259040371 * lms_l + 0.7827717662 * lms_m - 0.8086757660 * lms_s,  # b
    )


def oklab(h: str) -> tuple[float, float, float]:
    return oklab_from_lin(lin(h))


def oklch(h: str) -> tuple[float, float]:
    L, a, b = oklab(h)
    return L, math.hypot(a, b)


def okhue(h: str) -> float:
    _, a, b = oklab(h)
    return (math.degrees(math.atan2(b, a)) % 360 + 360) % 360


def simulate(h: str, kind: str) -> tuple[float, float, float]:
    r, g, b = lin(h)
    M = MACHADO[kind]
    clamp = lambda c: max(0.0, min(1.0, c))  # noqa: E731
    return (
        clamp(M[0][0] * r + M[0][1] * g + M[0][2] * b),
        clamp(M[1][0] * r + M[1][1] * g + M[1][2] * b),
        clamp(M[2][0] * r + M[2][1] * g + M[2][2] * b),
    )


def delta_e(h1: str, h2: str, kind: str | None = None) -> float:
    """Distância euclidiana em OKLab ×100. ``kind=None`` = visão não simulada."""
    a = oklab_from_lin(simulate(h1, kind) if kind else lin(h1))
    b = oklab_from_lin(simulate(h2, kind) if kind else lin(h2))
    return 100 * math.dist(a, b)


def _pairlist(n: int, pairs: str) -> list[tuple[int, int]]:
    if pairs == "all":
        return [(i, j) for i in range(n) for j in range(i + 1, n)]
    return [(i, i + 1) for i in range(n - 1)]


Report = list[tuple[str, object, str]]


# -- checagens -----------------------------------------------------------------
def validate(
    palette: Sequence[str],
    mode: str = "light",
    surface: str | None = None,
    pairs: str = "adjacent",
) -> tuple[Report, bool]:
    surface = surface or DEFAULT_SURFACE[mode]
    lo, hi = BAND[mode]
    report: Report = []
    ok = True

    # 2. faixa de luminosidade
    offband = [(c, round(oklch(c)[0], 3)) for c in palette if not lo <= oklch(c)[0] <= hi]
    if offband:
        ok = False
    report.append(
        (
            "Lightness band",
            not offband,
            f"outside band: {offband}" if offband else f"all {len(palette)} inside L {lo}–{hi}",
        )
    )

    # 3. piso de croma (abaixo dele o matiz é lido como cinza)
    lowc = [(c, round(oklch(c)[1], 3)) for c in palette if oklch(c)[1] < CHROMA_FLOOR]
    if lowc:
        ok = False
    report.append(
        (
            "Chroma floor",
            not lowc,
            f"below floor (reads gray): {lowc}"
            if lowc
            else f"all {len(palette)} >= {CHROMA_FLOOR}",
        )
    )

    # 4. separação CVD — adjacente em barras/linhas; TODOS os pares em dispersão,
    #    bolhas, mapas e pequenos múltiplos.
    pl = _pairlist(len(palette), pairs)
    label = "all-pairs" if pairs == "all" else "adjacent"
    worst: tuple[float, str, str, str] | None = None
    for kind in ("protan", "deutan"):
        for i, j in pl:
            d = delta_e(palette[i], palette[j], kind)
            if worst is None or d < worst[0]:
                worst = (d, kind, palette[i], palette[j])
    tri = min((delta_e(palette[i], palette[j], "tritan") for i, j in pl), default=99.0)
    wd = worst[0] if worst else 99.0
    cvd_state = "pass" if wd >= CVD_TARGET else "floor" if wd >= CVD_FLOOR else "fail"
    if cvd_state == "fail":
        ok = False
    report.append(
        (
            "CVD separation",
            cvd_state,
            f"worst {label} {worst[3]}↔{worst[2]} ΔE {wd:.1f} ({worst[1]}) · tritan {tri:.1f}"
            if worst
            else "n/a",
        )
    )

    # 4b. piso de visão normal. O portão de CVD protege quem é dicromata; este
    #     protege todo o resto — vizinhos têm que continuar fáceis de distinguir.
    #     É portão duro: codificação secundária não desculpa.
    nworst: tuple[float, str, str] | None = None
    for i, j in pl:
        d = delta_e(palette[i], palette[j])
        if nworst is None or d < nworst[0]:
            nworst = (d, palette[i], palette[j])
    nd = nworst[0] if nworst else 99.0
    nor_state = "pass" if nd >= NORMAL_FLOOR else "fail"
    if nor_state == "fail":
        ok = False
    detail = f"worst {label} {nworst[2]}↔{nworst[1]} ΔE {nd:.1f} (normal)" if nworst else "n/a"
    if nworst and nd < NORMAL_FLOOR:
        detail += f" — below {NORMAL_FLOOR:.0f}, hard to tell apart even with full color vision"
    report.append(("Normal-vision floor", nor_state, detail))

    # 5. contraste contra a superfície — abaixo de 3:1 é alívio documentado
    #    (rótulos visíveis / visão de tabela), não reprovação.
    low = [
        (c, round(contrast(c, surface), 2)) for c in palette if contrast(c, surface) < CONTRAST_MIN
    ]
    report.append(
        (
            "Contrast vs surface",
            "relief" if low else "pass",
            f"below {CONTRAST_MIN}:1 — relief required (visible labels or table view): {low}"
            if low
            else f"all {len(palette)} >= {CONTRAST_MIN}:1",
        )
    )

    return report, ok


def validate_ordinal(
    palette: Sequence[str], mode: str = "light", surface: str | None = None
) -> tuple[Report, bool]:
    """Categorias ordenadas usam rampa de um matiz, não matizes categóricos.

    As checagens categóricas reprovam uma rampa correta por construção (ela
    atravessa a faixa de luminosidade e os degraus claros ficam abaixo do piso
    de croma). Estas verificam que a rampa é lida *como* rampa.
    """
    surface = surface or DEFAULT_SURFACE[mode]
    report: Report = []
    ok = True
    Ls = [oklch(c)[0] for c in palette]

    # Luminosidade monotônica: a ordem por L tem que ser a de entrada ou seu inverso.
    order = sorted(range(len(Ls)), key=lambda i: Ls[i])
    fwd = all(v == i for i, v in enumerate(order))
    rev = all(v == len(Ls) - 1 - i for i, v in enumerate(order))
    mono = fwd or rev
    if not mono:
        ok = False
    report.append(
        (
            "Lightness monotone",
            mono,
            "steps read light→dark"
            if mono
            else f"out of order — L values {[round(valor, 3) for valor in Ls]}",
        )
    )

    # ΔL adjacente: filtra no vão CRU e só arredonda para exibir — filtrar o
    # valor arredondado deixaria passar vãos em [0.0595, 0.06).
    gaps = [abs(Ls[i + 1] - Ls[i]) for i in range(len(Ls) - 1)]
    thin = [
        (palette[i], palette[i + 1], round(g, 3)) for i, g in enumerate(gaps) if g < ORDINAL_MIN_DL
    ]
    if thin:
        ok = False
    report.append(
        (
            "Adjacent ΔL",
            not thin,
            f"steps too close: {thin}" if thin else f"all gaps >= {ORDINAL_MIN_DL}",
        )
    )

    # Degrau mais claro contra a superfície: a ponta pálida ainda tem que ser marca.
    by_l = sorted(palette, key=lambda c: oklch(c)[0])
    lightest = by_l[-1] if mode == "light" else by_l[0]
    cr = contrast(lightest, surface)
    if cr < ORDINAL_LIGHT_FLOOR:
        ok = False
    report.append(
        (
            "Light-end contrast",
            cr >= ORDINAL_LIGHT_FLOOR,
            f"{lightest} at {cr:.2f}:1 vs surface"
            + ("" if cr >= ORDINAL_LIGHT_FLOOR else f" — below {ORDINAL_LIGHT_FLOOR}:1 floor"),
        )
    )

    # Matiz único: salto de matiz significa que a rampa é categórica disfarçada.
    hues = [okhue(c) for c in palette]
    spread = (max(hues) - min(hues)) if hues else 0.0
    if spread > 180:
        spread = 360 - spread
    one_hue = spread <= 40
    if not one_hue:
        ok = False
    report.append(
        (
            "Single hue",
            one_hue,
            f"hue spread {spread:.0f}°" + ("" if one_hue else " — >40°, not a one-hue ramp"),
        )
    )

    return report, ok


# -- saída ---------------------------------------------------------------------
GLYPH: dict[object, str] = {
    True: "PASS",
    False: "FAIL",
    "pass": "PASS",
    "floor": "WARN",
    "fail": "FAIL",
    "relief": "WARN",
}


def print_report(report: Report, ok: bool, mode: str, surface: str, ordinal: bool, n: int) -> None:
    kind = "ordinal ramp" if ordinal else "categorical"
    print(f"\nPalette ({mode}, surface {surface}, {kind}): {n} slots")
    for name, state, detail in report:
        print(f"  [{GLYPH.get(state, state):<4}] {name:<22} {detail}")
    verdict = "ALL CHECKS PASS" if ok else "FAILED — fix the marked checks"
    if ordinal:
        print(
            f"\n  → {verdict}  (ordinal: one hue, monotone L, visible step gaps,"
            " light end clears surface)"
        )
    else:
        print(f"\n  → {verdict}  (CVD in the 6–8 floor band is legal ONLY with secondary encoding)")
        print(
            "  scope: categorical palettes only. For a lone status/text color check"
            " WCAG text contrast;"
        )
        print("  for a sequential ramp, lightness monotonicity.\n")


def run(
    raw: str,
    mode: str = "light",
    surface: str | None = None,
    pairs: str = "adjacent",
    ordinal: bool = False,
) -> bool:
    """Valida e imprime. Retorna ``True`` se nada reprovou."""
    palette = split_colors(raw)
    surf = strip_ws(surface) if surface else ""
    surf = surf or DEFAULT_SURFACE[mode]
    bad = [c for c in [*palette, surf] if not is_hex_color(c)]
    if not palette or bad:
        raise ValueError(f"paleta vazia ou hex inválido: {bad}")
    report, ok = (
        validate_ordinal(palette, mode, surf) if ordinal else validate(palette, mode, surf, pairs)
    )
    print_report(report, ok, mode, surf, ordinal, len(palette))
    return ok


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Valida uma paleta categórica ou uma rampa ordinal.")
    p.add_argument("palette", help='hexadecimais separados por vírgula: "#2a78d6,#eb6834,..."')
    p.add_argument("--mode", choices=("light", "dark"), default="light")
    p.add_argument("--surface", default=None)
    p.add_argument("--pairs", choices=("adjacent", "all"), default="adjacent")
    p.add_argument("--ordinal", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    palette = split_colors(args.palette)
    surface = strip_ws(args.surface) if args.surface else ""
    surface = surface or DEFAULT_SURFACE[args.mode]
    if not palette:
        print(
            'usage: python validate_palette.py "#hex,#hex,..." [--mode light|dark]'
            " [--surface #hex] [--pairs adjacent|all] [--ordinal]",
            file=sys.stderr,
        )
        return 2
    bad = [c for c in [*palette, surface] if not is_hex_color(c)]
    if bad:
        print(f"invalid hex value(s): {', '.join(bad)} — expected #rrggbb", file=sys.stderr)
        return 2

    report, ok = (
        validate_ordinal(palette, args.mode, surface)
        if args.ordinal
        else validate(palette, args.mode, surface, args.pairs)
    )
    print_report(report, ok, args.mode, surface, args.ordinal, len(palette))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
