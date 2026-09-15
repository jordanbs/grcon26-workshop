"""The colorimeter's frequency plan, which is the whole demo.

Every claim the demo makes rests on one arithmetic fact: a square wave
of exactly K cycles in a 4096-sample buffer, sampled at the same rate it
was played, lands in bin K and nowhere else. If that stops being true --
someone rounds a frequency, someone changes NFFT -- the transmittance
numbers stay plausible and quietly stop meaning anything.

`bench/colorimeter.py` imports gnuradio, which the test interpreter does
not have, so the constants and the generator are lifted out of it with
`ast` the way `test_beacon.py` lifts constants out of the `.grc`. That
is the point: these tests check the code that actually runs on the
bench, not a copy of it.
"""

import ast
import cmath
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "bench", "colorimeter.py")
DOC = os.path.join(ROOT, "docs", "colorimeter.md")

WANTED = ("NFFT", "RATE", "CYCLES", "COLOURS", "PINS")


def _lift():
    """Module-level constants and `square`, without importing gnuradio."""
    tree = ast.parse(open(BENCH).read())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in WANTED
                for t in node.targets):
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in ("square",
                                                                 "bin_hz"):
            keep.append(node)
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), BENCH, "exec"), ns)
    return ns


BENCH_NS = _lift()
NFFT = BENCH_NS["NFFT"]
RATE = BENCH_NS["RATE"]
CYCLES = BENCH_NS["CYCLES"]
COLOURS = BENCH_NS["COLOURS"]
PINS = BENCH_NS["PINS"]
square = BENCH_NS["square"]


def dft_bin(samples, k):
    """|X[k]| by direct summation. No numpy in this interpreter."""
    n = len(samples)
    mean = sum(samples) / float(n)
    step = -2j * cmath.pi * k / n
    return abs(sum((s - mean) * cmath.exp(step * i)
                   for i, s in enumerate(samples)))


def test_the_plan_is_three_colours_on_three_pins():
    assert COLOURS == ["red", "green", "blue"]
    assert len(PINS) == 3
    assert set(CYCLES) == set(COLOURS)


@pytest.mark.parametrize("colour", ["red", "green", "blue"])
def test_a_colour_lands_in_its_own_bin(colour):
    """The peak is AT k, not near it. This is the coherence claim."""
    k = CYCLES[colour]
    wave = square(k)
    assert len(wave) == NFFT

    here = dft_bin(wave, k)
    for offset in (-2, -1, 1, 2):
        assert dft_bin(wave, k + offset) < here / 100.0, (
            "bin %d leaks into %d" % (k, k + offset))


@pytest.mark.parametrize("colour", ["red", "green", "blue"])
def test_nothing_of_a_colour_reaches_another_colours_bin(colour):
    """Frequency multiplexing only works if the channels do not overlap.

    A square wave carries every odd harmonic, so this is not obvious --
    it is a property of the three numbers that were chosen.
    """
    wave = square(CYCLES[colour])
    own = dft_bin(wave, CYCLES[colour])
    for other in COLOURS:
        if other == colour:
            continue
        assert dft_bin(wave, CYCLES[other]) < own / 1000.0, (
            "%s bleeds into %s" % (colour, other))


def test_no_odd_harmonic_sits_on_a_fundamental():
    """The arithmetic behind the test above, stated directly."""
    fundamentals = set(CYCLES.values())
    for colour, k in CYCLES.items():
        for harmonic in range(3, 40, 2):
            assert k * harmonic not in fundamentals, (
                "%s harmonic %d lands on another colour" % (colour, harmonic))


def test_the_square_wave_is_roughly_balanced():
    """Badly unbalanced and most of the energy would be at DC instead."""
    for colour in COLOURS:
        wave = square(CYCLES[colour])
        duty = sum(wave) / float(len(wave))
        assert 0.49 < duty < 0.51


def test_the_document_quotes_the_frequencies_the_code_generates():
    """Doc drift here is invisible -- both halves keep working separately."""
    text = open(DOC).read()
    for colour in COLOURS:
        k = CYCLES[colour]
        hz = k * RATE / float(NFFT)
        row = re.search(r"^\|\s*%s\s*\|(.+)$" % colour, text, re.M)
        assert row, "no table row for %s in docs/colorimeter.md" % colour
        cells = row.group(1)
        assert str(k) in cells, "%s: cycle count %d missing" % (colour, k)
        assert "%.1f" % hz in cells, (
            "%s: frequency %.1f Hz missing" % (colour, hz))
