"""Frame on the gap between one sync marker and the next.

The decision behind the **Sync-to-Sync Framer** block, in a module that
imports nothing, so it is tested with no GNU Radio present.

**Why not Keep M in N.** It is handed an alignment once, by Tagged
Stream Align, and from then on it counts: every N items it keeps the
first M, forever. That is exact while the transmitter never stops,
which is why a continuous loopback is perfectly happy with it. A
transmitter that bursts and then goes quiet breaks it on the second
burst -- the counter keeps counting through the silence, the silence is
not a whole number of frames, and nothing downstream ever re-aligns. The
error is permanent rather than transient, and it presents as bit-perfect
garbage, which is indistinguishable from bad range.

This throws the counter away and uses the only thing that is true every
time: the correlator tags the first bit after each sync marker, so the
payload is whatever lies between one tag and the next, less the sync
word that closes it.

That has a property the counter never had -- **it never needs to know
how long the payload is.** The receiving side stops having to be told a
capacity, so one flowgraph decodes an eight-byte frame and a
thirty-two-byte frame with no change at all.

A transmitter using this needs a trailing sync word after its last
frame, or that frame has no closing delimiter and is dropped.
"""

# Why a span is thrown away. Kept as a tally rather than a log: at 200
# baud the rejections are the normal shape of a bursty link, and a line
# per rejection would bury the frames.
REASONS = ("emitted", "over_max", "ragged", "runt", "join")


def bits_of(byte):
    """A byte as eight bits, most significant first."""
    return [(byte >> i) & 1 for i in range(7, -1, -1)]


class SyncFramer(object):
    """Spans between sync tags, in; whole payloads, out.

    Feed it `push(bits, tags)` where `tags` are bit positions, relative
    to the start of `bits`, at which a sync marker was found. Each call
    returns the payloads that completed during it, as `bytes`.
    """

    def __init__(self, sync_bits=32, min_bits=64, max_bits=1024,
                 preamble_byte=0xAA):
        self.sync_bits = int(sync_bits)
        self.min_bits = int(min_bits)
        self.max_bits = int(max_bits)
        # Negative turns the join check off. Zero cannot mean that: a
        # transmitter may legitimately idle at 0x00, and more to the
        # point a payload is allowed to END in a zero byte -- treating
        # 0 as "disabled" would be indistinguishable from treating it
        # as "reject anything ending in 0x00", which silently eats real
        # frames on a binary payload.
        self.preamble_byte = int(preamble_byte)
        self._pre = (bits_of(self.preamble_byte)
                     if self.preamble_byte >= 0 else [])
        self._open = False      # have we seen a first tag yet
        self._bits = []         # bits since that tag
        self.stats = dict((reason, 0) for reason in REASONS)

    # ------------------------------------------------------------------
    def _close(self):
        """Judge the buffered span and return its payload, or None."""
        span = self._bits
        if len(span) > self.max_bits:
            # Almost always the gap between two bursts: the previous
            # burst's trailing sync to the next burst's first. Dropping
            # it is the point -- it is silence, not a frame.
            self.stats["over_max"] += 1
            return None
        payload = span[:len(span) - self.sync_bits]
        if len(payload) < self.min_bits:
            # The join between two back-to-back bursts, which holds the
            # preamble and not a frame. A floor, deliberately, rather
            # than the frame length: the block still never has to be
            # told how big a payload is.
            self.stats["runt"] += 1
            return None
        if self._pre and payload[-8:] == self._pre:
            # The span crosses a burst boundary: silence, then the
            # preamble, then the sync that closed it. The preamble is a
            # protocol constant exactly as the sync word is, so
            # recognising it costs no knowledge of the payload's length.
            self.stats["join"] += 1
            return None
        if len(payload) % 8:
            # A real frame is a whole number of bytes. Anything else is
            # a correlator hit on noise.
            self.stats["ragged"] += 1
            return None
        out = bytearray(len(payload) // 8)
        for i, bit in enumerate(payload):
            if bit:
                out[i // 8] |= 0x80 >> (i % 8)
        self.stats["emitted"] += 1
        return bytes(out)

    # ------------------------------------------------------------------
    def push(self, bits, tags=()):
        """Absorb a chunk of bits; return the payloads it completed."""
        bits = [int(b) & 1 for b in bits]
        done = []
        pos = 0
        for cut in sorted(int(t) for t in tags):
            if self._open:
                self._bits.extend(bits[pos:cut])
                payload = self._close()
                if payload is not None:
                    done.append(payload)
            self._open = True
            self._bits = []
            pos = cut

        if self._open:
            self._bits.extend(bits[pos:])
            if len(self._bits) > self.max_bits:
                # Runaway: a sync was missed. Drop it now rather than
                # grow without bound waiting for a delimiter.
                self._open = False
                self._bits = []
                self.stats["over_max"] += 1
        return done
