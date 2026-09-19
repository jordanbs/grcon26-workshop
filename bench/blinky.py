"""Is the pin doing what the flowgraph asked, and will it light an LED?

The two blinky flowgraphs drive DIO0 and trust it. This measures the same
pin in volts on analog input 1, on the clock section 5 of the bench
checklist already verified, so "the LED is flashing" stops being the only
evidence.

Wiring, all three commands:

    LED anode (long leg) --> DIO0        cathode --> GND
    DIO0 --> 1+                          1- --> GND

Use the **'low'** input range. 3.3 V logic clips flat on 'high', which is
the +/-2.5 V one despite the name.

    python3 bench/blinky.py wires        # is analog 1 really on DIO0
    python3 bench/blinky.py pin          # does DIO0 toggle at the asked rate
    python3 bench/blinky.py pin 2000
    python3 bench/blinky.py duty         # is duty cycle linear in mean volts
    python3 bench/blinky.py led          # how hard is the LED loading the pin

Run `wires` first. A disconnected input still reports the right frequency,
because a few tens of millivolts of crosstalk from the pin next door carries
the pin's own timing -- so `pin` can look like a pass on a wire that is
attached to nothing. `wires` holds the pin still, which crosstalk cannot fake.

`pin` and `duty` drive the same chains the flowgraphs do -- a square wave
for one, a descending ramp into a comparator for the other -- so what is
measured here is what participants run, not a second implementation of it.

`led` is the one that answers the question these LEDs actually raise.
Integrated-resistor LEDs are sold rated for 3 V, 5 V, 12 V and 24 V, and
DIO is 3.3 V logic. Droop on the high level means the pin is being asked
for more current than it wants to give; no droop and no light means the
part needs more voltage than the pin has.

Run from the repo root, with a gnuradio interpreter -- the project .venv
does not have one.
"""
import sys, os, time
sys.path.insert(0, "gr-m2k")
from gnuradio import gr, blocks, analog
from m2k_blocks.digital import digital_sink
from m2k_blocks.analog_source import analog_source

URI = "ip:192.168.2.1"
DIO_RATE = 100000          # what both flowgraphs use
PWM_HZ = 1000              # 100 samples per period, so 1% duty steps
SCOPE_RATE = 1000000
RANGE = "low"              # the wide one; 'high' is +/-2.5 V and clips 3.3 V
BUF = 16384
LOGIC_SWING = 1.0          # below this it is pickup, not a pin
SETTLE = 1.5               # seconds of pin activity before anything is read
CAPTURE = 200000           # samples read after settling, 200 ms at 1 MS/s


def drive_and_capture(build_source, seconds=None, capture=CAPTURE):
    """Run one chain into DIO0 and hand back analog 1 in volts.

    `build_source` returns the float stream that becomes the pin: 0.0 and
    1.0, nothing between. The conversion to a short and the sink are the
    same two blocks in every caller, so they live here.
    """
    tb = gr.top_block()
    sink = digital_sink(uri=URI, pins=[0], names=["LED"],
                        sample_rate=DIO_RATE, buffer_size=BUF,
                        drive="push-pull", cyclic=False, idle_level="low")
    head = blocks.float_to_short(1, 1)
    tb.connect(build_source(tb), head, sink)

    scope = analog_source(uri=URI, ch1_enabled=True, ch2_enabled=False,
                          sample_rate=SCOPE_RATE, ch1_range=RANGE,
                          buffer_size=BUF, units="volts", trigger_source="off")
    grabbed = blocks.vector_sink_f()
    tb.connect(scope,
               blocks.skiphead(gr.sizeof_float, int(SETTLE * SCOPE_RATE)),
               blocks.head(gr.sizeof_float, capture), grabbed)

    tb.start()
    time.sleep(seconds if seconds else SETTLE + capture / SCOPE_RATE + 1.0)
    tb.stop()
    tb.wait()
    return list(grabbed.data())


def levels(volts):
    """High level, low level and the midpoint between them.

    Median rather than mean on each side, so the handful of samples caught
    mid-edge do not drag either figure.
    """
    if not volts:
        return None
    lo_v, hi_v = min(volts), max(volts)
    mid = (lo_v + hi_v) / 2.0
    highs = sorted(v for v in volts if v > mid)
    lows = sorted(v for v in volts if v <= mid)
    if not highs or not lows:
        return None
    return (highs[len(highs) // 2], lows[len(lows) // 2], mid)


def crossings(volts, mid):
    """Rising edges, counted against the midpoint with a bit of hysteresis."""
    span = max(volts) - min(volts)
    band = 0.15 * span
    edges, armed = 0, volts[0] > mid
    for v in volts:
        if armed and v < mid - band:
            armed = False
        elif not armed and v > mid + band:
            armed = True
            edges += 1
    return edges


def square(hz):
    def build(tb):
        return analog.sig_source_f(DIO_RATE, analog.GR_SQR_WAVE, hz, 1, 0)
    return build


def pwm(duty):
    """The flowgraph's chain: descending ramp, offset by duty, comparator."""
    def build(tb):
        ramp = analog.sig_source_f(DIO_RATE, analog.GR_SAW_WAVE, PWM_HZ, -1, 0)
        offset = blocks.add_const_ff(duty)
        compare = blocks.threshold_ff(0, 0, 0)
        tb.connect(ramp, offset, compare)
        return compare
    return build


def cmd_pin():
    want = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
    # Enough capture for at least ten periods, however slow the request.
    capture = max(CAPTURE, int(10 * SCOPE_RATE / want))
    print("driving DIO0 with a %.4g Hz square, reading analog 1\n" % want)
    volts = drive_and_capture(square(want), capture=capture)
    if len(volts) < 1000:
        print("RESULT only %d samples -- no capture" % len(volts))
        return 1

    found = levels(volts)
    if found is None:
        print("RESULT the pin never changed. Constant %.3f V."
              % (sum(volts) / len(volts)))
        return 1
    high, low, mid = found
    seconds = len(volts) / SCOPE_RATE
    got = crossings(volts, mid) / seconds
    swing = high - low

    print("  high        %+.3f V" % high)
    print("  low         %+.3f V" % low)
    print("  swing        %.3f V" % swing)
    print("  asked for   %.4g Hz" % want)
    print("  measured    %.4g Hz over %.3f s" % (got, seconds))

    # The rate can come out perfect on a wire that is not connected to
    # anything, because a few tens of millivolts of crosstalk from the
    # pin next door carries the pin's own timing. Measured that way once;
    # it reads as a clean PASS if nobody checks the amplitude.
    if swing < LOGIC_SWING:
        print("\nRESULT FAIL -- %.0f mV is not a logic swing, whatever the "
              "rate says.\n       This is what crosstalk looks like when 1+ "
              "is not on DIO0.\n       Run `blinky.py wires` to see whether "
              "the pin moves the input at all." % (1000 * swing))
        return 1

    off = abs(got - want) / want
    print("\nRESULT %s -- %.2f%% from the requested rate"
          % ("PASS" if off < 0.02 else "FAIL", 100 * off))
    return 0 if off < 0.02 else 1


def cmd_duty():
    """Is mean voltage linear in duty cycle?

    If it is, the pin plus a low-pass filter -- your eye, here -- is a
    one-bit DAC, and the brightness slider is doing real work rather than
    landing on a handful of levels.
    """
    steps = [i / 10.0 for i in range(11)]
    print("DIO0 at %d Hz PWM, %d samples per period\n"
          % (PWM_HZ, DIO_RATE // PWM_HZ))
    print("  duty    mean V")
    rows = []
    for duty in steps:
        volts = drive_and_capture(pwm(duty))
        if len(volts) < 1000:
            print("  %.2f    no capture" % duty)
            return 1
        mean = sum(volts) / len(volts)
        rows.append((duty, mean))
        print("  %.2f    %+.3f" % (duty, mean))
        sys.stdout.flush()

    dark, lit = rows[0][1], rows[-1][1]
    span = lit - dark
    if abs(span) < LOGIC_SWING:
        print("\nRESULT the pin barely moved between 0%% and 100%% duty "
              "(%.3f V apart), which is not a logic swing.\n       Run "
              "`blinky.py wires` before reading anything into this." % span)
        return 1

    print("\n  duty 0 reads %+.3f V, duty 1 reads %+.3f V\n" % (dark, lit))
    print("  duty    expected V   measured V   error")
    worst = 0.0
    for duty, mean in rows:
        want = dark + duty * span
        err = mean - want
        worst = max(worst, abs(err))
        print("  %.2f      %+.3f       %+.3f     %+.0f mV"
              % (duty, want, mean, 1000 * err))
    tol = 0.03 * abs(span)
    print("\nRESULT %s -- worst departure from linear %.0f mV, %.1f%% of the "
          "swing" % ("PASS" if worst < tol else "FAIL", 1000 * worst,
                     100 * worst / abs(span)))
    return 0 if worst < tol else 1


def cmd_led():
    """How hard is the LED loading the pin?

    Two measurements of the same steady high level, one with the LED on
    the pin and one without. The difference is the whole answer.
    """
    print("This one needs you to unplug something halfway through.\n")
    readings = {}
    for state in ("with the LED connected", "with the LED disconnected"):
        input("  %s, then press return: " % state)
        volts = drive_and_capture(square(500.0))
        found = levels(volts)
        if found is None:
            print("    the pin never changed -- check DIO0 to 1+")
            return 1
        readings[state] = found[0]
        print("    high level %+.3f V\n" % found[0])

    loaded = readings["with the LED connected"]
    free = readings["with the LED disconnected"]
    droop = free - loaded
    print("  unloaded   %+.3f V" % free)
    print("  loaded     %+.3f V" % loaded)
    print("  droop       %.3f V\n" % droop)

    if droop > 0.4:
        print("RESULT the LED is pulling the pin down by %.0f mV. It is "
              "lighting, and it is asking for more current than the pin is "
              "comfortable giving. A higher-value series resistor would be "
              "kinder; the demo will still work." % (1000 * droop))
    elif droop > 0.05:
        print("RESULT %.0f mV of droop. The LED is drawing current and the "
              "pin is holding up. This is the good case." % (1000 * droop))
    else:
        print("RESULT under %.0f mV of droop, so almost no current is "
              "flowing. If the LED is also dark, its internal resistor is "
              "sized for a higher rail than 3.3 V -- see the fallback in "
              "flowgraphs/README.md." % (1000 * droop))
    return 0


def cmd_wires():
    """Is analog 1 actually on DIO0? No timing, no flowgraph, no scheduler.

    Hold the pin high, read the input. Hold it low, read it again. If the
    two readings are the same the wire is somewhere else, and every other
    command in this file is measuring the air.

    This one goes straight at libm2k rather than through the blocks,
    because a static level is not a stream and there is nothing to be
    gained from making it one.
    """
    import libm2k
    print("holding DIO0 still and reading analog 1\n")
    ctx = libm2k.m2kOpen(URI)
    if ctx is None:
        print("RESULT no context at %s -- is Scopy holding the board?" % URI)
        return 1
    try:
        ctx.calibrateADC()
        dig, ain = ctx.getDigital(), ctx.getAnalogIn()
        ain.enableChannel(0, True)
        ain.setSampleRate(1000000)
        ain.setRange(0, libm2k.PLUS_MINUS_25V)
        dig.setDirection(0, libm2k.DIO_OUTPUT)
        dig.enableChannel(0, True)
        seen = {}
        for level in (1, 0):
            dig.setValueRaw(0, level)
            time.sleep(0.3)
            block = ain.getSamples(20000)[0]
            seen[level] = sum(block) / len(block)
            print("  DIO0 held %s   analog 1 reads %+.3f V"
                  % ("high" if level else "low ", seen[level]))
    finally:
        libm2k.contextClose(ctx, True)

    step = seen[1] - seen[0]
    print("\n  difference    %+.3f V\n" % step)
    if step < LOGIC_SWING:
        print("RESULT FAIL -- the input does not follow the pin. 1+ is not "
              "on DIO0.\n       Check, in this order: 1+ in the same "
              "breadboard row as DIO0,\n       1- in the ground row, and "
              "the flywire labelled DIO0 rather than a neighbour.")
        return 1
    print("RESULT PASS -- the input follows the pin. The other three "
          "commands are measuring something real.")
    return 0


COMMANDS = {"wires": cmd_wires, "pin": cmd_pin, "duty": cmd_duty,
            "led": cmd_led}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    code = COMMANDS[name]()
    sys.stdout.flush()
    # gr-iio holds the network context open past the interpreter's exit and
    # the process hangs. digital_coherence.py does the same.
    os._exit(code)
