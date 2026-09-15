"""The colorimeter board, measured rather than assumed.

The board is `docs/colorimeter-board.md`. The demo is
`docs/colorimeter.md`. This is the script that establishes the four
things those two documents are not allowed to guess at.

    coherence   Is the DIO output clock the same clock as the ADC?
                The workshop claims an FFT is a lock-in when excitation
                and sampling share a clock. On this board that claim is
                either true or it is a slide. Measures it in ppm.

    pins        Which DIO pin lights which color, asked of a human
                rather than read off a silkscreen.

    channels    Which TIA is the reference and which is the sample.
                That is mechanical -- it depends on which photodiode
                riser sits behind the cuvette -- so it cannot be read
                out of a schematic at all.

    run         Continuous transmittance, the demo itself.

    supply      Two-point meter check of V+ and V- against what
                m2k_scale believes. Wants a DMM on the header.

Before any of it, fit the jumpers: JP1 to Out1, JP2 to Out2, JP4/JP5 and
JP6/JP7 to one gain each, JP3 for the bias you want, JP8 for the sink
rail. `docs/colorimeter-board.md` says what those are.

Run from the repo root:

    python3 bench/colorimeter.py coherence
    python3 bench/colorimeter.py pins
    python3 bench/colorimeter.py channels
    python3 bench/colorimeter.py run
    python3 bench/colorimeter.py supply

Needs a gnuradio interpreter -- the project .venv does not have one.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, "gr-m2k")
from gnuradio import blocks                                   # noqa: E402
from gnuradio import gr                                       # noqa: E402
from m2k_blocks.analog_source import analog_source            # noqa: E402
from m2k_blocks.digital import digital_sink                   # noqa: E402
from m2k_blocks.power_supply import power_supply              # noqa: E402

URI = "ip:192.168.2.1"
RATE = 100000              # both the ADC and the pattern generator
PINS = [13, 14, 15]        # red, green, blue -- until `pins` says otherwise

# The excitation buffer is 4096 samples long and repeats in hardware, so
# a color driven at exactly K cycles per buffer is a tone at K * RATE /
# 4096 Hz and lands in bin K of a 4096-point FFT taken at the same rate.
# Nothing has to be windowed and nothing leaks -- IF the two clocks
# agree, which is what `coherence` is for.
#
# Thoren's exercise uses 5, 6 and 7 kHz. (Its published source says 500,
# 600 and 700, but it generates the buffer at 10 kS/s and plays it at
# 100 kS/s; the bin numbers hard-coded further down that file --
# 202..207, 243..248, 284..289 -- are the giveaway.) These are the
# nearest frequencies that fall exactly on a bin.
NFFT = 4096
CYCLES = {"red": 205, "green": 246, "blue": 287}   # 5004.9 / 6005.9 / 7006.8 Hz
COLORS = ["red", "green", "blue"]

CAPTURE = NFFT * 8         # one ADC buffer, sliced into 8 blocks
SETTLE = CAPTURE * 4       # samples thrown away before the one we keep


def bin_hz(k):
    return k * RATE / float(NFFT)


def square(cycles, n=NFFT):
    """`cycles` whole periods of a square wave in exactly n samples.

    n/cycles is not an integer here, so the duty cycle wobbles by a
    sample from period to period. That puts a little energy in the odd
    harmonics and none at all anywhere near the fundamental, which is
    the only bin that gets read.
    """
    return [1 if (i * cycles * 2) // n % 2 else 0 for i in range(n)]


# Every rig ever built, kept alive on purpose, along with every block it
# holds. A top_block keeps its blocks alive on the C++ side only. The
# digital sink wraps a PYTHON block, and a Python block whose last
# Python reference goes away is torn down underneath the C++ scheduler
# that is still calling into it -- which shows up as an AttributeError
# inside gr's own gateway.py and then a segfault in a worker thread,
# some seconds after the flowgraph started and nowhere near the cause.
#
# Hold the blocks. `os._exit` at the end skips the teardown, so nothing
# here leaks for longer than the process lives.
_KEEP = []


class Rig(object):
    """Rails up, excitation running, both scope channels captured.

    The rails are the first thing and the last thing. V+ feeds the LED
    anodes as well as the op-amp, so nothing on the board does anything
    until they are up, and the board stays biased after the flowgraph
    stops unless somebody takes them down. Hence the context manager.
    """

    def __init__(self, cycles=None, capture=CAPTURE, live=False):
        self.cycles = CYCLES if cycles is None else cycles
        self.capture = capture
        # A live rig never stops. Stopping the flowgraph tears down the
        # cyclic DIO buffer, and pushing a cyclic buffer a second time
        # returns -EBUSY, so `run` reads out of a sink that is still
        # filling instead of restarting anything.
        self.live = live
        self.tb = None
        self.rails = []
        self.sink = None
        self.src = None
        self.sources = []

    def __enter__(self):
        _KEEP.append(self)
        self.rails = [power_supply(uri=URI, rail="v+", voltage=5.0),
                      power_supply(uri=URI, rail="v-", voltage=-5.0)]
        time.sleep(0.5)                       # let the TIA settle at DC

        self.tb = gr.top_block()

        # idle_level HIGH, not low. The DIO bit does not gate a color,
        # it steers that color's current sink between LED riser 0 (J5,
        # select low) and riser 1 (J6, select high). Only J5 is
        # populated, so low is lit and high is dark -- and idling low
        # would leave all three colors on and the LED white whenever the
        # flowgraph is not running.
        self.sink = digital_sink(uri=URI, pins=PINS, sample_rate=RATE,
                                 buffer_size=NFFT, cyclic=True,
                                 idle_level="high")
        self.sources = []
        for index, color in enumerate(COLORS):
            k = self.cycles.get(color, 0)
            wave = square(k) if k else [1] * NFFT   # not driven -> dark
            self.sources.append(blocks.vector_source_s(wave, True))
            self.tb.connect(self.sources[-1], (self.sink, index))

        self.src = src = analog_source(uri=URI, ch1_enabled=True, ch2_enabled=True,
                            sample_rate=RATE, ch1_range="high",
                            ch2_range="high", buffer_size=self.capture,
                            units="volts")
        self.vecs = []
        for ch in range(2):
            v = blocks.vector_sink_f()
            if self.live:
                self.tb.connect((src, ch), v)
            else:
                # Skip whole buffers, then keep exactly one. A block that
                # straddles a refill boundary has a gap in the middle of
                # it and would read as a phase jump.
                self.tb.connect((src, ch),
                                blocks.skiphead(gr.sizeof_float, SETTLE),
                                blocks.head(gr.sizeof_float, self.capture), v)
            self.vecs.append(v)

        self.tb.start()
        return self

    def grab(self, seconds=0.5):
        """The most recent NFFT samples from each channel, as volts.

        Live rigs only. Drains and clears the sinks so they do not grow
        without bound, and takes the tail of what was there -- the last
        block is the one that straddles no start-up transient.
        """
        time.sleep(seconds)
        out = []
        for v in self.vecs:
            data = np.array(v.data(), dtype=float)
            v.reset()
            out.append(data[-NFFT:] if len(data) >= NFFT else data)
        return out

    def __exit__(self, *exc):
        if self.tb is not None:
            self.tb.stop()
            self.tb.wait()
        for rail in self.rails:
            rail.power_down()
        return False


def capture_once(cycles=None, capture=CAPTURE, settle=3.0):
    with Rig(cycles=cycles, capture=capture) as rig:
        time.sleep(settle)
        return [np.array(v.data(), dtype=float) for v in rig.vecs]


# ---------------------------------------------------------------- coherence

def cmd_coherence():
    """Does a chop tone sit still in one bin, or does it walk?

    Two independent readings of the same question.

    Leakage: with a rectangular window and a coherent tone, bin K holds
    essentially all of the energy. Spread it across the neighbours and
    the clocks differ, or the buffer did not repeat cleanly.

    Drift: the phase of bin K, block after block through one contiguous
    capture. Coherent means a constant phase. A steady slope is a
    frequency offset, and the slope converts straight into ppm.
    """
    data = capture_once()
    nblocks = len(data[0]) // NFFT
    print("captured %d samples per channel, %d blocks of %d"
          % (len(data[0]), nblocks, NFFT))
    if nblocks < 2:
        print("RESULT not enough samples to judge")
        return 1

    verdict = []
    for ch, samples in enumerate(data):
        print("\nanalog %d" % (ch + 1))
        blocks_ = [samples[i * NFFT:(i + 1) * NFFT] for i in range(nblocks)]
        spectra = [np.fft.rfft(b - b.mean()) for b in blocks_]

        for color in COLORS:
            k = CYCLES[color]
            mags = [abs(s[k]) for s in spectra]
            if max(mags) < 1e-6:
                print("  %-5s bin %3d (%7.1f Hz)  nothing there"
                      % (color, k, bin_hz(k)))
                continue

            # How much of the local energy is in the one bin.
            near = spectra[0][k - 4:k + 5]
            leak = 1.0 - abs(spectra[0][k]) ** 2 / float(np.sum(np.abs(near) ** 2))

            # Where the peak actually is, in case it is not where we put it.
            window = np.abs(spectra[0][k - 20:k + 21])
            peak = k - 20 + int(np.argmax(window))

            phases = np.unwrap([np.angle(s[k]) for s in spectra])
            slope = np.polyfit(np.arange(nblocks), phases, 1)[0]
            # A phase advance of `slope` radians per block of NFFT
            # samples is a frequency error of slope / (2 pi) bins.
            ppm = (slope / (2 * np.pi)) / float(k) * 1e6

            ok = leak < 0.05 and abs(ppm) < 50 and peak == k
            verdict.append(ok)
            print("  %-5s bin %3d (%7.1f Hz)  peak at %3d  leak %5.1f%%  "
                  "drift %+8.1f ppm  %s"
                  % (color, k, bin_hz(k), peak, 100 * leak, ppm,
                     "coherent" if ok else "NOT coherent"))

    if not verdict:
        print("\nRESULT saw no tones at all -- check the rails, the "
              "jumpers, and that an LED riser is fitted")
        return 1
    print("\nRESULT %s"
          % ("the DIO output and the ADC share a clock; an FFT here is a "
             "lock-in" if all(verdict) else
             "the clocks do NOT agree -- the FFT needs a window and "
             "several bins, as Thoren's script does"))
    return 0


# -------------------------------------------------------------------- pins

def cmd_pins():
    """Light one pin at a time and let a human name the color.

    The silkscreen says 13/14/15 is R/G/B and the schematic agrees, but
    the LED riser is a separate board on a 6-pin connector and can be
    seated the other way round. Confirmed by eye 2026-09-15: it is not.

    The two colors that are not under test sit at 1, not 0. A select bit
    steers its color to riser 0 (low) or riser 1 (high), and only riser
    0 is populated -- so 0 is lit and a color left at 0 would wash out
    the one being tested.
    """
    seen = {}
    for index, pin in enumerate(PINS):
        cycles = {c: (CYCLES[c] if i == index else 0)
                  for i, c in enumerate(COLORS)}
        print("\ndriving DIO%d only, at %.0f Hz."
              % (pin, bin_hz(CYCLES[COLORS[index]])))
        with Rig(cycles=cycles):
            answer = input("  what color is the LED? ").strip().lower()
        seen[pin] = answer
        print("  DIO%d -> %s" % (pin, answer))

    print("\nRESULT")
    for index, pin in enumerate(PINS):
        expected = COLORS[index]
        mark = "" if seen[pin].startswith(expected[0]) else "   <-- NOT the silkscreen"
        print("  DIO%-3d %-8s (expected %s)%s" % (pin, seen[pin], expected, mark))
    return 0


# ---------------------------------------------------------------- channels

def cmd_channels():
    """Which analog input is the reference and which is the sample?

    Block the cuvette slot. The channel that drops is the one whose
    light goes through the cuvette -- that is the sample. The one that
    does not move is the reference. Nothing in the schematic can tell
    you this; it is which riser sits where.
    """
    def levels(label):
        input(label)
        data = capture_once()
        out = []
        for ch, samples in enumerate(data):
            s = np.fft.rfft(samples[:NFFT] - samples[:NFFT].mean())
            out.append({c: abs(s[CYCLES[c]]) for c in COLORS})
            print("  analog %d  %s" % (ch + 1, "  ".join(
                "%s %8.4f" % (c, out[ch][c]) for c in COLORS)))
        return out

    print("clear light path:")
    clear = levels("  empty the cuvette slot, then press enter ")
    print("blocked light path:")
    blocked = levels("  put something opaque in the cuvette slot, "
                     "then press enter ")

    drop = []
    for ch in range(2):
        ratios = [blocked[ch][c] / clear[ch][c] if clear[ch][c] > 1e-9 else 1.0
                  for c in COLORS]
        drop.append(float(np.mean(ratios)))
        print("\nanalog %d keeps %.1f%% of its signal when blocked"
              % (ch + 1, 100 * drop[ch]))

    sample = 0 if drop[0] < drop[1] else 1
    if abs(drop[0] - drop[1]) < 0.1:
        print("\nRESULT both channels moved by about the same amount. "
              "Either both beams pass the slot or neither does -- check "
              "which riser is behind the cuvette.")
        return 1
    print("\nRESULT analog %d is the SAMPLE, analog %d is the REFERENCE"
          % (sample + 1, 2 - sample))
    return 0


# --------------------------------------------------------------------- run

def cmd_run(ref_ch=0, sample_ch=1):
    """Transmittance, continuously, the way the demo shows it.

    Reference and sample default to analog 1 and 2, which is what
    Thoren's script assumes. `channels` is how you find out whether that
    is true of the board in front of you.
    """
    print("reference = analog %d, sample = analog %d"
          % (ref_ch + 1, sample_ch + 1))
    print("ctrl-c to stop\n")
    with Rig(live=True) as rig:
        time.sleep(2.0)
        rig.grab(0.5)                     # throw away the start-up transient
        try:
            while True:
                data = rig.grab()
                if min(len(d) for d in data) < NFFT:
                    continue
                ref = np.fft.rfft(data[ref_ch] - data[ref_ch].mean())
                sam = np.fft.rfft(data[sample_ch] - data[sample_ch].mean())
                out = []
                for color in COLORS:
                    k = CYCLES[color]
                    t = 100.0 * abs(sam[k]) / abs(ref[k]) if abs(ref[k]) > 1e-9 else 0.0
                    out.append("%s %6.1f%%" % (color, t))
                print("  ".join(out))
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


# ------------------------------------------------------------------ supply

def cmd_supply():
    """Two points per rail, against a meter.

    m2k_scale converts volts to DAC codes through a fixed coefficient
    and the board's own calibration gain and offset. This is the check
    that the result is a volt.
    """
    plan = {"v+": [1.0, 4.5], "v-": [-1.0, -4.5]}
    print("put a DMM between the header pin and ground.\n")
    for rail, points in plan.items():
        supply = power_supply(uri=URI, rail=rail, voltage=0.0)
        got = []
        try:
            for want in points:
                supply.set_voltage(want, now=True)
                time.sleep(0.5)
                got.append(float(input(
                    "  %s commanded %+.2f V -- meter reads? " % (rail, want))))
        finally:
            supply.power_down()

        gain = (got[1] - got[0]) / (points[1] - points[0])
        offset = got[0] - gain * points[0]
        err = max(abs(g - w) for g, w in zip(got, points))
        print("  %s  gain %.4f  offset %+.4f V  worst error %+.1f mV\n"
              % (rail, gain, offset, 1000 * err))
    return 0


COMMANDS = {"coherence": cmd_coherence, "pins": cmd_pins,
            "channels": cmd_channels, "run": cmd_run, "supply": cmd_supply}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    code = COMMANDS[name]()
    sys.stdout.flush()
    # gr-iio holds the network context open past the interpreter's exit
    # and the process hangs. digital_coherence.py does the same.
    os._exit(code)
