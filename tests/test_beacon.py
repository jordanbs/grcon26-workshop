"""The Pico beacon, checked against the flowgraph it has to talk to.

The beacon and the receiver are two programs in two languages on two
boards, and the only thing holding them together is a handful of
constants that appear in both. So the first half of this file reads
those constants back out of `flowgraphs/m2k_ultrasonic_fsk.grc` and
refuses to let them drift.

The second half runs the beacon's own bits through the real receive
chain. That is the part worth having: it is the only evidence that the
preamble is long enough for symbol_sync to converge before the sync word
arrives, which is the one thing about a bursty beacon that the
continuously transmitting bench link never had to answer.

None of this touches a Pico. `main.py` is not importable here -- it
imports `machine` -- which is exactly why everything testable lives in
`beacon.py` instead.
"""

import ast
import json
import os
import re
import sys

import pytest

from test_grc_integration import needs_gnuradio, run_in_gr

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "booth", "pico"))

import beacon  # noqa: E402

MESSAGE = "GRC-4A7F"


@pytest.fixture(scope="module")
def grc(repo_root):
    with open(os.path.join(repo_root, "flowgraphs",
                           "m2k_ultrasonic_fsk.grc"), encoding="utf-8") as fh:
        return fh.read()


def variable(source, name):
    """One `variable` block's value, as Python.

    GRC writes YAML and quotes its scalars, so a number arrives as a
    string containing a number. Evaluating twice unwraps that without
    pulling PyYAML in for four lookups.
    """
    for chunk in source.split("\n- name: "):
        if chunk.startswith(name + "\n"):
            raw = re.search(r"value: (.*)", chunk).group(1).strip().rstrip("}")
            value = ast.literal_eval(raw)
            return ast.literal_eval(value) if isinstance(value, str) else value
    raise AssertionError("no variable %r in the flowgraph" % (name,))


def test_the_sync_word_is_the_flowgraphs_sync_word(grc):
    """Four bytes in two files. The receiver correlates against one."""
    assert list(beacon.SYNC) == variable(grc, "code_bytes")


def test_the_payload_length_is_the_flowgraphs_capacity(grc):
    """A short frame walks keep_m_in_n off the end of every later one."""
    assert beacon.CAPACITY == variable(grc, "msg_capacity")


def test_the_frame_is_the_length_the_receiver_strips_to(grc):
    """`frame_len` is an expression in the flowgraph, so check both halves."""
    assert "value: len(code_bytes) + msg_capacity" in grc
    assert (len(beacon.frame(MESSAGE))
            == len(variable(grc, "code_bytes"))
            + variable(grc, "msg_capacity"))


def test_the_tones_and_the_baud_rate_match(grc):
    assert beacon.BAUD == variable(grc, "baud")
    assert beacon.F0 == variable(grc, "f0")
    assert beacon.SPACING == variable(grc, "spacing")
    assert beacon.FMARK == variable(grc, "f0") + variable(grc, "spacing") / 2
    assert beacon.FSPACE == variable(grc, "f0") - variable(grc, "spacing") / 2


def test_a_short_flag_is_padded_and_a_long_one_is_refused():
    """Padding is silent; overflow is not. One is a choice, one is a bug."""
    assert beacon.payload("AB") == (65, 66, 32, 32, 32, 32, 32, 32)
    assert len(beacon.payload("")) == beacon.CAPACITY
    with pytest.raises(ValueError):
        beacon.payload("NINECHARS")
    with pytest.raises(ValueError):
        beacon.payload("café")


def test_bits_come_out_most_significant_first():
    """pack_k_bits_bb reassembles that way, so anything else scrambles."""
    assert beacon.bits([0x1A]) == [0, 0, 0, 1, 1, 0, 1, 0]
    assert beacon.bits([0xAA]) == [1, 0, 1, 0, 1, 0, 1, 0]


def test_the_burst_is_a_preamble_then_frames_then_one_more_sync_word():
    """The trailing sync word is what lets the last payload decode.

    Keep M in N keeps eight of every twelve bytes, and the aligned
    stream is payload-then-sync. Drop the last sync and the last
    payload never finishes its group of twelve.
    """
    burst = beacon.burst(MESSAGE, 3)
    head, tail = 8 * len(beacon.PREAMBLE), 8 * len(beacon.SYNC)
    assert len(burst) == head + 8 * 3 * 12 + tail
    assert burst[:head] == beacon.bits(beacon.PREAMBLE)
    assert burst[head:-tail] == beacon.bits(beacon.frame(MESSAGE) * 3)
    assert burst[-tail:] == beacon.bits(beacon.SYNC)
    assert beacon.burst_ms(MESSAGE, 3) == 1760


def test_the_burst_leaves_room_for_the_other_beacon():
    """Two beacons share the air by taking turns, which only works if a
    burst fits in half a period. main.py refuses to boot otherwise; this
    is the same arithmetic where it can be seen without a Pico."""
    assert beacon.burst_ms(MESSAGE, 3) <= 5000 // 2


@pytest.mark.parametrize("sysclk", [125000000, 150000000])
def test_the_pwm_lands_on_the_tones(sysclk):
    """The divider stays at 1, so the tone is quantized to sysclk/N.

    Both Picos land within 5 Hz. The demodulator's gain maps 300 Hz onto
    1.0, so 5 Hz is 1.7% of a full-scale eye and nothing has to care --
    but the number is worth pinning, because a future f0 might quantize
    somewhere far worse and nothing else would notice.
    """
    for want in (beacon.FMARK, beacon.FSPACE):
        got = beacon.pwm_freq(sysclk, beacon.pwm_top(sysclk, want))
        assert abs(got - want) < 5.0, (sysclk, want, got)


@needs_gnuradio
def test_the_beacons_burst_decodes_through_the_real_receive_chain():
    """One burst, from silence, into the chain the attendee is given.

    The skew is deliberately not a multiple of a bit: over the air the
    capture starts where it starts. Three frames go out and three come
    back, which also says the preamble converged the timing loop before
    the first sync word rather than during it.
    """
    bits = beacon.burst(MESSAGE, 3)
    payload = json.loads(run_in_gr('''
        import json, math, sys
        import numpy as np
        from gnuradio import gr, blocks, analog, digital
        from gnuradio import filter as gr_filter
        from gnuradio.filter import firdes

        RX, F0, DEV, BITLEN, DECIM = 1e6, 40755.0, 300.0, 5e-3, 200
        CODE = "00011010110011111111110000011101"
        CAPACITY, FRAME_LEN, SKEW = 8, 12, 1373

        bits = np.array(json.loads(sys.argv[1]), dtype=np.uint8)
        n = int(round(RX * BITLEN))
        f = np.where(np.repeat(bits, n) == 1, F0 + DEV, F0 - DEV)
        x = 0.14 * np.sin(2 * np.pi * np.cumsum(f) / RX)
        rng = np.random.default_rng(11)
        x = x + rng.normal(0, 0.14 / math.sqrt(2) / 10 ** 0.5, x.size)
        volts = np.concatenate([np.zeros(SKEW), x, np.zeros(n * 4)])

        tb = gr.top_block()
        rate = RX / DECIM
        out = blocks.vector_sink_b()
        tb.connect(blocks.vector_source_f(volts.tolist(), False),
                   gr_filter.freq_xlating_fir_filter_fcf(
                       DECIM, firdes.low_pass(1.0, RX, 600.0, 600.0), F0, RX),
                   analog.quadrature_demod_cf(rate / (2 * math.pi * DEV)),
                   digital.symbol_sync_ff(
                       digital.TED_ZERO_CROSSING, rate * BITLEN, 0.045, 1.0,
                       1.0, 1.5, 1, digital.constellation_bpsk().base(),
                       digital.IR_MMSE_8TAP, 128, []),
                   digital.binary_slicer_fb(),
                   digital.correlate_access_code_tag_bb(CODE, 0, "sync"),
                   blocks.tagged_stream_align(gr.sizeof_char, "sync"),
                   blocks.pack_k_bits_bb(8),
                   blocks.keep_m_in_n(gr.sizeof_char, CAPACITY, FRAME_LEN, 0),
                   out)
        tb.run()
        print(json.dumps(list(out.data())))
    ''', json.dumps(bits)))

    got = bytes(payload)
    assert len(got) >= 3 * beacon.CAPACITY, got
    frames = [got[i:i + beacon.CAPACITY]
              for i in range(0, 3 * beacon.CAPACITY, beacon.CAPACITY)]
    assert all(f == MESSAGE.encode() for f in frames), frames
