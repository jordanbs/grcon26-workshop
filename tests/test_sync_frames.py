"""Framing on the gap between one sync marker and the next.

Runs in the ordinary test interpreter: `m2k_blocks.sync_frames` imports
nothing.

The frames here are built from the sync-word rules directly rather than
imported from anything that generates them, so the framer is checked
against an independent construction rather than against its own mirror
image.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks.sync_frames import SyncFramer, bits_of   # noqa: E402

# 0x1ACFFC1D, the CCSDS attached sync marker. A published constant, not
# a secret -- it marks a byte boundary and nothing else.
SYNC = (0x1A, 0xCF, 0xFC, 0x1D)
PREAMBLE = (0xAA,) * 4

SHORT = b"GRC-4A7F"                              # 8 bytes
LONG = b"A=00000 B=XXXXXX C=example".ljust(32)   # 32 bytes


def bits(data):
    out = []
    for byte in bytearray(data):
        out.extend(bits_of(byte))
    return out


def burst(payload, frames=3):
    """Preamble, then frames, then the trailing sync that closes the last.

    The trailing marker is not decoration: without it the final payload
    has no closing delimiter and is dropped.
    """
    body = b"".join(bytes(bytearray(SYNC)) + payload for _ in range(frames))
    return bits(bytearray(PREAMBLE)) + bits(body) + bits(bytearray(SYNC))


def tags_in(stream):
    """Where Correlate Access Code - Tag would tag: the bit AFTER a sync."""
    marker = bits(bytearray(SYNC))
    n = len(marker)
    return [i + n for i in range(len(stream) - n + 1)
            if stream[i:i + n] == marker]


def run(stream, framer=None):
    framer = framer or SyncFramer()
    return framer.push(stream, tags_in(stream)), framer


# ---------------------------------------------------------------------------
# The frames come back
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [SHORT, LONG])
def test_every_frame_in_a_burst_is_recovered(payload):
    got, framer = run(burst(payload))
    assert got == [payload] * 3
    assert framer.stats["emitted"] == 3


def test_the_last_frame_needs_the_trailing_sync():
    """Drop it and the final payload has no closing delimiter."""
    stream = burst(SHORT)
    without = stream[:-8 * len(SYNC)]
    got, _ = run(without)
    assert got == [SHORT] * 2


def test_one_framer_decodes_both_capacities_untouched():
    """The property Keep M in N never had. The receiving side is never
    told how long a payload is, so the same instance handles an
    eight-byte frame and a thirty-two-byte one in the same run."""
    framer = SyncFramer()
    got, _ = run(burst(SHORT, 2) + burst(LONG, 2), framer)
    assert got == [SHORT, SHORT, LONG, LONG]


# ---------------------------------------------------------------------------
# The gap, which is the whole reason this block exists
# ---------------------------------------------------------------------------

def test_ragged_gaps_between_bursts_do_not_shift_the_framing():
    """What Keep M in N gets wrong.

    It counts: every N items it keeps the first M, forever. A gap that
    is not a whole number of frames puts it permanently out of phase and
    it never re-aligns -- bit-perfect garbage, which reads as bad range.
    Here the gaps are deliberately ragged and every payload still comes
    back whole.
    """
    rng = random.Random(7)
    stream = []
    for _ in range(3):
        stream += burst(SHORT)
        stream += [rng.randrange(2) for _ in range(rng.randrange(500, 900))]
    got, framer = run(stream)
    assert got == [SHORT] * 9
    assert framer.stats["emitted"] == 9


def test_the_span_across_a_gap_is_thrown_away_not_emitted():
    got, framer = run(burst(SHORT) + [0] * 4000 + burst(SHORT))
    assert got == [SHORT] * 6
    assert framer.stats["over_max"] >= 1


def test_back_to_back_bursts_do_not_emit_the_join():
    """No silence between, so the span from one burst's trailing sync to
    the next one's first is short rather than long -- it holds the
    preamble and nothing else.

    At the defaults the length floor catches it before the preamble
    check gets a look: the span is 32 bits of preamble plus the 32-bit
    sync that closed it, leaving a 32-bit payload against a 64-bit
    minimum. Either way it is refused, which is what matters here.
    """
    got, framer = run(burst(SHORT) + burst(SHORT))
    assert got == [SHORT] * 6
    assert framer.stats["runt"] + framer.stats["join"] >= 1


def test_the_preamble_check_catches_a_join_the_length_floor_misses():
    """Why the preamble check exists at all.

    Lower the floor -- or lengthen the preamble -- and the join span is
    long enough to pass for a frame. Then the only thing distinguishing
    it is that it ends in the byte the transmitter idles with, and
    recognising that still costs no knowledge of how long a payload is.
    """
    framer = SyncFramer(min_bits=8)
    stream = burst(SHORT) + burst(SHORT)
    got = framer.push(stream, tags_in(stream))
    assert got == [SHORT] * 6
    assert framer.stats["join"] >= 1


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------

def test_a_span_that_is_not_whole_bytes_is_refused():
    """A correlator hit on noise. A real frame is a whole number of
    bytes, so anything else did not come from the transmitter."""
    framer = SyncFramer()
    marker = bits(bytearray(SYNC))
    stream = marker + bits(SHORT) + [1, 0, 1] + marker
    got = framer.push(stream, tags_in(stream))
    assert got == []
    assert framer.stats["ragged"] == 1


def test_nothing_is_emitted_before_the_first_tag():
    """A capture that starts mid-frame has lost an unknown number of
    bits, and the bits that remain would still make a plausible,
    wrong payload."""
    framer = SyncFramer()
    assert framer.push(bits(b"not a frame at all"), []) == []
    assert framer.stats["emitted"] == 0


def test_a_missed_sync_does_not_grow_the_buffer_without_bound():
    """A runaway span is dropped rather than accumulated -- an hour of
    noise must not become an hour of RAM."""
    framer = SyncFramer(max_bits=512)
    marker = bits(bytearray(SYNC))
    framer.push(marker + [0] * 20_000, tags_in(marker + [0] * 20_000))
    assert len(framer._bits) <= 512
    assert framer.stats["over_max"] >= 1


def test_a_negative_preamble_byte_turns_the_join_check_off():
    """There has to be a way to say "no idle byte", and 0 is not it.

    A transmitter may legitimately idle at 0x00, and a payload is
    allowed to END in a zero byte. If 0 meant "disabled" it would be
    indistinguishable from "reject anything ending in 0x00", which eats
    real frames on a binary payload without saying so.
    """
    assert SyncFramer(preamble_byte=-1)._pre == []
    assert SyncFramer(preamble_byte=0)._pre == [0] * 8


def test_a_payload_ending_in_the_idle_byte_survives_when_the_check_is_off():
    framer = SyncFramer(preamble_byte=-1)
    payload = b"ABCDEFG\xaa"          # 8 bytes, to clear the 64-bit floor
    marker = bits(bytearray(SYNC))
    stream = marker + bits(payload) + marker
    assert framer.push(stream, tags_in(stream)) == [payload]


def test_chunk_boundaries_do_not_change_the_answer():
    """work() is handed whatever size buffer GNU Radio feels like, so a
    frame split across two calls has to survive."""
    # Idle after the burst, because a receiver does not stop when the
    # transmitter does. Without it the final sync tag lands exactly at
    # the end of the stream, where GNU Radio would hand it to the next
    # work() call and this loop has no next chunk to put it in.
    stream = burst(LONG) + [0] * 64
    tags = tags_in(stream)
    whole, _ = run(stream)

    framer = SyncFramer()
    got = []
    step = 137                      # deliberately not a frame multiple
    for start in range(0, len(stream), step):
        chunk = stream[start:start + step]
        local = [t - start for t in tags if start <= t < start + len(chunk)]
        got.extend(framer.push(chunk, local))
    assert got == whole
