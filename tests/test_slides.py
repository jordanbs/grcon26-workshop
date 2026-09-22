"""The deck's structure, checked the way every other artifact here is.

`slides/check_deck.py` is the real check -- it is also runnable on its own,
because someone editing the deck should not have to know pytest exists. This
wires it into the suite so a frame that loses its title, or a present block
that grows past what a room can read, fails on the same run as everything
else.

What it cannot check is layout: whether a frame fits one screen in present
mode is a question for a browser, and the answer is in `slides/README.md`
under "Checking a change".
"""
import os
import subprocess
import sys

import pytest

SLIDES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slides")
CHECK = os.path.join(SLIDES, "check_deck.py")


@pytest.fixture(scope="module")
def deck():
    with open(os.path.join(SLIDES, "index.html"), encoding="utf-8") as handle:
        return handle.read()


def test_the_deck_passes_its_own_structural_check():
    result = subprocess.run([sys.executable, CHECK], capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_check_is_runnable_on_its_own(repo_root):
    """It is documented as `./slides/check_deck.py`, so it has to be that."""
    assert os.access(CHECK, os.X_OK)
    with open(CHECK, encoding="utf-8") as handle:
        assert handle.readline().startswith("#!")


def test_every_asset_the_deck_asks_for_is_checked_in(deck):
    """A missing stylesheet is a deck that renders as a wall of text and
    still scrolls, which is the kind of failure a rehearsal does not catch."""
    import re
    refs = re.findall(r'(?:href|src)="(assets/[^"]+)"', deck)
    assert refs, "the deck loads no local assets -- did the markup change?"
    for ref in sorted(set(refs)):
        assert os.path.exists(os.path.join(SLIDES, ref)), ref


def _renderers():
    """Every figure each `slides/render_*.py` knows how to make.

    Read out of the source with `ast` rather than by importing them:
    `render_grc.py` needs PyGObject, which is native and lives in system
    site-packages where this venv cannot see it.

    A renderer declares two things at module scope. `SUFFIX` is the extension
    it writes, and `FIGURES` is its manifest -- shaped differently on purpose.
    `render_grc.py` maps a flowgraph to {stem: block ids}, so it literal-evals
    and the stems are one level down; the others map a stem to the function
    that draws it, which does not literal-eval, so only its keys are read.

    Globbed rather than listed, so a fourth renderer needs no edit here.
    """
    import ast
    import glob

    out = {}
    for path in sorted(glob.glob(os.path.join(SLIDES, "render_*.py"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        suffix, stems = None, None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = {getattr(t, "id", None) for t in node.targets}
            if "SUFFIX" in targets:
                suffix = ast.literal_eval(node.value)
            elif "FIGURES" in targets:
                try:
                    nested = ast.literal_eval(node.value)
                except ValueError:
                    stems = [k.value for k in node.value.keys]
                else:
                    stems = [stem for fg in nested.values() for stem in fg]
        assert stems is not None, f"{name} has no FIGURES manifest"
        assert suffix, f"{name} declares no SUFFIX, so nothing knows what it writes"
        out[name] = [stem + suffix for stem in stems]
    return out


def _manifest():
    produced = set()
    for files in _renderers().values():
        produced |= set(files)
    return produced


# Three pictures no script can draw, and the reason each is exempt rather
# than missing. The rule below exists to catch a hand-placed screenshot of a
# flowgraph, which goes stale the next time a parameter moves. None of these
# three can: a photograph and a pinout drawing are of the hardware, and the
# Scopy shot is of a program this repo does not build. Naming them here keeps
# the rule sharp for everything else -- a fourth entry has to be argued for.
NOT_RENDERED = {
    "adalm2000.jpg",            # the board and its cable
    "adalm2000-pin-wires.png",  # ADI's own header pinout drawing
    "osc-main1.png",            # Scopy, with the oscilloscope open
}


def test_every_figure_the_deck_uses_is_one_a_renderer_produces(deck):
    """A picture of a flowgraph drifts; a render of one cannot.

    The point of both renderers is that re-running them reproduces every
    figure in the deck. An `<img>` pointing at a file neither script knows
    how to make is a hand-placed screenshot that will quietly go stale, so it
    fails here rather than at the next parameter change -- unless it is one
    of the three in `NOT_RENDERED`, which nothing could have drawn.
    """
    import re

    produced = _manifest() | NOT_RENDERED
    assert produced, "neither renderer has a FIGURES manifest any more"
    used = {os.path.basename(src)
            for src in re.findall(r'<img[^>]+src="img/([^"]+)"', deck)}
    assert used, "the deck references no rendered figures"
    assert used <= produced, (
        "the deck uses figures no renderer produces: "
        f"{sorted(used - produced)}")


def test_the_unrendered_figures_are_all_on_disk_and_all_used(deck):
    """`NOT_RENDERED` is an exemption list, so it has to stay honest.

    An entry for a file that is gone exempts nothing and hides a broken
    `<img>`; an entry the deck stopped using is an exemption nobody is
    watching, and the next hand-placed screenshot could inherit the name.
    """
    import re

    used = {os.path.basename(src)
            for src in re.findall(r'<img[^>]+src="img/([^"]+)"', deck)}
    for name in sorted(NOT_RENDERED):
        assert os.path.exists(os.path.join(SLIDES, "img", name)), \
            f"{name} is exempted from rendering but is not in slides/img/"
        assert name in used, \
            f"{name} is exempted from rendering but the deck no longer uses it"


def test_the_renderers_do_not_collide_on_a_filename():
    """Two scripts writing the same path would race, silently."""
    files = [f for produced in _renderers().values() for f in produced]
    assert len(files) == len(set(files)), \
        f"two renderers claim the same file: {sorted(set(files))}"


def test_every_renderer_is_runnable_on_its_own():
    """Each is documented as `./slides/render_*.py`, so each has to be that."""
    for name in _renderers():
        path = os.path.join(SLIDES, name)
        assert os.access(path, os.X_OK), name
        with open(path, encoding="utf-8") as fh:
            assert fh.readline().startswith("#!"), name


def test_no_rendered_figure_is_dead_weight():
    """Every committed image is one the deck actually shows."""
    import re
    with open(os.path.join(SLIDES, "index.html"), encoding="utf-8") as fh:
        used = set(re.findall(r'<img[^>]+src="img/([^"]+)"', fh.read()))
    on_disk = {f for f in os.listdir(os.path.join(SLIDES, "img"))
               if not f.startswith(".")}
    assert on_disk - used == set(), \
        f"committed but never shown: {sorted(on_disk - used)}"


def test_nothing_is_loaded_from_a_third_party_at_run_time(deck):
    """A conference room's network is not a dependency.

    One exception, and it is deliberate: the Google Fonts stylesheet. Every
    rule that uses it names a full fallback stack, so the deck renders
    correctly with the request blocked -- which is how it was checked.
    """
    import re
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    # Only things the page FETCHES. An <a href> to the repository is a link
    # somebody may follow later, not a load-time dependency.
    remote = re.findall(
        r'<(?:link|script|img|iframe)\b[^>]*\b(?:href|src)="(https?://[^"]+)"',
        deck)
    for url in remote:
        assert url.startswith(allowed), url
    assert not re.search(r'<script[^>]+src="https?://', deck), \
        "no script may come off the network"
