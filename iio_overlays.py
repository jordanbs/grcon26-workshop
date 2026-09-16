#!/usr/bin/env python3
"""
iio_overlays.py -- hand-written meaning that the ABI cannot give you.

iio_semantics.py explains everything the IIO ABI defines, which is most of
any device. What it cannot tell you is what a channel is physically wired
to. Nothing in libiio knows that `voltage0` on m2k-adc is the BNC labelled
1+ on the front of the box. That has to be written down by a person.

Everything in this file is therefore lower-trust than everything in
iio_semantics.py, and it says so. Each entry carries a `confidence`:

    UNVERIFIED  written from documentation, not yet checked against a
                real board. Renderers MUST show this as unverified.
    MEASURED    confirmed by running iio_discover.py against the
                hardware and checking the claim holds.

Promote entries to MEASURED as they get checked, and record how in the
`check` field so the next person can repeat it. Nothing here should be
taught as fact while it still says UNVERIFIED.
"""

UNVERIFIED = "unverified"
SOURCED = "sourced"      # traced to vendor source code, not yet bench-checked
MEASURED = "measured"


def _e(text, confidence=UNVERIFIED, check=None, source=None):
    return {"text": text, "confidence": confidence, "check": check,
            "source": source}


LIBM2K = ("libm2k src/analog/m2kanalogin_impl.cpp -- "
          "https://github.com/analogdevicesinc/libm2k")

LIBM2K_TRIG = ("libm2k src/m2khardwaretrigger_impl.cpp -- "
               "https://github.com/analogdevicesinc/libm2k")


# The M2K exposes six IIO devices. Names are matched against the device's
# `name` first and its `id` second, so this works whether libiio reports
# "m2k-adc" or "iio:device0".

DEVICE_PACKS = {
    "m2k-adc": {
        "device": _e("The oscilloscope input. Both scope channels arrive "
                     "through this one device, interleaved in the same "
                     "buffer.",
                     check="iio_discover.py --device m2k-adc; expect two "
                           "input voltage channels."),
        "channels": {
            "voltage0": _e(
                "Scope channel 1. libm2k's M2kAnalogIn indexes this device's "
                "channels directly as ANALOG_IN_CHANNEL_1 and _2, so "
                "voltage0 is the first scope input, not an internal rail.",
                confidence=SOURCED, source=LIBM2K,
                check="Inject a known signal on 1+ and confirm voltage0 "
                      "moves and voltage1 does not."),
            "voltage1": _e("Scope channel 2, by the same indexing.",
                           confidence=SOURCED, source=LIBM2K),
        },
        "attrs": {
            "oversampling_ratio": _e(
                "Decimation. The M2K always samples at 100 MS/s internally; "
                "this divides that down. Your real sample rate is "
                "100e6 / oversampling_ratio, and that is the number a GNU "
                "Radio flowgraph needs.",
                check="Set it, then capture a known tone and confirm the "
                      "measured frequency does not move."),
            "sampling_frequency": _e(
                "The rate after decimation -- what you should feed to every "
                "downstream block."),
            "calibscale": _e(
                "Written by the M2K calibration routine, not by you. "
                "Overwriting it silently invalidates the calibration."),
            "calibbias": _e(
                "Also written by calibration. Same warning."),
        },
    },

    "m2k-dac-a": {
        "device": _e("Waveform generator output W1."),
        "channels": {"voltage0": _e("The W1 output pin.")},
        "attrs": {},
    },

    "m2k-dac-b": {
        "device": _e("Waveform generator output W2."),
        "channels": {"voltage0": _e("The W2 output pin.")},
        "attrs": {},
    },

    "m2k-logic-analyzer-rx": {
        "device": _e("Digital input -- the 16 DIO pins read as logic levels "
                     "rather than voltages."),
        "channels": {},
        "attrs": {},
    },

    "m2k-logic-analyzer-tx": {
        "device": _e("Digital output -- the same 16 DIO pins driven as a "
                     "pattern generator. A pin is either an input or an "
                     "output, not both."),
        "channels": {},
        "attrs": {},
    },

    "ad9963": {
        "device": _e("The mixed-signal front-end chip itself: the actual "
                     "ADC and DAC silicon behind m2k-adc and the two DAC "
                     "devices. You rarely touch it directly; libm2k drives "
                     "it during calibration.",
                     check="Compare its attribute set against the AD9963 "
                           "datasheet register map."),
        "channels": {},
        "attrs": {},
    },

    "m2k-fabric": {
        "device": _e("FPGA fabric control. This is where the analogue front "
                     "end is configured -- it holds settings that change "
                     "what the ADC counts mean but that are not part of the "
                     "ADC device.",
                     check="Toggle gain and watch in_voltage0_scale on "
                           "m2k-adc change."),
        "channels": {
            "voltage0": _e("Front-end control for scope channel 1."),
            "voltage1": _e("Front-end control for scope channel 2."),
        },
        "attrs": {
            "gain": _e(
                "The input range switch. libm2k reads this exact attribute "
                "to decide the range: 'high' means the +/-2.5 V range, "
                "anything else means +/-25 V. It is an attenuator in front "
                "of the ADC, so changing it changes what a raw count is "
                "worth -- re-read _scale on m2k-adc afterwards.",
                confidence=SOURCED, source=LIBM2K,
                check="Set gain, then read in_voltage0_scale on m2k-adc "
                      "and confirm it moved by the expected ratio."),
            "powerdown": _e(
                "Powers the front end down. Remember 1 means off."),
        },
    },
}


# The one CN0363 in the box. Included to show the overlay mechanism is not
# M2K-specific -- and because its channels are a clean example of why
# intensity channels are unitless.

DEVICE_PACKS["cn0363"] = {
    "device": _e("The colorimeter. Measures how much light of each color "
                 "passes through a sample.",
                 check="Only one board exists -- verify before the workshop, "
                       "not during."),
    "channels": {},
    "attrs": {},
}


# ---------------------------------------------------------------------------
# The trigger subsystem.
#
# This is the largest single gap in what the kernel can tell you, and it is
# not close: of the M2K's trigger, DDS and logic-analyzer attributes, exactly
# one appears in any kernel ABI file. They come from Analog Devices' FPGA HDL
# drivers, which ship no ABI documentation at all.
#
# So libm2k's source is not a convenience here, it is the only description
# that exists. Everything below is read out of
# src/m2khardwaretrigger_impl.cpp -- the value vocabularies are that file's
# own string tables, quoted exactly.
# ---------------------------------------------------------------------------

DEVICE_PACKS["m2k-adc-trigger"] = {
    "device": _e(
        "The FPGA trigger block for the scope. libm2k opens this device by "
        "name as its analog trigger, and sorts its channels by which "
        "attributes they carry: a channel with trigger + trigger_level + "
        "trigger_hysteresis is an analog trigger, one with trigger alone is "
        "a digital trigger, and one with mode is a logic channel. The "
        "attribute set IS the channel's role -- nothing else labels them.",
        confidence=SOURCED, source=LIBM2K_TRIG),
    "channels": {},
    "attrs": {
        "trigger": _e(
            "The trigger condition. For an analog channel the choices are "
            "edge-rising, edge-falling, level-low, level-high; a digital "
            "channel adds edge-any and none. Note this is NOT the ABI's "
            "device-level 'current trigger' attribute of the same name -- "
            "same word, different meaning.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "trigger_level": _e(
            "The threshold, in RAW ADC COUNTS -- not volts, not millivolts. "
            "libm2k reads it as a number and casts straight to int. To set "
            "it from a voltage you have to run the conversion backwards: "
            "raw = value / scale - offset, using the scale and offset of the "
            "matching m2k-adc channel. Change the input range and the same "
            "raw number means a different voltage.",
            confidence=SOURCED, source=LIBM2K_TRIG,
            check="Set a level, capture a triggered waveform, and confirm "
                  "the trigger point sits where (raw + offset) * scale says."),
        "trigger_hysteresis": _e(
            "How far the signal must fall back before the trigger will fire "
            "again, also in raw counts. Stops a noisy edge from triggering "
            "repeatedly.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "trigger_delay": _e(
            "How many samples to wait after the trigger fires before the "
            "capture starts. Negative values give you pre-trigger data.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "logic_mode": _e(
            "Badly named: this holds the analog trigger SOURCE, not a logic "
            "mode. Its values are a, b, a_OR_b, a_AND_b, a_XOR_b -- which "
            "scope channel, or which combination, is allowed to fire the "
            "trigger. libm2k reads this attribute in getAnalogSource().",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "mode": _e(
            "How the analog and digital triggers combine: always, analog, "
            "digital, digital_OR_analog, digital_AND_analog, "
            "digital_XOR_analog, and the negated forms of the last three. "
            "'always' means free-running -- no triggering at all.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "streaming": _e(
            "Continuous capture rather than one buffer per trigger. libm2k "
            "always writes 0 to reset the trigger before enabling this, "
            "which suggests turning it on from an already-armed state does "
            "not behave.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "out_select": _e(
            "Routes the trigger out to a physical pin. libm2k treats the "
            "presence of this attribute as the test for whether the board "
            "supports an external trigger output at all, which is how you "
            "chain two M2Ks together.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "triggered": _e("Whether the trigger has fired. Read-only status."),
        "holdoff_raw": _e(
            "Dead time after a trigger during which it will not re-arm. "
            "The _raw suffix says counts rather than seconds."),
        "delay": _e("A second delay control alongside trigger_delay; which "
                    "one applies has not been worked out."),
        "embedded": _e("Not yet identified."),
        "out_direction": _e("Direction of the external trigger pin."),
    },
}

DEVICE_PACKS["m2k-logic-analyzer"] = {
    "device": _e("The 16 DIO pins. The -rx and -tx devices carry the data; "
                 "this one carries the per-pin configuration."),
    "channels": {},
    "attrs": {
        "direction": _e(
            "Whether a DIO pin is an input or an output. A pin is one or the "
            "other, never both, so this is the attribute that decides "
            "whether the logic analyzer or the pattern generator owns it."),
        "outputmode": _e("Push-pull or open-drain drive for an output pin."),
        "clocksource": _e("Which clock the DIO block samples against."),
    },
}

DEVICE_PACKS["m2k-logic-analyzer-rx"] = {
    "device": _e("Digital capture -- the DIO pins read as logic levels. "
                 "libm2k drives its triggering through the same attribute "
                 "vocabulary as the analog trigger.",
                 confidence=SOURCED, source=LIBM2K_TRIG),
    "channels": {},
    "attrs": {
        "trigger_logic_mode": _e(
            "How the per-pin digital trigger conditions combine: or, and.",
            confidence=SOURCED, source=LIBM2K_TRIG),
        "trigger_mux_out": _e("Routing for the digital trigger output."),
        "data_in_delay": _e("Input sampling delay, for lining the capture "
                            "clock up against the incoming data."),
        "data_delay_auto": _e("Let the hardware pick data_in_delay."),
        "rate_mux": _e("Sample-rate divider selection for the DIO block."),
    },
}

DEVICE_PACKS["m2k-logic-analyzer-tx"] = {
    "device": _e("Digital output -- the same DIO pins driven as a pattern "
                 "generator."),
    "channels": {},
    "attrs": {},
}

DEVICE_PACKS["m2k-dds"] = {
    "device": _e("The direct digital synthesis block behind the waveform "
                 "generators. Its channels are altvoltage rather than "
                 "voltage, which is the ABI's way of saying you set a "
                 "frequency and the hardware makes the tone, instead of "
                 "writing samples yourself."),
    "channels": {},
    "attrs": {
        "sync_start_enable": _e("Start several DDS channels on the same "
                                "clock edge, so their phase relationship is "
                                "defined."),
    },
}

DEVICE_PACKS["pll"] = {
    "device": _e("The clock synthesiser. Nothing you measure comes from "
                 "here, but everything you measure is timed by it. Its "
                 "attribute names match the ADF435x family.",
                 check="Confirm the part number against the M2K schematic."),
    "channels": {},
    "attrs": {
        "pfd_frequency": _e("Phase-frequency-detector comparison frequency: "
                            "the reference divided down, and the step size "
                            "the loop can tune in."),
        "power_down": _e("Powers the synthesiser down. Note this one is "
                         "power_down with an underscore, while the IIO ABI "
                         "spells the generic attribute powerdown."),
        "power_level": _e("Output drive level."),
        "muxout_mode": _e("What the chip's MUXOUT pin reports -- lock "
                          "detect, a divided clock, or a logic level."),
        "mute_till_lock_detect": _e("Hold the output muted until the loop "
                                    "has locked, so nothing downstream sees "
                                    "an unlocked sweep."),
    },
}

# Attributes seen on the DAC devices.
DEVICE_PACKS["m2k-dac-a"]["attrs"].update({
    "trigger_src": _e("Which trigger starts playback of the buffer."),
    "trigger_condition": _e("The condition that trigger_src must meet."),
    "trigger_status": _e("Whether playback is armed or running. Read-only."),
    "auto_rearm_trigger": _e("Re-arm automatically after playback finishes, "
                             "so a triggered waveform repeats."),
    "dma_sync": _e("Hold the DMA so several channels can be released "
                   "together."),
    "dma_sync_start": _e("Release the channels held by dma_sync. This is how "
                         "W1 and W2 start phase-aligned."),
    "raw_enable": _e("Switch between buffer playback and a single held "
                     "value written through _raw."),
    "calibrate": _e("Runs the calibration routine. An action attribute -- "
                    "writing to it does something rather than storing a "
                    "value, which is why reading it may error."),
})
DEVICE_PACKS["m2k-dac-b"]["attrs"].update(DEVICE_PACKS["m2k-dac-a"]["attrs"])

DEVICE_PACKS["m2k-adc"]["attrs"]["calibrate"] = _e(
    "Runs the ADC calibration routine. An action attribute: writing to it "
    "does something rather than storing a value, so a read may legitimately "
    "fail. It rewrites calibscale and calibbias.")

DEVICE_PACKS["m2k-fabric"]["attrs"].update({
    "calibration_mode": _e("Switches the front end to an internal reference "
                           "so calibration can measure a known input instead "
                           "of whatever is on the BNC."),
    "clk_powerdown": _e("Powers down clocking in the fabric."),
})


# ---------------------------------------------------------------------------
# When the device does not expose a scale at all.
#
# A real m2k-adc channel has exactly two attributes: calibbias and calibscale.
# No _raw, no _scale, no _offset. So the IIO interface genuinely cannot tell
# you what a scope sample is worth -- the conversion lives in libm2k, computed
# from the input range and the calibration, and is never written back to
# sysfs.
#
# That is worth stating outright rather than leaving as a shrug. A recipe here
# is rendered wherever the explainer would otherwise say "nothing on the
# device tells you what these counts are worth".
# ---------------------------------------------------------------------------

DEVICE_PACKS["m2k-adc"]["scale_recipe"] = _e(
    "IIO will not tell you -- but libm2k computes it, and you can too.\n"
    "\n"
    "    volts = sample * scale\n"
    "    scale = 0.78 / (2048 * 1.3 * range_gain) * calib_gain * filter_comp\n"
    "\n"
    "range_gain comes from the `gain` attribute on m2k-fabric for the same\n"
    "channel number:\n"
    "\n"
    "    gain = 'low'   ->  range_gain 0.02017   (the +/-25 V range)\n"
    "                       scale 14.52 mV/count, full scale about +/-29.7 V\n"
    "    gain = 'high'  ->  range_gain 0.21229   (the +/-2.5 V range)\n"
    "                       scale 1.380 mV/count, full scale about +/-2.83 V\n"
    "\n"
    "calib_gain is this channel's calibscale, and filter_comp is a per-sample-\n"
    "rate correction libm2k keeps in a lookup table -- both are 1.0 until\n"
    "calibration runs. So the two numbers above are what a fresh board gives\n"
    "you.\n"
    "\n"
    "The consequence worth remembering: a raw count means nothing on its own\n"
    "here, and it means something DIFFERENT depending on a setting stored on\n"
    "a completely different IIO device.",
    confidence=SOURCED, source=LIBM2K,
    check="Feed a known DC level in, capture samples, and confirm "
          "sample * scale lands on it. Then flip m2k-fabric gain and "
          "confirm the same input needs the other scale.")


def scale_recipe(device):
    """How to convert counts to real units when no _scale attribute exists."""
    pack = _pack(device)
    return pack.get("scale_recipe") if pack else None


# ---------------------------------------------------------------------------
# The three devices that are not part of the signal path.
# ---------------------------------------------------------------------------

DEVICE_PACKS["xadc"] = {
    "device": _e(
        "The Zynq's own system monitor, not part of your signal path at all. "
        "It measures the FPGA's die temperature and internal supply rails. "
        "Worth recognising precisely so you do not go looking for your "
        "signal here: its temp and voltage channels are the board's health, "
        "not the input. It is an upstream Linux driver, so unlike most of "
        "this board its attributes are properly documented by the kernel.",
        check="Compare in_temp0_raw against the die temperature Vivado "
              "reports."),
    "channels": {},
    "attrs": {},
}

DEVICE_PACKS["ad5625"] = {
    "device": _e(
        "A quad DAC used for control, not for output. libm2k reads and "
        "writes its channels to set the scope's hardware vertical offset -- "
        "M2kAnalogIn reaches for channel (2 + i) of this device to get the "
        "offset for scope channel i. So moving a trace up and down on screen "
        "changes a DAC here, not anything on m2k-adc.",
        confidence=SOURCED, source=LIBM2K,
        check="Change the vertical offset in Scopy and watch this device's "
              "raw values move."),
    "channels": {},
    "attrs": {},
}

DEVICE_PACKS["ad5627"] = {
    "device": _e(
        "A dual DAC on the control path alongside ad5625. Which reference it "
        "drives has not been traced -- the trigger level and the DAC output "
        "stage are both candidates.",
        check="Sweep each channel's raw value and watch what moves on the "
              "analog front end."),
    "channels": {},
    "attrs": {},
}

# trigger_delay exists on the digital side too, with the same meaning.
DEVICE_PACKS["m2k-logic-analyzer-rx"]["attrs"]["trigger_delay"] = _e(
    "How many samples to wait after the trigger fires before capture "
    "starts; negative values give pre-trigger data. libm2k reads and writes "
    "it on channel 0 of this device for the whole digital block, not "
    "per-pin.",
    confidence=SOURCED, source=LIBM2K_TRIG)


# ------------------------------------------------------------------ lookup

def _pack(device):
    """Find the pack for a device dict, by name then by id."""
    if not device:
        return None
    for key in (device.get("name"), device.get("id")):
        if key and key in DEVICE_PACKS:
            return DEVICE_PACKS[key]
    return None


def device_note(device):
    pack = _pack(device)
    return pack.get("device") if pack else None


def channel_note(device, channel):
    pack = _pack(device)
    if not pack or not channel:
        return None
    return pack.get("channels", {}).get(channel.get("id"))


def attr_note(device, info):
    """Look up an attribute note by its parsed info word."""
    pack = _pack(device)
    if not pack or not info:
        return None
    return pack.get("attrs", {}).get(info)


def coverage():
    """How many overlay entries exist and how many are still unverified."""
    total = 0
    counts = {}
    for pack in DEVICE_PACKS.values():
        entries = [pack.get("device")]
        entries += list(pack.get("channels", {}).values())
        entries += list(pack.get("attrs", {}).values())
        for entry in entries:
            if not entry:
                continue
            total += 1
            counts[entry["confidence"]] = counts.get(entry["confidence"], 0) + 1
    counts["total"] = total
    return counts
