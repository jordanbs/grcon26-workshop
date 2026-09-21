#!/usr/bin/env python3
"""The setup QR code on the title frame, rendered to SVG.

    uv run ./slides/render_qr.py           # into slides/img/
    uv run ./slides/render_qr.py --check    # 0 if the file on disk is current

Same arrangement as the GRC figures: the picture is generated from the
one value that decides it, the output is committed, and a test fails if
the two drift apart. Here that value is the URL, which appears in three
places -- this script, the deck, and install/README.md -- and a QR code
is the one of the three nobody can proofread.

`segno` is a dev dependency rather than a runtime one. Opening the deck
needs nothing installed; regenerating this file needs `uv sync`.

Why SVG and not PNG: a projector and a phone camera want different
resolutions and the room's is not known in advance. Vector sidesteps it,
and the file is under 2 kB.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "img")

SUFFIX = ".svg"

# What the code points at. The repository front page, because that is
# where the setup instructions now are and because a URL somebody can
# read off a slide and type by hand is worth more than a short link to
# somewhere opaque.
URL = "https://github.com/livethisdream/grcon26-workshop"

# Error correction M -- 15% recoverable. A projected code is read at an
# angle, off a screen that may be washed out, by twenty phones at once;
# L is enough in a datasheet and not enough in a lecture theatre. H would
# be denser for no gain we can rely on.
ERROR = "m"

# No border in the file. The frame gives it a white card with padding of
# its own, and a 4-module quiet zone baked into the SVG makes the code
# itself smaller inside a box of fixed width -- which is the opposite of
# what a reader at the back needs. The card supplies the quiet zone.
BORDER = 0


def render():
    """The SVG text, deterministically -- no timestamp, no id."""
    import segno

    code = segno.make(URL, error=ERROR)
    import io
    buf = io.BytesIO()
    code.save(buf, kind="svg", border=BORDER, xmldecl=False, svgns=True,
              svgclass=None, lineclass=None, omitsize=True, unit="",
              svgversion=None, nl=True)
    return buf.getvalue().decode("utf-8")


FIGURES = {"setup-qr": render}


def target(out=OUT):
    return os.path.join(out, "setup-qr" + SUFFIX)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the file is out of date")
    ap.add_argument("--url", action="store_true",
                    help="print the encoded URL and exit")
    args = ap.parse_args(argv)

    if args.url:
        print(URL)
        return 0

    try:
        svg = render()
    except ImportError:
        sys.stderr.write(
            "segno is not installed. It is a dev dependency:\n"
            "    uv sync\n"
            "    uv run ./slides/render_qr.py\n")
        return 2

    path = target(args.out)

    if args.check:
        if not os.path.exists(path):
            sys.stderr.write("%s does not exist\n" % path)
            return 1
        with open(path, encoding="utf-8") as handle:
            if handle.read() != svg:
                sys.stderr.write(
                    "%s is out of date; re-run %s\n"
                    % (path, os.path.relpath(__file__)))
                return 1
        print("%s is current (%s)" % (os.path.relpath(path), URL))
        return 0

    os.makedirs(args.out, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print("wrote %s  (%s)" % (os.path.relpath(path), URL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
