"""Which DIO pins each digital block claims, and in what order.

`pins_for` decides this, and getting it wrong is expensive: a source and
a sink that share a pin fight over `direction`, and the loser reads or
drives nothing without saying so. The order matters just as much -- the
list is the port order, so a list written wrong wires the bus wrong and
still runs. These are the only tests that pin the mapping down.

`m2k_blocks.digital` imports gnuradio, which is usually not the
interpreter running this suite, so the checks run in the same borrowed
Python that test_grc_integration finds.
"""

import json
import os

import pytest

from test_grc_integration import needs_gnuradio, run_in_gr

PRELUDE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import pins_for, line_names, line_label, PIN_COUNT
'''


def pins(repo_root, expr):
    """Evaluate `expr` against pins_for in the gnuradio interpreter."""
    out = run_in_gr(PRELUDE + "print(json.dumps(%s))" % expr,
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


def raises(repo_root, expr):
    """The ValueError message `expr` raises, or None."""
    script = PRELUDE + '''
try:
    %s
except ValueError as exc:
    print(json.dumps(str(exc)))
else:
    print(json.dumps(None))
''' % expr
    return json.loads(run_in_gr(script, os.path.join(repo_root, "gr-m2k")))


def refused(repo_root, expr):
    """The ValueError message pins_for raises for `expr`, or None."""
    return raises(repo_root, "pins_for(%s)" % expr)


@needs_gnuradio
def test_one_pin_is_one_channel(repo_root):
    assert pins(repo_root, "pins_for([0])") == ["voltage0"]
    assert pins(repo_root, "pins_for([15])") == ["voltage15"]


@needs_gnuradio
def test_the_list_is_the_port_order(repo_root):
    """Port 0 carries whichever pin was named first, not the lowest one.

    gr-iio's device_source reads channels in the order the caller lists
    them, so this is a promise the hardware keeps, not a convenience.
    """
    assert pins(repo_root, "pins_for([6, 2, 0])") == [
        "voltage6", "voltage2", "voltage0"]


@needs_gnuradio
def test_pins_need_not_be_adjacent(repo_root):
    """Wire the bus where the jumpers reach and say so here."""
    assert pins(repo_root, "pins_for([3, 7, 1])") == [
        "voltage3", "voltage7", "voltage1"]


@needs_gnuradio
def test_a_sink_and_source_can_be_kept_apart(repo_root):
    """No shared pin, no fight over direction."""
    sink = pins(repo_root, "pins_for([0, 1, 2])")
    source = pins(repo_root, "pins_for([4, 5, 6])")
    assert not set(sink) & set(source)


@needs_gnuradio
def test_the_full_span_still_fits(repo_root):
    assert len(pins(repo_root, "pins_for(list(range(16)))")) == 16


@needs_gnuradio
@pytest.mark.parametrize("expr,word", [
    ("[]", "at least one"),
    ("list(range(17))", "will not fit"),
    ("[-1]", "DIO-1 does not exist"),
    ("[16]", "DIO16 does not exist"),
    ("[0, 1, 0]", "more than once"),
    ("['clk']", "whole numbers"),
    ("'012'", "must be a list"),
    ("7", "must be a list"),
])
def test_a_pin_list_that_cannot_work_is_refused(repo_root, expr, word):
    """Every one of these would otherwise be a flowgraph that runs wrong."""
    message = refused(repo_root, expr)
    assert message is not None, expr
    assert word in message, message


@needs_gnuradio
def test_a_repeated_pin_names_itself(repo_root):
    """Which pin was doubled is the whole of what you need to know."""
    message = refused(repo_root, "[4, 9, 4, 9, 2]")
    assert message is not None
    assert "DIO4, DIO9" in message


# ---------------------------------------------------------------- names

# Names change no behaviour at all. They exist so a mistake reports
# itself as 'MOSI (DIO7)' rather than 'DIO7', which is the difference
# between a wiring error you can see and one you have to go look up.


@needs_gnuradio
def test_naming_is_optional(repo_root):
    assert pins(repo_root, "line_names(None, 3)") == [None, None, None]


@needs_gnuradio
def test_a_blank_name_is_not_an_error(repo_root):
    """Half a bus named is a normal thing to have typed."""
    assert pins(repo_root, "line_names(['SCLK', '', '  '], 3)") == [
        "SCLK", None, None]


@needs_gnuradio
def test_one_name_per_line_or_none(repo_root):
    message = raises(repo_root, "line_names(['a', 'b'], 3)")
    assert message is not None
    assert "3 lines but 2 names" in message


@needs_gnuradio
def test_a_bare_string_is_not_a_list_of_names(repo_root):
    """'SCLK' is three names to len() and one to everybody else."""
    message = raises(repo_root, "line_names('SCLK', 4)")
    assert message is not None
    assert "must be a list" in message


@needs_gnuradio
def test_a_named_line_reports_both(repo_root):
    assert pins(repo_root, "line_label('voltage7', 'MOSI')") == "MOSI (DIO7)"


@needs_gnuradio
def test_an_unnamed_line_reports_its_pin(repo_root):
    assert pins(repo_root, "line_label('voltage7')") == "DIO7"


# --------------------------------------------------------------- config

# _apply_trigger and _apply_idle are the whole of what the trigger and the
# idle level do, and both are pure attribute writes. Running them against
# a stub that records the writes tests the real code without a board --
# which matters, because on a board a wrong attribute is silent.

CONFIG_PRELUDE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import (digital_source, digital_sink, pins_for,
                                line_names, line_label)


class Stub(object):
    """Everything _apply_* touches, without a hier block or a board."""

    def __init__(self, pins, names=None):
        self.pins = pins_for(pins)
        self.names = line_names(names, len(self.pins))
        self.labels = [line_label(pin, name)
                       for pin, name in zip(self.pins, self.names)]
        self.writes = []

    def _write(self, uri, device, channel, attr, value):
        self.writes.append([device, channel, attr, str(value)])

    _write_once = _write
'''


def writes(repo_root, body):
    """The attribute writes `body` makes, as [device, channel, attr, value]."""
    out = run_in_gr(CONFIG_PRELUDE + body + "\nprint(json.dumps(s.writes))",
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


def rejected(repo_root, body):
    """The ValueError message `body` raises, or None."""
    script = CONFIG_PRELUDE + '''
try:
%s
except ValueError as exc:
    print(json.dumps(str(exc)))
else:
    print(json.dumps(None))
''' % "\n".join("    " + line for line in body.strip().splitlines())
    return json.loads(run_in_gr(script, os.path.join(repo_root, "gr-m2k")))


def attr(records, channel, name):
    """The last value written to one attribute, or None."""
    found = [value for _, chan, key, value in records
             if chan == channel and key == name]
    return found[-1] if found else None


@needs_gnuradio
def test_free_running_disarms_every_pin(repo_root):
    """'none' on all of them is the only way to say off."""
    records = writes(repo_root, '''
s = Stub([0, 1, 2, 3])
digital_source._apply_trigger(s, "ip:none", "off", "edge-rising", 0)
''')
    for pin in ["voltage%d" % i for i in range(4)]:
        assert attr(records, pin, "trigger") == "none", pin


@needs_gnuradio
def test_arming_touches_one_pin_and_disarms_the_rest(repo_root):
    records = writes(repo_root, '''
s = Stub([0, 1, 2, 3])
digital_source._apply_trigger(s, "ip:none", "2", "edge-falling", 0)
''')
    assert attr(records, "voltage2", "trigger") == "edge-falling"
    for pin in ["voltage0", "voltage1", "voltage3"]:
        assert attr(records, pin, "trigger") == "none", pin


@needs_gnuradio
def test_the_trigger_pin_is_absolute_not_an_offset(repo_root):
    """DIO9 means DIO9, whichever pins the block happens to list."""
    records = writes(repo_root, '''
s = Stub([8, 9, 10, 11])
digital_source._apply_trigger(s, "ip:none", "9", "edge-rising", 0)
''')
    assert attr(records, "voltage9", "trigger") == "edge-rising"
    assert attr(records, "voltage8", "trigger") == "none"


@needs_gnuradio
@pytest.mark.parametrize("pin", ["off", "0"])
def test_leftover_board_state_is_always_overwritten(repo_root, pin):
    """A stale 'and', or a mux pointing elsewhere, silently eats the
    trigger. Both are rewritten whether we are arming or not."""
    records = writes(repo_root, '''
s = Stub([0, 1])
digital_source._apply_trigger(s, "ip:none", "%s", "edge-rising", 7)
''' % pin)
    assert attr(records, "voltage0", "trigger_logic_mode") == "or"
    assert attr(records, "voltage0", "trigger_mux_out") == "trigger-logic"
    assert attr(records, "voltage0", "trigger_delay") == "7"


@needs_gnuradio
def test_a_trigger_pin_outside_the_range_is_refused(repo_root):
    """Otherwise it is a capture that never fires, which looks like a hang."""
    message = rejected(repo_root, '''
s = Stub([4, 5])
digital_source._apply_trigger(s, "ip:none", "9", "edge-rising", 0)
''')
    assert message is not None
    assert "DIO9" in message and "DIO4" in message and "DIO5" in message


@needs_gnuradio
def test_the_refusal_names_the_lines_you_named(repo_root):
    """The point of naming: 'CS (DIO5)' says which wire to go and move."""
    message = rejected(repo_root, '''
s = Stub([4, 5], ["MOSI", "CS"])
digital_source._apply_trigger(s, "ip:none", "9", "edge-rising", 0)
''')
    assert message is not None
    assert "MOSI (DIO4)" in message and "CS (DIO5)" in message


@needs_gnuradio
def test_an_unknown_trigger_condition_is_refused(repo_root):
    message = rejected(repo_root, '''
s = Stub([0, 1])
digital_source._apply_trigger(s, "ip:none", "0", "edge-sideways", 0)
''')
    assert message is not None
    assert "edge-sideways" in message


@needs_gnuradio
def test_the_condition_is_not_checked_when_free_running(repo_root):
    """Nothing reads it, so nothing should complain about it."""
    records = writes(repo_root, '''
s = Stub([0])
digital_source._apply_trigger(s, "ip:none", "off", "nonsense", 0)
''')
    assert attr(records, "voltage0", "trigger") == "none"


@needs_gnuradio
@pytest.mark.parametrize("level,raw", [("low", "0"), ("high", "1")])
def test_the_idle_level_sets_raw_on_every_pin(repo_root, level, raw):
    records = writes(repo_root, '''
s = Stub([0, 1, 2])
digital_sink._apply_idle(s, "ip:none", "%s")
''' % level)
    for pin in ["voltage0", "voltage1", "voltage2"]:
        assert attr(records, pin, "raw") == raw, pin


@needs_gnuradio
def test_leave_as_found_writes_nothing(repo_root):
    records = writes(repo_root, '''
s = Stub([0, 1, 2])
digital_sink._apply_idle(s, "ip:none", "leave")
''')
    assert records == []


@needs_gnuradio
def test_an_unknown_idle_level_is_refused(repo_root):
    message = rejected(repo_root, '''
s = Stub([0])
digital_sink._apply_idle(s, "ip:none", "floating")
''')
    assert message is not None
    assert "floating" in message


# -------------------------------------------------------------- packing

PACK_PRELUDE = '''
import json, sys
import numpy
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import pack_word, pin_shift, _packed_sink

class FakeBuffer(object):
    """Records the words that would have reached the DMA."""

    def __init__(self):
        self.pushes = []
        self._pending = None

    def write(self, data):
        self._pending = bytes(data)
        return len(self._pending)

    def push(self):
        self.pushes.append(
            [int(w) for w in numpy.frombuffer(self._pending,
                                              dtype=numpy.uint16)])

def sink(pins, buffer_size, cyclic=False):
    """A packed sink wired to a fake buffer, so no board is involved."""
    s = _packed_sink("ip:none", pins, buffer_size, cyclic)
    s._buffer = FakeBuffer()
    s._staged = numpy.empty(0, dtype=numpy.uint16)
    s._pushed = False
    return s

def feed(s, streams):
    """One work() call. `streams` is a list of samples per port."""
    s.work([numpy.array(x, dtype=numpy.int16) for x in streams], [])
    return s._buffer.pushes
'''


def packed(repo_root, body):
    """Evaluate a packing snippet in the gnuradio interpreter."""
    out = run_in_gr(PACK_PRELUDE + body,
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


@needs_gnuradio
def test_every_port_reaches_the_word(repo_root):
    """The regression test for the gr-iio bug this sink exists to avoid.

    device_sink let each channel overwrite the whole word, so only the
    last pin survived. All three bits must be present at once.
    """
    pushes = packed(repo_root, '''
s = sink(["voltage0", "voltage1", "voltage2"], 4)
print(json.dumps(feed(s, [[1, 0, 1, 0], [1, 1, 0, 0], [1, 0, 0, 1]])))
''')
    assert pushes == [[0b111, 0b010, 0b001, 0b100]]


@needs_gnuradio
def test_the_bit_position_is_the_pin_not_the_port(repo_root):
    """A sink starting at DIO4 puts its first port in bit 4."""
    pushes = packed(repo_root, '''
s = sink(["voltage4", "voltage5"], 2)
print(json.dumps(feed(s, [[1, 0], [0, 1]])))
''')
    assert pushes == [[1 << 4, 1 << 5]]


@needs_gnuradio
def test_pack_word_agrees_with_the_streaming_path(repo_root):
    """The scalar helper and the vectorised one must not drift apart."""
    same = packed(repo_root, '''
pins = ["voltage2", "voltage3", "voltage7"]
shifts = [pin_shift(p) for p in pins]
rows = [[1, 0, 1], [0, 0, 0], [1, 1, 1], [0, 1, 0]]
s = sink(pins, 4)
streamed = feed(s, [[r[i] for r in rows] for i in range(3)])[0]
print(json.dumps([pack_word(r, shifts) for r in rows] == streamed))
''')
    assert same is True


@needs_gnuradio
def test_any_nonzero_sample_is_a_one(repo_root):
    """Ports are one bit. A stream of counts must not truncate to zero."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 3)
print(json.dumps(feed(s, [[2, 7, -1]])))
''')
    assert pushes == [[1, 1, 1]]


@needs_gnuradio
def test_a_partial_buffer_is_held_until_it_fills(repo_root):
    """The DMA takes whole buffers only."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 4)
first = list(feed(s, [[1, 1]]))
second = feed(s, [[0, 0]])
print(json.dumps([first, second]))
''')
    assert pushes == [[], [[1, 1, 0, 0]]]


@needs_gnuradio
def test_a_cyclic_buffer_is_pushed_exactly_once(repo_root):
    """Later pushes return -EBUSY, so we stop rather than provoke them."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 2, cyclic=True)
feed(s, [[1, 0]])
print(json.dumps(feed(s, [[1, 1, 0, 0]])))
''')
    assert pushes == [[1, 0]]


@needs_gnuradio
def test_a_plain_buffer_is_pushed_every_time_it_fills(repo_root):
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 2)
print(json.dumps(feed(s, [[1, 0, 0, 1, 1, 1]])))
''')
    assert pushes == [[1, 0], [0, 1], [1, 1]]


# ------------------------------------------------------------ unpacking

# The source is gr-iio's device_source everywhere except USB, where one
# interface is one context and the sink is already holding it. These
# cover the hand-rolled path that USB therefore takes.

UNPACK_PRELUDE = '''
import json, sys
import numpy
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import pack_word, pin_shift, _packed_source

class FakeBuffer(object):
    """Hands back a fixed buffer, so no board is involved."""

    def __init__(self, words):
        self.words = numpy.array(words, dtype=numpy.uint16)

    def refill(self):
        pass

    def read(self):
        return self.words.tobytes()

    def cancel(self):
        pass

def source(pins, words):
    s = _packed_source("ip:none", pins, len(words))
    s._buffer = FakeBuffer(words)
    s._staged = numpy.empty(0, dtype=numpy.uint16)
    return s

def drain(s, n, nports):
    """One work() call asking for `n` samples per port."""
    out = [numpy.zeros(n, dtype=numpy.int16) for _ in range(nports)]
    got = s.work([], out)
    return [[int(v) for v in o[:got]] for o in out]
'''


def unpacked(repo_root, body):
    """Evaluate an unpacking snippet in the gnuradio interpreter."""
    out = run_in_gr(UNPACK_PRELUDE + body,
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


@needs_gnuradio
def test_the_bit_read_is_the_pin_not_the_port(repo_root):
    """A source starting at DIO4 takes its first port from bit 4."""
    ports = unpacked(repo_root, '''
s = source(["voltage4", "voltage5"], [1 << 4, 1 << 5, (1 << 4) | (1 << 5), 0])
print(json.dumps(drain(s, 4, 2)))
''')
    assert ports == [[1, 0, 1, 0], [0, 1, 1, 0]]


@needs_gnuradio
def test_unpacking_is_the_packing_backwards(repo_root):
    """Source and sink must agree, or the loopback flowgraphs lie."""
    same = unpacked(repo_root, '''
pins = ["voltage2", "voltage3", "voltage7"]
shifts = [pin_shift(p) for p in pins]
rows = [[1, 0, 1], [0, 0, 0], [1, 1, 1], [0, 1, 0]]
words = [pack_word(r, shifts) for r in rows]
ports = drain(source(pins, words), len(rows), len(pins))
print(json.dumps([list(row) for row in zip(*ports)] == rows))
''')
    assert same is True


@needs_gnuradio
def test_a_buffer_is_drained_across_several_calls(repo_root):
    """The DMA hands over whole buffers; the scheduler asks for what fits.

    The remainder has to wait in order. Losing it here would drop
    samples silently, which on a decoded bus looks like corruption
    rather than like a bug in this block.
    """
    parts = unpacked(repo_root, '''
s = source(["voltage0"], [1, 0, 1, 1, 0, 1])
print(json.dumps([drain(s, 2, 1)[0] for _ in range(3)]))
''')
    assert parts == [[1, 0], [1, 1], [0, 1]]


@needs_gnuradio
def test_the_pins_we_do_not_read_stay_out_of_the_answer(repo_root):
    """One word carries all sixteen pins, and unwired ones float high.

    Masking is the only thing keeping that noise out of a port.
    """
    ports = unpacked(repo_root, '''
s = source(["voltage0"], [0xAE38, 0xAE39])
print(json.dumps(drain(s, 2, 1)))
''')
    assert ports == [[0, 1]]


# ------------------------------------------------------------ generated

# Sixteen pins and sixteen names, twice over, is six hundred lines of
# YAML that differ only by an index -- and a source and a sink that drift
# apart there wire a bus backwards with nothing to show for it. So the
# two ymls are generated and committed, and this is the check that the
# committed copy is still what the generator produces.


def generator():
    """gr-m2k/generate_digital_grc.py, imported. It needs nothing."""
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "gr-m2k", "generate_digital_grc.py")
    spec = importlib.util.spec_from_file_location("generate_digital_grc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name,template,verb,reads", [
    ("m2k_digital_source", "SOURCE", "read", "reads"),
    ("m2k_digital_sink", "SINK", "drive", "drives"),
])
def test_the_committed_yml_is_what_the_generator_writes(
        repo_root, name, template, verb, reads):
    """Edit the yml by hand and this fails; rerun the generator and it
    passes. That is the whole contract."""
    module = generator()
    fresh = module.render(getattr(module, template), verb, reads)
    path = os.path.join(repo_root, "gr-m2k", "grc", "%s.block.yml" % name)
    with open(path) as handle:
        committed = handle.read()
    assert committed == fresh, "%s is out of date; rerun %s" % (
        path, "gr-m2k/generate_digital_grc.py")


def test_both_blocks_get_the_same_sixteen_lines(repo_root):
    """A source that maps DIO7 differently from a sink is unfindable."""
    module = generator()
    source = module.render(module.SOURCE, "read", "reads")
    sink = module.render(module.SINK, "drive", "drives")
    for index in range(16):
        for key in ("pin%d" % index, "name%d" % index):
            assert ("id: %s\n" % key) in source, key
            assert ("id: %s\n" % key) in sink, key
    assert module.PINS in source and module.PINS in sink
