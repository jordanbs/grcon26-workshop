"""Finding text in a stream that never said where a byte begins.

These run in the ordinary test interpreter, not the borrowed gnuradio
one, because `m2k_blocks.ascii_scan` imports nothing. That is the whole
reason it is a separate module from the block that wraps it.

The block this backs is what a player uses at the booth: the beacon
sends no sync word, so `Pack K Bits` has no boundary to be told about
and picks the arbitrary one. Seven times in eight that is mojibake, and
mojibake looks like bad range rather than like bad framing -- which
sends somebody off to move the transducer instead of shifting the
offset by one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks.ascii_scan import (MIN_CHARS, pack, runs,  # noqa: E402
                                   scan)

PAYLOAD = b"A=00000 B=XXXXXX C=example"


def bits_of(data):
    """A bytes object as a bit list, most significant bit first."""
    out = []
    for byte in bytearray(data):
        out.extend((byte >> i) & 1 for i in range(7, -1, -1))
    return out


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------

def test_offset_zero_is_the_bytes_that_went_in():
    assert pack(bits_of(PAYLOAD)) == PAYLOAD


def test_a_ragged_tail_is_dropped_not_padded():
    """Seven spare bits are not a byte, and padding them invents data."""
    assert pack(bits_of(b"AB") + [1] * 7) == b"AB"


def test_inverting_flips_every_bit():
    packed = pack(bits_of(b"\x00\xff"), invert=True)
    assert packed == b"\xff\x00"


def test_an_offset_past_the_end_gives_nothing_rather_than_raising():
    assert pack([1, 0, 1], offset=8) == b""


@pytest.mark.parametrize("offset", range(8))
def test_the_payload_is_recoverable_at_whatever_offset_it_landed_on(offset):
    """The whole point: shift the stream and the text is still in there,
    it has just moved to a different one of the eight packings."""
    stream = [0] * offset + bits_of(PAYLOAD)
    assert pack(stream, offset) == PAYLOAD


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def test_a_run_shorter_than_the_floor_is_not_reported():
    assert runs(b"\x00" + b"hello" + b"\x00", min_chars=16) == []


def test_a_run_at_the_very_end_still_counts():
    """An off-by-one here loses the last burst in a capture."""
    found = runs(b"\x00" + b"A" * 20, min_chars=16)
    assert [text for _, text in found] == [b"A" * 20]


def test_the_index_is_where_the_run_starts():
    found = runs(b"\x00\x00" + b"B" * 18, min_chars=16)
    assert found[0][0] == 2


def test_space_and_tilde_are_inside_the_printable_range():
    """The payload has spaces in it, so an exclusive bound would cut
    every frame into three."""
    assert runs(b" " * 16, min_chars=16)
    assert runs(b"~" * 16, min_chars=16)
    assert runs(b"\x7f" * 16, min_chars=16) == []


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def test_the_payload_is_found_and_its_offset_reported():
    stream = [1, 0, 1] + bits_of(PAYLOAD * 2)
    hit = scan(stream)[0]
    assert PAYLOAD in hit.text
    assert hit.offset == 3
    assert not hit.inverted


def test_an_inverted_stream_is_found_and_flagged():
    """A demodulator that hands back the two tones the wrong way up."""
    stream = [b ^ 1 for b in bits_of(PAYLOAD * 2)]
    hit = scan(stream)[0]
    assert PAYLOAD in hit.text
    assert hit.inverted


def test_inversion_can_be_turned_off():
    stream = [b ^ 1 for b in bits_of(PAYLOAD * 2)]
    assert scan(stream, try_inverted=False) == []


def test_positions_are_absolute_so_windows_can_be_deduplicated():
    """The wrapper drops a hit it has already reported by position, so a
    hit's position has to be in the stream, not in the window."""
    stream = bits_of(PAYLOAD * 2)
    hit = scan(stream, base=10_000)[0]
    assert hit.start >= 10_000
    assert hit.end == hit.start + 8 * hit.chars


def test_longest_first_so_the_real_payload_leads():
    stream = bits_of(b"\x00" + b"x" * 40 + b"\x00" + b"y" * 18 + b"\x00")
    lengths = [h.chars for h in scan(stream)]
    assert lengths == sorted(lengths, reverse=True)


def test_noise_alone_stays_quiet_at_the_default_floor():
    """The property worth having: silence here means silence on the air,
    not a wrong guess about framing.

    Sixteen printable bytes in a row is about one in five million, so a
    fixed-seed noise run of this length reporting nothing is the
    expected outcome rather than a lucky one.
    """
    import random
    rng = random.Random(20260920)
    noise = [rng.randrange(2) for _ in range(200_000)]
    assert scan(noise, min_chars=MIN_CHARS) == []


def test_eight_characters_is_the_tempting_wrong_floor():
    """Why the default is not one byte. Same noise, floor at eight, and
    it chatters -- which is the argument for sixteen, made as a test
    rather than as a comment."""
    import random
    rng = random.Random(20260920)
    noise = [rng.randrange(2) for _ in range(200_000)]
    assert len(scan(noise, min_chars=8)) > 20


def test_the_reported_line_carries_offset_and_text():
    hit = scan(bits_of(PAYLOAD * 2))[0]
    line = hit.line()
    assert "offset 0" in line
    assert "A=00000" in line
    assert "INVERTED" not in line
