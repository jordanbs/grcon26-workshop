"""M2K Analog Sink -- the signal generator, W1 and W2.

The generator is not the scope with the arrows reversed, and the places
it differs are the places people get caught:

    Its base clock is 75 MS/s, not 100. The rate lists do not overlap, so
    a flowgraph that generates and captures at "the same rate" is doing
    no such thing unless both were chosen deliberately.

    Its volts-to-counts conversion inverts the sign. A positive voltage
    becomes a negative count. Convert by hand and your waveform comes out
    upside down.

    W1 and W2 are separate IIO devices, m2k-dac-a and m2k-dac-b, not two
    channels of one. Picking the output picks the device.

All three are handled here so nobody has to know them.
"""

import numpy

from gnuradio import blocks
from gnuradio import gr
from gnuradio import iio

from .m2k_config import (context, release, usb_backend, write_channel_attr,
                         write_device_attr)
from .m2k_scale import (DAC_FULL_SCALE_V, DAC_SAMPLE_RATES,
                        check_dac_sample_rate, dac_filter_compensation,
                        volts_to_dac_raw)

# The output you pick is the device you get.
OUTPUT_DEVICE = {"w1": "m2k-dac-a", "w2": "m2k-dac-b"}

# Powering the output stage up lives on the fabric, as with the scope's
# input range -- a different device from the one taking the samples.
DEV_FABRIC = "m2k-fabric"
FABRIC_OUTPUT = {"w1": "voltage0", "w2": "voltage1"}


class _dac_sink(gr.sync_block):
    """The generator output, written through pylibiio rather than gr-iio.

    Same reason as `_adc_source` on the scope side, and the same
    non-reason: gr-iio's device_sink drives one DAC channel perfectly
    well. It is the second CONTEXT that is the problem. A USB interface
    takes exactly one claim, the digital sink is forced onto pylibiio
    because device_sink cannot drive more than one DIO pin, and so on
    USB every m2k block has to share the one pylibiio context. See
    `m2k_config.release`.

    Unlike the digital sink there is no packing to do -- one channel,
    one int16 per sample -- so this is only the buffering.
    """

    def __init__(self, uri, device, buffer_size, cyclic):
        gr.sync_block.__init__(
            self, name="m2k_dac_sink",
            in_sig=[numpy.int16], out_sig=[])
        self.uri = uri
        self.device = device
        self.buffer_size = int(buffer_size)
        self.cyclic = bool(cyclic)
        self._buffer = None
        self._staged = None
        self._pushed = False

    def start(self):
        """Allocate the DMA buffer, as late as the sink does.

        Allocated here rather than in __init__ for the same reason as
        the digital sink: a block that is constructed and never started
        must not hold the DMA.
        """
        import iio as pyiio

        device = context(self.uri).find_device(self.device)
        if device is None:
            raise RuntimeError("no %s at %s" % (self.device, self.uri))
        for channel in device.channels:
            channel.enabled = channel.id == "voltage0"

        self._buffer = pyiio.Buffer(device, self.buffer_size, self.cyclic)
        self._staged = numpy.empty(0, dtype=numpy.int16)
        self._pushed = False
        return True

    def stop(self):
        """Drop the buffer.

        No `cancel` needed, unlike the sources: `push` does not block.
        Note that dropping a CYCLIC buffer stops the output, which is
        the opposite of what the block docstring says about the hardware
        continuing -- the waveform survives only as long as the buffer
        does.
        """
        self._buffer = None
        self._staged = None
        return True

    def work(self, input_items, output_items):
        count = len(input_items[0])

        # A cyclic buffer is already repeating on the hardware. Take the
        # samples so upstream keeps running and throw them away.
        if self._pushed or self._buffer is None:
            return count

        self._staged = numpy.concatenate((self._staged, input_items[0]))

        # The DMA takes whole buffers only, so partial ones wait here.
        while len(self._staged) >= self.buffer_size and not self._pushed:
            self._buffer.write(
                bytearray(self._staged[:self.buffer_size].tobytes()))
            self._buffer.push()
            self._staged = self._staged[self.buffer_size:]
            self._pushed = self.cyclic

        return count


class analog_sink(gr.hier_block2):
    """Play samples out of W1 or W2, in volts or in raw counts."""

    def __init__(self, uri="ip:192.168.2.1", output="w1",
                 sample_rate=750000, units="volts",
                 buffer_size=16384, cyclic=False):

        if output not in OUTPUT_DEVICE:
            raise ValueError("output must be 'w1' or 'w2', got %r" % (output,))

        as_volts = (units == "volts")
        item_size = gr.sizeof_float if as_volts else gr.sizeof_short
        gr.hier_block2.__init__(
            self, "m2k_analog_sink",
            gr.io_signature(1, 1, item_size),
            gr.io_signature(0, 0, 0))

        device = OUTPUT_DEVICE[output]

        self._config = []
        # The output stage is powered down until something says otherwise,
        # and 0 means on -- the sense is inverted, per the IIO ABI.
        write_channel_attr(self, self._config, uri, DEV_FABRIC,
                           FABRIC_OUTPUT[output], "powerdown", 0, output=True)

        if usb_backend(uri):
            # One interface, one context, shared with every other m2k
            # block in the flowgraph. See _dac_sink. The rate rode into
            # device_sink as `params`; with that block gone it has to be
            # written like any other attribute.
            write_device_attr(self, self._config, uri, device,
                              "sampling_frequency",
                              check_dac_sample_rate(sample_rate))
            self.sink = _dac_sink(uri, device, buffer_size, bool(cyclic))
        else:
            # Configuration first, then the streaming block -- these two
            # cannot both hold the interface, and the samples win. See
            # m2k_config.release.
            release(uri)
            self.sink = iio.device_sink(
                uri, device, ["voltage0"], device,
                ["sampling_frequency=%d" % check_dac_sample_rate(sample_rate)],
                buffer_size, 0, bool(cyclic))

        if as_volts:
            # Volts in, counts out, with libm2k's conversion including its
            # sign inversion. multiply_const then float_to_short would lose
            # the -0.5 term, so the scale and the offset are applied
            # separately and in that order.
            #
            # The interpolation filter's gain is in here too. Divide the
            # whole conversion by it, exactly as convVoltsToRaw does --
            # leave it out and the output is 16.4% too big at 750 kS/s,
            # which a meter will tell you and a loopback will not.
            comp = dac_filter_compensation(sample_rate)
            scale = blocks.multiply_const_ff(-1.0 / (_vlsb() * comp))
            offset = blocks.add_const_ff(-0.5 / comp)
            to_short = blocks.float_to_short(1, 1 << 4)
            self.connect(self, scale, offset, to_short, self.sink)
            self._config.extend([scale, offset, to_short])
        else:
            self.connect(self, self.sink)


def _vlsb():
    from .m2k_scale import DAC_VLSB
    return DAC_VLSB
