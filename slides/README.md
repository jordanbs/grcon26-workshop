# The workshop deck

One HTML file, two ways to read it, and a printer.

```
xdg-open slides/index.html          # that is the whole build step
```

There is no generator, no toolchain and nothing to install. Open the file
from disk, from a web server, or from a Pages URL and it behaves the same.

## Two modes, one document

The format is [ECE 444's frame view](https://github.com/livethisdream/ece444)
ported to a standalone page. A frame is one full-viewport section; the deck is
a stack of them under `scroll-snap`.

| mode | what it is | who it is for |
| --- | --- | --- |
| **read** (default) | continuous notes, everything visible | a participant, before or after |
| **present** | one frame a screen, detail collapsed | the room |

The two are the same document. `:::{depth}` content — here, `<div class="depth">`
— is **always in the DOM**. Present mode hides it behind *More detail +*; it is
never deleted, so presenting cannot lose anything the notes carry.

A frame marked `cut` shows only its `<h2>` and its `.present` blocks on screen.
Two present blocks in one `.stage` sit side by side on a laptop and stack on a
phone: key points beside the table or the diagram they talk to.

**Titles say what the frame is.** "The IIO Model", "What Are Raw Values",
"GR-IIO", "Sample Flow", "The 6 M2K Instruments" — a noun phrase naming the
subject, in title case. Not a claim about the slide ("Mode 0, in one
sentence"), not a comma clause that withholds the subject until the second
half ("Four nouns, and that is the whole model"), and not a joke. Cheekiness
lands when it is rare, and a title is the wrong place to spend it.
`check_deck.py` flags the constructions this deck kept reaching for.

**Do not justify the work on a slide.** The room is about to watch the thing
run, which settles it better than a claim does. No "this has been verified on
a real board", no test counts, no "which also proves". Where a claim genuinely
is still an assumption, say so in the notes.

**The prose voice** follows ECE 444's `VOICE.md`, which is a calibration set
built from Neil's own review corrections rather than a style opinion. The four
that this deck kept breaking: do not narrate your own rhetorical moves ("worth
pausing on", "the interesting part") — say the thing; never vouch for the
material's own honesty or rigor; no cost-and-payment metaphors; active voice
with the agent named. `check_deck.py` gates the unambiguous ones. Passive voice
and verbless sentences need a reader, so they are not gated — the guide's own
self-check greps are the way to find them.

Bullets are the exception to "complete sentences": a `<ul>` is a list, and a
list item is a fragment by convention. A `<p>` is not.

**What goes in a present block.** Bullets and pictures — things to talk *about*.
Not paragraphs: a paragraph on screen is a paragraph the room reads instead of
listening, and the presenter ends up reading it too. The shapes that earn a
slide are a `<ul>` of fragments, a figure, a code block, a table, and one
`<p class="pull">` carrying the frame's claim. Running prose belongs in
`.depth`, where it is the notes. When a beat needs a sentence to be understood,
that is the sentence to say out loud, not to project.

| class | means |
| --- | --- |
| `frame cut` | has a present layer; present mode shows only that |
| `frame section-frame` | a divider — which act we are in |
| `frame read-only` | notes material, skipped by present mode *and* by the counter |
| `stage split` / `split-r` | the wider track goes left / right, for a table beside a callout |
| `present callout` | the one present block that keeps a box in both modes |

## The GRC figures are rendered, not screenshotted

Every block and canvas picture in the deck comes out of GNU Radio Companion's
own drawing code:

```
xvfb-run -a ./slides/render_grc.py          # into slides/img/
xvfb-run -a ./slides/render_grc.py --list   # block ids per flowgraph
```

It loads the same `.grc` a participant opens, asks GRC to lay it out, and
draws it to Cairo. Same fonts, same colors, same port shapes, same wire
routing — so the slide and their screen match, and a changed parameter shows
up by re-running the script rather than by somebody noticing.

Rendering a **subset** is not a crop: the named blocks are drawn into a
surface sized to their own extents, and a connection comes along when both of
its ends do. That is how a two-block figure shows the wire between them and
nothing bleeds in at the edges.

`--scale` is pixels per canvas unit and defaults to **3**. A block figure is
displayed at roughly the width of a slide column, which is wider than the
block itself, so at 2 the deck upscales it and the text goes soft.

**What it needs, and why it is not in `uv sync`.** PyGObject and GNU Radio are
native, so they live in system site-packages where the project venv cannot see
them — the script uses `#!/usr/bin/python3` for the same reason
`iio-tools/iio_discover.py` does. On Ubuntu 24.04:

```
sudo apt install gnuradio gir1.2-gtk-3.0
```

Gtk needs a display to lay text out, so a headless machine needs `xvfb-run`.
No board and no running flowgraph are involved: GRC parses the `.grc` and the
block YAML and never constructs a block's Python class.

One thing to know if it ever stops working: `GRC_BLOCKS_PATH` **replaces** the
search path rather than adding to it, so the script names the stock block
directory alongside `gr-m2k/grc`. Without the stock path the platform cannot
find `options` and refuses to build a library at all.

## The SPI waveforms come out of the encoder

```
./slides/render_spi.py          # into slides/img/
```

Same principle one layer down. `slides/render_spi.py` asks `SpiEncoder` — the
module that builds the levels the M2K puts on DIO0–2 — for the actual samples,
and draws them. Nothing is drawn from a description of SPI: if the encoder's
idea of mode 0 changed, so would the picture. The bit labels on
`spi-mode0.svg` are read off MOSI at each rising edge rather than out of the
byte, so LSB-first would show up as labels in the wrong order.

`spi-framing.svg` is the one worth knowing about. Both halves come from the
same encoder; the only difference is that the top called `send` once with three
bytes and the bottom called it three times. That is exactly the bug from
section 11 of the bench checklist, drawn rather than described.

`SpiEncoder` imports nothing, so this needs no GNU Radio and no board — just
the standard library, on any interpreter.

**Two things about the SVGs.** They carry their own light/dark palette in an
internal `@media (prefers-color-scheme: dark)` block, because an `<img>` cannot
see the page's custom properties; the deck follows the OS scheme too, so they
stay in step. And the viewBox is deliberately narrow (560 units): an SVG's type
scales with its box, and at 760 the annotations landed at 7px on a 1280 screen.

## The colorimeter figures are computed, not drawn

```
./slides/render_colorimeter.py          # into slides/img/
```

Two SVGs. `colorimeter-optics.svg` is the light path -- one LED, a 45 degree
splitter slot, a Reference well straight on and a Sample well at the elbow --
because the board's own silkscreen suggests the diagonal slot is a second
cuvette position and it is not.

`colorimeter-coherent.svg` is the argument for 5004.9 Hz. Both panels come out
of a DFT this script computes, of a square wave this script generates: 205
whole cycles in 4096 samples on the left, a round 5000 Hz on the right. The
spurs and the leakage in the caption are the numbers that fell out, not numbers
chosen to make the point -- the left panel is not bare either, and the caption
says so.

Standard library only, on any interpreter.

## The setup QR is generated too, and checked by a decoder

```
uv run ./slides/render_qr.py           # into slides/img/
uv run ./slides/render_qr.py --check   # 0 if the committed file is current
uv run ./slides/render_qr.py --url     # what it encodes
```

The code on the title frame is the one figure in the deck nobody can
proofread. A wrong URL looks exactly like a right one, and it fails in the
room, on every phone at once. So it is generated from a single constant in
`render_qr.py`, the output is committed, and three checks sit behind it:
`--check` fails if the committed SVG has drifted, `tests/test_install.py`
asserts that the same URL appears in the deck and in every document that
carries it, and one test reads the code back with **zxing-cpp** — a decoder
with no relation to `segno`, which is what wrote it. An encoder agreeing with
itself proves nothing.

`segno` is a dev dependency, so `uv sync` is needed to regenerate but not to
open the deck.

**The SVG carries no quiet zone.** Baking the four-module border into the file
would shrink the code inside a box of fixed width, which is backwards for
somebody scanning from the back of a room. The `.qr img` card in `frames.css`
supplies the border instead, with more padding than the minimum, on white,
whatever the deck's palette is doing around it.


**There is no rasterizer on this machine** -- no `rsvg-convert`, no Inkscape --
so nothing here can be previewed as a picture before it ships. The script
carries a `Canvas` class instead that records every box and every text extent
it emits and then reports labels that fall outside the viewBox or sit on a box
that is not theirs. It runs on every render and prints its complaints. It
caught an inverted dB axis and a caption running off the edge, which is about
what a pair of eyes would have caught.

## Keys

<kbd>&rarr;</kbd> <kbd>&larr;</kbd> move · <kbd>P</kbd> present or read ·
<kbd>D</kbd> detail · <kbd>G</kbd> contents (the counter is the button; double-tap
for the top) · <kbd>L</kbd> laser · <kbd>S</kbd> spotlight · <kbd>F</kbd> fullscreen.

## Printing to PDF

**tools → print / PDF**, or <kbd>&#8984;</kbd><kbd>P</kbd>. The button switches
to read mode first, because the browser prints whatever mode the page is in and
present mode would send projector-sized type to A4.

`@media print` in `frames.css` releases the deck's fixed-height scroll container
— without that the whole deck prints as **one** page — and gives each frame
`break-after: page`, so a printed frame has room to write beside it. The depth
is always shown on paper: the handout carries the material the projected deck
does not.

Measured, not assumed: 48 frames print as 59 sheets — one each, plus the ten
where a rendered canvas and its notes run past a single side. If a change ever
makes that number 1, the print block has been overridden.

## Hosting it

`.github/workflows/pages.yml` publishes `slides/` on every push to `main`. It
needs **Settings → Pages → Source: GitHub Actions** turned on once; nothing else.

The deck is entirely self-contained apart from one Google Fonts stylesheet, and
every rule that uses it names a full fallback stack — it was checked with the
request blocked. A conference room's network is not a dependency.

## Checking a change

```
./slides/check_deck.py        # structure: titles, ids, word budgets
uv run pytest tests/test_slides.py
```

The structural check enforces the voice rules above and what is invisible
until it is wrong in front of people: every frame has a title (or the contents overlay cannot name it), ids
are unique (or deep links land in the wrong place), a `cut` frame actually has
a present layer, no present block is over **40 words**, and no frame's present
layer is over **85**. It also asserts that every id `frames.js` reaches for by
name still exists in the markup, that every `<img>` the deck names is on disk,
and that each one has alt text.

**What it cannot check is layout.** Whether a frame fits one screen in present
mode is a question for a browser. The way to answer it:

```js
// headless, at the projector's size
const over = [];
document.querySelectorAll('.frame:not(.read-only)').forEach(f => {
  const w = f.querySelector('.wrap');
  const cs = getComputedStyle(f);
  const h = w.getBoundingClientRect().height
          + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
  if (h > window.innerHeight) over.push(f.id + ' ' + Math.round(h));
});
```

Run in present mode. Every frame currently fits at 1024&times;768, 1280&times;800 and
1440&times;900, and nothing overflows horizontally at 390px. When a frame overruns,
**split it or move detail into `depth` — never cut the content.**

## Files

```
index.html          the deck
assets/shell.css    palette, type, HUD, popovers, jump overlay
assets/frames.css   the scroller, present/read, the present layer, print
assets/shell.js     one popover implementation
assets/frames.js    position, counter, laser, contents, keys, modes
check_deck.py       the structural check
render_grc.py       the GRC figures, from GRC's own canvas code
render_spi.py       the SPI waveforms, from the encoder that drives the pins
render_colorimeter.py
                    the colorimeter optics, and the coherence argument
render_qr.py        the setup QR on the title frame, from one URL
img/                what they produce -- generated, but committed, so the
                    deck opens on a machine with no GNU Radio
```
