"""Find text in a bit stream that never said where a byte begins.

The arithmetic behind the **ASCII at Every Offset** block, in a module
that imports nothing -- same arrangement as `spi_decode.py`, and for the
same reason: it can then be tested in an ordinary interpreter, with no
GNU Radio and no numpy anywhere near it.

The problem it solves. A receiver that frames on a sync word knows where
each byte starts because the correlator told it. Take the sync word away
-- which a transmitter that stops and starts often has to do, see the
ultrasonic notes in `flowgraphs/README.md` -- and nothing in the stream
marks a boundary. `Pack K Bits` still has to pick one, and picks the arbitrary
one, which is right about an eighth of the time. The other seven eighths
come out as mojibake and look exactly like a broken link.

So do not pick. Pack the same bits eight ways, and if the demodulator
may have handed back the two tones the wrong way up, sixteen. Print any
run of printable ASCII at least `min_chars` long, and say which offset
it turned up at.

**Why sixteen and not eight.** Random bytes are printable about 37% of
the time, so eight in a row happens roughly once in every 3500
positions -- constantly, across sixteen offset-and-polarity combinations
scanning every position in the stream. Sixteen in a row is about one in
five million, which works out to silence between bursts. That matters
more than it sounds: it means silence here is silence on the air, rather
than a wrong guess about framing.
"""

# Space through tilde. The printable range, which is what a readable
# payload is written in.
LOW, HIGH = 0x20, 0x7E

# Sixteen characters, for the reason in the module docstring. Eight is
# the tempting number because it is one byte; it is also noise.
MIN_CHARS = 16


def pack(bits, offset=0, invert=False):
    """Bits to bytes, starting at `offset`, dropping any ragged tail.

    `bits` is any iterable of 0/1 ints. A bit stream is most-significant
    first, the same order `Pack K Bits` uses, because the transmitter
    unpacked it that way.
    """
    seq = [int(b) & 1 for b in bits]
    if invert:
        seq = [b ^ 1 for b in seq]
    usable = (len(seq) - offset) // 8 * 8
    if usable <= 0:
        return b""
    out = bytearray(usable // 8)
    for i in range(usable):
        if seq[offset + i]:
            out[i // 8] |= 0x80 >> (i % 8)
    return bytes(out)


def runs(data, min_chars=MIN_CHARS):
    """Every run of printable ASCII at least `min_chars` long.

    Yields `(start_index, text)` with the index in bytes into `data`.
    Written as a scan rather than a regex so the module keeps its
    promise of importing nothing at all.
    """
    found = []
    start = None
    for i, byte in enumerate(data):
        if LOW <= byte <= HIGH:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_chars:
                found.append((start, data[start:i]))
            start = None
    if start is not None and len(data) - start >= min_chars:
        found.append((start, data[start:]))
    return found


class Hit(object):
    """One readable run, and where in the stream it sat.

    `start` and `end` are absolute bit positions, which is what lets a
    caller drop a run it has already reported when two overlapping
    windows both turn it up.
    """

    __slots__ = ("offset", "inverted", "text", "start", "end")

    def __init__(self, offset, inverted, text, start, end):
        self.offset = offset
        self.inverted = inverted
        self.text = text
        self.start = start
        self.end = end

    @property
    def chars(self):
        return len(self.text)

    def overlaps(self, other_start, other_end):
        return self.start < other_end and other_start < self.end

    def line(self):
        """The one-line report, which is the block's whole output."""
        return "offset %d%s  %3d chars  %s" % (
            self.offset,
            "  INVERTED" if self.inverted else "          ",
            self.chars,
            self.text.decode("ascii"))

    def __repr__(self):                     # pragma: no cover - debugging
        return "<Hit %s>" % self.line()


def scan(bits, base=0, min_chars=MIN_CHARS, try_inverted=True):
    """Every readable run at every byte offset, longest first.

    `base` is the absolute bit position of `bits[0]`, so the hits come
    back with positions in the stream rather than in the window.

    Sorted by length descending, then by position, so the caller can
    print the best few and stop: the real payload is nearly always the
    longest thing in the window, and a spurious run is short by
    construction.
    """
    hits = []
    for invert in ((False, True) if try_inverted else (False,)):
        for offset in range(8):
            data = pack(bits, offset, invert)
            if not data:
                continue
            for index, text in runs(data, min_chars):
                start = base + offset + 8 * index
                hits.append(Hit(offset, invert, text,
                                start, start + 8 * len(text)))
    hits.sort(key=lambda h: (-h.chars, h.start))
    return hits
