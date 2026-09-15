"""GNU Radio blocks that treat the ADALM2000 as an instrument.

The stock IIO Device Source is general: it will talk to any IIO device on
any board, and the price is that every parameter is a name or a string you
have to already know. These blocks give that up in exchange for being
obvious. You pick a sample rate in samples per second, an input range in
volts and a trigger level in volts, and the block works out which
attribute on which of the M2K's fourteen IIO devices that means.

Nothing here needs anything beyond GNU Radio itself -- no libm2k, no
libiio Python bindings. Configuration that lives on a device other than
the streaming one is applied with gr-iio's own attribute blocks.

Only the arithmetic is re-exported here. The blocks themselves import
gnuradio, so they live in submodules and are imported directly:

    from m2k_blocks.analog_source import analog_source

That keeps `m2k_blocks.m2k_scale` importable -- and therefore testable --
on a machine with no GNU Radio at all.
"""

from .m2k_scale import (ADC_FILTER_COMP, BASE_RATE, DAC_FILTER_COMP,
                        RANGE_GAIN, RANGE_VOLTS, SAMPLE_RATES,
                        SUPPLY_MAX_V, SUPPLY_RAW_MAX, SUPPLY_READ_COEFF,
                        SUPPLY_RESET_RAW, SUPPLY_WRITE_COEFF,
                        adc_filter_compensation, check_sample_rate,
                        check_supply_rail, dac_filter_compensation,
                        divider_for, raw_to_volts, supply_raw_to_volts,
                        supply_volts_to_raw, volts_per_count, volts_to_raw)

__all__ = ["ADC_FILTER_COMP", "BASE_RATE", "DAC_FILTER_COMP", "RANGE_GAIN",
           "RANGE_VOLTS", "SAMPLE_RATES", "SUPPLY_MAX_V", "SUPPLY_RAW_MAX",
           "SUPPLY_READ_COEFF", "SUPPLY_RESET_RAW", "SUPPLY_WRITE_COEFF",
           "adc_filter_compensation", "check_sample_rate",
           "check_supply_rail", "dac_filter_compensation", "divider_for",
           "raw_to_volts", "supply_raw_to_volts", "supply_volts_to_raw",
           "volts_per_count", "volts_to_raw"]
