#!/usr/bin/env python3
"""
iio_grc.py -- turn a discovery selection into GNU Radio block parameters.

iio_discover.py answers "what is here". iio_explain.py answers "what does
it mean". This answers the question that follows both: "what do I type
into the IIO Device Source block to get it".

It imports no libiio. It works off a snapshot, like iio_explain.py, so
the mapping can be taught anywhere.

The shapes below are read off gr-iio 3.10, not guessed:

    iio.device_source(uri, device, channels, device_phy, params,
                      buffer_size, decimation - 1)

  channels  list of channel names, one stream output each. Only scan
            elements can stream -- a channel with no scan index is
            configuration, not data.
  params    list of "<attribute name>=<value>" strings. gr-iio feeds each
            key to iio_device_identify_filename(), which wants the full
            sysfs filename: "in_voltage0_oversampling_ratio", not the bare
            "oversampling_ratio" that libiio reports against the channel.
            Restoring that prefix is what sysfs_name() is for, and it is
            the single easiest thing to get wrong by hand.
  device_phy  where params are applied, if that is not the streaming
            device itself. Left empty, gr-iio uses the streaming device.

In GRC, `uri` and `device` are string fields -- type the text bare, no
quotes. `channels` and `params` are raw fields -- type a Python list.
"""

import iio_overlays
import iio_semantics as sem

DEFAULT_BUFFER_SIZE = 0x8000


# ------------------------------------------------------------- lookups

def find_device(data, wanted):
    """A device by name or id. Returns None if the snapshot has no such device."""
    for device in data.get("devices", []):
        if wanted in (device.get("name"), device.get("id")):
            return device
    return None


def find_channel(device, chan_id, output=None):
    """A channel by id or driver name.

    `output` disambiguates. It has to: on a real M2K both m2k-fabric and
    ad9963 expose voltage0 AND voltage1 twice, once as an input and once
    as an output, carrying different attributes. Matching on the id alone
    silently returns whichever the driver happened to list first, and the
    two need different sysfs prefixes.
    """
    matches = [c for c in (device or {}).get("channels", [])
               if chan_id in (c.get("id"), c.get("name"))]
    if output is not None:
        matches = [c for c in matches if bool(c.get("output")) == bool(output)]
    return matches[0] if matches else None


def channel_is_ambiguous(device, chan_id):
    """Does this id name more than one channel on this device?"""
    return len([c for c in (device or {}).get("channels", [])
                if chan_id in (c.get("id"), c.get("name"))]) > 1


def stream_channels(device):
    """The channels that can actually carry samples: the scan elements.

    In hardware order: this list becomes the order of the block's ports.
    """
    streams = [c for c in (device or {}).get("channels", [])
               if c.get("scan_element")]
    return sorted(streams, key=sem.channel_sort_key)


def is_sink_device(device):
    """Does this device take samples rather than give them?

    Decided by the device's own streaming channels, not by an argument.
    The M2K's DAC devices only make sense as sinks, and a caller should
    not have to know that in advance.
    """
    streams = stream_channels(device)
    return bool(streams) and all(c.get("output") for c in streams)


def sysfs_name(channel, attr_name):
    """The full filename gr-iio needs for a params key.

    A device-level attribute already carries its own full name. A channel
    attribute does not -- libiio strips the prefix, so "raw" has to become
    "in_voltage0_raw" before gr-iio can find it again.
    """
    return sem.parse_attr_name(attr_name, channel)["sysfs_name"]


def find_attr(device, chan_id, attr_name):
    """Locate an attribute. Returns (channel_or_None, attr) or (None, None).

    chan_id None means look at device, buffer and debug level. gr-iio's
    set_params() tries device attributes then debug attributes, so both
    are legal here.
    """
    if chan_id:
        channel = find_channel(device, chan_id)
        if channel is None:
            return None, None
        for attr in channel.get("attrs", []):
            if attr["name"] == attr_name:
                return channel, attr
        return channel, None

    for group in ("device_attrs", "buffer_attrs", "debug_attrs"):
        for attr in (device or {}).get(group, []):
            if attr["name"] == attr_name:
                return None, attr
    return None, None


# ---------------------------------------------------------- validation

def _numerically_in(value, options):
    """Does `value` equal one of `options` as a number?

    Returns False as soon as anything is not a number -- an option list
    of words is compared as words.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    for option in options:
        try:
            if float(option) == number:
                return True
        except (TypeError, ValueError):
            return False
    return False


def check_value(attr, value):
    """Is `value` legal for `attr`, as far as the capture can say?

    Returns None if it is fine or if the hardware published no opinion,
    otherwise a sentence saying what is wrong. The capture only knows
    about attributes that folded an *_available sibling -- silence here
    means unknown, not approved.
    """
    available = (attr or {}).get("available")
    if not available:
        return None

    if available["kind"] == "options":
        if value in available["values"]:
            return None
        # The list is text, but a numeric attribute is compared as a
        # number by the driver: an option printed "0.062500" accepts
        # "0.0625". Complaining about that would be crying wolf.
        if _numerically_in(value, available["values"]):
            return None
        return ("'%s' is not one of the values this attribute accepts "
                "(%s)." % (value, " ".join(available["values"])))

    try:
        number = float(value)
        low = float(available["min"])
        high = float(available["max"])
    except (TypeError, ValueError):
        return None
    if number < low or number > high:
        return ("%s is outside the range the hardware reports (%s to %s)."
                % (value, available["min"], available["max"]))
    return None


# ------------------------------------------------------------- building

def build(data, selection):
    """Selection -> block parameters, with every complaint spelled out.

    `selection` is the object the browser holds and the only thing the
    later GRC-block generator and runtime message path need:

        {"device": "m2k-adc",
         "channels": ["voltage0", "voltage1"],
         "settings": [{"channel": "voltage0", "attr": "raw", "value": "1"},
                      {"channel": null, "attr": "oversampling_ratio",
                       "value": "4"}],
         "buffer_size": 32768, "decimation": 1, "device_phy": ""}

    Returns {"fields", "params", "warnings", "make"}. Warnings never stop
    the emit -- they are teaching material, and the hardware is the final
    authority on all of them.
    """
    warnings = []
    device_name = selection.get("device") or ""
    device = find_device(data, device_name)
    if device is None:
        return {"fields": {}, "params": [], "make": "",
                "warnings": ["No device '%s' in this capture." % device_name]}

    label = device.get("name") or device.get("id")
    is_sink = is_sink_device(device)

    channels = []
    for chan_id in selection.get("channels", []):
        channel = find_channel(device, chan_id)
        if channel is None:
            warnings.append("Channel '%s' is not on %s." % (chan_id, label))
            continue
        if not channel.get("scan_element"):
            warnings.append(
                "Channel '%s' has no scan index, so it cannot stream. It is "
                "a configuration channel -- set its attributes through "
                "params instead of listing it here." % chan_id)
            continue
        # Only meaningful on a mixed device. A device whose streaming
        # channels are all outputs is a sink, and its output channels are
        # exactly right; is_sink_device() has already decided that.
        if channel.get("output") and not is_sink:
            warnings.append(
                "Channel '%s' is an output, but %s also has input channels "
                "so it is being built as a source. A Device Source reads "
                "inputs; this channel belongs on a Device Sink."
                % (chan_id, label))
        channels.append(channel)

    channels.sort(key=sem.channel_sort_key)
    channels = [c.get("id") for c in channels]

    if not channels:
        warnings.append(
            "No streaming channels selected. The block will have no outputs.")

    params = []
    for setting in selection.get("settings", []):
        attr_name = setting.get("attr")
        chan_id = setting.get("channel")
        value = setting.get("value")
        if attr_name is None or value in (None, ""):
            continue

        if chan_id and channel_is_ambiguous(device, chan_id):
            warnings.append(
                "'%s' names more than one channel on %s -- an input and an "
                "output, with different attributes. Using the first one the "
                "driver lists; say which you mean if that is wrong."
                % (chan_id, label))
        channel, attr = find_attr(device, chan_id, attr_name)
        if attr is None:
            where = ("channel %s" % chan_id) if chan_id else "device level"
            warnings.append("No attribute '%s' at %s on %s."
                            % (attr_name, where, label))
            continue

        complaint = check_value(attr, value)
        if complaint:
            warnings.append("%s: %s" % (sysfs_name(channel, attr_name),
                                        complaint))
        params.append("%s=%s" % (sysfs_name(channel, attr_name), value))

    buffer_size = int(selection.get("buffer_size") or DEFAULT_BUFFER_SIZE)
    # A sink calls the same knob interpolation. Accept either key so a
    # caller that does not care which direction it is gets it right anyway.
    rate_key = "interpolation" if is_sink else "decimation"
    rate = int(selection.get(rate_key)
               or selection.get("decimation")
               or selection.get("interpolation") or 1)
    device_phy = selection.get("device_phy") or ""

    fields = {
        "uri": data.get("uri") or "local:",
        "device": label,
        "device_phy": device_phy,
        "channels": channels,
        "buffer_size": buffer_size,
        rate_key: rate,
        "params": params,
        "len_tag_key": selection.get("len_tag_key") or "packet_len",
        "is_sink": is_sink,
    }
    if is_sink:
        fields["cyclic"] = bool(selection.get("cyclic", False))
    return {"fields": fields, "fields_display": render_fields(fields),
            "params": params, "warnings": warnings, "is_sink": is_sink,
            "make": render_python(fields)}


# ------------------------------------------------------------ rendering

def render_python(fields):
    """The constructor call GRC generates, for pasting into plain Python.

    Both shapes are copied from gr-iio 3.10's own block templates, which
    are identical on main:

        iio.device_source(uri, device, channels, device_phy, params,
                          buffer_size, decimation - 1)
        iio.device_sink(uri, device, channels, device_phy, params,
                        buffer_size, interpolation - 1, cyclic)

    Two things people miss. The rate argument is "samples to drop", one
    less than the factor GRC shows -- hence the subtraction. And the
    length tag key is not a constructor argument at all; GRC emits a
    second line calling set_len_tag_key(), so a hand-written flowgraph
    that stops at the constructor is missing it.
    """
    if fields.get("is_sink"):
        call = ("iio.device_sink(%r, %r, %r, %r, %r, %d, %d, %r)"
                % (fields["uri"], fields["device"], fields["channels"],
                   fields["device_phy"], fields["params"],
                   fields["buffer_size"], fields["interpolation"] - 1,
                   bool(fields.get("cyclic", False))))
    else:
        call = ("iio.device_source(%r, %r, %r, %r, %r, %d, %d)"
                % (fields["uri"], fields["device"], fields["channels"],
                   fields["device_phy"], fields["params"],
                   fields["buffer_size"], fields["decimation"] - 1))
    return "%s\nself.blk.set_len_tag_key(%r)" % (call, fields["len_tag_key"])


def render_fields(fields):
    """What to type in each GRC box, in the block's own order.

    `kind` says how GRC reads the box, using the dtype the block itself
    declares: `string` takes bare text, `int` and `raw` take an
    expression, `bool` takes True or False. Typing quotes into a string
    field is the classic first mistake.
    """
    boxes = [
        {"id": "uri", "label": "IIO context URI", "kind": "string",
         "text": fields["uri"]},
        {"id": "device", "label": "Device Name/ID", "kind": "string",
         "text": fields["device"]},
        {"id": "device_phy", "label": "PHY Device Name/ID", "kind": "string",
         "text": fields["device_phy"]},
        {"id": "channels", "label": "Channels", "kind": "raw",
         "text": repr(fields["channels"])},
        {"id": "buffer_size", "label": "Buffer size", "kind": "int",
         "text": str(fields["buffer_size"])},
    ]
    if fields.get("is_sink"):
        boxes.append({"id": "interpolation", "label": "Interpolation",
                      "kind": "int", "text": str(fields["interpolation"])})
        boxes.append({"id": "cyclic", "label": "Cyclic", "kind": "bool",
                      "text": str(bool(fields.get("cyclic", False)))})
    else:
        boxes.append({"id": "decimation", "label": "Decimation",
                      "kind": "int", "text": str(fields["decimation"])})
    boxes.append({"id": "params", "label": "Parameters", "kind": "raw",
                  "text": repr(fields["params"])})
    boxes.append({"id": "len_tag_key", "label": "Packet Length Tag",
                  "kind": "string", "text": fields["len_tag_key"]})
    return boxes


# ------------------------------------------------- generated GRC blocks
#
# GRC cannot populate a dropdown from live hardware. It does not have to:
# a block definition is a YAML file, and the legal values are sitting in
# the capture. So generate the block instead of patching GRC.
#
# Two facts about GRC decide the shape of what follows, both read off
# grc/core/params/param.py rather than guessed:
#
#   1. An `enum` parameter's option is substituted into the make template
#      VERBATIM -- it is never evaluated. A string option therefore has to
#      carry its own quotes: "'push-pull'", not "push-pull". gr-iio's own
#      blocks do exactly this.
#   2. GRC finds out-of-tree definitions through GRC_BLOCKS_PATH.

CATEGORY = "[ADALM2000]"

# Above this many dropdowns a block stops being usable. Attributes that
# repeat across channels collapse into one parameter that applies to all
# of them; the per-channel keys go in the documentation so nothing is
# actually taken away.
COLLAPSE_FROM = 2


def _identifier(text):
    """A GRC parameter id has to be a Python identifier."""
    return "p_" + "".join(c if c.isalnum() or c == "_" else "_" for c in text)


def _assign_ids(entries):
    """Give each entry a parameter id that is unique within the block.

    The attribute name alone is not enough. Entries are grouped by name
    AND legal values, so one driver that offers different options for the
    same attribute on different channels produces two entries with one
    name -- and two GRC parameters with the same id, which is a broken
    block: GRC keeps one, and the make template writes that one's value to
    both sets of channels.

    Where that happens the channel the entry starts at disambiguates,
    because a channel only appears in one entry for a given attribute.
    """
    counts = {}
    for entry in entries:
        counts[entry["attr"]] = counts.get(entry["attr"], 0) + 1

    used = set()
    for entry in entries:
        base = entry["attr"]
        if counts[base] > 1 and entry["channels"]:
            base = "%s_%s" % (base, entry["channels"][0])
        candidate = _identifier(base)
        suffix = 2
        while candidate in used:
            candidate = _identifier("%s_%d" % (base, suffix))
            suffix += 1
        used.add(candidate)
        entry["id"] = candidate
        # The label has to separate them on screen too, or two dropdowns
        # read as the same control.
        if counts[entry["attr"]] > 1 and entry["channels"]:
            entry["label"] = "%s (%s)" % (
                entry["attr"],
                ", ".join(entry["channels"][:3]) +
                (", ..." if len(entry["channels"]) > 3 else ""))
    return entries


def _quote(text):
    """Quote a value for verbatim substitution into a make template."""
    return "'%s'" % str(text).replace("\\", "\\\\").replace("'", "\\'")


def _yaml_scalar(text):
    """Emit a scalar that survives a YAML round trip.

    Everything here is quoted rather than guessing which bare words are
    safe -- "on", "no" and "1.0" all mean something else unquoted.
    """
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def _yaml_block(text, indent):
    """A literal block scalar, for documentation that contains anything."""
    pad = " " * indent
    lines = str(text).rstrip().split("\n")
    return "|\n" + "\n".join(pad + line if line else "" for line in lines)


def dropdown_attrs(device):
    """The attributes this device published a list of legal values for.

    Returns a list of {"key_template", "attr", "channels", "options",
    "attr_dict"}. A channel attribute that appears on several channels
    with the same options becomes one entry covering all of them.
    """
    entries = []

    for group in ("device_attrs", "buffer_attrs", "debug_attrs"):
        for attr in device.get(group, []):
            available = attr.get("available")
            if available and available["kind"] == "options":
                entries.append({
                    "attr": attr["name"],
                    "label": attr["name"],
                    "channels": [],
                    "keys": [attr["name"]],
                    "options": available["values"],
                    "attr_dict": attr,
                    "channel_dict": None,
                })

    # Group channel attributes by (name, options) so 18 identical
    # trigger_mux_out dropdowns become one.
    grouped = {}
    order = []
    for channel in device.get("channels", []):
        for attr in channel.get("attrs", []):
            available = attr.get("available")
            if not available or available["kind"] != "options":
                continue
            key = (attr["name"], tuple(available["values"]))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append((channel, attr))

    for key in order:
        members = grouped[key]
        name, options = key[0], list(key[1])
        keys = [sysfs_name(channel, attr["name"]) for channel, attr in members]
        label = name
        if len(members) >= COLLAPSE_FROM:
            label = "%s (all %d channels)" % (name, len(members))
        entries.append({
            "attr": name,
            "label": label,
            "channels": [c.get("id") for c, _ in members],
            "keys": keys,
            "options": options,
            "attr_dict": members[0][1],
            "channel_dict": members[0][0],
        })

    return _assign_ids(entries)


def _documentation(device, entries, streaming, is_sink):
    """What GRC shows in the block's Documentation tab.

    The point of putting it here is that a participant reading a
    flowgraph never has to leave GRC to find out what an attribute means
    or where the claim came from.
    """
    import iio_explain

    label = device.get("name") or device.get("id")
    lines = ["Generated from a live capture of %s." % label, ""]

    note = iio_overlays.device_note(device)
    if note:
        lines += [note["text"], "  [overlay: %s]" % note["confidence"], ""]

    lines.append("Streaming channels: %s"
                 % (", ".join(streaming) or "none"))
    lines.append("Direction: %s" % ("output (sink)" if is_sink else "input (source)"))
    lines.append("")

    for entry in entries:
        annotated = iio_explain.annotate_attr(
            device, entry["channel_dict"], entry["attr_dict"])
        lines.append("%s" % entry["label"])
        lines.append("  legal values: %s" % " ".join(entry["options"]))
        if annotated["summary"]:
            lines.append("  %s  [abi]" % annotated["summary"])
        if annotated["abi"]:
            lines.append("  kernel: %s" % annotated["abi"]["paragraphs"][0])
        if annotated["overlay"]:
            lines.append("  on this board: %s  [overlay: %s]"
                         % (annotated["overlay"]["text"],
                            annotated["overlay"]["confidence"]))
        if len(entry["keys"]) > 1:
            lines.append("  applies to all of: %s" % " ".join(entry["keys"]))
        lines.append("")

    lines += [
        "Anything not offered as a dropdown goes in 'Other parameters' as",
        "\"<sysfs name>=<value>\" strings -- that is also how you set one",
        "channel differently from the rest.",
    ]
    return "\n".join(lines)


def generate_block(data, device_name, category=CATEGORY):
    """Write a GRC block definition for one device, with real dropdowns.

    Returns the YAML text. Whether it is a source or a sink is decided by
    the device's own streaming channels, not by an argument -- the M2K's
    DAC devices only make sense as sinks.
    """
    device = find_device(data, device_name)
    if device is None:
        raise ValueError("no device '%s' in this capture" % device_name)

    label = device.get("name") or device.get("id")
    streams = stream_channels(device)
    if not streams:
        # Five of the M2K's fourteen devices are like this. A block for one
        # would carry `asserts: len(channels) > 0` that can never be met,
        # so it would sit in GRC permanently in error. The way to reach
        # these attributes is another block's device_phy, which is exactly
        # what gr-iio's set_params(phy, params) applies them to.
        raise ValueError(
            "%s has no streaming channels, so it is configuration only and "
            "cannot be a source or a sink. To set its attributes from a "
            "flowgraph, put device_phy=%s on the block that does stream, and "
            "list the attributes in that block's params -- gr-iio applies "
            "params to device_phy when it is set." % (label, label))
    is_sink = is_sink_device(device)
    stream_ids = [c.get("id") for c in streams]
    entries = dropdown_attrs(device)

    block_id = "m2k_%s_%s" % (
        "".join(c if c.isalnum() else "_" for c in label),
        "sink" if is_sink else "source")

    out = []
    out.append("id: %s" % block_id)
    out.append("label: %s" % _yaml_scalar(
        "M2K %s %s" % (label, "sink" if is_sink else "source")))
    out.append("category: %s" % _yaml_scalar(category))
    out.append("flags: [python, throttle]")
    out.append("")
    out.append("parameters:")
    out.append("-   id: uri")
    out.append("    label: IIO context URI")
    out.append("    dtype: string")
    out.append("    default: %s" % _yaml_scalar(data.get("uri") or "local:"))
    out.append("")
    out.append("-   id: channels")
    out.append("    label: Channels")
    out.append("    dtype: raw")
    out.append("    default: %s" % _yaml_scalar(repr(stream_ids)))
    out.append("")
    out.append("-   id: buffer_size")
    out.append("    label: Buffer size")
    out.append("    dtype: int")
    out.append("    default: %d" % DEFAULT_BUFFER_SIZE)
    out.append("")
    if is_sink:
        out.append("-   id: interpolation")
        out.append("    label: Interpolation")
        out.append("    dtype: int")
        out.append("    default: 1")
        out.append("")
        out.append("-   id: cyclic")
        out.append("    label: Cyclic")
        out.append("    dtype: bool")
        out.append("    default: %s" % _yaml_scalar("False"))
        out.append("    options: [%s, %s]"
                   % (_yaml_scalar("False"), _yaml_scalar("True")))
        out.append("    option_labels: [%s, %s]"
                   % (_yaml_scalar("False"), _yaml_scalar("True")))
        out.append("")
    else:
        out.append("-   id: decimation")
        out.append("    label: Decimation")
        out.append("    dtype: int")
        out.append("    default: 1")
        out.append("")

    for entry in entries:
        out.append("-   id: %s" % entry["id"])
        out.append("    label: %s" % _yaml_scalar(entry["label"]))
        out.append("    dtype: enum")
        # An enum option is substituted verbatim, so it carries its own
        # quotes. The empty option is what "leave this alone" looks like:
        # a shown value must never mean a value written to the hardware.
        options = ["''"] + [_quote(v) for v in entry["options"]]
        labels = ["leave alone"] + list(entry["options"])
        out.append("    default: %s" % _yaml_scalar("''"))
        out.append("    options: [%s]"
                   % ", ".join(_yaml_scalar(o) for o in options))
        out.append("    option_labels: [%s]"
                   % ", ".join(_yaml_scalar(l) for l in labels))
        out.append("")

    out.append("-   id: extra_params")
    out.append("    label: Other parameters")
    out.append("    dtype: raw")
    out.append("    default: \"[]\"")
    out.append("")

    if is_sink:
        out.append("inputs:")
    else:
        out.append("outputs:")
    out.append("-   domain: stream")
    out.append("    dtype: short")
    out.append("    multiplicity: ${ len(channels) }")
    if not is_sink:
        out.append("-   domain: message")
        out.append("    id: msg")
        out.append("    optional: true")
    out.append("")
    out.append("asserts:")
    out.append("- ${ len(channels) > 0 }")
    out.append("")

    out.append("templates:")
    out.append("    imports: from gnuradio import iio")
    out.append("    make: |-")
    for line in _make_template(label, entries, is_sink).split("\n"):
        out.append("        " + line)
    out.append("")
    out.append("documentation: %s"
               % _yaml_block(_documentation(device, entries, stream_ids,
                                            is_sink), 4))
    out.append("")
    out.append("file_format: 1")
    return "\n".join(out) + "\n"


def _make_template(label, entries, is_sink):
    """The constructor call, assembling params from the dropdowns.

    Empty dropdowns drop out of the list, so a block that has been opened
    and closed again writes nothing to the hardware.
    """
    pairs = []
    for entry in entries:
        variable = "${%s}" % entry["id"]
        if len(entry["keys"]) == 1:
            pairs.append("(%r, %s)" % (entry["keys"][0], variable))
        else:
            pairs.append("[(k, %s) for k in %r]" % (variable, entry["keys"]))

    singles = [p for p in pairs if p.startswith("(")]
    multiples = [p for p in pairs if p.startswith("[")]
    terms = []
    if singles:
        terms.append("[%s]" % ", ".join(singles))
    terms.extend(multiples)
    assembled = " + ".join(terms) if terms else "[]"

    call = "iio.device_sink" if is_sink else "iio.device_source"
    tail = ("${buffer_size}, ${interpolation} - 1, ${cyclic})" if is_sink
            else "${buffer_size}, ${decimation} - 1)")
    return ("%s(${uri}, %r, ${channels}, '',\n"
            "    [k + '=' + v for k, v in %s if v] + ${extra_params},\n"
            "    %s" % (call, label, assembled, tail))


def generate_all(data, category=CATEGORY):
    """Every device that can stream, as {filename: yaml text}."""
    out = {}
    for device in data.get("devices", []):
        if not stream_channels(device):
            continue
        label = device.get("name") or device.get("id")
        text = generate_block(data, label, category)
        out["%s.block.yml" % text.split("\n", 1)[0][4:]] = text
    return out


def main():
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(
        description="Generate GNU Radio block definitions from an IIO "
                    "capture, with dropdowns filled in from the hardware.")
    parser.add_argument("snapshot", help="JSON from iio_discover.py --json")
    parser.add_argument("--out", default="grc_blocks",
                        help="directory to write .block.yml files into")
    parser.add_argument("--device", help="just this one device")
    args = parser.parse_args()

    with open(args.snapshot) as handle:
        data = json.load(handle)

    if args.device:
        text = generate_block(data, args.device)
        blocks = {"%s.block.yml" % text.split("\n", 1)[0][4:]: text}
    else:
        blocks = generate_all(data)

    os.makedirs(args.out, exist_ok=True)
    for name, text in sorted(blocks.items()):
        with open(os.path.join(args.out, name), "w") as handle:
            handle.write(text)
        print("%s" % os.path.join(args.out, name))
    print("\nGRC_BLOCKS_PATH=%s gnuradio-companion"
          % os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
