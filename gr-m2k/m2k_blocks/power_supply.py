"""M2K Power Supply -- one of the two +/-5 V rails, set in volts.

The M2K has a pair of programmable supplies on the header, V+ and V-,
and nothing on an add-on board works without them. The colorimeter's
transimpedance amplifier is the case in point: no rails, no photodiode
signal, and the flowgraph looks like a broken instrument rather than an
unpowered one.

Three things have to happen, on three different devices, and libm2k does
all three inside one `pushChannel()` call:

    ad5627      the 12-bit DAC that actually sets the voltage -- a `raw`
                attribute per rail, plus a `powerdown` of its own

    m2k-fabric  the rail's enable, one channel per rail, also called
                `powerdown`. libm2k reaches these by hardcoded index 2
                and 3; the board labels them `user_supply`, so this
                block asks for the label and keeps the index as a
                fallback

    the context the calibration. Four numbers -- a gain and an offset per
                rail -- stored as `cal,*` context attributes, on no
                device at all. Skip them and a commanded 5 V lands about
                a percent off, which is exactly the kind of error that
                reads as "the supply is fine" right up until you put a
                meter on it

Both `powerdown` attributes are inverted: 0 means the rail is on.

Nothing here is kept alive, and that is a departure from the rest of this
package. Everywhere else an attribute is written twice -- once
immediately, then repeatedly by an `attr_updater`/`attr_sink` pair --
because the updater alone leaves the first second of a run unconfigured.
Neither of this block's attributes can stand that treatment:

    the setpoint, because `iio.attr_updater` has no way to change its
    value once built. A keep-alive on `raw` would rewrite the voltage you
    started with, one second after you moved the slider.

    the two `powerdown` attributes, because a keep-alive holding them at
    0 is a keep-alive that turns the rail back on. `power_down()` would
    be undone within the second, which is the worst possible way for a
    teardown to fail. Nothing else on the board touches a rail enable, so
    the keep-alive was defending against nothing and preventing something
    that matters.

Every write here is therefore a single direct one. A side benefit: with
no `attr_sink` to construct, an unreachable board warns and carries on
rather than raising out of gr-iio, which is what `write_now` promises
everywhere else.

The rail stays up when the flowgraph stops. A hier block with no ports is
never scheduled, so its `stop()` is not a thing GNU Radio will call on
the way out -- the same shape as the cyclic buffer that keeps playing
after the graph ends. Call `power_down()` to take the rail off. Setting
the voltage to 0 is NOT the same thing: the rail stays enabled and an
attached amplifier stays biased at zero rather than unpowered.
"""

import threading

from gnuradio import gr

from .m2k_config import channels_with_label, context_float, write_now
from .m2k_scale import (SUPPLY_RESET_RAW, check_supply_rail,
                        supply_volts_to_raw)

# The DAC that sets the rails, and the fabric channel that enables them.
DEV_SUPPLY = "ad5627"
DEV_FABRIC = "m2k-fabric"

# ad5627's output channels, one per rail.
SUPPLY_CHANNEL = {"v+": "voltage0", "v-": "voltage1"}

# The fabric enables, in libm2k's order: index 2 is the positive rail,
# index 3 the negative. Used only when the label lookup cannot reach the
# board -- when it can, the board says which is which itself.
FABRIC_CHANNEL = {"v+": "voltage2", "v-": "voltage3"}
FABRIC_LABEL = "user_supply"

# The context attributes holding this board's rail calibration.
CAL_KEYS = {"v+": ("cal,gain_pos_dac", "cal,offset_pos_dac"),
            "v-": ("cal,gain_neg_dac", "cal,offset_neg_dac")}

# Slowest sensible cadence for setpoint writes, in seconds. A dragged
# slider emits a callback per pixel; each one is a network round trip to
# the board, and the intermediate voltages are of no interest to anyone.
MIN_WRITE_INTERVAL = 0.1


class power_supply(gr.hier_block2):
    """Hold one M2K rail at a commanded voltage."""

    def __init__(self, uri="ip:192.168.2.1", rail="v+", voltage=0.0,
                 calibrated=True, min_interval=MIN_WRITE_INTERVAL):

        check_supply_rail(rail)
        gr.hier_block2.__init__(
            self, "m2k_power_supply",
            gr.io_signature(0, 0, 0),
            gr.io_signature(0, 0, 0))

        self._uri = uri
        self._rail = rail
        self._min_interval = max(float(min_interval), 0.0)

        # Read once, at build time. These do not change while the board
        # is powered, and re-reading them per write would put a network
        # round trip in front of every slider movement.
        if calibrated:
            gain_key, offset_key = CAL_KEYS[rail]
            self._gain = context_float(uri, gain_key, 1.0)
            self._offset = context_float(uri, offset_key, 0.0)
        else:
            self._gain, self._offset = 1.0, 0.0

        # Trailing-edge rate limiter. `_pending` is the voltage a timer is
        # about to write; the lock covers both it and `_timer`, because
        # the timer thread and the GUI thread both touch them.
        self._lock = threading.Lock()
        self._timer = None
        self._pending = None
        self._last_raw = None

        # Resolved once. power_down() has to take down the same channel
        # power_up() brought up, and a board that goes away mid-run would
        # otherwise send the teardown to a different one.
        self._fabric = self._resolve_fabric_channel()
        self.power_up()
        self.set_voltage(voltage, now=True)

    def power_up(self):
        """Clear both powerdowns, parking the DAC before the rail comes up.

        Order matters. The DAC is set to its reset code first so the rail
        starts from a known place rather than from whatever the last
        program left in the register -- otherwise enabling the fabric can
        briefly put the previous session's voltage on the header.
        """
        self._set("raw", SUPPLY_RESET_RAW)
        # 0 means on, for both of them. The sense is inverted, per the
        # IIO ABI.
        self._set("powerdown", 0)
        self._set_fabric(0)

    def power_down(self):
        """Take the rail off: disable it, then park the DAC.

        The enable goes first, matching libm2k's powerDownDacs(), so the
        rail is already off before the register underneath it changes.

        Worth being clear about what this is for. GNU Radio will not call
        it -- a block with no ports is never scheduled -- so it is a
        button to wire up, or a line to run after the graph stops. An
        attached board stays biased until somebody calls it.
        """
        # Drop anything the rate limiter is holding first. A deferred
        # setpoint landing after the teardown would put a code back in a
        # register we just parked -- harmless while the rail is off, but
        # it makes the board's state disagree with what this object says.
        with self._lock:
            self._pending = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._set_fabric(1)
        self._set("powerdown", 1)
        self._set("raw", SUPPLY_RESET_RAW)
        self._last_raw = None

    def _set(self, attr, value):
        """One direct write to this rail's DAC channel."""
        # keepalive=False: nothing follows any of these up, and the
        # warning on failure should say so rather than promise an updater
        # that is not there.
        return write_now(self._uri, DEV_SUPPLY, SUPPLY_CHANNEL[self._rail],
                         attr, value, output=True, keepalive=False)

    def _set_fabric(self, value):
        """One direct write to this rail's fabric enable."""
        return write_now(self._uri, DEV_FABRIC, self._fabric,
                         "powerdown", value, output=True, keepalive=False)

    def _resolve_fabric_channel(self):
        """The fabric enable for this rail, by label where possible.

        Both rail channels carry `label=user_supply`, in device order:
        positive then negative. If the board cannot be reached the index
        libm2k hardcodes is the answer, and the write that follows will
        report its own failure.
        """
        labelled = channels_with_label(self._uri, DEV_FABRIC, FABRIC_LABEL)
        if len(labelled) >= 2:
            return labelled[0] if self._rail == "v+" else labelled[1]
        return FABRIC_CHANNEL[self._rail]

    def set_voltage(self, voltage, now=False):
        """Command a new rail voltage, at most one write per interval.

        Callable from a GUI widget while the graph runs. Writes that
        arrive faster than `min_interval` are collapsed: the most recent
        value is kept and written when the interval is up, so a dragged
        slider costs a handful of writes and still ends on the number it
        was released at.
        """
        volts = float(voltage)
        # Convert before deciding to defer, so a value out of range
        # raises here -- in the caller's hands -- rather than a tenth of
        # a second later on a timer thread where nothing will see it.
        raw = supply_volts_to_raw(volts, self._rail,
                                  self._gain, self._offset)

        with self._lock:
            if not now and self._min_interval > 0:
                self._pending = raw
                if self._timer is None:
                    self._timer = threading.Timer(self._min_interval,
                                                  self._flush)
                    self._timer.daemon = True
                    self._timer.start()
                return
            self._pending = None
        self._write_raw(raw)

    def _flush(self):
        """Write whatever the limiter is holding, once the interval is up."""
        with self._lock:
            self._timer = None
            raw, self._pending = self._pending, None
        if raw is not None:
            self._write_raw(raw)

    def _write_raw(self, raw):
        """The one write that actually moves the rail."""
        self._last_raw = raw
        self._set("raw", raw)

    def commanded_raw(self):
        """The last code written, for a flowgraph that wants to show it."""
        return self._last_raw
