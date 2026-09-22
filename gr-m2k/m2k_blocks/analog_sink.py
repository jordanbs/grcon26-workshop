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

from gnuradio import blocks
from gnuradio import gr
from gnuradio import iio

from .m2k_config import release, write_channel_attr
from .m2k_scale import (DAC_FULL_SCALE_V, DAC_SAMPLE_RATES,
                        check_dac_sample_rate, dac_filter_compensation,
                        volts_to_dac_raw)

# The output you pick is the device you get.
OUTPUT_DEVICE = {"w1": "m2k-dac-a", "w2": "m2k-dac-b"}

# Powering the output stage up lives on the fabric, as with the scope's
# input range -- a different device from the one taking the samples.
DEV_FABRIC = "m2k-fabric"
FABRIC_OUTPUT = {"w1": "voltage0", "w2": "voltage1"}


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

        # Configuration first, then the streaming block -- on USB these
        # two cannot both hold the interface, and the samples win. See
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
