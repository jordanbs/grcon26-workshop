"""The ultrasonic FSK link end to end: modulate, transmit, capture, decode.

Four questions, in the order they have to be answered:

    Are the two tones where we say they are?
    Does a non-cyclic stream hold at 750 kS/s, or does the DAC starve?
    Does each bit last 5 ms on the air, or does it stretch?
    Does the text that went in come back out?

ECE448's fsk_project.grc is the source. Its live path is file-to-file:
unpack_k_bits(8) -> repeat -> scale -> offset -> vco_f, and the scale and
offset are what map a bit onto a tone. That arithmetic is copied exactly.
What is NOT copied is anything that assumed one sample rate for both
directions -- see below.

    W1 -> TX +, TX - -> GND
    RX + -> 1+, RX - -> GND, 1- -> GND

Tones come from the measured resonance, not from 40 kHz nominal. The
pair peaks at 40.755 kHz with a -6 dB width of 1023 Hz, so the mark and
space sit at f0 +/- 300 and the whole signal fits, barely: 200 baud at
600 Hz spacing has a Carson bandwidth near 1000 Hz.

The original's `repeat` is used twice, once to interpolate bits up to the
sample rate and once as keep_one_in_n on the way back down. That only
works while both directions share a rate. Here they do not -- 750 kS/s
out, 1 MS/s back -- so the transmit figure is tx_repeat, the receive one
is derived from the decimated rate, and the two are never the same
number. 3750 samples per bit going out, 25 coming back.

Two more things the original could take for granted and this cannot.
Its filter decimated by 1 because 48 kS/s was already close to the
signal; capturing at 1 MS/s against a 1023 Hz channel means decimating
hard first, or the demodulator spends all its time on empty spectrum.
And its file-to-file path had bit 0 at sample 0, so keep_one_in_n was
enough. Over the air the capture starts wherever it starts, so the
sampling phase is found from the eye and the byte boundary from a
correlation against the known message. That correlation is also what
produces the error count -- see align().

The receive chain is real GNU Radio blocks run offline on the capture,
not a hand-written detector, because these parameters are what goes
into the participant-facing .grc. A number measured with something else
would have to be re-derived there.

Non-cyclic is the point of the streaming test, and it changes what a
warning means. A CYCLIC sink pushes once and every later push returns
EBUSY, which is normal and noisy. A NON-CYCLIC sink pushing every buffer
should never see EBUSY, so here any "Unable to push buffer" is a real
underrun. The script captures stderr and counts them rather than letting
them scroll past.

Run from the repo root, with a gnuradio interpreter:

    python3 bench/ultrasonic_fsk.py
    python3 bench/ultrasonic_fsk.py --message HELLO --seconds 2.0
    python3 bench/ultrasonic_fsk.py --amplitude 2.0
    python3 bench/ultrasonic_fsk.py --decim 100
"""
import sys, os, math, time, argparse, tempfile
sys.path.insert(0, "gr-m2k")
import numpy as np
from gnuradio import gr, blocks, analog
from gnuradio import filter as gr_filter
from gnuradio.filter import firdes
from m2k_blocks.analog_sink import analog_sink
from m2k_blocks.analog_source import analog_source
from m2k_blocks.m2k_scale import volts_per_count

URI = "ip:192.168.2.1"
TX_RATE, RX_RATE = 750000, 1000000
RANGE = "high"

# Measured on the bench 2026-09-09, not the 40 kHz on the part.
F0 = 40755.0
SPACING = 600.0                      # mark minus space, the ECE448 convention
FSPACE, FMARK = F0 - SPACING / 2.0, F0 + SPACING / 2.0
FMAX = FMARK                         # the VCO's full-scale frequency

BITLEN = 5e-3                        # 200 baud, unchanged from ECE448
TX_BUF, RX_BUF = 65536, 16384

# Long enough to resolve 600 Hz (needs 1.67 ms), short enough to sit
# inside a 5 ms bit. 2 ms is the compromise; this is a tone check, not a
# demodulator.
WIN, STEP = 2000, 500

# How far around each expected tone to look, and how far off it may land.
# Non-cyclic streaming has no buffer-periodicity grid, so the VCO should
# produce the frequency asked for; the slack is FFT resolution and the
# broadening from a tone that is only present half the time.
TONE_SPAN, TONE_TOL = 200.0, 20.0

# 1 MS/s down to 5 kS/s, which is 25 samples per bit -- plenty of eye to
# find a phase in, and 2.5 kHz of Nyquist for a signal that needs 0.5.
RX_DECIM = 200

# The filter is designed at the INPUT rate; firdes knows nothing about
# the decimation that follows. +/-600 Hz passband covers the deviation
# and the first sidebands, and a transition band as wide as the passband
# keeps the tap count near 5500 instead of five figures.
LP_CUTOFF, LP_TRANS = 600.0, 600.0


class _graph(gr.top_block):
    def __init__(self, message, amplitude, tx_repeat):
        gr.top_block.__init__(self, "ultrasonic_fsk_tx")

        # Bits out of bytes, each held for one bit period, then mapped
        # onto [fspace/fmax, fmark/fmax] so the VCO lands on the tones.
        self.src = blocks.vector_source_b(list(message), True)
        unpack = blocks.unpack_k_bits_bb(8)
        hold = blocks.repeat(gr.sizeof_char, tx_repeat)
        to_float = blocks.uchar_to_float()
        scale = blocks.multiply_const_ff((FMARK - FSPACE) / FMAX)
        offset = blocks.add_const_ff(FSPACE / FMAX)
        # sensitivity 2*pi*fmax makes the output frequency fmax * input.
        vco = blocks.vco_f(TX_RATE, 2.0 * math.pi * FMAX, amplitude)
        self.gen = analog_sink(URI, output="w1", sample_rate=TX_RATE,
                               units="volts", buffer_size=TX_BUF,
                               cyclic=False)
        self.connect(self.src, unpack, hold, to_float, scale, offset, vco,
                     self.gen)
        self._hold = [unpack, hold, to_float, scale, offset, vco]

        self.scope = analog_source(URI, ch1_enabled=True, ch2_enabled=True,
                                   sample_rate=RX_RATE,
                                   ch1_range=RANGE, ch2_range=RANGE,
                                   buffer_size=RX_BUF, units="counts",
                                   trigger_source="off")
        self.rx = blocks.vector_sink_s()
        self.other = blocks.vector_sink_s()
        self.connect((self.scope, 0), self.rx)
        self.connect((self.scope, 1), self.other)


class _demod(gr.top_block):
    """The receive chain, run offline on the capture.

    Finite source, no IIO blocks, so run() is safe here -- the rule
    against it applies to graphs holding an m2k config keep-alive, which
    never finishes. This one does.
    """

    def __init__(self, volts, decim):
        gr.top_block.__init__(self, "ultrasonic_fsk_rx")
        self.taps = firdes.low_pass(1.0, RX_RATE, LP_CUTOFF, LP_TRANS)
        self.rate = RX_RATE / float(decim)
        # Mixing to baseband at f0 puts space at -300 and mark at +300,
        # so the demod output is symmetric about zero and the slicer
        # threshold is 0 rather than something that has to be tuned.
        self.gain = self.rate / (2.0 * math.pi * (SPACING / 2.0))
        src = blocks.vector_source_f(volts.tolist(), False)
        xlate = gr_filter.freq_xlating_fir_filter_fcf(decim, self.taps,
                                                      F0, RX_RATE)
        qd = analog.quadrature_demod_cf(self.gain)
        self.out = blocks.vector_sink_f()
        self.connect(src, xlate, qd, self.out)


def eye(d, sps):
    """Pick the sampling phase: the one whose samples sit furthest from 0.

    Nothing about the message goes into this. Choosing the phase that
    decodes best would be fitting to the answer, and would report a
    clean link on a marginal one.
    """
    best, opening = 0, -1.0
    for p in range(int(round(sps))):
        idx = (p + np.arange(int((len(d) - p) / sps)) * sps).astype(int)
        if not len(idx):
            continue
        m = float(np.abs(d[idx]).mean())
        if m > opening:
            best, opening = p, m
    return best, opening


def align(recovered, known):
    """Best cyclic offset of the recovered bits against what was sent.

    The transmitter repeats the message forever and the capture starts
    wherever it starts, so the receiver has no byte boundary of its own.
    Both polarities are tried: a swapped mark and space decodes to
    nonsense but is a wiring answer, not a demodulator one, so it is
    worth naming rather than hiding in the error count.
    """
    n = len(known)
    i = np.arange(len(recovered))
    best = None
    for invert in (False, True):
        bits = (1 - recovered) if invert else recovered
        for off in range(n):
            errors = int(np.count_nonzero(bits != known[(i + off) % n]))
            if best is None or errors < best[0]:
                best = (errors, off, invert)
    return best


def to_text(bits, offset, period):
    """Pack the recovered bits into bytes at the alignment just found."""
    start = (-offset) % period
    usable = bits[start:]
    usable = usable[:len(usable) // 8 * 8]
    if not len(usable):
        return ""
    return "".join(chr(b) if 32 <= b < 127 else "."
                   for b in np.packbits(usable.astype(np.uint8)))


def run(message, amplitude, tx_repeat, seconds):
    """Run the graph with stderr diverted, so underruns can be counted."""
    tb = _graph(message, amplitude, tx_repeat)
    saved, spill = os.dup(2), tempfile.TemporaryFile(mode="w+b")
    os.dup2(spill.fileno(), 2)
    try:
        tb.start()
        time.sleep(0.3)
        tb.rx.reset()
        time.sleep(seconds)
        tb.stop(); tb.wait()
    finally:
        os.dup2(saved, 2); os.close(saved)
    spill.seek(0)
    noise = spill.read().decode("utf-8", "replace")
    spill.close()
    return list(tb.rx.data()), noise


def tracks(volts):
    """Coherent magnitude at each tone, in sliding windows."""
    n = np.arange(WIN)
    refs = [np.exp(-2j * math.pi * f * n / RX_RATE) for f in (FSPACE, FMARK)]
    starts = np.arange(0, len(volts) - WIN, STEP)
    out = []
    for ref in refs:
        out.append(np.array([2.0 * abs(np.vdot(ref, volts[i:i + WIN])) / WIN
                             for i in starts]))
    return out[0], out[1], starts / float(RX_RATE)


def runs(mark, space, times):
    """Dwell length of each symbol, in ms.

    Measured from the start of one run to the start of the next, not from
    the first window of a run to its last -- the latter is short by one
    STEP every time, which reads as a 4 ms bit and looks like an underrun.

    Using only the transitions drops the first and last runs, which is
    what we want: the capture truncates both.
    """
    symbol = mark > space
    edges = np.flatnonzero(np.diff(symbol)) + 1
    if len(edges) < 2:
        return []
    return [(times[edges[i + 1]] - times[edges[i]]) * 1e3
            for i in range(len(edges) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", default="GRCON26 ULTRASONIC")
    ap.add_argument("--amplitude", type=float, default=4.0,
                    help="drive amplitude in volts (default 4.0)")
    # 2 s, not 1: the decoder starts at the first message boundary and
    # may throw away most of a period getting there, so a 720 ms
    # message needs about 1.5 s of capture to be sure of one whole copy.
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--decim", type=int, default=RX_DECIM,
                    help="receive decimation, 1 MS/s divided by this "
                         "(default %d)" % RX_DECIM)
    args = ap.parse_args()

    if not 0.0 < args.amplitude <= 5.0:
        ap.error("amplitude must be within 0-5 V; W1 cannot swing past +/-5 V")

    message = args.message.encode()
    tx_repeat = int(TX_RATE * BITLEN)
    vpc = volts_per_count(RANGE, RX_RATE)

    print()
    print("  message   %r  (%d bytes, %d bits, %.0f ms per pass)"
          % (args.message, len(message), len(message) * 8,
             len(message) * 8 * BITLEN * 1e3))
    print("  tones     space %.1f Hz   mark %.1f Hz   spacing %.0f Hz"
          % (FSPACE, FMARK, SPACING))
    print("  rates     tx %d S/s (%d samples/bit)   rx %d S/s"
          % (TX_RATE, tx_repeat, RX_RATE))
    print("  drive     %.1f V, non-cyclic, %d-sample buffers"
          % (args.amplitude, TX_BUF))
    print()

    counts, noise = run(message, args.amplitude, tx_repeat, args.seconds)
    if not counts:
        print("  Captured nothing. Is the board at %s?" % URI)
        return 1

    x = np.asarray(counts, dtype=np.float64)
    peak = int(np.max(np.abs(x)))
    x = (x - x.mean()) * vpc

    # 1. Underruns. Non-cyclic, so every one of these is real.
    underruns = noise.count("Unable to push buffer")
    print("  underruns          %d %s"
          % (underruns, "" if underruns == 0 else "<- the DAC starved"))

    # 2. Where the energy actually is.
    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x * window)) * 2.0 / window.sum()
    freqs = np.fft.rfftfreq(len(x), 1.0 / RX_RATE)
    print("  capture            %.3f s, %d samples, peak %d counts%s"
          % (len(counts) / float(RX_RATE), len(counts), peak,
             "  CLIPPED" if peak >= 1950 else ""))
    print()
    # Search around each tone separately. Taking the two strongest lines
    # instead finds two adjacent bins on whichever tone is louder, and
    # reports the other one as 600 Hz off -- an artifact of the search,
    # not of the transmitter.
    print("  tone lines (strongest bin within +/-%.0f Hz of each)" % TONE_SPAN)
    tones_ok = True
    for want in (FSPACE, FMARK):
        near = np.abs(freqs - want) <= TONE_SPAN
        got = freqs[near][np.argmax(spectrum[near])]
        level = spectrum[near].max()
        off = got - want
        good = abs(off) <= TONE_TOL
        tones_ok = tones_ok and good
        print("    %9.1f Hz   %8.3f mV     want %.1f  (%+.1f Hz)%s"
              % (got, level * 1e3, want, off, "" if good else "   OFF"))
    band = (freqs > 30000) & (freqs < 55000)
    loudest = freqs[band][np.argmax(spectrum[band])]
    print("    strongest line in 30-55 kHz is %.1f Hz -- %s"
          % (loudest, "a tone" if min(abs(loudest - FSPACE),
                                      abs(loudest - FMARK)) <= TONE_SPAN
             else "NOT one of the tones, something else is louder"))

    # 3. Bit timing. A starved DAC stretches a bit; a healthy one does not.
    space_t, mark_t, times = tracks(x)
    lengths = runs(mark_t, space_t, times)
    print()
    if len(lengths) < 4:
        print("  Too few transitions to time. Is the transmitter running?")
        return 1
    units = np.array(lengths) / (BITLEN * 1e3)
    err = np.abs(units - np.round(units))
    print("  symbol dwell       %d runs, %.2f-%.2f ms"
          % (len(lengths), min(lengths), max(lengths)))
    print("  as bit periods     %.3f-%.3f, worst deviation %.3f of a bit"
          % (units.min(), units.max(), err.max()))
    timing_ok = err.max() < 0.25

    # 4. Demodulate and read the message back.
    rx = _demod(x, args.decim)
    rx.run()
    d = np.asarray(rx.out.data(), dtype=np.float64)
    sps = rx.rate * BITLEN
    print()
    print("  receiver           decim %d -> %.0f S/s, %.1f samples/bit"
          % (args.decim, rx.rate, sps))
    print("                     %d taps at %.0f Hz cutoff, quad gain %.3f"
          % (len(rx.taps), LP_CUTOFF, rx.gain))

    # Drop two bits at each end: the filter is 5.5 ms long, so the first
    # outputs are still filling and the last are running dry.
    guard = int(2 * sps)
    d = d[guard:len(d) - guard]
    if len(d) < 16 * sps:
        print("  Too little left after the filter transient to decode.")
        return 1

    phase, opening = eye(d, sps)
    idx = (phase + np.arange(int((len(d) - phase) / sps)) * sps).astype(int)
    samples = d[idx]
    bits = (samples > 0).astype(np.int8)

    known = np.unpackbits(np.frombuffer(message, dtype=np.uint8))
    errors, offset, inverted = align(bits, known)
    text = to_text((1 - bits) if inverted else bits, offset, len(known))

    print("  sampling           phase %d of %d, eye %.3f (1.0 is ideal)"
          % (phase, int(round(sps)), opening))
    print("  bits recovered     %d, offset %d into the message%s"
          % (len(bits), offset, ", POLARITY INVERTED" if inverted else ""))
    print("  bit errors         %d of %d  (BER %.2e)"
          % (errors, len(bits), errors / float(len(bits))))
    print()
    print("  sent      %r" % args.message)
    print("  received  %r" % text[:len(args.message) * 3])

    decode_ok = errors == 0 and not inverted
    ok = timing_ok and underruns == 0 and tones_ok and decode_ok
    print()
    if ok:
        print("  Clean link. Tones, timing, and the message all hold.")
    else:
        broken = [n for n, good in (("tones", tones_ok),
                                    ("timing", timing_ok),
                                    ("underruns", underruns == 0),
                                    ("decode", decode_ok)) if not good]
        print("  Not clean yet -- %s. See above." % ", ".join(broken))
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
