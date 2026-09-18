#!/usr/bin/env python3
"""Structural checks on the deck.

The frame view has a handful of rules that are invisible until they are
wrong on a projector: a frame with no title is unreachable from the contents
overlay, a duplicate id makes deep links land in the wrong place, and a
present block over the word budget is a slide nobody can read from the back
of the room. None of that raises anything in a browser.

Standard library only, same as everything else here.

    ./slides/check_deck.py            # 0 on success
"""
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
DECK = os.path.join(HERE, "index.html")

# Forty words a present block, which is the budget the frame view was
# re-cut against. Counted per block, not per frame: two blocks in a stage sit
# side by side and are read as one screen, but each has to stand on its own.
WORD_BUDGET = 40
# A frame's whole present layer. Two blocks at budget is already a busy slide.
FRAME_BUDGET = 85


# Void elements have no end tag, so pushing them onto the tag stack leaves it
# permanently one deeper and the depth comparison that closes a present block
# never matches again -- the block then swallows everything after it and
# reports a word count for half the frame. Cost one wrong failure the day the
# deck grew its first <img>.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class Deck(HTMLParser):
    """Collect frames, their ids, titles, and present-block word counts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames = []          # dicts: id, classes, title, present[], depth
        self.ids = []
        self.stack = []           # open tags, innermost last
        self.cur = None           # frame being read
        self.in_title = False
        self.present_depth = None  # nesting level of the open present block
        self.buf = []

    # -- helpers ---------------------------------------------------------
    def _classes(self, attrs):
        return dict(attrs).get("class", "").split()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        classes = self._classes(attrs)
        if tag in VOID:
            return
        self.stack.append(tag)

        if tag == "section" and "frame" in classes:
            self.cur = {
                "id": a.get("id", ""),
                "classes": classes,
                "section": a.get("data-section", ""),
                "title": None,
                "present": [],
                "depth": False,
            }
            self.frames.append(self.cur)
        elif self.cur is not None:
            if tag in ("h1", "h2") and self.cur["title"] is None:
                self.in_title = True
                self.buf = []
            elif "present" in classes and self.present_depth is None:
                self.present_depth = len(self.stack)
                self.buf = []
            elif "depth" in classes:
                self.cur["depth"] = True

    def handle_endtag(self, tag):
        if self.in_title and tag in ("h1", "h2"):
            self.cur["title"] = "".join(self.buf).strip()
            self.in_title = False
            self.buf = []
        if self.present_depth is not None and len(self.stack) == self.present_depth:
            self.cur["present"].append("".join(self.buf))
            self.present_depth = None
            self.buf = []
        if tag in VOID:
            return
        if tag == "section" and self.stack and self.stack[-1] == "section":
            self.cur = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.in_title or self.present_depth is not None:
            self.buf.append(data)


# The deck's prose follows ECE 444's voice guide, which is a calibration set
# built from Neil's own review corrections rather than a style opinion. What
# is gated here is the part a regex can decide on its own. General passive
# voice is not: `\b(is|are|was|were)\s+\w+(ed|en)\b` matches "is silent",
# "are different devices" and "is seven times out of eight" as readily as it
# matches a real one, and a check that cries wolf gets turned off. Verbless
# sentences need a reader for the same reason. Both still apply -- see the
# guide's own self-check list -- they are just enforced by reading.
BANNED = {
    # Rule 2 -- never vouch for the material's own honesty or rigor. Claiming
    # it implies the surrounding material is not.
    r"\b(honest|honestly|genuinely|truly|rigorous)\b": "self-praise",
    r"\bno hand-waving\b": "self-praise",
    r"\bdear reader\b": "self-praise",
    # Rule 1 -- do not narrate your own rhetorical moves. Say the thing.
    r"\bworth (pausing|dwelling|quoting|noting|more than)\b": "narration",
    r"\bit is worth\b": "narration",
    r"\bthe single most\b": "narration",
    r"\bthe interesting part\b": "narration",
    # Rule 20 -- no cost-and-payment metaphors. A literal price is fine, so
    # the amount-bearing forms are excluded rather than the words.
    r"\bis the price\b": "metaphor",
    r"\bthat is the trade\b": "metaphor",
    r"\b(bought|buys|payoff)\b": "money metaphor",
    r"\b(spends?|spent|earns?)\b": "money metaphor",
    r"\b(cost|costs)\b(?!\s*\$)": "money metaphor",
    r"\b(cheap|expensive)\b": "money metaphor",
    # Rule 20 -- and no framing that stands outside the material describing it.
    r"\bthe shape of\b": "flowery framing",
    r"\bin one (line|slide)\b": "flowery framing",
    r"\bthe whole of it\b": "flowery framing",
    # Rule 9 -- the passive constructions that are always passive. The
    # general case is left to a reader; these six are not ambiguous.
    r"\bis used\b": "passive",
    r"\bis shown\b": "passive",
    r"\bcan be seen\b": "passive",
    r"\bwill be connected\b": "passive",
    r"\bneeds? to be\b": "passive",
    r"\bis referred to as\b": "passive",
    # Rule 22 -- American English.
    r"\b\w*(quantis|behaviour|colour|analys|generalis|normalis)\w*\b": "British spelling",
    r"\b(centred|metre|metres|favour|realise|realised|recognise|organise)\b":
        "British spelling",
}


# A frame title says what the frame is. The constructions below are the ones
# this deck kept reaching for instead -- a comma clause that withholds the
# subject, a promise about brevity, a leftover marker. Cheekiness lands when
# it is rare, so the title is not where it goes.
TITLE_TELLS = {
    r",\s+and (that|how|what)\b": "comma clause; name the thing instead",
    r"\bin one sentence\b": "a claim about the slide, not its subject",
    r"\band what it does not\b": "comma clause; name the thing instead",
    r"\bplaceholder\b": "say the subject; the body can say it is unbuilt",
    r"\.$": "a title is not a sentence",
}


def prose(source):
    """The running text, which is what the voice rules govern.

    Bullets are a list and take fragments; `alt` text is a description for a
    screen reader and is not prose anyone reads aloud. What is left is the
    depth, the callouts, the pull claims and the captions.
    """
    out = []
    for pattern in (r'<div class="depth">(.*?)\n    </div>',
                    r'<div class="present[^"]*callout[^"]*">(.*?)\n      </div>',
                    r'<p class="pull">(.*?)</p>',
                    r'<figcaption>(.*?)</figcaption>'):
        for m in re.finditer(pattern, source, re.S):
            out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))))
    return out


def words(text):
    """Words a person reads off the screen.

    A code block is one glance, not fourteen words, so a `pre` run counts as
    a single item -- but the parser has already flattened it into the same
    buffer, so this is deliberately crude: anything with no letters in it is
    not a word.
    """
    return [w for w in re.split(r"\s+", text) if re.search(r"[A-Za-z]", w)]


def main():
    with open(DECK, encoding="utf-8") as fh:
        source = fh.read()

    deck = Deck()
    deck.feed(source)
    fails = []

    if not deck.frames:
        fails.append("no frames found -- did the markup change?")

    for f in deck.frames:
        where = f["id"] or "(no id)"
        if not f["id"]:
            fails.append("a frame has no id, so nothing can link to it")
        if not f["title"] and "title-frame" not in f["classes"]:
            fails.append(f"{where}: no <h1>/<h2>, so the contents overlay "
                         f"cannot name it")
        if "cut" in f["classes"] and not f["present"]:
            fails.append(f"{where}: marked `cut` but carries no present block, "
                         f"so present mode shows a bare title")
        if f["present"] and "cut" not in f["classes"]:
            fails.append(f"{where}: has present blocks but is not `cut`, so "
                         f"they will not lay out side by side")
        if f["title"]:
            for pattern, why in TITLE_TELLS.items():
                if re.search(pattern, f["title"], re.I):
                    fails.append(f'{where}: title "{f["title"]}" -- {why}')
        total = 0
        for i, block in enumerate(f["present"]):
            n = len(words(block))
            total += n
            if n > WORD_BUDGET:
                fails.append(f"{where}: present block {i + 1} is {n} words "
                             f"(budget {WORD_BUDGET}) -- move detail to depth")
        if total > FRAME_BUDGET:
            fails.append(f"{where}: {total} present words (budget "
                         f"{FRAME_BUDGET}) -- split the frame")

    for src in sorted(set(re.findall(r'<img[^>]+src="([^"]+)"', source))):
        if not src.startswith(("http:", "https:", "data:")):
            if not os.path.exists(os.path.join(HERE, src)):
                fails.append(f"missing image `{src}` -- render it with "
                             f"slides/render_grc.py")
    for tag in re.findall(r'<img[^>]*>', source):
        if 'alt="' not in tag:
            fails.append(f"an <img> has no alt text: {tag[:70]}")

    for blob in prose(source):
        for pattern, why in BANNED.items():
            for hit in re.finditer(pattern, blob, re.I):
                start = max(0, hit.start() - 40)
                fails.append(f"{why}: ...{blob[start:hit.end() + 40].strip()}...")

    dupes = {i for i in deck.ids if deck.ids.count(i) > 1}
    for i in sorted(dupes):
        fails.append(f"duplicate id `{i}` -- deep links land on the first one")

    # Every id frames.js reaches for by name. A rename in the markup that
    # misses one of these breaks a control silently, with the page looking
    # fine.
    wired = ["deck", "laser", "spot", "railfill", "cur", "tot", "index",
             "indexlist", "btnIndex", "btnIndexClose", "btnMode", "btnTools",
             "btnLaser", "btnSpot", "btnFull", "btnPrint", "btnPresent",
             "btnRead", "modepop", "toolspop"]
    for i in wired:
        if i not in deck.ids:
            fails.append(f"frames.js wires `{i}` by id and the markup has none")

    counted = [f for f in deck.frames if "read-only" not in f["classes"]]
    print(f"{len(deck.frames)} frames, {len(counted)} in the counter, "
          f"{sum(1 for f in deck.frames if f['depth'])} carrying depth")

    if fails:
        print(f"\n{len(fails)} failures:", file=sys.stderr)
        for m in fails:
            print(f"  {m}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
