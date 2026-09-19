"""The blinky pair: the pin level is the stream, and duty is linear in it.

Two flowgraphs drive DIO0 and one bench script measures it. Three things
have to agree or the demo teaches something false:

    the rate         100 kS/s in both flowgraphs and in bench/blinky.py
    the carrier      1 kHz, which is what makes duty resolution 1%
    the comparator   a descending ramp offset by duty, thresholded at 0

The third is the one worth testing hardest. `blocks.threshold_ff` fires
above its high limit, so the sense of the comparison depends on the sign
of the ramp's amplitude -- get it backwards and the LED is brightest at
duty 0, which looks like a wiring mistake rather than a sign error.

The chain is exercised through real GNU Radio blocks in a subprocess,
because the interpreter running these tests has no gnuradio. Everything
else here is YAML and `ast`, and runs anywhere.
"""

import ast
import json
import os

import pytest

from test_grc_integration import (BUILD, M2K_GRC, needs_gnuradio, needs_yaml,
                                  run_in_gr)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "bench", "blinky.py")
BLINK = os.path.join(ROOT, "flowgraphs", "m2k_blinky.grc")
PWM = os.path.join(ROOT, "flowgraphs", "m2k_led_pwm.grc")

DIO_RATE = 100000
PWM_HZ = 1000


def bench_constants():
    """Module-level constants of bench/blinky.py, without importing it.

    It imports gnuradio at the top, which the test interpreter does not
    have. Same trick as test_colorimeter.
    """
    tree = ast.parse(open(BENCH).read())
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found


def variables(doc):
    """The plain `variable` blocks of a flowgraph, by name."""
    return {b["name"]: b["parameters"]["value"]
            for b in doc["blocks"] if b["id"] == "variable"}


def block(doc, block_id):
    for b in doc["blocks"]:
        if b["id"] == block_id:
            return b
    raise AssertionError("no %s in the flowgraph" % block_id)


# ---------------------------------------------------------------- the chain

COMPARATOR = '''
    import json, sys
    from gnuradio import gr, blocks, analog
    rate, carrier = 100000, 1000
    out = {}
    for duty in [0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0]:
        tb = gr.top_block()
        ramp = analog.sig_source_f(rate, analog.GR_SAW_WAVE, carrier, -1, 0)
        offset = blocks.add_const_ff(duty)
        compare = blocks.threshold_ff(0, 0, 0)
        short = blocks.float_to_short(1, 1)
        head = blocks.head(gr.sizeof_short, rate)
        sink = blocks.vector_sink_s()
        tb.connect(ramp, offset, compare, short, head, sink)
        tb.run()
        data = sink.data()
        out[str(duty)] = {"ones": sum(data), "n": len(data),
                          "values": sorted(set(data))}
    print(json.dumps(out))
'''


@needs_gnuradio
def test_duty_is_the_on_fraction_to_within_one_sample():
    """Not approximately, and not within a few percent -- to the sample.

    100 samples per period means a 1% step moves exactly one sample, and
    every duty in the sweep comes out exact except 0.5, which is one
    sample light out of 100000. That one is the tie: the descending ramp
    passes through exactly 0.0 once per period, and `threshold_ff` fires
    on strictly greater, so the sample sitting on the threshold counts as
    off. It is a rounding rule, not an error, and it is invisible.
    """
    got = json.loads(run_in_gr(COMPARATOR))
    for duty, result in got.items():
        expected = round(float(duty) * result["n"])
        error = result["ones"] - expected
        assert abs(error) <= 1, (
            "duty %s is off by %d samples in %d" % (duty, error, result["n"]))


@needs_gnuradio
def test_the_pin_only_ever_sees_zero_and_one():
    """`float_to_short` truncates, so a stray 0.5 would become 0 in silence.

    The sink treats anything non-zero as a one, which means a chain that
    quietly produced 2 or -1 would still drive the pin and still look
    right on a scope. Check the values, not just the average.
    """
    got = json.loads(run_in_gr(COMPARATOR))
    for duty, result in got.items():
        assert set(result["values"]) <= {0, 1}, (
            "duty %s put %r on the pin" % (duty, result["values"]))
    assert got["0.0"]["values"] == [0], "duty 0 should be dark"
    assert got["1.0"]["values"] == [1], "duty 1 should be solid on"


@needs_gnuradio
def test_flipping_the_ramp_sign_kills_the_slider_entirely():
    """The minus sign on the amplitude is load-bearing, and tidying it away
    fails in the least obvious way available.

    An ascending ramp runs 0 to +1, so adding any positive duty leaves the
    whole period above the threshold: the pin is stuck on and the slider
    does nothing at all. On the bench that looks like a broken slider or a
    dead M2K, not like a sign error, which is why the .grc carries a
    comment about it and why this test exists.
    """
    stuck = json.loads(run_in_gr('''
        import json
        from gnuradio import gr, blocks, analog
        out = {}
        for duty in [0.01, 0.25, 0.75, 0.99]:
            tb = gr.top_block()
            ramp = analog.sig_source_f(100000, analog.GR_SAW_WAVE, 1000, 1, 0)
            head = blocks.head(gr.sizeof_short, 100000)
            sink = blocks.vector_sink_s()
            tb.connect(ramp, blocks.add_const_ff(duty),
                       blocks.threshold_ff(0, 0, 0),
                       blocks.float_to_short(1, 1), head, sink)
            tb.run()
            out[str(duty)] = sum(sink.data()) / len(sink.data())
        print(json.dumps(out))
    '''))
    assert set(stuck.values()) == {1.0}, (
        "the sign flip was supposed to stick the pin on; got %r" % stuck)


# --------------------------------------------------------- the square wave

@needs_gnuradio
def test_the_square_wave_is_already_the_two_values_the_pin_wants():
    """GNU Radio's square is 0 to amplitude, not plus and minus it.

    The blinky leans on that: amplitude 1 needs no offset block and no
    threshold, which is why the flowgraph is four blocks rather than six.
    """
    out = run_in_gr('''
        import json
        from gnuradio import gr, blocks, analog
        tb = gr.top_block()
        src = analog.sig_source_f(100000, analog.GR_SQR_WAVE, 1000, 1, 0)
        short = blocks.float_to_short(1, 1)
        head = blocks.head(gr.sizeof_short, 100000)
        sink = blocks.vector_sink_s()
        tb.connect(src, short, head, sink)
        tb.run()
        data = sink.data()
        print(json.dumps({"values": sorted(set(data)),
                          "ones": sum(data), "n": len(data)}))
    ''')
    got = json.loads(out)
    assert got["values"] == [0, 1]
    # Same one-sample tie as the PWM comparator, for the same reason.
    assert abs(got["ones"] - got["n"] // 2) <= 1


# ------------------------------------------------------------ the arithmetic

def test_the_carrier_divides_the_rate_into_whole_samples():
    """1% duty steps exist only because 100000/1000 is 100.

    Change either number to something that does not divide and the slider
    grows dead zones, which presents as a brightness control that sticks.
    """
    assert DIO_RATE % PWM_HZ == 0
    assert DIO_RATE // PWM_HZ == 100


@needs_yaml
def test_the_pwm_flowgraph_uses_those_two_numbers():
    import yaml
    doc = yaml.safe_load(open(PWM))
    var = variables(doc)
    assert int(var["samp_rate"]) == DIO_RATE
    assert int(var["pwm_hz"]) == PWM_HZ
    # The sink's own rate is a literal, not the variable -- it is an enum
    # the block offers, so it cannot be an expression. It still has to match.
    assert int(block(doc, "m2k_digital_sink")["parameters"]["sample_rate"]) \
        == DIO_RATE


@needs_yaml
def test_the_bench_script_measures_the_same_chain_the_demo_runs():
    """Written twice on purpose; this is the guard that they do not drift.

    Same reasoning as the colorimeter's naming rule: a bench script that
    imports out of flowgraphs/ would put a PYTHONPATH on the critical
    path of a live demo.
    """
    import yaml
    const = bench_constants()
    assert const["DIO_RATE"] == DIO_RATE
    assert const["PWM_HZ"] == PWM_HZ

    for path in (BLINK, PWM):
        doc = yaml.safe_load(open(path))
        sink = block(doc, "m2k_digital_sink")["parameters"]
        assert int(sink["sample_rate"]) == const["DIO_RATE"]
        assert sink["pin0"] == "0", "the bench script wires DIO0 to 1+"
        assert sink["num_lines"] == "1"
        assert sink["idle_level"] == "'low'", (
            "idle high leaves the LED lit whenever the flowgraph is stopped")
        assert sink["cyclic"] == "False", (
            "a repeating buffer would ignore the slider")


@needs_yaml
def test_the_blink_slider_stays_in_the_range_an_eye_reads_as_blinking():
    """Below about 0.5 Hz it reads as a fault; above about 20 Hz it fuses."""
    import yaml
    doc = yaml.safe_load(open(BLINK))
    rng = block(doc, "variable_qtgui_range")["parameters"]
    assert rng["label"] == "Blink rate (Hz)"
    start, stop = float(rng["start"]), float(rng["stop"])
    assert 0.1 <= start < stop <= 20

    # The fastest blink still gets thousands of samples per period, so the
    # edges land where they are asked to. Nothing here is rate-limited.
    assert DIO_RATE / stop > 1000


@needs_yaml
def test_moving_a_slider_takes_effect_in_about_a_sixth_of_a_second():
    """One buffer is the delay between a slider move and the LED changing.

    16384 at 100 kS/s is 164 ms, which reads as immediate. It is worth
    pinning because the obvious way to make the scope trace prettier --
    a bigger buffer -- is also the way to make the slider feel broken.
    """
    import yaml
    for path in (BLINK, PWM):
        sink = block(yaml.safe_load(open(path)), "m2k_digital_sink")["parameters"]
        latency = int(sink["buffer_size"]) / DIO_RATE
        assert latency < 0.25, "%s lags %.0f ms behind the slider" % (
            os.path.basename(path), 1000 * latency)


@needs_yaml
def test_the_duty_slider_spans_off_to_solid():
    import yaml
    doc = yaml.safe_load(open(PWM))
    rng = block(doc, "variable_qtgui_range")["parameters"]
    assert float(rng["start"]) == 0.0
    assert float(rng["stop"]) == 1.0
    # A step finer than one sample per period would be a slider position
    # that changes nothing.
    assert float(rng["step"]) >= 1.0 / (DIO_RATE // PWM_HZ)


@needs_yaml
def test_the_blinky_scope_leg_is_decimated_enough_to_see():
    """512 samples of a 2 Hz square at 100 kS/s is 5 ms of a 500 ms period."""
    import yaml
    doc = yaml.safe_load(open(BLINK))
    var = variables(doc)
    scope = block(doc, "qtgui_time_sink_x")["parameters"]
    window = int(scope["size"]) * int(var["view_decim"]) / DIO_RATE
    assert window > 2.0, "the window is %.2f s; a slow blink will not fit" % window


# ------------------------------------------------------------------- GRC

@needs_gnuradio
@pytest.mark.parametrize("name", ["m2k_blinky.grc", "m2k_led_pwm.grc"])
def test_both_flowgraphs_build_and_generate(repo_root, name):
    path = os.path.join(repo_root, "flowgraphs", name)
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    make = result["make"]
    assert "digital_sink(" in make
    assert "pins=[0]" in make
    assert "idle_level='low'" in make


@needs_gnuradio
def test_the_sliders_are_wired_to_callbacks_not_just_drawn():
    """A range widget with no callback is a slider that does nothing.

    GRC only emits the setter if the block declares it, so this is really
    a test that `duty` reached `add_const` and `blink_hz` reached the
    signal source, rather than being read once at startup.
    """
    pwm = json.loads(run_in_gr(BUILD, PWM,
                               os.path.join(ROOT, M2K_GRC)))["make"]
    assert "def set_duty" in pwm
    assert "set_k(self.duty)" in pwm

    blink = json.loads(run_in_gr(BUILD, BLINK,
                                 os.path.join(ROOT, M2K_GRC)))["make"]
    assert "def set_blink_hz" in blink
    assert "set_frequency(self.blink_hz)" in blink


# ----------------------------------------------------------------- the CLI

def test_the_bench_script_names_its_commands_in_its_own_docstring():
    """The usage text is what prints on a bad argument, so it has to be true."""
    tree = ast.parse(open(BENCH).read())
    doc = ast.get_docstring(tree)
    commands = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "COMMANDS"
                for t in node.targets):
            commands = [k.value for k in node.value.keys]
    assert commands, "bench/blinky.py defines no COMMANDS"
    for name in commands:
        assert "blinky.py %s" % name in doc, (
            "%r is a command but the docstring never shows it" % name)


def test_the_bench_script_reaches_for_the_wide_input_range():
    """3.3 V logic clips flat on the +/-2.5 V range, which is called 'high'."""
    const = bench_constants()
    assert const["RANGE"] == "low"
