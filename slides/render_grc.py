#!/usr/bin/python3
"""Render the workshop's flowgraphs and blocks as GRC itself draws them.

The deck used to carry a hand-drawn diagram of `m2k_spi_loopback.grc`. A
diagram of a flowgraph is a second copy of it: it drifts the moment a
parameter changes, and it teaches a participant to recognise a picture rather
than the canvas they are about to sit in front of. These images come out of
GRC's own canvas code, so what is on the slide is what is on their screen --
same fonts, same colors, same port labels, same rounded corners.

No hardware and no running flowgraph: GRC parses the .grc and the block
definitions, and Cairo draws them. It never constructs a block's Python
class, so `gr-m2k` needs to be on `GRC_BLOCKS_PATH` but nothing needs to
import.

    ./slides/render_grc.py              # everything the deck uses
    ./slides/render_grc.py --list       # what is in each flowgraph
    ./slides/render_grc.py --scale 3    # denser, for print

**Uses the system interpreter,** the same way `iio_discover.py` does and for
the same reason: it needs PyGObject, which is a native binding that lands in
system site-packages where the project venv cannot see it. On Debian and
Ubuntu the packages are `gnuradio` and `gir1.2-gtk-3.0`.

Gtk needs a display to lay text out, and a headless machine has none:

    xvfb-run -a ./slides/render_grc.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "slides", "img")

# `build_library` takes the list of directories to read, and it is not the
# GRC_BLOCKS_PATH environment variable -- nothing here consults that. The
# stock blocks have to be named explicitly because without them the platform
# cannot find `options` and refuses to build a library at all.
STOCK_BLOCKS = "/usr/share/gnuradio/grc/blocks"

SUFFIX = ".png"

_APP = None

# What the deck asks for. A value of None means the whole flowgraph;
# otherwise it is the block ids to draw, and any connection with both ends
# inside that set is drawn with them.
FIGURES = {
    "m2k_spi_loopback.grc": {
        "flowgraph-spi-loopback": None,
        # The same canvas with the Options block and the variables left out.
        # Nothing is redrawn -- it is the signal path's own extents -- and it
        # is what fits on a slide, because the .grc puts a screen of empty space
        # between the variables and the graph.
        "flowgraph-spi-signal-path": [
            "spi_entry", "spi_encode_0", "m2k_digital_sink_0",
            "m2k_digital_source_0", "spi_decode_0", "message_debug_0",
            "sclk_f", "mosi_f", "cs_f", "qtgui_time_sink_x_0",
        ],
        "grc-variables": ["samp_rate", "half", "buffer_len", "frame"],
        # Four variables side by side is a wide, short strip, and a strip
        # constrained to a column is unreadable from the back of a room. The
        # one that carries the idea gets its own figure.
        "grc-variable-frame": ["frame"],
        "grc-entry": ["spi_entry"],
        "grc-spi-encode": ["spi_encode_0"],
        "grc-digital-sink": ["m2k_digital_sink_0"],
        "grc-digital-source": ["m2k_digital_source_0"],
        "grc-spi-decode": ["spi_decode_0"],
        "grc-message-debug": ["spi_decode_0", "message_debug_0"],
        "grc-display": ["sclk_f", "mosi_f", "cs_f", "qtgui_time_sink_x_0"],
    },
    "m2k_scope.grc": {
        "grc-analog-source": ["m2k_analog_source_0"],
    },
    # The first flowgraph anyone runs. Four blocks, and the whole point is
    # that none of them is a blink block -- so the signal path is drawn on
    # its own, without the scope leg that only exists to make it visible.
    "m2k_blinky.grc": {
        "grc-blinky": [
            "analog_sig_source_x_0", "blocks_float_to_short_0",
            "m2k_digital_sink_0",
        ],
    },
    # Same pin, same sink, two blocks in between. Drawn beside the blink to
    # show that brightness is not a different kind of thing.
    "m2k_led_pwm.grc": {
        "grc-led-pwm": [
            "analog_sig_source_x_0", "blocks_add_const_vxx_0",
            "blocks_threshold_ff_0", "blocks_float_to_short_0",
            "m2k_digital_sink_0",
        ],
    },
    # The colorimeter's whole canvas is six parallel copies of the same three
    # blocks, which reads as wallpaper. Drawn as one color's chain instead --
    # the other five are the same picture -- plus the three sources that make
    # the simultaneity visible, and the decision the chain ends in.
    "m2k_colorimeter.grc": {
        "grc-colorimeter-chop": ["red_chop", "green_chop", "blue_chop", "led"],
        "grc-colorimeter-lockin": [
            "photodiodes", "ref_red", "sam_red", "ref_red_mag", "sam_red_mag",
            "red_ratio", "red_pct",
        ],
        "grc-colorimeter-decide": ["decide", "verdict"],
    },
    # Nineteen blocks on one canvas is a strip nine times as wide as it is
    # tall, and a strip constrained to a slide column is unreadable from the
    # back of a room. Drawn instead as the stages a person builds it in --
    # three or four blocks each, which lands near 3:1.
    "m2k_ultrasonic_fsk.grc": {
        "grc-ultrasonic-rates": ["tx_rate", "rx_rate", "tx_repeat", "sps"],
        "grc-ultrasonic-frame": ["message", "frame"],
        "grc-ultrasonic-tuning": ["f0", "spacing", "fspace", "fmark"],
        "grc-ultrasonic-tx": [
            "blocks_vector_source_x_0", "blocks_unpack_k_bits_bb_0",
            "blocks_repeat_0",
        ],
        "grc-ultrasonic-scale": [
            "blocks_uchar_to_float_0", "blocks_multiply_const_vxx_0",
            "blocks_add_const_vxx_0",
        ],
        "grc-ultrasonic-sink": ["blocks_vco_f_0", "m2k_analog_sink_0"],
        "grc-ultrasonic-rx": [
            "m2k_analog_source_0", "freq_xlating_fir_filter_xxx_0",
            "analog_quadrature_demod_cf_0",
        ],
        "grc-ultrasonic-clock": [
            "digital_symbol_sync_xx_0", "digital_binary_slicer_fb_0",
        ],
        "grc-ultrasonic-sync": [
            "digital_correlate_access_code_tag_xx_0",
            "blocks_tagged_stream_align_0", "blocks_pack_k_bits_bb_0",
        ],
        "grc-ultrasonic-out": [
            "blocks_keep_m_in_n_0", "blocks_stream_to_tagged_stream_0",
            "pdu_tagged_stream_to_pdu_0", "blocks_message_debug_0",
        ],
    },
}


def platform():
    """A GRC platform that can see both the stock blocks and gr-m2k."""
    os.environ["GRC_BLOCKS_PATH"] = os.pathsep.join(
        [os.path.join(ROOT, "gr-m2k", "grc"), STOCK_BLOCKS])

    try:
        import gi
    except ImportError:
        raise SystemExit(
            "PyGObject is missing from this interpreter. It is a native "
            "binding, so it lives in system site-packages and a venv (or a "
            "second python from a PPA) cannot see it. Run this with the "
            "interpreter the distro package installed for -- on Ubuntu 24.04 "
            "that is python3.12:\n"
            "    xvfb-run -a /usr/bin/python3.12 slides/render_grc.py")
    gi.require_version("Gtk", "3.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Gtk

    # The gui FlowGraph reaches for the running application to hang a context
    # menu off, and there is no application here. Give it one, and stub the
    # menu -- nothing is ever going to right-click these.
    # Held at module scope on purpose: `set_default()` does not take a
    # reference, so a local would be collected the moment this function
    # returns and `Gtk.Application.get_default()` would hand back None again.
    global _APP
    _APP = Gtk.Application(application_id="org.grcon26.render")
    _APP.set_default()

    from gnuradio.grc.gui.canvas import flowgraph as gui_flowgraph

    class NoContextMenu(object):
        def __init__(self, *args, **kwargs):
            pass

        def popup(self, *args, **kwargs):
            pass

    gui_flowgraph._ContextMenu = NoContextMenu

    from gnuradio.grc.gui.Platform import Platform
    plat = Platform(version="3.10", version_parts=("3", "10", "9"),
                    prefs=None, install_prefix="/usr")
    plat.build_library()
    return plat


def load(plat, name):
    """One flowgraph, laid out and ready to draw.

    `create_labels` needs a Cairo context to measure text with, and nothing
    has an extent until `create_shapes` has run -- which is why a flowgraph
    straight out of the parser reports its extents as the empty sentinel.
    """
    import cairo
    flow_graph = plat.make_flow_graph(os.path.join(ROOT, "flowgraphs", name))
    flow_graph.rewrite()
    flow_graph.validate()
    errors = flow_graph.get_error_messages()
    if errors:
        raise SystemExit(f"{name} does not validate:\n  " +
                         "\n  ".join(errors))
    # `update_elements_to_draw` reads GRC's own view toggles, and with no
    # prefs file behind them they come up at their defaults -- which hides
    # the variables. On this canvas the variables ARE the figure (`half` is
    # the bus speed and `frame` is computed from it), so say so rather than
    # inheriting whatever a fresh install happens to think.
    from gnuradio.grc.gui import Actions
    Actions.TOGGLE_HIDE_VARIABLES.set_active(False)
    Actions.TOGGLE_HIDE_DISABLED_BLOCKS.set_active(False)
    # Block comments are a note to whoever opens the .grc, not part of the
    # graph, and this one runs to a paragraph. Off, so the figure is the
    # flowgraph.
    Actions.TOGGLE_SHOW_BLOCK_COMMENTS.set_active(False)

    # `create_labels` and `create_shapes` both walk `_elements_to_draw`,
    # which is empty until this runs -- so without it every block keeps the
    # zero-size area it was constructed with and Cairo is handed an empty
    # rectangle.
    flow_graph.update_elements_to_draw()
    scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    flow_graph.create_labels(scratch)
    flow_graph.create_shapes()
    return flow_graph


def extents(elements):
    """The box around a set of blocks, in flowgraph coordinates.

    Ports hang off the block body -- an input sits at negative x relative to
    its block -- so a box drawn from `width` and `height` alone cuts every
    input port in half down the left edge. Measured, not padded around,
    because port size is a GRC constant nobody here should be guessing at.
    """
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for block in elements:
        bx, by = block.coordinate
        boxes = [(bx, by, bx + block.width, by + block.height)]
        for port in block.active_ports():
            px, py = port.coordinate
            boxes.append((bx + px, by + py,
                          bx + px + port.width, by + py + port.height))
        for ax, ay, bx2, by2 in boxes:
            x0, y0 = min(x0, ax), min(y0, ay)
            x1, y1 = max(x1, bx2), max(y1, by2)
    return x0, y0, x1, y1


def render(flow_graph, block_ids, path, scale, padding=14):
    """Draw the whole flowgraph, or the named blocks out of it.

    Drawing a subset is not a crop: each element is asked to draw itself into
    a surface sized to that subset, so nothing from a neighbouring block ever
    bleeds in at the edge. Connections come along when both of their ends do,
    which is what makes a two-block figure show the wire between them.
    """
    import cairo
    from gnuradio.grc.gui.canvas.colors import FLOWGRAPH_BACKGROUND_COLOR

    if block_ids is None:
        blocks = list(flow_graph.blocks)
        connections = list(flow_graph.connections)
    else:
        by_name = {b.name: b for b in flow_graph.blocks}
        missing = [i for i in block_ids if i not in by_name]
        if missing:
            raise SystemExit(f"no such block(s): {', '.join(missing)}")
        blocks = [by_name[i] for i in block_ids]
        chosen = set(blocks)
        connections = [c for c in flow_graph.connections
                       if c.source_block in chosen and c.sink_block in chosen]

    x0, y0, x1, y1 = extents(blocks)
    width = (x1 - x0) + 2 * padding
    height = (y1 - y0) + 2 * padding

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                 round(width * scale), round(height * scale))
    cr = cairo.Context(surface)
    cr.scale(scale, scale)
    cr.set_source_rgba(*FLOWGRAPH_BACKGROUND_COLOR)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    cr.translate(padding - x0, padding - y0)

    # Connections under blocks, the same order the canvas draws in.
    for element in connections + blocks:
        cr.save()
        element.draw(cr)
        cr.restore()

    surface.write_to_png(path)
    _shrink(path)
    return round(width * scale), round(height * scale)


def _shrink(path):
    """Palette-encode the PNG, if Pillow is here to do it.

    Cairo writes 32-bit RGBA. A GRC canvas is flat fills, black strokes and
    antialiased text, so an adaptive 256-color palette is visually identical
    and about a third of the size -- 248 kB to 91 kB on the signal-path
    figure, which is the difference between a deck that is mostly pictures of
    itself and one that is not. Skipped silently where Pillow is absent: the
    uncompressed file is correct, only larger.
    """
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as image:
        # RGB first: quantizing straight from RGBA spends palette entries on
        # alpha levels that a fully opaque canvas never uses.
        image.convert("RGB").quantize(colors=256).save(path, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scale", type=float, default=3.0,
                    help="pixels per canvas unit. 3 is the default because a "
                         "block figure is displayed at roughly the width of a "
                         "slide column, which is wider than the block: at 2 "
                         "the deck upscales it and the text goes soft "
                         "(default: 3)")
    ap.add_argument("--out", default=OUT, help=f"output directory "
                    f"(default: {os.path.relpath(OUT, ROOT)})")
    ap.add_argument("--list", action="store_true",
                    help="print each flowgraph's block ids and stop")
    args = ap.parse_args()

    plat = platform()

    if args.list:
        for name in FIGURES:
            flow_graph = load(plat, name)
            print(name)
            for block in sorted(flow_graph.blocks, key=lambda b: b.name):
                print(f"  {block.name:28} {block.key}")
        return 0

    os.makedirs(args.out, exist_ok=True)
    for name, figures in FIGURES.items():
        flow_graph = load(plat, name)
        for stem, block_ids in figures.items():
            path = os.path.join(args.out, stem + SUFFIX)
            w, h = render(flow_graph, block_ids, path, args.scale)
            print(f"{os.path.relpath(path, ROOT):44} {w}x{h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
