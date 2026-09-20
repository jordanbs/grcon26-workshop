"""Everything the beacon needs to work out before it touches a pin.

Split from main.py so it can be tested. A Pico runs this under
MicroPython; pytest runs the same file under CPython and checks it
against `flowgraphs/m2k_ultrasonic_fsk.grc`, which is the flowgraph the
attendee is handed. Nothing here imports `machine` and nothing here
knows what a GPIO is.

The frame is the flowgraph's frame: four sync bytes, then eight payload
bytes. Keeping the two in step is not left to whoever reads this --
tests/test_beacon.py pulls both numbers out of the .grc and fails if
they drift apart.
"""

# 0x1ACFFC1D, the CCSDS attached sync marker, and the flowgraph's
# code_bytes. The receiver correlates against it to find the byte
# boundary, so it has to be these four bytes in this order.
SYNC = (0x1A, 0xCF, 0xFC, 0x1D)

# msg_capacity in the flowgraph. Every frame is this long after the sync
# word, which is what lets keep_m_in_n strip the next frame's sync bytes.
CAPACITY = 8

# Alternating ones and zeros give the zero-crossing timing detector a
# transition on every bit, which is the fastest way for it to converge.
# The bench link never needed a preamble because it transmits forever and
# symbol_sync can settle whenever it likes. A burst starts from silence:
# at a loop bandwidth of 0.045 the loop takes roughly twenty symbols, so
# thirty-two bits of preamble arrive before the sync word does. The
# receiver throws all of it away for free, because
# correlate_access_code_tag ignores everything until the marker.
PREAMBLE = (0xAA,) * 4

# 200 baud, from the flowgraph's `baud`.
BAUD = 200

# The measured resonance and the deviation either side of it. Both come
# off bench/ultrasonic_sweep.py on 2026-09-09, not off the datasheet.
F0 = 40755.0
SPACING = 600.0
FSPACE = F0 - SPACING / 2.0
FMARK = F0 + SPACING / 2.0


def payload(message):
    """The message as exactly CAPACITY bytes, space-padded on the right.

    A message that is too long is a setup mistake worth catching at boot
    rather than discovering from a truncated capture at the booth, so
    this refuses rather than trimming.
    """
    if len(message) > CAPACITY:
        raise ValueError("message is %d characters; the frame carries %d"
                         % (len(message), CAPACITY))
    for c in message:
        if not 0x20 <= ord(c) <= 0x7E:
            raise ValueError("message has a character the frame "
                             "cannot carry: %r" % (c,))
    return tuple(ord(c) for c in message) + (0x20,) * (CAPACITY - len(message))


def frame(message):
    """Sync word, then payload. The twelve bytes that go on the air."""
    return SYNC + payload(message)


def bits(values):
    """Bytes to bits, most significant first.

    That order is not a preference. pack_k_bits_bb at the far end
    reassembles most significant first, so anything else comes back as
    eight bits of the right values in the wrong places.
    """
    out = []
    for v in values:
        for shift in (7, 6, 5, 4, 3, 2, 1, 0):
            out.append((v >> shift) & 1)
    return out


def burst(message, frames=3):
    """One transmission: preamble, the frame `frames` times, sync again.

    The preamble goes at the front and not before every frame. Once the
    timing loop has locked it stays locked, so what the repeats give you
    is more chances at the correlation, not more chances at the clock.

    The sync word on the end is not decoration. Tagged Stream Align
    hands on a stream that starts at the first payload byte, so what
    Keep M in N sees is payload, sync, payload, sync -- and it keeps the
    first eight of every twelve. The last payload in a burst needs the
    four bytes after it to exist before it completes a group of twelve.
    Without them the receiver decodes two frames out of three, which
    looks like a marginal link and is not one.
    """
    return bits(PREAMBLE) + bits(frame(message) * frames) + bits(SYNC)


def burst_ms(message, frames=3):
    """How long that takes on the air, in milliseconds."""
    return 1000 * len(burst(message, frames)) // BAUD


def pwm_top(sysclk, freq):
    """The TOP register value for a square wave at `freq`.

    The slice counts 0 to TOP inclusive, so the period is TOP+1 clocks
    and the divider stays at 1. Which means the frequency is quantized
    to sysclk/N -- at 125 MHz that puts the mark 4.1 Hz low and the
    space 1.9 Hz low. Against a 600 Hz deviation the demodulator cannot
    tell, but main.py prints what it achieved anyway so nobody has to
    take that on trust.
    """
    top = int(round(sysclk / float(freq))) - 1
    if not 1 <= top <= 65534:
        raise ValueError("%g Hz needs TOP %d, which the slice cannot hold"
                         % (freq, top))
    return top


def pwm_freq(sysclk, top):
    """What a slice with that TOP actually puts out."""
    return sysclk / float(top + 1)
