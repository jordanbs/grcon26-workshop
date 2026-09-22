"""M2K Digital Source and Sink -- the 16 DIO pins.

Three IIO devices are involved and none of them is optional:

    m2k-logic-analyzer      per-pin configuration. `direction` decides
                            whether a pin is an input or an output, and
                            it lives HERE, not on either data device.
                            So does `raw`, the idle level.
    m2k-logic-analyzer-rx   the samples coming in, and the trigger.
    m2k-logic-analyzer-tx   the samples going out.

A pin is an input or an output, never both, so a source and a sink in
the same flowgraph must share no pin. Each block takes its own list --
`pins=[3, 7, 1]` -- and that list is the port order, not merely a set:
port 0 carries whichever pin you named first. Each block writes
`direction` for its own pins at construction, so where two lists DO
overlap, whichever is built last wins and the other block silently
reads or drives nothing.

Nothing here is protocol-aware. Three lines are three lines; whether
they are SPI's clock, data and select or a latch strobe beside a data
bus is the business of whatever block reads them next. Lines may be
named -- `names=['SCLK', 'MOSI', 'CS']` -- and the names change no
behaviour whatever. They only mean a mistake reports itself as
`MOSI (DIO7)` instead of `DIO7`, which is the difference between a
wiring error you can see and one you have to go and look up.

An output pin has two sources of truth. The stream drives it while the
flowgraph runs; `raw` drives it the rest of the time, and the pin snaps
back to `raw` the moment the flowgraph stops. The sink's idle level sets
`raw`, which is the only way to say what the pins should do when nothing
is playing.

One port per pin, carrying one bit per sample in a short. That is
gr-iio's model, not a choice made here: each DIO pin is its own IIO
channel with a 1-bit scan element.

Those sixteen channels are not sixteen samples. They are sixteen 1-bit
fields inside ONE 16-bit word, each at a shift equal to its pin number,
and this is why the sink does not use gr-iio's device_sink. See
`_packed_sink` for the whole story; the short version is that
device_sink writes each channel with a full-width store to the same
address, so every pin erases the one before it and only the highest
survives. The sink here packs the word itself and writes raw bytes.

The source has no such problem -- reading a shared word and handing out
one bit per port is exactly what libiio's demux does correctly -- so
`digital_source` is plain gr-iio.
"""

import numpy

from gnuradio import gr
from gnuradio import iio

from .m2k_config import (context, release, write_channel_attr,
                         write_device_attr, write_now)

DEV_CONFIG = "m2k-logic-analyzer"
DEV_RX = "m2k-logic-analyzer-rx"
DEV_TX = "m2k-logic-analyzer-tx"

PIN_COUNT = 16

# The digital side publishes no sampling_frequency_available, unlike the
# scope and the generator. These are the decade divisions of the same
# 100 MS/s clock. All six are confirmed on the bench, timed against the
# scope rather than read back -- see docs/bench-checklist.md section 7.
DIGITAL_SAMPLE_RATES = [100000000, 10000000, 1000000, 100000, 10000, 1000]

# What an output pin does when the flowgraph is not running, and the
# value that goes into `raw` to mean it. 'leave' is the third choice and
# writes nothing at all.
IDLE_LEVELS = {"low": 0, "high": 1}

# m2k-logic-analyzer-rx voltageN trigger_available, minus 'none'. 'none'
# is not offered as a condition because "off" is the pin selector's job.
DIGITAL_TRIGGER_CONDITIONS = ["edge-rising", "edge-falling", "edge-any",
                              "level-high", "level-low"]


def pins_for(pins):
    """Channel ids for a list of DIO pin numbers, in the order given.

    The list is the port order. `pins_for([6, 2, 0])` puts DIO6 on port
    0, and that is a supported thing to ask for rather than an accident
    worth guarding against: gr-iio's device_source reads channels in
    the order the caller lists them, and the sink packs each pin at its
    own bit shift. Neither cares whether the numbers ascend.

    Which means the pins need not be adjacent either. Wire a bus across
    DIO3, DIO7 and DIO1 because that is where the jumpers reach, and
    say so here.
    """
    if isinstance(pins, (str, bytes)) or not hasattr(pins, "__iter__"):
        raise ValueError(
            "pins must be a list of DIO numbers like [0, 1, 2], got %r"
            % (pins,))
    numbers = []
    for pin in pins:
        try:
            numbers.append(int(pin))
        except (TypeError, ValueError):
            raise ValueError(
                "DIO pin numbers must be whole numbers, got %r" % (pin,))
    if not numbers:
        raise ValueError("a digital block needs at least one pin")
    if len(numbers) > PIN_COUNT:
        raise ValueError("the M2K has %d DIO pins, so %d will not fit"
                         % (PIN_COUNT, len(numbers)))
    for number in numbers:
        if number < 0 or number >= PIN_COUNT:
            raise ValueError("DIO%d does not exist; the M2K has DIO0 to DIO%d"
                             % (number, PIN_COUNT - 1))
    repeated = sorted(set(n for n in numbers if numbers.count(n) > 1))
    if repeated:
        raise ValueError(
            "each pin can drive or read only one port, but DIO%s appears "
            "more than once"
            % ", DIO".join(str(number) for number in repeated))
    return ["voltage%d" % number for number in numbers]


def pin_label(channel):
    """'voltage3' -> 'DIO3', for error messages people have to read."""
    return "DIO" + channel[len("voltage"):]


def pin_shift(channel):
    """'voltage3' -> 3, the bit this pin occupies in the output word."""
    return int(channel[len("voltage"):])


def line_names(names, count):
    """One name per line, or None for a line that was not named.

    Naming is optional and always has been -- a blank name is not an
    error, it just leaves that line reporting as its pin.
    """
    if names is None:
        return [None] * count
    if isinstance(names, (str, bytes)):
        raise ValueError(
            "names must be a list, one per line, like ['SCLK', 'MOSI'], "
            "got %r" % (names,))
    names = [str(name).strip() or None for name in names]
    if len(names) != count:
        raise ValueError("there are %d lines but %d name%s"
                         % (count, len(names), "" if len(names) == 1 else "s"))
    return names


def line_label(channel, name=None):
    """How a line is named in an error: 'MOSI (DIO7)', or just 'DIO7'."""
    pin = pin_label(channel)
    return "%s (%s)" % (name, pin) if name else pin


def pack_word(values, shifts):
    """One 16-bit output word from one sample of every port.

    `values` is one sample per port and `shifts` the pin number each
    port drives. The bit position is the PIN, not the port: a sink
    starting at DIO4 puts its first port in bit 4, because that is the
    shift the hardware gave that channel.

    Anything non-zero is a one. Ports are one bit each, so a stream of
    counts rather than levels would otherwise silently truncate.
    """
    word = 0
    for value, shift in zip(values, shifts):
        if int(value) != 0:
            word |= 1 << shift
    return word


class _digital(gr.hier_block2):
    """Shared plumbing: pick the pins, set their direction, stream."""

    def __init__(self, name, uri, pins, sample_rate, buffer_size,
                 direction, names=None):
        self.pins = pins_for(pins)
        self.names = line_names(names, len(self.pins))
        self.labels = [line_label(pin, name)
                       for pin, name in zip(self.pins, self.names)]
        self._config = []
        self._make_signature(name, len(self.pins))

        # Direction first: a pin driven as an output while still
        # configured as an input does nothing at all.
        for pin in self.pins:
            self._write(uri, DEV_CONFIG, pin, "direction", direction)

        self.params = ["sampling_frequency=%d" % int(sample_rate)]
        self.buffer_size = int(buffer_size)
        self.uri = uri

    def _write(self, uri, device, channel, attr, value):
        """Set an attribute, and keep it set for as long as we run."""
        write_channel_attr(self, self._config, uri, device, channel,
                           attr, value)

    def _write_once(self, uri, device, channel, attr, value):
        """Set an attribute now and then leave it alone."""
        write_now(uri, device, channel, attr, value, keepalive=False)

    def _write_device(self, uri, device, attr, value):
        """Set a device-level attribute, and keep it set."""
        write_device_attr(self, self._config, uri, device, attr, value)


class _packed_sink(gr.sync_block):
    """The DIO output stream, packed by hand rather than by gr-iio.

    gr-iio's device_sink cannot drive more than one DIO pin, and it does
    not say so -- it reports success and the extra pins simply never
    move. This block exists to work around that, so it is worth writing
    down why, because the failure is invisible from the outside.

    The sixteen logic-analyzer channels are not sixteen samples side by
    side. They are sixteen 1-bit fields inside ONE 16-bit word, each at
    a shift equal to its pin number, which is why `iio_buffer_step` is 2
    bytes whether you enable one channel or all sixteen. libiio knows
    this; `iio_buffer_first` hands back the SAME address for every one
    of them.

    device_sink's inner loop then does:

        for each channel i:
            iio_channel_convert_inverse(chan[i], dst, src[i])

    and convert_inverse is a full-width store, not a read-modify-write.
    So channel i+1 writes its own bit and zeroes every other bit in the
    word, erasing channel i. Measured on the bench:

        ch0 <- 1,1,1,1   buffer = 0100 0100 0100 0100
        ch1 <- 0,0,0,0   buffer = 0000 0000 0000 0000
        ch1 <- 1,1,1,1   buffer = 0200 0200 0200 0200

    Only the last channel in the list survives, which for us is the
    highest-numbered pin. A three-pin bus drives one wire.

    The way out is to never let convert_inverse near the buffer.
    `Buffer.write` copies raw bytes, so we pack the word ourselves --
    one 16-bit word per sample, bit per pin -- and the DMA gets exactly
    what the hardware wants. See docs/gr-iio-multipin-sink.md.

    Two consequences worth knowing:

    The buffer is allocated in `start`, not here. A sink that is
    constructed and never started must not hold the DMA, because
    building a sink and leaving the flowgraph stopped is how you set a
    static output level.

    A cyclic buffer takes exactly one push; later pushes return -EBUSY.
    So we push once and then quietly consume the rest of the stream,
    rather than pushing into an error every buffer and printing the
    `Device or resource busy` warning that gr-iio prints.
    """

    def __init__(self, uri, pins, buffer_size, cyclic):
        gr.sync_block.__init__(
            self, name="m2k_digital_packed_sink",
            in_sig=[numpy.int16] * len(pins), out_sig=[])
        self.uri = uri
        self.pins = list(pins)
        self.shifts = [pin_shift(pin) for pin in self.pins]
        self.buffer_size = int(buffer_size)
        self.cyclic = bool(cyclic)
        self._buffer = None
        self._staged = None
        self._pushed = False

    def start(self):
        """Claim the pins we drive and allocate the DMA buffer.

        Every other channel is disabled deliberately. Our packed word
        carries all sixteen bits, so a channel left enabled by whatever
        ran last would be driven by a bit we never set -- low, and
        silently. This is also why there is only room for one digital
        sink in a flowgraph: one tx device, one buffer, one word.
        """
        import iio as pyiio

        device = context(self.uri).find_device(DEV_TX)
        if device is None:
            raise RuntimeError("no %s at %s" % (DEV_TX, self.uri))
        wanted = set(self.pins)
        for channel in device.channels:
            channel.enabled = channel.id in wanted

        self._buffer = pyiio.Buffer(device, self.buffer_size, self.cyclic)
        self._staged = numpy.empty(0, dtype=numpy.uint16)
        self._pushed = False
        return True

    def stop(self):
        """Release the buffer, which is what stops the pins driving.

        The pins then fall back to `raw`, the idle level. Dropping the
        reference is the release; pylibiio destroys the buffer with it.
        """
        self._buffer = None
        self._staged = None
        return True

    def work(self, input_items, output_items):
        count = len(input_items[0])

        # A cyclic buffer is already repeating on the hardware. Take the
        # samples so upstream keeps running and throw them away.
        if self._pushed:
            return count

        words = numpy.zeros(count, dtype=numpy.uint32)
        for port, shift in enumerate(self.shifts):
            words |= (input_items[port] != 0).astype(numpy.uint32) << shift
        self._staged = numpy.concatenate(
            (self._staged, words.astype(numpy.uint16)))

        # The DMA takes whole buffers only, so partial ones wait here.
        while len(self._staged) >= self.buffer_size and not self._pushed:
            self._buffer.write(
                bytearray(self._staged[:self.buffer_size].tobytes()))
            self._buffer.push()
            self._staged = self._staged[self.buffer_size:]
            self._pushed = self.cyclic

        return count


class digital_source(_digital):
    """Read the DIO pins. One output port per pin, in the order listed."""

    def __init__(self, uri="ip:192.168.2.1", pins=(0,),
                 sample_rate=1000000, buffer_size=16384, names=None,
                 trigger_pin="off", trigger_condition="edge-rising",
                 trigger_delay=0):
        _digital.__init__(self, "m2k_digital_source", uri, pins,
                          sample_rate, buffer_size, "in", names)
        self._apply_trigger(uri, trigger_pin, trigger_condition, trigger_delay)
        # Configuration first, then the streaming block -- on USB these
        # two cannot both hold the interface, and the samples win. See
        # m2k_config.release. The digital SINK is the exception: its data
        # path is pylibiio's Buffer, so it keeps the context it has.
        release(uri)
        self.source = iio.device_source(
            uri, DEV_RX, self.pins, DEV_RX, self.params, self.buffer_size, 0)
        self.source.set_len_tag_key("packet_len")
        for index in range(len(self.pins)):
            self.connect((self.source, index), (self, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(0, 0, 0),
            gr.io_signature(nports, nports, gr.sizeof_short))

    def _apply_trigger(self, uri, trigger_pin, condition, delay):
        """Arm the trigger on one pin, or free-run.

        Every pin carries its own `trigger`, and 'none' on all of them is
        what free-running means -- there is no separate off switch, the
        same shape as the scope's 'always'.

        `trigger_logic_mode` and `trigger_mux_out` are written every time
        rather than only when arming. Both are board state that outlives
        the program that set them, and either one left over from
        something else -- 'and' across pins that are not triggering, or a
        mux pointing at the external trigger input -- stops a perfectly
        correct single-pin trigger from ever firing. A trigger that never
        fires looks like a hung flowgraph, not like a wrong setting.
        """
        armed = None
        if trigger_pin != "off":
            armed = "voltage%d" % int(trigger_pin)
            if armed not in self.pins:
                raise ValueError(
                    "the trigger pin %s is not one of the pins this block "
                    "reads (%s)"
                    % (pin_label(armed), ", ".join(self.labels)))
            if condition not in DIGITAL_TRIGGER_CONDITIONS:
                raise ValueError(
                    "trigger condition must be one of %s, got %r"
                    % (", ".join(DIGITAL_TRIGGER_CONDITIONS), condition))

        first = self.pins[0]
        self._write(uri, DEV_RX, first, "trigger_logic_mode", "or")
        self._write(uri, DEV_RX, first, "trigger_mux_out", "trigger-logic")
        self._write(uri, DEV_RX, first, "trigger_delay", int(delay))

        for pin in self.pins:
            self._write(uri, DEV_RX, pin, "trigger",
                        condition if pin == armed else "none")


class digital_sink(_digital):
    """Drive the DIO pins. One input port per pin, in the order listed.

    Only one of these per flowgraph. There is a single tx device, a
    single DMA buffer and a single 16-bit word behind all sixteen pins,
    so a second sink would take the buffer away from the first and
    overwrite its bits. A source alongside it is fine -- that is a
    different device -- as long as the two share no pin.

    The stream is packed in Python rather than by gr-iio, for reasons
    `_packed_sink` explains at length. That puts Python in the path of
    every buffer, which costs nothing at the rates a bus demo uses:
    1 MS/s with the default 16384-sample buffer is 61 pushes a second.
    100 MS/s is 6100 a second and will not keep up. Nothing enforces
    this, because whether it matters depends on the buffer size as much
    as the rate -- a bigger buffer buys headroom in exchange for
    latency.
    """

    def __init__(self, uri="ip:192.168.2.1", pins=(0,),
                 sample_rate=1000000, buffer_size=16384,
                 drive="push-pull", cyclic=False, names=None,
                 idle_level="low"):
        _digital.__init__(self, "m2k_digital_sink", uri, pins,
                          sample_rate, buffer_size, "out", names)
        for pin in self.pins:
            self._write(uri, DEV_CONFIG, pin, "outputmode", drive)
        self._apply_idle(uri, idle_level)
        # device_sink applied this through its `params`; the packed sink
        # does not take params, so the rate is written like every other
        # attribute. It is a device attribute, not a channel one.
        self._write_device(uri, DEV_TX, "sampling_frequency",
                           int(sample_rate))
        self.sink = _packed_sink(uri, self.pins, self.buffer_size, cyclic)
        for index in range(len(self.pins)):
            self.connect((self, index), (self.sink, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(nports, nports, gr.sizeof_short),
            gr.io_signature(0, 0, 0))

    def _apply_idle(self, uri, idle_level):
        """Set what the pins do when the flowgraph is not running.

        `raw` is a second output register, entirely separate from the
        stream. The stream wins while the flowgraph runs; the moment it
        stops, the pins snap back to whatever `raw` holds. Note that this
        is the opposite of the analog generator, which keeps playing its
        last cyclic buffer with the flowgraph stopped.

        'leave' is offered but is not the default, because leaving it
        alone means the resting level is whatever the last program to
        touch this board happened to set -- invisible from the flowgraph
        and different every session.

        Written once, with no keep-alive. A keep-alive here would spend
        the whole run rewriting a register the stream is deliberately
        overriding, once a second, for no reason.
        """
        if idle_level not in IDLE_LEVELS and idle_level != "leave":
            raise ValueError(
                "idle level must be one of %s, got %r"
                % (", ".join(sorted(IDLE_LEVELS) + ["leave"]), idle_level))
        if idle_level == "leave":
            return
        for pin in self.pins:
            self._write_once(uri, DEV_CONFIG, pin, "raw",
                             IDLE_LEVELS[idle_level])
