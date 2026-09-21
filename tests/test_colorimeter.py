"""The colorimeter's frequency plan, which is the whole demo.

Every claim the demo makes rests on one arithmetic fact: a square wave
of exactly K cycles in a 4096-sample buffer, sampled at the same rate it
was played, lands in bin K and nowhere else. If that stops being true --
someone rounds a frequency, someone changes NFFT -- the transmittance
numbers stay plausible and quietly stop meaning anything.

`bench/colorimeter.py` imports gnuradio, which the test interpreter does
not have, so the constants and the generator are lifted out of it with
`ast`, rather than imported. That is the point: these tests check the
code that actually runs on the bench, not a copy of it.
"""

import ast
import cmath
import contextlib
import math
import os
import re
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "bench", "colorimeter.py")
DOC = os.path.join(ROOT, "docs", "colorimeter.md")

WANTED = ("NFFT", "RATE", "CYCLES", "COLORS", "PINS")


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
COLORS = BENCH_NS["COLORS"]
PINS = BENCH_NS["PINS"]
square = BENCH_NS["square"]


def dft_bin(samples, k):
    """|X[k]| by direct summation. No numpy in this interpreter."""
    n = len(samples)
    mean = sum(samples) / float(n)
    step = -2j * cmath.pi * k / n
    return abs(sum((s - mean) * cmath.exp(step * i)
                   for i, s in enumerate(samples)))


def test_the_plan_is_three_colors_on_three_pins():
    assert COLORS == ["red", "green", "blue"]
    assert len(PINS) == 3
    assert set(CYCLES) == set(COLORS)


@pytest.mark.parametrize("color", ["red", "green", "blue"])
def test_a_color_lands_in_its_own_bin(color):
    """The peak is AT k, not near it. This is the coherence claim."""
    k = CYCLES[color]
    wave = square(k)
    assert len(wave) == NFFT

    here = dft_bin(wave, k)
    for offset in (-2, -1, 1, 2):
        assert dft_bin(wave, k + offset) < here / 100.0, (
            "bin %d leaks into %d" % (k, k + offset))


@pytest.mark.parametrize("color", ["red", "green", "blue"])
def test_nothing_of_a_color_reaches_another_colors_bin(color):
    """Frequency multiplexing only works if the channels do not overlap.

    A square wave carries every odd harmonic, so this is not obvious --
    it is a property of the three numbers that were chosen.
    """
    wave = square(CYCLES[color])
    own = dft_bin(wave, CYCLES[color])
    for other in COLORS:
        if other == color:
            continue
        assert dft_bin(wave, CYCLES[other]) < own / 1000.0, (
            "%s bleeds into %s" % (color, other))


def test_no_odd_harmonic_sits_on_a_fundamental():
    """The arithmetic behind the test above, stated directly."""
    fundamentals = set(CYCLES.values())
    for color, k in CYCLES.items():
        for harmonic in range(3, 40, 2):
            assert k * harmonic not in fundamentals, (
                "%s harmonic %d lands on another color" % (color, harmonic))


def test_the_square_wave_is_roughly_balanced():
    """Badly unbalanced and most of the energy would be at DC instead."""
    for color in COLORS:
        wave = square(CYCLES[color])
        duty = sum(wave) / float(len(wave))
        assert 0.49 < duty < 0.51


def test_the_document_quotes_the_frequencies_the_code_generates():
    """Doc drift here is invisible -- both halves keep working separately."""
    text = open(DOC).read()
    for color in COLORS:
        k = CYCLES[color]
        hz = k * RATE / float(NFFT)
        row = re.search(r"^\|\s*%s\s*\|(.+)$" % color, text, re.M)
        assert row, "no table row for %s in docs/colorimeter.md" % color
        cells = row.group(1)
        assert str(k) in cells, "%s: cycle count %d missing" % (color, k)
        assert "%.1f" % hz in cells, (
            "%s: frequency %.1f Hz missing" % (color, hz))


# --------------------------------------------------- the rule, in two places

GRC = os.path.join(ROOT, "flowgraphs", "m2k_colorimeter.grc")

# The two blocks and the bench script all `import numpy as np`, and this
# interpreter has no numpy. They want two things out of it: `isfinite`,
# which numpy applies elementwise and `math` does not, and `float32` as
# a dtype label. Both are a couple of lines.
class _NP(object):
    float32 = float

    @staticmethod
    def isfinite(x):
        try:
            return [math.isfinite(v) for v in x]
        except TypeError:
            return math.isfinite(x)


@contextlib.contextmanager
def _stubbed(published):
    """numpy, pmt and gnuradio, in the shapes these blocks touch."""
    pmt_stub = types.ModuleType("pmt")
    pmt_stub.intern = lambda s: s
    pmt_stub.cons = lambda a, b: (a, b)
    pmt_stub.from_double = float

    class _Block(object):
        def __init__(self, **kwargs):
            pass

        def message_port_register_in(self, port):
            pass

        def message_port_register_out(self, port):
            pass

        def message_port_pub(self, port, msg):
            published.append((port, msg))

        def set_msg_handler(self, port, handler):
            pass

    gnuradio = types.ModuleType("gnuradio")
    gr_stub = types.ModuleType("gnuradio.gr")
    gr_stub.sync_block = _Block
    gnuradio.gr = gr_stub

    numpy_stub = types.ModuleType("numpy")
    numpy_stub.isfinite = _NP.isfinite
    numpy_stub.float32 = float

    added = {"pmt": pmt_stub, "gnuradio": gnuradio,
             "gnuradio.gr": gr_stub, "numpy": numpy_stub}
    saved = {k: sys.modules.get(k) for k in added}
    sys.modules.update(added)
    try:
        yield
    finally:
        for key, was in saved.items():
            if was is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = was


# Every block carries these whatever it is; they are not constructor
# arguments to the embedded class.
_GRC_STANDARD = ("comment", "_source_code", "alias", "affinity",
                 "minoutbuf", "maxoutbuf")


def _embedded(name):
    """One epy_block's source, and the arguments the canvas passes it.

    The arguments matter as much as the source. A threshold set on the
    canvas overrides the default in the embedded __init__, so a test
    that instantiates the class bare is testing a block nobody runs.
    """
    yaml = pytest.importorskip("yaml")
    graph = yaml.safe_load(open(GRC))
    for block in graph["blocks"]:
        if block["name"] == name:
            params = block["parameters"]
            kwargs = {k: ast.literal_eval(str(v))
                      for k, v in params.items() if k not in _GRC_STANDARD}
            return params["_source_code"], kwargs
    raise AssertionError("no block named %s in %s" % (name, GRC))


def _instantiate(name, **kwargs):
    """The epy_block's class, run outside GNU Radio."""
    published = []
    source, on_canvas = _embedded(name)
    on_canvas.update(kwargs)
    with _stubbed(published):
        ns = {}
        exec(source, ns)
        return ns["blk"](**on_canvas), published


def _bench_rule():
    """`verdict` and its thresholds, lifted out of the bench script."""
    tree = ast.parse(open(BENCH).read())
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name)
                and t.id in ("CLEAR", "OPAQUE", "MARGIN", "NAMES")
                for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "verdict")]
    ns = {"np": _NP}
    exec(compile(ast.Module(body=keep, type_ignores=[]), BENCH, "exec"), ns)
    return ns


BENCH_RULE = _bench_rule()

# Coarse enough to run fast, placed either side of every threshold the
# rule has: 5 (opaque), 85 (clear), and the 1.3x margin between them.
GRID = [0.0, 4.9, 5.0, 5.1, 20.0, 30.0, 39.0, 40.0, 84.9, 85.0, 100.0]


def test_the_two_verdict_rules_agree():
    """The same rule is written twice, and neither one can import the other.

    The flowgraph's copy lives inside an embedded Python block so the
    demo has no PYTHONPATH to get wrong in front of a room; the bench
    script's copy is what `filter` reports while somebody is collecting
    the readings those thresholds should be set from. Two copies drift.
    This is the thing that notices.
    """
    flowgraph, _ = _instantiate("decide")
    bench = BENCH_RULE["verdict"]
    disagreed = []
    for r in GRID:
        for g in GRID:
            for b in GRID:
                t = [r, g, b]
                mine, theirs = flowgraph.verdict(list(t)), bench(list(t))
                if mine != theirs:
                    disagreed.append((t, mine, theirs))
    assert not disagreed, disagreed[:5]


def test_the_thresholds_are_the_same_numbers():
    """Agreeing on a grid is not enough if both copies moved together."""
    flowgraph, _ = _instantiate("decide")
    for name in ("clear", "opaque", "margin"):
        assert getattr(flowgraph, name) == BENCH_RULE[name.upper()], name


def test_the_green_strip_reads_green():
    """The one filter anybody has actually measured. docs/colorimeter.md."""
    assert BENCH_RULE["verdict"]([9.3, 66.0, 24.4]) == "Green"


def test_the_guards_catch_what_is_not_a_color():
    flowgraph, _ = _instantiate("decide")
    assert flowgraph.verdict([100.0, 100.0, 100.0]) == "nothing in the beam"
    assert flowgraph.verdict([0.1, 0.2, 0.3]) == "opaque"
    assert flowgraph.verdict([70.0, 68.0, 10.0]) == "mixed"
    assert flowgraph.verdict([float("nan"), 1.0, 2.0]) == "no reference"


# ------------------------------------------------------------- blank on demand

def test_blanking_captures_what_is_in_the_beam_now():
    blanker, published = _instantiate("blanker", depth=4)
    blanker.work([[1.0053] * 4, [0.9757] * 4, [0.9911] * 4], [])
    blanker.blank(None)
    assert [key for key, _ in published] == ["red", "green", "blue"]
    assert [pair[0] for _, pair in published] == [
        "blank_red", "blank_green", "blank_blue"]
    assert abs(published[0][1][1] - 1.0053) < 1e-9


def test_blanking_forgets_older_readings():
    """Otherwise the first blank of the session leaks into every later one."""
    blanker, published = _instantiate("blanker", depth=4)
    blanker.work([[9.0] * 4, [9.0] * 4, [9.0] * 4], [])
    blanker.work([[2.0] * 4, [2.0] * 4, [2.0] * 4], [])
    blanker.blank(None)
    assert [pair[1] for _, pair in published] == [2.0, 2.0, 2.0]


def test_a_dark_reference_does_not_become_the_blank():
    """100.0/blank is a live constant downstream. Zero takes the chain out."""
    blanker, published = _instantiate("blanker", depth=4)
    blanker.work([[0.0] * 4, [float("inf")] * 4, [float("nan")] * 4], [])
    blanker.blank(None)
    assert published == []


def test_blanking_before_any_reading_arrives_is_harmless():
    """The button exists from the moment the GUI does."""
    blanker, published = _instantiate("blanker")
    blanker.blank(None)
    assert published == []
