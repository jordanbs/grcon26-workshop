#!/usr/bin/python3
"""Draw the transducer's response from the sweep the bench actually took.

The ultrasonic section rests on one claim -- that a "40 kHz" pair does not
resonate at 40 kHz -- and a claim like that wants the measurement on the
slide, not a number in a sentence. These figures are plotted straight out of
the CSVs `bench/ultrasonic_sweep.py` wrote on 2026-09-09. Re-sweep and
re-run, and the picture moves with the bench.

    ./slides/render_sweep.py        # into slides/img/

Two of them:

    ultrasonic-response   36-44 kHz at two spacings, each normalised to its
                          own peak. They lie on top of each other, which is
                          what rules out a standing wave: a room resonance
                          moves when you move the transducers, and this
                          does not.
    ultrasonic-tones      the same peak at 46 Hz resolution, with the two
                          FSK tones marked, because the whole reason to
                          measure f0 is to put them somewhere.

Standard library only -- no GNU Radio, no libiio, no board. SVG for the same
reasons as `render_spi.py`: line drawings stay sharp on a projector, they
cost a couple of kB, and they carry their own light/dark palette in an
internal media query because an <img> cannot see the page's variables.
"""
import argparse
import csv
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "slides", "img")
BENCH = os.path.join(ROOT, "bench")

SUFFIX = ".svg"

# The three sweeps, by the spacing they were taken at.
COARSE = {"4 in": "ultrasonic-sweep-4in-20260909.csv",
          "8 in": "ultrasonic-sweep-8in-20260909.csv"}
FINE = "ultrasonic-sweep-fine-20260909.csv"

# What the flowgraph does with the answer. Kept here rather than read from
# the .grc so this stays a stdlib script; the numbers are asserted against
# the flowgraph in tests/test_slides.py.
SPACING = 600.0

HALF_DB = 20.0 * math.log10(2.0)          # -6 dB is half amplitude

STYLE = """
  .bg   { fill: #fafaf7; }
  .axis { stroke: #5a5a5a; stroke-width: 1; fill: none; }
  .grid { stroke: #5a5a5a; stroke-width: .5; stroke-dasharray: 2 4; }
  .cur  { fill: none; stroke: #1a1a1a; stroke-width: 2.2;
          stroke-linejoin: round; stroke-linecap: round; }
  .cur2 { fill: none; stroke: #0067b9; stroke-width: 1.6;
          stroke-dasharray: 6 4; stroke-linejoin: round; }
  .lbl  { fill: #004a85; font: 700 13px ui-monospace, Menlo, Consolas, monospace; }
  .note { fill: #5a5a5a; font: 400 11px ui-monospace, Menlo, Consolas, monospace; }
  .tick { fill: #5a5a5a; font: 400 11px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .tickr{ fill: #5a5a5a; font: 400 11px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: end; }
  .mark { stroke: #b01e24; stroke-width: 1; stroke-dasharray: 3 3; }
  .mkt  { fill: #b01e24; font: 700 12px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .dot  { fill: #b01e24; }
  .dim  { stroke: #0067b9; stroke-width: 1; }
  .dimt { fill: #0067b9; font: 400 10.5px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  @media (prefers-color-scheme: dark) {
    .bg   { fill: #0d1826; }
    .axis, .grid { stroke: #93a3b5; }
    .cur  { stroke: #e9eef4; }
    .cur2 { stroke: #58a7e5; }
    .lbl  { fill: #8cc4ee; }
    .note, .tick, .tickr { fill: #93a3b5; }
    .mkt, .dot { fill: #e4737a; }
    .mark { stroke: #e4737a; }
    .dim  { stroke: #58a7e5; }
    .dimt { fill: #58a7e5; }
  }
"""


def sweep(name):
    """(freq_hz, rx_volts) out of one of the bench CSVs."""
    with open(os.path.join(BENCH, name), newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return ([float(r["freq_hz"]) for r in rows],
            [float(r["rx_volts"]) for r in rows])


def db(amp, top):
    return -99.0 if amp <= 0.0 else 20.0 * math.log10(amp / top)


def peak(freqs, amps):
    """f0 by a parabola through the three points around the largest.

    The sweep grid is 45.78 Hz -- the cyclic buffer's own resolution -- so
    the top sample is not the top of the curve. Three points and a parabola
    is what turns 40740.97 into the 40.755 kHz everything downstream uses.
    """
    i = amps.index(max(amps))
    if i in (0, len(amps) - 1):
        return freqs[i], amps[i]
    y0, y1, y2 = amps[i - 1], amps[i], amps[i + 1]
    denom = y0 - 2.0 * y1 + y2
    shift = 0.0 if denom == 0.0 else 0.5 * (y0 - y2) / denom
    return freqs[i] + shift * (freqs[i + 1] - freqs[i]), y1


def edge(freqs, amps, step):
    """Where the response crosses -6 dB, walking out from the peak.

    The same interpolation `bench/ultrasonic_sweep.py` prints, repeated here
    so the figure and the bench agree by construction rather than by my
    having copied a number across.
    """
    i = amps.index(max(amps))
    top = amps[i]
    while 0 <= i + step < len(amps):
        j = i + step
        if amps[j] < top / 2.0:
            d1, d2 = db(amps[i], top), db(amps[j], top)
            if d1 == d2:
                return freqs[j]
            frac = (d1 + HALF_DB) / (d1 - d2)
            return freqs[i] + frac * (freqs[j] - freqs[i])
        i = j
    return None


class Plot(object):
    """One set of axes, in dB relative to the curve's own peak.

    The viewBox is narrow for the reason `render_spi.py` gives: these are
    shown about one slide column wide and an SVG's type scales with its box.
    """

    def __init__(self, width, height, x_lo, x_hi, y_lo, left=52, top=40,
                 bottom=46, right=16):
        self.w, self.h = width, height
        self.x0, self.x1 = left, width - right
        self.y0, self.y1 = top, height - bottom
        self.x_lo, self.x_hi, self.y_lo = x_lo, x_hi, y_lo
        self.parts = []

    def px(self, f):
        return self.x0 + (self.x1 - self.x0) * (f - self.x_lo) / (self.x_hi - self.x_lo)

    def py(self, d):
        return self.y0 + (self.y1 - self.y0) * min(0.0, max(self.y_lo, d)) / self.y_lo

    def frame(self, x_ticks, y_ticks, x_fmt="%.0f"):
        self.parts.append(
            f'<path class="axis" d="M{self.x0},{self.y0 - 6} V{self.y1} '
            f'H{self.x1}"/>')
        for d in y_ticks:
            y = self.py(d)
            self.parts.append(f'<line class="grid" x1="{self.x0}" y1="{y:.2f}" '
                              f'x2="{self.x1}" y2="{y:.2f}"/>')
            self.parts.append(f'<text class="tickr" x="{self.x0 - 7}" '
                              f'y="{y + 4:.2f}">{d:g}</text>')
        for f in x_ticks:
            x = self.px(f)
            self.parts.append(f'<line class="axis" x1="{x:.2f}" y1="{self.y1}" '
                              f'x2="{x:.2f}" y2="{self.y1 + 5}"/>')
            self.parts.append(f'<text class="tick" x="{x:.2f}" '
                              f'y="{self.y1 + 19}">{x_fmt % (f / 1e3)}</text>')
        self.parts.append(f'<text class="note" x="{self.x1}" '
                          f'y="{self.y1 + 34}" text-anchor="end">kHz</text>')
        self.parts.append(f'<text class="note" x="{self.x0 - 46}" '
                          f'y="{self.y0 - 12}">dB</text>')

    def curve(self, freqs, amps, cls="cur"):
        top = max(amps)
        pts = " ".join(f"{self.px(f):.2f},{self.py(db(a, top)):.2f}"
                       for f, a in zip(freqs, amps))
        self.parts.append(f'<polyline class="{cls}" points="{pts}"/>')

    def vline(self, f, text, dy=-8):
        x = self.px(f)
        self.parts.append(f'<line class="mark" x1="{x:.2f}" y1="{self.y0 - 6}" '
                          f'x2="{x:.2f}" y2="{self.y1}"/>')
        self.parts.append(f'<text class="mkt" x="{x:.2f}" '
                          f'y="{self.y0 + dy:.2f}">{text}</text>')

    def dot(self, f, d):
        self.parts.append(f'<circle class="dot" cx="{self.px(f):.2f}" '
                          f'cy="{self.py(d):.2f}" r="3.2"/>')

    def svg(self, title):
        body = "\n  ".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {self.w} {self.h}"'
                f' role="img" aria-label="{title}">\n'
                f'  <style>{STYLE}  </style>\n'
                f'  <rect class="bg" x="0" y="0" width="{self.w}" '
                f'height="{self.h}"/>\n'
                f'  {body}\n</svg>\n')


def response(path_out):
    """The band, at two spacings, each against its own peak."""
    (f4, a4), (f8, a8) = sweep(COARSE["4 in"]), sweep(COARSE["8 in"])
    low, high = edge(f4, a4, -1), edge(f4, a4, +1)
    # f0 comes off the fine sweep. This sweep's grid is 229 Hz, which is
    # plenty to find the band and nowhere near enough to find its centre.
    f0, _ = peak(*sweep(FINE))

    p = Plot(560, 282, 35800.0, 44200.0, -30.0)
    p.frame([36000, 38000, 40000, 42000, 44000], [0, -6, -12, -18, -24, -30])

    # -6 dB gets a line of its own, because the band edges are read off it.
    y6 = p.py(-HALF_DB)
    p.parts.append(f'<line class="dim" x1="{p.x0}" y1="{y6:.2f}" '
                   f'x2="{p.x1}" y2="{y6:.2f}"/>')

    p.curve(f8, a8, "cur2")
    p.curve(f4, a4, "cur")

    p.vline(40000.0, "40 kHz")
    p.vline(f0, "f₀", dy=-24)
    p.dot(40000.0, db(a4[f4.index(min(f4, key=lambda f: abs(f - 40008.5)))],
                      max(a4)))

    # The band, dimensioned on the -6 dB line.
    xa, xb = p.px(low), p.px(high)
    for x in (xa, xb):
        p.parts.append(f'<line class="dim" x1="{x:.2f}" y1="{y6 - 5:.2f}" '
                       f'x2="{x:.2f}" y2="{y6 + 5:.2f}"/>')
    p.parts.append(f'<text class="dimt" x="{(xa + xb) / 2:.2f}" '
                   f'y="{y6 - 10:.2f}">{high - low:.0f} Hz</text>')

    p.parts.append(f'<text class="lbl" x="{p.x0 + 6}" y="{p.y0 + 6}">4 in</text>')
    p.parts.append(f'<text class="note" x="{p.x0 + 6}" y="{p.y0 + 20}">'
                   f'8 in, dashed</text>')

    nominal = db(a4[f4.index(min(f4, key=lambda f: abs(f - 40008.5)))], max(a4))
    with open(path_out, "w", encoding="utf-8") as fh:
        fh.write(p.svg(
            f"Response of the 40 kHz transducer pair from 36 to 44 kHz, in dB "
            f"below each curve's own peak, measured at 4 inches and again at 8 "
            f"inches. The two curves lie on top of one another and f0 is "
            f"{f0 / 1e3:.3f} kHz. The -6 dB band runs {low / 1e3:.3f} to "
            f"{high / 1e3:.3f} kHz, {high - low:.0f} Hz wide. Driving 40.0 kHz "
            f"sits {nominal:.1f} dB down."))
    return p.w, p.h


def tones(path_out):
    """The peak at the sweep's own resolution, with the FSK tones on it."""
    f, a = sweep(FINE)
    f0, _ = peak(f, a)
    space, mark = f0 - SPACING / 2.0, f0 + SPACING / 2.0

    p = Plot(560, 250, f[0] - 30.0, f[-1] + 30.0, -6.0)
    p.frame([40500, 40750, 41000], [0, -2, -4, -6], x_fmt="%.2f")
    p.curve(f, a, "cur")

    top = max(a)
    for freq, name in ((space, "space"), (mark, "mark")):
        p.vline(freq, name)
        # Linear interpolation onto the measured curve: the tone is between
        # two grid points and the level at it is what matters.
        for i in range(len(f) - 1):
            if f[i] <= freq <= f[i + 1]:
                t = (freq - f[i]) / (f[i + 1] - f[i])
                p.dot(freq, db(a[i] + t * (a[i + 1] - a[i]), top))
                break
    p.vline(f0, "f₀", dy=-24)

    with open(path_out, "w", encoding="utf-8") as fh:
        fh.write(p.svg(
            f"The same response at 46 Hz resolution across the peak, in dB below "
            f"the peak. f0 is {f0 / 1e3:.3f} kHz; the space tone at "
            f"{space / 1e3:.3f} kHz and the mark tone at {mark / 1e3:.3f} kHz sit "
            f"either side of it, both within a decibel of each other."))
    return p.w, p.h


FIGURES = {"ultrasonic-response": response, "ultrasonic-tones": tones}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for stem, draw in FIGURES.items():
        target = os.path.join(args.out, stem + SUFFIX)
        w, h = draw(target)
        size = os.path.getsize(target)
        print(f"{os.path.relpath(target, ROOT):36} {w}x{h}  {size / 1024:.1f} kB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
