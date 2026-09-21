#!/usr/bin/env python3
"""
iio_semantics.py -- what IIO attribute names actually mean.

iio_discover.py answers "what is here and what is it set to". This module
answers "what is it". It imports nothing from libiio and never talks to
hardware; it works on the JSON that `iio_discover.py --json` produces, so
it runs on a laptop with no M2K plugged in.

The central claim of this file is that an attribute's meaning is mostly
*derivable*, not hand-written. The Linux IIO ABI (Documentation/ABI/
testing/sysfs-bus-iio) fixes two things for every IIO driver ever merged:

  1. The attribute name grammar:
         {in|out}_{type}{index}[_{modifier}]_{info}
     Parse it and you get direction, quantity, channel, and role for free.

  2. The unit of each channel type, and the arithmetic that gets you
     there:
         real value = (raw + offset) * scale
     Units are fixed per channel type and they are deliberately not SI
     base units -- voltage is millivolts, temperature is millidegrees.

Only what is left over after those two needs a hand-written device pack
(see iio_overlays.py). Every annotation this module produces carries a
provenance tag saying which of those it came from, so nothing gets taught
as fact that isn't one.
"""

import re


# ------------------------------------------------------------- provenance

PARSED = "parsed"        # read straight out of the attribute name
ABI = "abi"              # Linux IIO ABI, true of every IIO device
OVERLAY = "overlay"      # hand-written device pack, may be unverified
MEASURED = "measured"    # confirmed against real hardware


# ---------------------------------------------------------- channel types
#
# unit/symbol come from the IIO ABI. These are the units you get AFTER
# applying scale and offset -- and they are not the units you expect,
# which is the single most common source of "why is my scope trace 1000x
# too big" in a GNU Radio flowgraph.

CHANNEL_TYPES = {
    "voltage": {
        "si_unit": "volts", "si_symbol": "V",
        "quantity": "electrical potential",
        "unit": "millivolts", "symbol": "mV", "si_per_unit": 1e-3,
        "note": "millivolts, not volts",
    },
    "altvoltage": {
        "si_unit": "volts", "si_symbol": "V",
        "quantity": "a synthesised output tone",
        "unit": "millivolts", "symbol": "mV", "si_per_unit": 1e-3,
        "note": "a generator channel -- you drive it with frequency, "
                "phase and scale rather than by writing raw samples",
    },
    "current": {
        "si_unit": "amps", "si_symbol": "A",
        "quantity": "electrical current",
        "unit": "milliamps", "symbol": "mA", "si_per_unit": 1e-3,
        "note": "milliamps, not amps",
    },
    "power": {
        "si_unit": "watts", "si_symbol": "W",
        "quantity": "power",
        "unit": "milliwatts", "symbol": "mW", "si_per_unit": 1e-3,
        "note": "milliwatts, not watts",
    },
    "temp": {
        "si_unit": "degrees Celsius", "si_symbol": "'C",
        "quantity": "temperature",
        "unit": "millidegrees Celsius", "symbol": "m'C", "si_per_unit": 1e-3,
        "note": "millidegrees Celsius -- divide by 1000 for degrees",
    },
    "accel": {
        "quantity": "acceleration",
        "unit": "metres per second squared", "symbol": "m/s^2",
        "si_per_unit": 1.0, "note": None,
    },
    "anglvel": {
        "quantity": "angular velocity",
        "unit": "radians per second", "symbol": "rad/s",
        "si_per_unit": 1.0, "note": "radians, not degrees",
    },
    "magn": {
        "si_unit": "tesla", "si_symbol": "T",
        "quantity": "magnetic field",
        "unit": "Gauss", "symbol": "G", "si_per_unit": 1e-4,
        "note": "Gauss, not Tesla (1 G = 100 uT)",
    },
    "angl": {
        "quantity": "angle",
        "unit": "radians", "symbol": "rad", "si_per_unit": 1.0,
        "note": "radians, not degrees",
    },
    "pressure": {
        "si_unit": "pascal", "si_symbol": "Pa",
        "quantity": "pressure",
        "unit": "kilopascal", "symbol": "kPa", "si_per_unit": 1e3,
        "note": "kilopascal, not pascal",
    },
    "humidityrelative": {
        "si_unit": "percent", "si_symbol": "%",
        "quantity": "relative humidity",
        "unit": "milli percent", "symbol": "m%", "si_per_unit": 1e-3,
        "note": "milli percent -- divide by 1000 for percent",
    },
    "illuminance": {
        "quantity": "illuminance",
        "unit": "lux", "symbol": "lx", "si_per_unit": 1.0, "note": None,
    },
    "intensity": {
        "quantity": "light intensity",
        "unit": "no unit", "symbol": "", "si_per_unit": None,
        "note": "deliberately unitless -- an intensity channel is a "
                "relative reading, which is why colorimeters compare "
                "channels against a reference rather than reading one "
                "channel absolutely",
    },
    "proximity": {
        "quantity": "proximity",
        "unit": "no unit", "symbol": "", "si_per_unit": None,
        "note": "unitless and usually not monotonic in distance",
    },
    "resistance": {
        "quantity": "resistance",
        "unit": "ohms", "symbol": "ohm", "si_per_unit": 1.0, "note": None,
    },
    "capacitance": {
        "si_unit": "farads", "si_symbol": "F",
        "quantity": "capacitance",
        "unit": "nanofarads", "symbol": "nF", "si_per_unit": 1e-9,
        "note": "nanofarads, not farads",
    },
    "velocity": {
        "quantity": "speed",
        "unit": "metres per second", "symbol": "m/s", "si_per_unit": 1.0,
        "note": None,
    },
    "distance": {
        "quantity": "distance",
        "unit": "metres", "symbol": "m", "si_per_unit": 1.0, "note": None,
    },
    "concentration": {
        "quantity": "concentration",
        "unit": "percent", "symbol": "%", "si_per_unit": None, "note": None,
    },
    "massconcentration": {
        "quantity": "mass concentration",
        "unit": "micrograms per cubic metre", "symbol": "ug/m^3",
        "si_per_unit": None, "note": None,
    },
    "ph": {
        "quantity": "acidity",
        "unit": "pH units", "symbol": "pH", "si_per_unit": None, "note": None,
    },
    "cct": {
        "quantity": "correlated color temperature",
        "unit": "Kelvin", "symbol": "K", "si_per_unit": 1.0, "note": None,
    },
    "count": {
        "quantity": "a count of events",
        "unit": "no unit", "symbol": "", "si_per_unit": None, "note": None,
    },
    "steps": {
        "quantity": "step count",
        "unit": "no unit", "symbol": "", "si_per_unit": None, "note": None,
    },
    "timestamp": {
        "si_unit": "seconds", "si_symbol": "s",
        "quantity": "sample time",
        "unit": "nanoseconds", "symbol": "ns", "si_per_unit": 1e-9,
        "note": "not a measurement -- a per-sample clock reading the "
                "kernel interleaves into the buffer",
    },
}


# ------------------------------------------------------------- modifiers
#
# A modifier narrows a channel of a given type: which axis, which color,
# which gas. It appears between the index and the info word.

MODIFIERS = {
    "x": "the X axis", "y": "the Y axis", "z": "the Z axis",
    "red": "the red part of the spectrum",
    "green": "the green part of the spectrum",
    "blue": "the blue part of the spectrum",
    "clear": "unfiltered -- all wavelengths the sensor can see",
    "ir": "infrared", "uv": "ultraviolet",
    "i": "the in-phase component of a complex sample",
    "q": "the quadrature component of a complex sample",
    "co2": "carbon dioxide", "o2": "oxygen",
    "voc": "volatile organic compounds", "ethanol": "ethanol",
    "rising": "the rising edge", "falling": "the falling edge",
    "either": "either edge",
    "pm1": "particles under 1 um", "pm2p5": "particles under 2.5 um",
    "pm10": "particles under 10 um",
    "sqrt(x^2+y^2+z^2)": "the magnitude of the three axes combined",
}


# ------------------------------------------------------------ info words
#
# The last part of an attribute name says what role it plays. "unit" here
# describes the attribute's OWN value, which is often not the channel's
# unit: in_voltage0_raw is a count, in_voltage0_sampling_frequency is Hz.

_RAW_STAT = ("A %s of the raw samples, on the same scale as _raw. "
             "Apply offset and scale exactly as you would to _raw.")

INFO_WORDS = {
    "raw": {
        "unit": "no unit -- a count",
        "summary": "The unconverted number the converter produced. This is "
                   "not a measurement yet.",
        "detail": "A raw value is whatever integer came out of the ADC (or "
                  "goes into the DAC). It has no units and it is meaningless "
                  "on its own. Combine it with _scale and _offset to get a "
                  "real value.",
        "needs_conversion": True,
    },
    "input": {
        "unit": "the channel's unit",
        "summary": "The converted value, already in the channel's units. "
                   "No arithmetic needed.",
        "detail": "When a driver can do the conversion itself it exposes "
                  "_input instead of _raw. If you see _input, there is "
                  "nothing to scale -- read it and you are done.",
        "needs_conversion": False,
    },
    "scale": {
        "unit": "the channel's unit per count",
        "summary": "The multiplier that turns raw counts into real units.",
        "detail": "Multiply after adding offset: (raw + offset) * scale. "
                  "Changing scale usually means changing an actual hardware "
                  "gain or range, not just relabelling the numbers.",
        "needs_conversion": False,
    },
    "offset": {
        "unit": "counts",
        "summary": "Added to the raw value BEFORE scale is applied.",
        "detail": "The order matters and is the most common mistake: it is "
                  "(raw + offset) * scale, never raw * scale + offset. "
                  "Offset is in raw counts, not in the channel's units.",
        "needs_conversion": False,
    },
    "calibscale": {
        "unit": "dimensionless multiplier",
        "summary": "A calibration gain the driver applies on top of scale.",
        "detail": "Per-unit correction, usually written by a calibration "
                  "routine rather than by you. Distinct from _scale, which "
                  "describes the hardware range.",
        "needs_conversion": False,
    },
    "calibbias": {
        "unit": "counts",
        "summary": "A calibration offset the driver applies on top of offset.",
        "detail": "Per-unit zero correction, usually written by a "
                  "calibration routine. Distinct from _offset.",
        "needs_conversion": False,
    },
    "peak_raw": {"unit": "no unit -- a count",
                 "summary": _RAW_STAT % "peak", "detail": None,
                 "needs_conversion": True},
    "mean_raw": {"unit": "no unit -- a count",
                 "summary": _RAW_STAT % "mean", "detail": None,
                 "needs_conversion": True},
    "rms_raw": {"unit": "no unit -- a count",
                "summary": _RAW_STAT % "root-mean-square", "detail": None,
                "needs_conversion": True},
    "sampling_frequency": {
        "unit": "hertz",
        "summary": "How many samples per second this device or channel "
                   "produces.",
        "detail": "In a GNU Radio flowgraph this must match the sample rate "
                  "you tell every downstream block, or every frequency axis "
                  "you plot will be wrong by exactly the ratio.",
        "needs_conversion": False,
    },
    "oversampling_ratio": {
        "unit": "no unit -- a ratio",
        "summary": "How many hardware samples get combined into one sample "
                   "you receive.",
        "detail": "Raising it lowers your effective sample rate by the same "
                  "factor and trades bandwidth for noise. On the M2K this is "
                  "the decimation control.",
        "needs_conversion": False,
    },
    "frequency": {
        "unit": "hertz",
        "summary": "The output frequency of a generator channel.",
        "detail": "Found on altvoltage channels -- a DDS or PLL output. You "
                  "set a frequency and the hardware synthesises the tone; "
                  "you are not writing samples.",
        "needs_conversion": False,
    },
    "phase": {
        "unit": "radians",
        "summary": "The phase of a generator channel.",
        "detail": "The ABI unit is radians, but some DDS drivers expose a "
                  "raw phase word instead. Check _available or the value "
                  "range before trusting it as radians.",
        "needs_conversion": False,
    },
    "hardwaregain": {
        "unit": "decibels",
        "summary": "A gain stage in the analogue path, in dB.",
        "detail": "Real hardware gain, applied before the converter. It "
                  "changes what the raw counts mean, so _scale usually "
                  "changes with it.",
        "needs_conversion": False,
    },
    "powerdown": {
        "unit": "boolean -- 1 means powered down",
        "summary": "Turns the channel or stage off. 1 is off, not on.",
        "detail": "The sense is inverted from what most people assume: "
                  "writing 1 disables.",
        "needs_conversion": False,
    },
    "powerdown_mode": {
        "unit": "text",
        "summary": "Which powerdown behaviour to use.",
        "detail": None, "needs_conversion": False,
    },
    "label": {
        "unit": "text",
        "summary": "A human-readable name the driver or device tree gives "
                   "this channel.",
        "detail": "The only place in all of IIO where a driver can tell you "
                  "in words what a channel is wired to. Most do not bother.",
        "needs_conversion": False,
    },
    "en": {
        "unit": "boolean -- 1 means enabled",
        "summary": "Whether this channel is included in the streaming buffer.",
        "detail": "A channel you have not enabled produces no samples, no "
                  "matter what the attribute tree says.",
        "needs_conversion": False,
    },
    "index": {
        "unit": "no unit -- a position",
        "summary": "Where this channel's sample sits inside each buffer "
                   "record.",
        "detail": "Enabled channels are interleaved in index order, not in "
                  "the order you enabled them.",
        "needs_conversion": False,
    },
    "type": {
        "unit": "text -- a format string",
        "summary": "The bit layout of each sample, e.g. le:s12/16>>0.",
        "detail": "See describe_data_format(): byte order, signedness, real "
                  "bits, container bits, shift.",
        "needs_conversion": False,
    },
    "filter_low_pass_3db_frequency": {
        "unit": "hertz",
        "summary": "Corner frequency of a low-pass filter in the signal path.",
        "detail": "Anything above this is already attenuated before you see "
                  "it, in hardware. No downstream block can recover it.",
        "needs_conversion": False,
    },
    "filter_high_pass_3db_frequency": {
        "unit": "hertz",
        "summary": "Corner frequency of a high-pass filter in the signal path.",
        "detail": "Often what removes DC. If your trace is centred on zero "
                  "when you expected an offset, look here.",
        "needs_conversion": False,
    },
    "integration_time": {
        "unit": "seconds",
        "summary": "How long the sensor accumulates before producing a "
                   "reading.",
        "detail": None, "needs_conversion": False,
    },
    "current_timestamp_clock": {
        "unit": "text",
        "summary": "Which kernel clock the timestamp channel reads.",
        "detail": None, "needs_conversion": False,
    },
    # buffer-level attributes -- these govern streaming, which is all a
    # GNU Radio flowgraph ever does
    "enable": {
        "unit": "boolean",
        "summary": "Starts and stops the streaming buffer.",
        "detail": "Most channel settings cannot be changed while this is 1.",
        "needs_conversion": False,
    },
    "length": {
        "unit": "samples",
        "summary": "How many samples the kernel buffer holds.",
        "detail": "Too small and you get overruns; too large and you add "
                  "latency. This is the knob behind most 'O' characters in "
                  "a GNU Radio console.",
        "needs_conversion": False,
    },
    "watermark": {
        "unit": "samples",
        "summary": "How many samples must be ready before a read returns.",
        "detail": None, "needs_conversion": False,
    },
    "data_available": {
        "unit": "bytes",
        "summary": "How much captured data is waiting to be read.",
        "detail": None, "needs_conversion": False,
    },
    "direct_reg_access": {
        "unit": "hexadecimal register value",
        "summary": "Raw read/write access to the chip's registers, exposed "
                   "for debugging.",
        "detail": "Not part of the IIO ABI -- it is a debug attribute ADI "
                  "drivers add. It bypasses every check the driver makes, so "
                  "it will happily let you put the hardware in a state "
                  "nothing else expects.",
        "needs_conversion": False,
    },
    "length_align_bytes": {
        "unit": "bytes",
        "summary": "The alignment a buffer read must satisfy.",
        "detail": "A libiio-level detail rather than a kernel one: your "
                  "buffer size has to be a multiple of this.",
        "needs_conversion": False,
    },
    "trigger": {
        "unit": "text",
        "summary": "Which trigger drives sampling on this device.",
        "detail": None, "needs_conversion": False,
    },
}


# --------------------------------------------------------------- parsing

_CHAN_ID = re.compile(r"^([a-z]+?)(\d*)$")


def parse_channel_id(chan_id):
    """Split a libiio channel id into type, index and modifier.

    Handles the three shapes you actually meet:
        voltage0            -- ordinary indexed channel
        voltage0-voltage1   -- a differential pair
        accel_x             -- a channel with a modifier
    Returns None if the id does not look like an IIO channel id at all.
    """
    if not chan_id:
        return None

    out = {"type": None, "index": None, "modifier": None,
           "differential": False, "type2": None, "index2": None}

    head = chan_id
    if "-" in chan_id:
        head, tail = chan_id.split("-", 1)
        match = _CHAN_ID.match(tail)
        if match:
            out["differential"] = True
            out["type2"] = match.group(1)
            out["index2"] = int(match.group(2)) if match.group(2) else None

    parts = head.split("_")
    match = _CHAN_ID.match(parts[0])
    if not match:
        return None

    out["type"] = match.group(1)
    out["index"] = int(match.group(2)) if match.group(2) else None
    if len(parts) > 1:
        out["modifier"] = "_".join(parts[1:])
    return out


def parse_attr_name(name, channel=None):
    """Work out everything the attribute's name alone can tell you.

    libiio strips the channel prefix from channel attributes, so what you
    get from chan.attrs is bare ("raw", "scale"). Pass the channel dict
    from enumerate_context() as `channel` and this rebuilds the full sysfs
    name before parsing. Device and buffer attributes carry their own full
    names and need no channel.
    """
    parsed = {
        "name": name,
        "sysfs_name": name,
        "direction": None,
        "channel_id": None,
        "channel_type": None,
        "channel_index": None,
        "channel_index2": None,
        "differential": False,
        "modifier": None,
        "info": name,
        "is_available": False,
    }

    info = name
    # Careful: some attributes genuinely END in _available (data_available is
    # a buffer attribute, not the option list for an attribute called "data").
    # Only treat the suffix as an option list if the whole name is not itself
    # something we recognise.
    if info not in INFO_WORDS and (info.endswith("_available")
                                   or info.endswith("_range")):
        parsed["is_available"] = True
        info = info.rsplit("_", 1)[0]

    if channel is not None:
        # A channel attribute. libiio already removed the prefix, unless
        # the driver did something unusual and left it on.
        direction = "out" if channel.get("output") else "in"
        chan_id = channel.get("id") or ""
        prefix = "%s_%s_" % (direction, chan_id)
        if info.startswith(prefix):
            info = info[len(prefix):]
        parsed["direction"] = direction
        parsed["channel_id"] = chan_id
        parsed["sysfs_name"] = prefix + info
        bits = parse_channel_id(chan_id)
    else:
        # A device, buffer or context attribute. If it carries a direction
        # prefix it is really a channel attribute the driver exposed at
        # device level; otherwise it applies to the whole device.
        bits = None
        for direction in ("in", "out"):
            if info.startswith(direction + "_"):
                rest = info[len(direction) + 1:]
                head, _, tail = rest.partition("_")
                candidate = parse_channel_id(head)
                if candidate and tail:
                    parsed["direction"] = direction
                    parsed["channel_id"] = head
                    bits = candidate
                    info = tail
                break

    if bits:
        parsed["channel_type"] = bits["type"]
        parsed["channel_index"] = bits["index"]
        parsed["channel_index2"] = bits["index2"]
        parsed["differential"] = bits["differential"]
        parsed["modifier"] = bits["modifier"]

    # A modifier can also sit in front of the info word rather than in the
    # channel id, e.g. in_intensity_red_raw.
    head, _, tail = info.partition("_")
    if tail and head in MODIFIERS and parsed["modifier"] is None:
        parsed["modifier"] = head
        info = tail

    parsed["info"] = info
    if parsed["sysfs_name"] == name and parsed["channel_id"] and channel is None:
        parsed["sysfs_name"] = name
    return parsed


# ---------------------------------------------------------- data formats

def describe_data_format(fmt):
    """Turn a captured scan-element layout into shorthand and English.

    `fmt` is the dict iio_discover.collect_data_format() produced. Returns
    None if the channel is not a streaming channel.
    """
    if not fmt:
        return None

    bits = fmt.get("bits")
    length = fmt.get("length")
    # A non-streaming channel can still carry an all-zero data format --
    # xadc reports bits 0 in a 0-bit container. "le:u0/0>>0" is noise, not
    # information.
    if not bits or not length:
        return None
    shift = fmt.get("shift", 0) or 0
    signed = bool(fmt.get("is_signed"))
    big_endian = bool(fmt.get("is_be"))
    repeat = fmt.get("repeat") or 1

    shorthand = "%s:%s%s/%s>>%s" % (
        "be" if big_endian else "le",
        "s" if signed else "u",
        bits, length, shift)
    if repeat > 1:
        shorthand += "X%d" % repeat

    sentences = [
        "Each sample arrives as %s bits of storage, %s of which carry real "
        "data." % (length, bits),
        "The value is %s and stored %s-endian."
        % ("signed (two's complement)" if signed else "unsigned",
           "big" if big_endian else "little"),
    ]
    if shift:
        sentences.append(
            "Shift right by %d bits before using it -- the low bits are "
            "padding, not signal." % shift)
    else:
        sentences.append("No shift needed; the data is already aligned.")
    if repeat > 1:
        sentences.append("%d values are packed per sample slot." % repeat)
    if bits and length and bits < length:
        sentences.append(
            "Because only %s of %s bits are real, the full-scale count is "
            "%s, not %s -- this is why a raw value never reaches the "
            "container's maximum."
            % (bits, length,
               (2 ** (bits - 1) - 1) if signed else (2 ** bits - 1),
               (2 ** (length - 1) - 1) if signed else (2 ** length - 1)))

    return {"shorthand": shorthand, "english": " ".join(sentences),
            "bits": bits, "length": length, "shift": shift,
            "signed": signed, "big_endian": big_endian, "repeat": repeat}


# ------------------------------------------------------------ conversion

def _number(text):
    """Best-effort float from an attribute value string."""
    if text is None:
        return None
    try:
        return float(str(text).strip().split()[0])
    except (ValueError, IndexError):
        return None


def convert_raw(raw, offset=None, scale=None, chan_type=None):
    """Apply the IIO conversion contract and show the working.

    Returns a dict with the arithmetic laid out step by step, because the
    point of this tool is that a participant sees where the number came
    from rather than being handed a result.
    """
    raw_value = _number(raw)
    if raw_value is None:
        return None

    offset_value = _number(offset)
    scale_value = _number(scale)

    value = raw_value
    terms = ["%g" % raw_value]
    if offset_value is not None:
        value = value + offset_value
        terms = ["(%g + %g)" % (raw_value, offset_value)]
    if scale_value is not None:
        value = value * scale_value
        terms.append("%g" % scale_value)

    spec = CHANNEL_TYPES.get(chan_type or "")
    result = {
        "value": value,
        "expression": " * ".join(terms),
        "unit": spec["unit"] if spec else None,
        "symbol": spec["symbol"] if spec else None,
        "si_value": None,
        "si_unit": None,
        "si_symbol": None,
        "si_note": None,
        "used_offset": offset_value is not None,
        "used_scale": scale_value is not None,
    }

    # Only worth showing a second line when the ABI unit is not the unit
    # everyone actually thinks in.
    if spec and spec.get("si_per_unit") not in (None, 1.0):
        result["si_value"] = value * spec["si_per_unit"]
        result["si_unit"] = spec.get("si_unit")
        result["si_symbol"] = spec.get("si_symbol")
    result["si_note"] = spec.get("note") if spec else None
    return result


# --------------------------------------------------------------- lookups

def channel_type_info(chan_type):
    """ABI facts about a channel type, or None if we do not know it."""
    return CHANNEL_TYPES.get(chan_type or "")


def info_word_info(info):
    """ABI facts about an info word, or None if we do not know it."""
    return INFO_WORDS.get(info or "")


def modifier_info(modifier):
    return MODIFIERS.get(modifier or "")


def attrs_by_info(attrs, channel=None):
    """Index a channel's attribute list by its parsed info word.

    Lets a caller ask for the sibling _scale of a given _raw without
    caring whether libiio handed back bare or prefixed names.
    """
    out = {}
    for attr in attrs:
        parsed = parse_attr_name(attr["name"], channel)
        if not parsed["is_available"]:
            out.setdefault(parsed["info"], attr)
    return out


def channel_sort_key(channel):
    """Order channels the way the hardware does, not the way ls does.

    The scan index comes first, because that is the order samples arrive
    in. It is not enough on its own: the M2K's logic analyzer reports
    scan index 0 for all sixteen of its channels, since they share one
    scan element. The channel's own index breaks the tie, which is what
    stops voltage10 from sorting between voltage1 and voltage2.
    """
    bits = parse_channel_id(channel.get("id") or "")
    index = bits["index"] if bits and bits["index"] is not None else 0
    scan = channel.get("scan_index")
    return (scan if scan is not None and scan >= 0 else 1 << 30,
            index, channel.get("id") or "")


def describe_channel(channel):
    """One-sentence plain-English description of what a channel measures."""
    bits = parse_channel_id(channel.get("id") or "")
    if not bits:
        return None

    spec = CHANNEL_TYPES.get(bits["type"])
    direction = "output" if channel.get("output") else "input"

    if spec:
        text = "An %s channel measuring %s" % (direction, spec["quantity"]) \
            if direction == "input" else \
            "An output channel driving %s" % spec["quantity"]
        text += ", reported in %s" % spec["unit"]
    else:
        text = "An %s channel of unrecognised type '%s'" % (
            direction, bits["type"])

    if bits["differential"]:
        text += ". This is a differential pair: it measures the difference " \
                "between two pins, not either one against ground"
    if bits["modifier"]:
        mod = MODIFIERS.get(bits["modifier"])
        if mod:
            text += ". Restricted to %s" % mod
        else:
            text += ". Modifier '%s' (unrecognised)" % bits["modifier"]
    return text + "."


def is_understood(parsed, attr_type=None):
    """Did anything generic actually explain this attribute?

    Drives `iio_explain.py --unknown`, which is the honest measure of how
    much hand-written glossary is still owed -- so it has to count every
    generic source, not just our own table. An attribute the kernel
    documents is explained whether or not we got round to summarising it.
    """
    if parsed["info"] in INFO_WORDS:
        return True
    return abi_reference(parsed["sysfs_name"], attr_type) is not None


# ------------------------------------------------- the kernel's own words
#
# Everything above is our summary. This is the authority: the description
# the IIO maintainers wrote for the attribute, fetched by iio_abi_fetch.py
# and quoted verbatim with a citation. When the two disagree, the kernel
# is right and our table is a bug.

try:
    import iio_abi_fetch
except ImportError:                                # pragma: no cover
    iio_abi_fetch = None

_ABI_CACHE = []


def abi_data():
    """Load the cached kernel ABI descriptions once."""
    if not _ABI_CACHE:
        _ABI_CACHE.append(iio_abi_fetch.load() if iio_abi_fetch else None)
    return _ABI_CACHE[0]


def abi_reference(sysfs_name, attr_type=None):
    """The kernel's description of an attribute, or None if undocumented.

    Returns {"description": [paragraphs], "kernel_version", "source"}.
    """
    data = abi_data()
    if not data or not iio_abi_fetch:
        return None
    return iio_abi_fetch.lookup(data, sysfs_name, attr_type)


# ------------------------------------------------------ channel identity
#
# "What is voltage0 -- pin 0, or some internal rail?" There is no single
# source that answers this, so ask four in order of how much they know,
# and always say which one answered.

DRIVER = "driver"


def channel_identity(device, channel, overlays=None):
    """Best available answer to what a channel is physically connected to.

    Evidence ladder, strongest first:

      1. channel name   -- the driver's own extend_name/datasheet_name,
                           surfaced by iio_channel_get_name(). This is the
                           driver author naming the pin. Usually absent.
      2. label attribute -- same idea, settable from the device tree.
      3. device pack     -- hand-written, see iio_overlays.py. Carries its
                           own confidence.
      4. the ABI default -- the kernel says channel index Y corresponds to
                           an externally available input unless the driver
                           used a named channel instead. So a bare index
                           with no name is, by convention, an external
                           input -- but that is a convention, not a promise.

    Returns a list of {"text", "provenance", "confidence"} in that order.
    """
    findings = []

    name = (channel or {}).get("name")
    chan_id = (channel or {}).get("id") or ""
    if name and name != chan_id:
        findings.append({
            "text": "The driver names this channel '%s'. That name comes "
                    "from the driver's own channel table, which is the "
                    "closest thing to an authoritative label." % name,
            "provenance": DRIVER, "confidence": MEASURED})

    for attr in (channel or {}).get("attrs", []):
        if parse_attr_name(attr["name"], channel)["info"] != "label":
            continue
        label = attr.get("value")
        # A driver that sets extend_name usually surfaces the same string
        # as the label. Reporting it twice looks like corroboration from
        # two sources when it is one source read two ways.
        if label and label != name:
            findings.append({
                "text": "The device reports a label of '%s'." % label,
                "provenance": DRIVER, "confidence": MEASURED})

    if overlays:
        note = overlays.channel_note(device, channel)
        if note:
            findings.append({"text": note["text"], "provenance": OVERLAY,
                             "confidence": note["confidence"],
                             "source": note.get("source"),
                             "check": note.get("check")})

    bits = parse_channel_id(chan_id)
    if bits and bits["index"] is not None:
        findings.append({
            "text": "No driver-supplied name. By the IIO convention, an "
                    "indexed channel corresponds to externally available "
                    "input %d; a driver is supposed to use a named channel "
                    "instead when it does not. Treat that as a strong hint, "
                    "not a guarantee -- confirm against the schematic."
                    % bits["index"],
            "provenance": ABI, "confidence": "convention",
            # Only worth printing when nothing stronger answered.
            "fallback": True})

    return findings


# ------------------------------------------------- the vendor's own view
#
# A third question, alongside "what does it mean" and "what is it wired
# to": will you ever need it? The kernel cannot say. libm2k can, for this
# board -- an attribute it reads or writes is one that operating the M2K
# as an instrument requires, and the method that touches it says which
# instrument. See iio_libm2k_fetch.py.

try:
    import iio_libm2k_fetch
except ImportError:                                # pragma: no cover
    iio_libm2k_fetch = None

_LIBM2K_CACHE = []


def libm2k_data():
    if not _LIBM2K_CACHE:
        _LIBM2K_CACHE.append(
            iio_libm2k_fetch.load() if iio_libm2k_fetch else None)
    return _LIBM2K_CACHE[0]


def libm2k_use(info):
    """How libm2k drives this attribute, or None if it never touches it.

    Absence is not a verdict on importance -- scale and offset are absent
    because libm2k computes the scope conversion itself instead of reading
    it back, and they matter on every other IIO device. It means "not part
    of this board's instrument abstraction".
    """
    data = libm2k_data()
    if not data or not iio_libm2k_fetch:
        return None
    return iio_libm2k_fetch.lookup(data, info)
