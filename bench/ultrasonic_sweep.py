"""Sweep the 40 kHz pair for resonance and the real -6 dB bandwidth.

Everything in Phase 3 needs f0. The datasheet number is for the part, not
for the two transducers on this bench at this spacing, and the FSK tones
sit at f0 +/- 300 Hz -- so a resonance that is 800 Hz off puts one tone
down the skirt and the link looks like a coding problem.

    W1 -> TX +, TX - -> GND
    RX + -> 1+, RX - -> GND, 1- -> GND
    input range 'high' (+/-2.5 V)

1- must go to GND. The scope inputs are differential into an in-amp and a
piezo is a floating capacitive source with no DC return; leave 1- open
and the common mode wanders instead of sitting still.

Channel 2 is captured too but nothing needs to be wired to it. The ADC
returns both channels whatever you ask for -- see analog_source -- so the
second capture is free, and W1 -> 2+ makes it the drive reference for
time-of-flight later.

    generator 750 kS/s      the third rung of the DAC ladder
    scope     1 MS/s        the third rung of the ADC ladder, a different one

A cyclic buffer only produces multiples of rate/N, so at 750 kS/s and
16384 samples the grid is 45.78 Hz and 40 kHz is really 40008.5 Hz. Every
frequency here is snapped to that grid and the ACTUAL one is what gets
printed and what f0 is reported from. The buffer holds a whole number of
cycles for the same reason: a fractional one has a step at the wrap, and
a step at 45 Hz is a click the transducer will happily radiate.

Read the amplitude against the floor, not on its own. Two controls:

    the script measures a zero-amplitude floor first, which is noise
    the pair turned away from each other is the crosstalk floor, which
      is drive coupling through the shared ground, and is yours to set up

A reading that does not clear both is not an acoustic path. Take the
crosstalk floor with --tone before believing any sweep.

Run from the repo root, with a gnuradio interpreter:

    python3 bench/ultrasonic_sweep.py --tone 40000
    python3 bench/ultrasonic_sweep.py
    python3 bench/ultrasonic_sweep.py --start 30000 --stop 50000 --step 500
    python3 bench/ultrasonic_sweep.py --csv > sweep.csv
"""
import sys, time, math, argparse
sys.path.insert(0, "gr-m2k")
import numpy as np
from gnuradio import gr, blocks
from m2k_blocks.analog_sink import analog_sink
from m2k_blocks.analog_source import analog_source
from m2k_blocks.m2k_scale import volts_per_count

URI = "ip:192.168.2.1"
GEN_RATE, SCOPE_RATE = 750000, 1000000
BUF = 16384
SETTLE, CAPTURE = 0.2, 0.1

# The ADC is 12-bit and full scale is 2048 counts, so a capture that gets
# near it is clipped and its amplitude is a flat top, not a peak. Warn
# early enough to be useful.
SAT_COUNTS = 1950

# -6 dB is half amplitude. Spelled out because 6.0 dB is not.
HALF_DB = 20.0 * math.log10(2.0)


class _graph(gr.top_block):
    def __init__(self, samples, input_range):
        gr.top_block.__init__(self, "ultrasonic_sweep")
        # Cyclic: the DAC repeats the buffer forever, which is what a
        # steady tone is. It also keeps holding it after we stop, so the
        # sweep ends with a deliberate zero buffer.
        self.tone = blocks.vector_source_f(samples, True)
        self.gen = analog_sink(URI, output="w1", sample_rate=GEN_RATE,
                               units="volts", buffer_size=BUF, cyclic=True)
        self.connect(self.tone, self.gen)

        self.scope = analog_source(URI, ch1_enabled=True, ch2_enabled=True,
                                   sample_rate=SCOPE_RATE,
                                   ch1_range=input_range, ch2_range=input_range,
                                   buffer_size=BUF, units="counts",
                                   trigger_source="off")
        self.rx = blocks.vector_sink_s()
        self.ref = blocks.vector_sink_s()
        self.connect((self.scope, 0), self.rx)
        self.connect((self.scope, 1), self.ref)


def snap(freq):
    """Nearest frequency the cyclic buffer can actually produce."""
    cycles = max(1, int(round(freq * BUF / float(GEN_RATE))))
    return cycles, cycles * GEN_RATE / float(BUF)


def tone_buffer(cycles, amplitude):
    n = np.arange(BUF)
    return (amplitude * np.sin(2.0 * math.pi * cycles * n / BUF)).tolist()


def detect(counts, freq, vpc):
    """Amplitude in volts of the component at freq, by coherent detection.

    Correlating against the known drive frequency rejects everything that
    is not at it. It does NOT reject crosstalk, which is at exactly that
    frequency -- that is what the physical control is for.
    """
    if not counts:
        return float("nan"), 0
    x = np.asarray(counts, dtype=np.float64)
    peak = int(np.max(np.abs(x)))
    x = (x - x.mean()) * vpc
    n = np.arange(x.size)
    ref = np.exp(-2j * math.pi * freq * n / float(SCOPE_RATE))
    return 2.0 * abs(np.vdot(ref, x)) / x.size, peak


def measure(samples, freq, input_range, vpc, settle, capture):
    tb = _graph(samples, input_range)
    # start/stop/wait, never run(): the config keep-alive never ends.
    tb.start()
    time.sleep(settle)
    tb.rx.reset(); tb.ref.reset()
    time.sleep(capture)
    tb.stop(); tb.wait()
    rx = detect(list(tb.rx.data()), freq, vpc)
    ref = detect(list(tb.ref.data()), freq, vpc)
    return rx, ref


def db(amp, reference):
    if amp <= 0.0 or reference <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(amp / reference)


def edge(freqs, amps, peak_i, step):
    """Where the response crosses -6 dB, walking out from the peak."""
    top = amps[peak_i]
    i = peak_i
    while 0 <= i + step < len(amps):
        j = i + step
        if amps[j] < top / 2.0:
            d1, d2 = db(amps[i], top), db(amps[j], top)
            if d1 == d2 or math.isinf(d2):
                return freqs[j]
            frac = (d1 + HALF_DB) / (d1 - d2)
            return freqs[i] + frac * (freqs[j] - freqs[i])
        i = j
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tone", type=float, default=None,
                    help="measure one frequency instead of sweeping")
    ap.add_argument("--start", type=float, default=36000.0)
    ap.add_argument("--stop", type=float, default=44000.0)
    ap.add_argument("--step", type=float, default=250.0)
    ap.add_argument("--amplitude", type=float, default=4.0,
                    help="drive amplitude in volts, 0-5 (default 4.0)")
    ap.add_argument("--range", dest="input_range", default="high",
                    choices=("high", "low"),
                    help="scope input range; 'high' is +/-2.5 V (default)")
    ap.add_argument("--settle", type=float, default=SETTLE)
    ap.add_argument("--capture", type=float, default=CAPTURE)
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    if not 0.0 <= args.amplitude <= 5.0:
        ap.error("amplitude must be 0-5 V; W1 cannot swing past +/-5 V")

    vpc = volts_per_count(args.input_range, SCOPE_RATE)

    requested = ([args.tone] if args.tone is not None
                 else list(np.arange(args.start, args.stop + args.step / 2.0,
                                     args.step)))
    points = []
    for want in requested:
        cycles, actual = snap(want)
        if not points or points[-1][0] != cycles:
            points.append((cycles, actual))

    if not args.csv:
        print()
        print("  W1 -> TX, RX -> 1+, 1- to GND   drive %.1f V, range '%s'"
              % (args.amplitude, args.input_range))
        print("  gen %d S/s (grid %.2f Hz), scope %d S/s, %.9f V/count"
              % (GEN_RATE, GEN_RATE / float(BUF), SCOPE_RATE, vpc))
        print()

    # Noise floor first: same capture, no drive. Anything at or under this
    # is not a measurement.
    (floor, _), _ = measure([0.0] * BUF, points[0][1], args.input_range, vpc,
                            args.settle, args.capture)
    if not args.csv:
        print("  noise floor (drive off)   %7.3f mV" % (floor * 1e3))
        print()
        print("   freq (kHz)     RX (mV)   ref 2 (mV)   peak counts")

    freqs, amps, saturated = [], [], False
    if args.csv:
        print("freq_hz,rx_volts,ref_volts,rx_peak_counts")
    for cycles, actual in points:
        samples = tone_buffer(cycles, args.amplitude)
        (rx, rx_peak), (ref, _) = measure(samples, actual, args.input_range,
                                          vpc, args.settle, args.capture)
        freqs.append(actual)
        amps.append(rx)
        clipped = rx_peak >= SAT_COUNTS
        saturated = saturated or clipped
        if args.csv:
            print("%.2f,%.6e,%.6e,%d" % (actual, rx, ref, rx_peak))
        else:
            print("   %9.3f   %9.3f    %9.3f        %5d%s"
                  % (actual / 1e3, rx * 1e3, ref * 1e3, rx_peak,
                     "  CLIPPED" if clipped else ""))

    # Leave the transducer quiet. The DAC holds its last cyclic buffer,
    # so without this W1 keeps driving at the last frequency forever.
    measure([0.0] * BUF, points[-1][1], args.input_range, vpc, 0.05, 0.02)

    if args.csv:
        return

    print()
    if saturated:
        print("  Some points CLIPPED at the input. Increase the spacing, or")
        print("  drop --amplitude, or use --range low. The peak below is not")
        print("  trustworthy until nothing clips.")
        print()

    peak_i = int(np.argmax(amps))
    top = amps[peak_i]
    if top <= floor * 3.0:
        print("  No acoustic path. The best point (%.3f mV at %.3f kHz) is not"
              % (top * 1e3, freqs[peak_i] / 1e3))
        print("  clear of the %.3f mV noise floor. Check the wiring, then check"
              % (floor * 1e3))
        print("  that the transducers face each other before sweeping again.")
        print()
        return

    print("  f0            %.3f kHz    %.3f mV" % (freqs[peak_i] / 1e3, top * 1e3))
    if len(points) == 1:
        print()
        print("  One point only. Run without --tone for f0 and the bandwidth,")
        print("  and take a crosstalk floor first: same tone, transducers")
        print("  turned away from each other.")
        print()
        return

    low = edge(freqs, amps, peak_i, -1)
    high = edge(freqs, amps, peak_i, +1)
    for name, value, where in (("-6 dB low ", low, freqs[0]),
                               ("-6 dB high", high, freqs[-1])):
        if value is None:
            print("  %s    not reached by %.3f kHz -- widen the sweep"
                  % (name, where / 1e3))
        else:
            print("  %s    %.3f kHz" % (name, value / 1e3))
    if low is not None and high is not None:
        print("  bandwidth     %.0f Hz" % (high - low))
        print()
        print("  FSK tones at f0 +/- 300 Hz land at %.3f and %.3f kHz."
              % ((freqs[peak_i] - 300) / 1e3, (freqs[peak_i] + 300) / 1e3))
    print()


if __name__ == "__main__":
    main()
