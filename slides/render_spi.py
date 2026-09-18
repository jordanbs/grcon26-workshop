#!/usr/bin/python3
"""Draw the SPI figures from the encoder that actually drives the pins.

`slides/render_grc.py` renders the blocks from GRC's own canvas so a slide
cannot drift from the participant's screen. Same idea one layer down: these
waveforms come out of `SpiEncoder`, the module that builds the levels the
M2K puts on DIO0-2. Nothing here is drawn from a description of SPI -- if
the encoder's idea of mode 0 changed, so would the picture.

    ./slides/render_spi.py          # into slides/img/

The figures carry a key and nothing else. Explanation belongs in the text
around a graphic rather than inside it, so what these drawings once said in
prose now sits in the frame's bullets and its caption.

`SpiEncoder` imports nothing, so this needs no GNU Radio, no libiio and no
board -- only the standard library. It writes SVG rather than PNG: these are
line drawings, they cost a couple of kB, and they stay sharp on a projector
and in print at any size.

The figures carry their own light/dark palette in an internal `@media
(prefers-color-scheme: dark)` block. An SVG loaded through `<img>` cannot see
the page's custom properties, but it does honour its own media query -- and
the deck follows the OS scheme too, so the two stay in step.

That is also why the background rect is painted the deck's ground rather than
white: an <img> is opaque over whatever is behind it, so a white plate on an
off-white page reads as a box somebody drew round the waveform on purpose.
Keeping the rect rather than dropping it means the file still stands up
opened on its own.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gr-m2k"))

from m2k_blocks.spi_encode import SpiEncoder            # noqa: E402

OUT = os.path.join(ROOT, "slides", "img")

SUFFIX = ".svg"

# The bench settings: 8 samples a half clock, and the quiet stretches the
# flowgraph actually uses.
HALF, LEAD, SETUP, TAIL, GAP = 8, 64, 8, 8, 48

STYLE = """
  .bg   { fill: #fafaf7; }
  .trace{ fill: none; stroke: #1a1a1a; stroke-width: 2.2;
          stroke-linejoin: miter; stroke-linecap: butt; }
  .lbl  { fill: #004a85; font: 700 13px ui-monospace, Menlo, Consolas, monospace; }
  .note { fill: #5a5a5a; font: 400 11px ui-monospace, Menlo, Consolas, monospace; }
  .bit  { fill: #b01e24; font: 700 12px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .edge { stroke: #b01e24; stroke-width: 1; stroke-dasharray: 3 3; }
  .dot  { fill: #b01e24; }
  .dim  { stroke: #0067b9; stroke-width: 1; }
  .dimt { fill: #0067b9; font: 400 10.5px ui-monospace, Menlo, Consolas, monospace;
          text-anchor: middle; }
  .band { fill: rgba(0,103,185,.07); }
  .warn { fill: #b01e24; font: 700 12px ui-monospace, Menlo, Consolas, monospace; }
  @media (prefers-color-scheme: dark) {
    .bg   { fill: #0d1826; }
    .trace{ stroke: #e9eef4; }
    .lbl  { fill: #8cc4ee; }
    .note { fill: #93a3b5; }
    .bit, .dot, .warn { fill: #e4737a; }
    .edge { stroke: #e4737a; }
    .dim  { stroke: #58a7e5; }
    .dimt { fill: #58a7e5; }
    .band { fill: rgba(140,196,238,.10); }
  }
"""


def levels(messages, **kwargs):
    """The three lines the encoder produces for these messages.

    One `send` is one transaction. Calling it once with three bytes and
    three times with one byte each is the whole difference between the two
    framings in `spi-framing.svg` -- and both come out of the encoder rather
    than out of a drawing of what we think it does.
    """
    enc = SpiEncoder(half=HALF, lead=LEAD, setup=SETUP, tail=TAIL, gap=GAP,
                     **kwargs)
    for message in messages:
        enc.send(message)
    return enc.pull(enc.pending())


def path(samples, x0, span, y_hi, y_lo, total=None):
    """A square wave as an SVG path, one vertex per level change.

    `total` is the number of samples the full span represents, which is not
    always this waveform's own length: `spi-framing.svg` puts a 512-sample
    frame above a 768-sample one and the entire point is that the shorter is
    two thirds as wide. Defaulting it to len(samples) stretched both to the
    full width and quietly drew two different time axes as one.

    Emitting a point per sample would be 256 segments of which 240 are
    collinear; the renderer would cope and the file would be ten times the
    size for a picture nobody can tell apart.
    """
    step = span / (total or len(samples))
    y = lambda v: y_hi if v else y_lo                        # noqa: E731
    d = [f"M{x0:.2f},{y(samples[0]):.2f}"]
    for i in range(1, len(samples)):
        if samples[i] != samples[i - 1]:
            x = x0 + i * step
            d.append(f"H{x:.2f}")
            d.append(f"V{y(samples[i]):.2f}")
    d.append(f"H{x0 + len(samples) * step:.2f}")
    return " ".join(d)


def rising(sclk):
    return [i for i in range(1, len(sclk)) if sclk[i] and not sclk[i - 1]]


def falling(cs):
    return [i for i in range(1, len(cs)) if cs[i] < cs[i - 1]]


class Figure(object):
    """Three stacked traces on a common time axis.

    The viewBox is deliberately narrow. These are displayed at about the
    width of one slide column, and an SVG's type scales with its box: at 760
    units wide the annotations landed at 7 pixels on a 1280 screen, which is
    nothing from the back of a room.
    """

    ROW_H, GAP_H, TOP = 26, 22, 30

    def __init__(self, width, height, x0=52, right=10):
        self.w, self.h = width, height
        self.x0, self.span = x0, width - x0 - right
        self.parts = []

    def at(self, sample, total):
        return self.x0 + self.span * sample / total

    def trace(self, row, name, samples, y_top, total=None):
        y_lo = y_top + self.ROW_H
        self.parts.append(
            f'<text class="lbl" x="8" y="{y_top + self.ROW_H - 4}">{name}</text>')
        self.parts.append(
            f'<path class="trace" d="'
            f'{path(samples, self.x0, self.span, y_top, y_lo, total)}"/>')
        return y_lo

    def svg(self, title):
        body = "\n  ".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}"'
                f' role="img" aria-label="{title}">\n'
                f'  <style>{STYLE}  </style>\n'
                f'  <rect class="bg" x="0" y="0" width="{self.w}" height="{self.h}"/>\n'
                f'  {body}\n</svg>\n')


def mode0(path_out):
    """One byte, with the edge that decides each bit marked."""
    byte = 0xA5
    sclk, mosi, cs = levels([[byte]])
    n = len(sclk)
    fig = Figure(560, 178)

    rows = [("SCLK", sclk), ("MOSI", mosi), ("CS", cs)]
    tops = []
    y = fig.TOP
    for name, samples in rows:
        tops.append(y)
        fig.trace(name, name, samples, y)
        y += fig.ROW_H + fig.GAP_H

    # The eight rising edges, and the bit each one latches. Drawn from the
    # waveform, not from the byte: if the encoder clocked LSB first these
    # labels would come out in the other order and say so.
    for k, i in enumerate(rising(sclk)):
        x = fig.at(i, n)
        fig.parts.append(
            f'<line class="edge" x1="{x:.2f}" y1="{tops[0] - 6:.2f}" '
            f'x2="{x:.2f}" y2="{tops[1] + fig.ROW_H:.2f}"/>')
        yb = tops[1] if mosi[i] else tops[1] + fig.ROW_H
        fig.parts.append(f'<circle class="dot" cx="{x:.2f}" cy="{yb:.2f}" r="3"/>')
        fig.parts.append(
            f'<text class="bit" x="{x:.2f}" y="{tops[0] - 10:.2f}">{mosi[i]}</text>')

    # No prose inside the graphic. A figure carries a key; the page around it
    # does the explaining, so what these notes used to say now sits in the
    # frame's bullets and its caption.
    with open(path_out, "w") as handle:
        handle.write(fig.svg(
            f"SPI mode 0 waveform for one byte, 0x{byte:02X}: SCLK, MOSI and CS, "
            f"with the eight rising clock edges marked and the bit each one "
            f"samples labelled, most significant first."))
    return fig.w, fig.h


def budget(path_out):
    """The same frame, dimensioned: where the 256 samples go."""
    sclk, mosi, cs = levels([[0xA5]])
    n = len(sclk)
    fig = Figure(560, 206)

    edges = [0, LEAD, LEAD + SETUP, n - GAP - TAIL, n - GAP, n]
    names = ["lead-in", "setup", "8 clocks", "tail", "idle after"]
    counts = [LEAD, SETUP, edges[3] - edges[2], TAIL, GAP]

    for k in range(len(names)):
        if k % 2 == 0:
            x1, x2 = fig.at(edges[k], n), fig.at(edges[k + 1], n)
            fig.parts.append(f'<rect class="band" x="{x1:.2f}" y="{fig.TOP - 8:.2f}" '
                             f'width="{x2 - x1:.2f}" height="{3 * fig.ROW_H + 2 * fig.GAP_H}"/>')

    y = fig.TOP
    for name, samples in (("SCLK", sclk), ("MOSI", mosi), ("CS", cs)):
        fig.trace(name, name, samples, y)
        y += fig.ROW_H + fig.GAP_H

    bar = y + 4
    for k, name in enumerate(names):
        x1, x2 = fig.at(edges[k], n), fig.at(edges[k + 1], n)
        mid = (x1 + x2) / 2
        fig.parts.append(f'<line class="dim" x1="{x1:.2f}" y1="{bar}" '
                         f'x2="{x2:.2f}" y2="{bar}"/>')
        for x in (x1, x2):
            fig.parts.append(f'<line class="dim" x1="{x:.2f}" y1="{bar - 4}" '
                             f'x2="{x:.2f}" y2="{bar + 4}"/>')
        fig.parts.append(f'<text class="dimt" x="{mid:.2f}" y="{bar + 17}">{name}</text>')
        fig.parts.append(f'<text class="dimt" x="{mid:.2f}" y="{bar + 29}">{counts[k]}</text>')

    with open(path_out, "w") as handle:
        handle.write(fig.svg(
            f"The same one-byte SPI frame with its {n} samples dimensioned: "
            f"lead-in {LEAD}, setup {SETUP}, eight clocks {counts[2]}, tail "
            f"{TAIL}, idle after {GAP}."))
    return fig.w, fig.h


def framing(path_out):
    """Why CS frames the transaction and not the byte.

    Top: `M2K` as one transaction. Bottom: the same three bytes sent as three,
    which is what the flowgraph did the first time. Both come from the
    encoder; the only difference is how many times `send` was called.
    """
    message = [0x4D, 0x32, 0x4B]                              # M 2 K
    one = levels([message])
    many = levels([[b] for b in message])
    total = max(len(one[0]), len(many[0]))

    fig = Figure(560, 272)
    fig.parts.append(f'<text class="note" x="{fig.x0}" y="16">one send</text>')
    y = 26
    fig.trace("CS", "CS", one[2], y, total)
    for i in falling(one[2]):
        x = fig.at(i, total)
        fig.parts.append(f'<line class="edge" x1="{x:.2f}" y1="{y - 4:.2f}" '
                         f'x2="{x:.2f}" y2="{y + fig.ROW_H + 6:.2f}"/>')
        fig.parts.append(f'<text class="bit" x="{x:.2f}" y="{y + fig.ROW_H + 18:.2f}">'
                         f'arm</text>')
    fig.trace("MOSI", "MOSI", one[1], y + fig.ROW_H + 48, total)

    y2 = 160
    fig.parts.append(f'<text class="warn" x="{fig.x0}" y="{y2 - 8:.2f}">'
                     f'three sends</text>')
    fig.trace("CS", "CS", many[2], y2, total)
    for i in falling(many[2]):
        x = fig.at(i, total)
        fig.parts.append(f'<line class="edge" x1="{x:.2f}" y1="{y2 - 4:.2f}" '
                         f'x2="{x:.2f}" y2="{y2 + fig.ROW_H + 6:.2f}"/>')
        fig.parts.append(f'<text class="bit" x="{x:.2f}" y="{y2 + fig.ROW_H + 18:.2f}">'
                         f'arm</text>')
    fig.trace("MOSI", "MOSI", many[1], y2 + fig.ROW_H + 48, total)

    with open(path_out, "w") as handle:
        handle.write(fig.svg(
            "Two chip-select framings of the message M2K. Above, one send: CS "
            "falls once and all three bytes are clocked inside it, so a capture "
            "armed on that edge starts at the message. Below, three sends: CS "
            "falls before each byte, so a capture starts on an arbitrary one."))
    return fig.w, fig.h


FIGURES = {"spi-mode0": mode0, "spi-frame": budget, "spi-framing": framing}


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
