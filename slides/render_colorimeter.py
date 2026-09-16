#!/usr/bin/python3
"""Draw the colorimeter's light path, and what coherent sampling buys.

Two figures, neither of them a photograph and neither of them hand-drawn
from a description:

    colorimeter-optics    the L-shaped light path through the cuvette
                          holder -- one LED, a 45 degree splitter, two
                          wells, two photodiodes. Geometry off the holder
                          PCB and the measurements in
                          docs/colorimeter-board.md.
    colorimeter-coherent  the same square wave at 205 cycles per buffer
                          and at a round 5 kHz, transformed. One is a
                          single bin; the other is smeared across a dozen.
                          That is the whole argument for 5004.9 Hz.

The second one is computed here, from the same 0/1 pattern the DIO buffer
carries -- the same principle as `render_spi.py` drawing from the encoder
rather than from an idea of SPI. Change `CYCLES` in `bench/colorimeter.py`
and this picture is wrong, which is the point.

    ./slides/render_colorimeter.py        # into slides/img/

Standard library only -- no GNU Radio, no libiio, no board. SVG because a
line drawing stays sharp on a projector and carries its own light/dark
palette in an internal media query, which an <img> cannot get from the page.
"""
import argparse
import cmath
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "slides", "img")

SUFFIX = ".svg"

# The frequency plan, repeated from bench/colorimeter.py rather than
# imported, so this stays a standard-library script. tests/test_slides.py
# asserts the two agree.
RATE = 100000
NFFT = 4096
RED_CYCLES = 205
# What somebody types when they want "about 5 kHz". 204.8 cycles in the
# buffer, so the cyclic repeat has a step in it and the energy has nowhere
# tidy to land.
ROUND_HZ = 5000.0

FLOOR_DB = -90.0

STYLE = """
  .bg   { fill: #fafaf7; }
  .axis { stroke: #5a5a5a; stroke-width: 1; fill: none; }
  .grid { stroke: #5a5a5a; stroke-width: .5; stroke-dasharray: 2 4; }
  .tick { fill: #5a5a5a; font: 400 10px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .tickr{ fill: #5a5a5a; font: 400 10px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: end; }
  .note { fill: #5a5a5a; font: 400 10.5px ui-monospace, Menlo, Consolas, monospace; }
  .hd   { fill: #1a1a1a; font: 700 12px ui-monospace, Menlo, Consolas, monospace; }
  .lbl  { fill: #004a85; font: 700 11.5px ui-monospace, Menlo, Consolas, monospace; }
  .mkt  { fill: #b01e24; font: 700 11px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .stem { stroke: #1a1a1a; stroke-width: 2; stroke-linecap: round; }
  .stemq{ stroke: #b01e24; stroke-width: 2; stroke-linecap: round; }
  .body { fill: #ffffff; stroke: #5a5a5a; stroke-width: 1.2; }
  .glass{ fill: #dce9f4; stroke: #0067b9; stroke-width: 1.2; }
  .split{ stroke: #7a5aa8; stroke-width: 3.5; stroke-linecap: round; }
  .beamr{ stroke: #d33; stroke-width: 1.6; }
  .beamg{ stroke: #1a8f3c; stroke-width: 1.6; }
  .beamb{ stroke: #2a6fd6; stroke-width: 1.6; }
  .arrow{ fill: #5a5a5a; }
  @media (prefers-color-scheme: dark) {
    .bg    { fill: #0d1826; }
    .axis, .grid { stroke: #93a3b5; }
    .tick, .tickr, .note { fill: #93a3b5; }
    .hd    { fill: #e9eef4; }
    .lbl   { fill: #8cc4ee; }
    .mkt   { fill: #e4737a; }
    .stem  { stroke: #e9eef4; }
    .stemq { stroke: #e4737a; }
    .body  { fill: #16263a; stroke: #93a3b5; }
    .glass { fill: #1d3550; stroke: #58a7e5; }
    .split { stroke: #b39ddb; }
    .beamr { stroke: #ff7b7b; }
    .beamg { stroke: #62d98a; }
    .beamb { stroke: #72aefc; }
    .arrow { fill: #93a3b5; }
  }
"""


# A monospace advance is 0.6 em in every stack named above, so a label's
# extent is arithmetic rather than a guess. That matters here because there
# is no SVG rasterizer on this machine that lays out text -- ImageMagick
# draws these with the wrong metrics -- so the only way to know a caption
# does not run off the edge or sit on top of a box is to compute it.
ADVANCE = 0.6


class Canvas:
    """Parts of an SVG, plus enough bookkeeping to check the layout."""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.parts = []
        self.rects = []        # (x0, y0, x1, y1, label)
        self.texts = []        # (x0, y0, x1, y1, string)

    def raw(self, markup):
        self.parts.append(markup)

    def rect(self, x, y, w, h, cls, name=""):
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" '
                          f'height="{h}" rx="3"/>')
        self.rects.append((x, y, x + w, y + h, name or cls))

    def text(self, x, y, cls, s, size, anchor="start", weight_pad=0):
        width = len(_plain(s)) * size * ADVANCE + weight_pad
        x0 = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
        self.parts.append(f'<text class="{cls}" x="{x:.0f}" y="{y:.0f}"'
                          + (f' text-anchor="{anchor}"' if anchor != "start"
                             else "") + f'>{s}</text>')
        self.texts.append((x0, y - size * 0.8, x0 + width, y + size * 0.25, s))

    def complaints(self, inside=()):
        """Labels off the edge, or sitting on a box that is not theirs."""
        out = []
        for x0, y0, x1, y1, s in self.texts:
            if x0 < 4 or x1 > self.w - 4 or y0 < 0 or y1 > self.h:
                out.append(f"{_plain(s)!r} runs outside the viewBox "
                           f"(x {x0:.0f}..{x1:.0f} of {self.w}, "
                           f"y {y0:.0f}..{y1:.0f} of {self.h})")
            for rx0, ry0, rx1, ry1, name in self.rects:
                if name in inside:
                    continue
                if x0 < rx1 and x1 > rx0 and y0 < ry1 and y1 > ry0:
                    out.append(f"{_plain(s)!r} overlaps the {name} box")
        return out

    def svg(self, title):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" '
                f'aria-label="{title}">\n'
                f'  <style>{STYLE}  </style>\n'
                f'  <rect class="bg" x="0" y="0" width="{self.w}" '
                f'height="{self.h}"/>\n'
                f'  ' + "\n  ".join(self.parts) + "\n</svg>\n")


def _plain(s):
    """Character entities are one glyph wide, not six."""
    return re.sub(r"&#?\w+;", "X", s)


def write(canvas, path_out, title, inside=()):
    for note in canvas.complaints(inside):
        print(f"  layout: {note}")
    with open(path_out, "w", encoding="utf-8") as fh:
        fh.write(canvas.svg(title))
    return canvas.w, canvas.h


# -- the light path ------------------------------------------------------

def optics(path_out):
    """One beam in, two beams out, at right angles.

    The holder is a 40 mm plate with two wells set at 90 degrees and a 2 mm
    slot across the elbow. Drawn to that arrangement rather than to scale:
    what has to be legible from the back of a room is which well is which
    and which photodiode is behind it, not the millimetres.
    """
    c = Canvas(560, 392)
    sx, sy = 250, 118                     # the splitter, at the elbow

    def beam(x1, y1, x2, y2):
        """Three colors along one axis, drawn as three lines a hair apart.

        Perpendicular offsets, so it reads as one beam carrying three
        colors rather than as three beams -- which is the fact the whole
        frequency plan exists to exploit.
        """
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy)
        ox, oy = -dy / n * 3.0, dx / n * 3.0
        for k, cls in ((-1, "beamr"), (0, "beamg"), (1, "beamb")):
            c.raw(f'<line class="{cls}" x1="{x1 + ox * k:.1f}" '
                  f'y1="{y1 + oy * k:.1f}" x2="{x2 + ox * k:.1f}" '
                  f'y2="{y2 + oy * k:.1f}"/>')

    def part(x, y, w, h, cls, lines, name):
        c.rect(x, y, w, h, cls, name)
        top = y + h / 2 - (len(lines) - 1) * 7 + 4
        for i, line in enumerate(lines):
            c.text(x + w / 2, top + i * 14, "hd", line, 12, "middle")

    c.text(16, 24, "hd", "One LED, two wells, two photodiodes", 12)

    part(16, 92, 104, 52, "body", ["RGB LED", "J5"], "led")
    beam(120, 118, 230, 118)

    # The splitter: a 2 mm slot at 45 degrees across the elbow.
    c.raw(f'<line class="split" x1="{sx - 20}" y1="{sy + 20}" '
          f'x2="{sx + 20}" y2="{sy - 20}"/>')
    c.text(248, 62, "lbl", "45&#176; splitter", 11.5, "end")
    c.text(248, 78, "note", "a slot, not a well", 10.5, "end")

    # Straight through, to Reference.
    beam(270, 118, 326, 118)
    part(326, 90, 56, 56, "glass", ["Ref"], "ref")
    beam(382, 118, 436, 118)
    part(436, 92, 108, 52, "body", ["photodiode", "analog 1"], "pd1")
    c.text(354, 82, "lbl", "Reference", 11.5, "middle")

    # Reflected 90 degrees, down to Sample.
    beam(sx, 138, sx, 216)
    part(222, 216, 56, 56, "glass", ["Smp"], "sample")
    beam(sx, 272, sx, 310)
    part(196, 310, 108, 52, "body", ["photodiode", "analog 2"], "pd2")
    c.text(214, 208, "lbl", "Sample", 11.5, "end")
    c.text(214, 224, "note", "the cuvette", 10.5, "end")
    c.text(214, 238, "note", "goes here", 10.5, "end")

    for i, line in enumerate([
            "Block the sample well and analog 2",
            "keeps 0.8%. Analog 1 keeps 88% --",
            "the empty cuvette itself takes the",
            "other 12%, in Fresnel reflection at",
            "two glass faces. Which is why a",
            "colorimeter blanks against an empty",
            "cuvette, not against an empty slot."]):
        c.text(326, 196 + i * 16, "note", line, 10.5)
    c.text(326, 330, "lbl", "transmittance = analog 2", 11.5)
    c.text(326, 346, "lbl", "&#160;&#160;over analog 1, per color", 11.5)

    return write(c, path_out,
                 "The colorimeter's light path: one RGB LED through a 45 "
                 "degree splitter into a reference well and a sample well, "
                 "each with its own photodiode",
                 inside=("led", "ref", "sample", "pd1", "pd2"))


# -- coherent against round ----------------------------------------------

def chop(cycles_per_buffer, n=NFFT):
    """The 0/1 pattern one DIO line carries, for a given tone.

    Not a sine. The pattern generator drives a pin, so what actually
    happens to the light is a square wave, and its transform has odd
    harmonics whether or not anybody planned for them.
    """
    out = []
    for i in range(n):
        phase = (cycles_per_buffer * i / n) % 1.0
        out.append(1.0 if phase < 0.5 else 0.0)
    return out


def dft_bins(x, lo, hi):
    """|X[k]| for k in [lo, hi), straight from the definition.

    A hundred bins of a 4096-point transform is under half a million
    multiplies, which is nothing, and writing the sum out keeps this a
    standard-library script with no numpy.
    """
    n = len(x)
    out = []
    for k in range(lo, hi):
        step = cmath.exp(-2j * math.pi * k / n)
        acc, rot = 0j, 1 + 0j
        for value in x:
            if value:
                acc += rot
            rot *= step
        out.append(abs(acc))
    return out


def coherent(path_out):
    """205 cycles beside 5000 Hz, transformed the same way."""
    lo, hi = 196, 216
    exact = dft_bins(chop(RED_CYCLES), lo, hi)
    round_cycles = ROUND_HZ * NFFT / RATE      # 204.8, and that .8 is the story
    rough = dft_bins(chop(round_cycles), lo, hi)
    peak = max(max(exact), max(rough))

    c = Canvas(560, 300)
    c.text(16, 24, "hd", "The same square wave, one fifth of a cycle apart", 12)

    def panel(x0, values, title, sub, cls, ticks):
        top, bot, pw = 84, 236, 210
        c.text(x0, 50, "lbl", title, 11.5)
        c.text(x0, 66, "note", sub, 10.5)
        c.raw(f'<line class="axis" x1="{x0}" y1="{bot}" x2="{x0 + pw}" '
              f'y2="{bot}"/>')
        c.raw(f'<line class="axis" x1="{x0}" y1="{top}" x2="{x0}" '
              f'y2="{bot}"/>')
        for dbline in (-20, -40, -60, -80):
            y = bot - (1 - dbline / FLOOR_DB) * (bot - top)
            c.raw(f'<line class="grid" x1="{x0}" y1="{y:.1f}" '
                  f'x2="{x0 + pw}" y2="{y:.1f}"/>')
            if ticks:
                c.text(x0 - 6, y + 3.5, "tickr", str(dbline), 10, "end")
        for i, mag in enumerate(values):
            db = FLOOR_DB if mag <= 0 else 20.0 * math.log10(mag / peak)
            if db <= FLOOR_DB + 0.5:
                continue
            x = x0 + (i + 0.5) / len(values) * pw
            y = bot - (1 - max(db, FLOOR_DB) / FLOOR_DB) * (bot - top)
            c.raw(f'<line class="{cls}" x1="{x:.1f}" y1="{bot}" '
                  f'x2="{x:.1f}" y2="{y:.1f}"/>')
        for k in (200, 205, 210, 215):
            x = x0 + (k - lo + 0.5) / len(values) * pw
            c.text(x, bot + 15, "tick", str(k), 10, "middle")
        c.text(x0 + pw / 2, bot + 31, "tick", "FFT bin", 10, "middle")

    panel(56, exact, "205 cycles a buffer", "5004.9 Hz", "stem", True)
    panel(330, rough, "5000 Hz, a round number", "204.8 cycles", "stemq", False)
    c.text(50, 88, "tickr", "dB", 10, "end")

    # The left panel is not empty either side of 205, and saying so is the
    # difference between a figure and an advertisement. A square wave's
    # edges can only fall on sample boundaries, so the duty cycle wobbles
    # by a fraction of a sample and puts a little energy four bins out.
    c.text(16, 262, "note",
           "Left is not bare: quantized edges put spurs 26 dB down at "
           "201 and 209. They sit on", 10.5)
    c.text(16, 276, "note",
           "no other color's bin. Right, the skirt reaches green's bin 246 "
           "at -47 dB, where left", 10.5)
    c.text(16, 290, "note",
           "leaves nothing at all. Both drawn from the 0/1 pattern the pin "
           "actually carries.", 10.5)

    return write(c, path_out,
                 "Two spectra: a 205-cycle square wave occupies one FFT bin, "
                 "while a 5000 Hz square wave spreads energy across every "
                 "bin around it")


FIGURES = {
    "colorimeter-optics": optics,
    "colorimeter-coherent": coherent,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for stem, draw in FIGURES.items():
        target = os.path.join(args.out, stem + SUFFIX)
        w, h = draw(target)
        size = os.path.getsize(target)
        print(f"{os.path.relpath(target, ROOT):40} {w}x{h}  {size / 1024:.1f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
