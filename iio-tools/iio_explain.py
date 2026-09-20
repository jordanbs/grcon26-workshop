#!/usr/bin/env python3
"""
iio_explain.py -- say what an IIO device's attributes actually mean.

iio_discover.py tells you what is there. This tells you what it is. It
reads the JSON that `iio_discover.py --json` produces and never imports
libiio itself, so it runs on a laptop with no hardware attached:

    on the bench:   ./iio_discover.py --json > m2k.json
    anywhere:       ./iio_explain.py m2k.json --channels

Meaning comes from four places, and every line says which one it came
from so you can tell fact from convention from guesswork:

    [abi]       the Linux IIO ABI. True of every IIO device ever merged.
                Quoted verbatim from the kernel docs -- see iio_abi_fetch.py.
    [parsed]    read straight out of the attribute name.
    [driver]    the driver named the channel itself. Rare and trustworthy.
    [overlay]   hand-written board knowledge -- see iio_overlays.py. Shows
                its own confidence, and says UNVERIFIED when it has one.

Usage:
    ./iio_explain.py m2k.json                    # what each channel measures
    ./iio_explain.py m2k.json --tree             # the whole tree, annotated
    ./iio_explain.py m2k.json --attr raw         # one attribute, in depth
    ./iio_explain.py m2k.json --unknown          # what we still cannot explain
    ./iio_explain.py m2k.json --glossary         # participant handout
    ./iio_explain.py --uri usb:1.5.5 --channels  # straight from hardware
"""

import argparse
import json
import sys
import textwrap

import iio_semantics as sem
import iio_overlays

WIDTH = 78


# --------------------------------------------------------------- printing

def para(text, indent=2, width=WIDTH):
    pad = " " * indent
    return textwrap.fill(text, width=width, initial_indent=pad,
                         subsequent_indent=pad)


def tag(provenance, confidence=None):
    if confidence in ("unverified",):
        return "[%s: UNVERIFIED]" % provenance
    if confidence in ("sourced", "measured", "convention"):
        return "[%s: %s]" % (provenance, confidence)
    return "[%s]" % provenance


def rule(char="=", width=WIDTH):
    return char * width


# ------------------------------------------------------------------ input

def load(args):
    if args.uri or args.local:
        import iio_discover
        return iio_discover.enumerate_context(args.uri, args.device)
    if not args.snapshot:
        sys.exit("Give a snapshot file (from `iio_discover.py --json`) "
                 "or --uri to read hardware directly.")
    if args.snapshot == "-":
        return json.load(sys.stdin)
    try:
        with open(args.snapshot) as handle:
            return json.load(handle)
    except (IOError, OSError) as exc:
        sys.exit("Could not read %s: %s" % (args.snapshot, exc))


def devices(data, device_filter=None):
    for device in data.get("devices", []):
        if device_filter and device_filter not in (device.get("id"),
                                                   device.get("name")):
            continue
        yield device


def walk(data, device_filter=None):
    """Yield (device, channel_or_None, attr) for every attribute."""
    for device in devices(data, device_filter):
        for key in ("device_attrs", "buffer_attrs", "debug_attrs"):
            for attr in device.get(key, []):
                yield device, None, attr
        for channel in device.get("channels", []):
            for attr in channel.get("attrs", []):
                yield device, channel, attr


# ------------------------------------------------------------- annotation

def conversion_for(channel, device=None):
    """Work the raw -> real arithmetic for a channel, if it can be worked."""
    by_info = sem.attrs_by_info(channel.get("attrs", []), channel)
    raw = by_info.get("raw")
    if raw is None:
        if "input" in by_info:
            return {"note": "This channel exposes _input, which is already "
                            "in the channel's units. Nothing to convert."}
        # No _raw at all. On a streaming channel that is not a gap -- it is
        # the whole point, and it is the thing most likely to confuse someone
        # coming from `cat`-ing sysfs files. Say so, and show the conversion
        # they will need in the flowgraph instead of here.
        if channel.get("scan_element"):
            bits = sem.parse_channel_id(channel.get("id") or "")
            return {
                "streaming": True,
                "note": "There is no _raw attribute here, and that is "
                        "expected: this is a streaming channel. Values come "
                        "out of the capture buffer, not from a one-shot "
                        "attribute read, so there is no single current "
                        "value to print.",
                "scale": (by_info.get("scale") or {}).get("value"),
                "offset": (by_info.get("offset") or {}).get("value"),
                "chan_type": bits["type"] if bits else None,
                "recipe": iio_overlays.scale_recipe(device),
            }
        return None
    if raw.get("value") is None:
        return {"note": "_raw is present but not readable here (%s). On an "
                        "output channel that is normal -- you write it, you "
                        "do not read it."
                        % (raw.get("read_error") or "no value")}

    bits = sem.parse_channel_id(channel.get("id") or "")
    offset = by_info.get("offset")
    scale = by_info.get("scale")
    result = sem.convert_raw(
        raw.get("value"),
        offset.get("value") if offset else None,
        scale.get("value") if scale else None,
        bits["type"] if bits else None)
    if result:
        result["raw"] = raw.get("value")
        result["offset"] = offset.get("value") if offset else None
        result["scale"] = scale.get("value") if scale else None
    return result


def print_conversion(result, indent=4):
    pad = " " * indent
    if result is None:
        return
    if result.get("streaming"):
        print(para(result["note"], indent))
        scale, offset = result.get("scale"), result.get("offset")
        if scale is None:
            print(para("No _scale either, so the samples are raw counts and "
                       "nothing on this device tells you what they are "
                       "worth.", indent))
            recipe = result.get("recipe")
            if recipe:
                print()
                for line in recipe["text"].splitlines():
                    print("%s%s" % (" " * indent, line) if line else "")
                print(para(tag("overlay", recipe["confidence"]), indent))
                if recipe.get("source"):
                    print(para("source: %s" % recipe["source"], indent))
            else:
                print(para("That conversion has to come from the datasheet "
                           "or from a vendor library.", indent))
            return
        print(para("The same contract still applies, one sample at a time. "
                   "Apply it in your flowgraph:", indent))
        formula = "(sample + %s) * %s" % (offset, scale) if offset is not None \
            else "sample * %s" % scale
        print("%s%s   real = %s" % (" " * indent, "", formula))
        example = sem.convert_raw("1000", offset, scale,
                                  result.get("chan_type"))
        if example:
            print(para("So a sample of 1000 -- an illustration, not a "
                       "reading -- would be %s = %g %s."
                       % (example["expression"], example["value"],
                          example["symbol"] or ""), indent))
        return
    if "note" in result:
        print(para(result["note"], indent))
        return

    parts = ["raw %s" % result["raw"]]
    if result["used_offset"]:
        parts.append("offset %s" % result["offset"])
    if result["used_scale"]:
        parts.append("scale %s" % result["scale"])
    print("%sRight now    %s" % (pad, ", ".join(parts)))

    line = "%s = %g %s" % (result["expression"], result["value"],
                           result["symbol"] or "")
    print("%s             %s" % (pad, line.strip()))
    if result.get("si_value") is not None:
        print("%s             = %g %s" % (pad, result["si_value"],
                                          result["si_symbol"]))


# ------------------------------------------------------------- the verbs

def show_channels(data, args):
    print(rule())
    print("What this hardware measures")
    print(rule())
    if data.get("_synthetic"):
        print()
        print(para("NOTE: this is a synthetic fixture, not a real capture. "
                   + (data.get("_synthetic_note") or ""), 2))

    for device in devices(data, args.device):
        print("\n" + rule("="))
        header = device.get("name") or device.get("id")
        if device.get("id") != device.get("name"):
            header += "   (%s)" % device.get("id")
        print(header)
        print(rule("="))

        note = iio_overlays.device_note(device)
        if note:
            print(para("%s %s" % (note["text"],
                                  tag("overlay", note["confidence"])), 2))

        if not device.get("channels"):
            print(para("No channels. Device-level attributes only.", 2))

        for channel in device.get("channels", []):
            tags = ["output" if channel.get("output") else "input"]
            if channel.get("scan_element"):
                tags.append("streaming")
                if channel.get("scan_index") is not None:
                    tags.append("buffer slot %s" % channel["scan_index"])
            print("\n  %s  [%s]" % (channel.get("id"), ", ".join(tags)))

            described = sem.describe_channel(channel)
            if described:
                print(para(described, 4))

            fmt = sem.describe_data_format(channel.get("data_format"))
            if fmt:
                print("    Samples      %s" % fmt["shorthand"])
                if args.verbose:
                    print(para(fmt["english"], 17, WIDTH))

            print_conversion(conversion_for(channel, device))

            findings = sem.channel_identity(device, channel, iio_overlays)
            if not args.verbose and any(not f.get("fallback") for f in findings):
                findings = [f for f in findings if not f.get("fallback")]
            for finding in findings:
                print(para("%s %s" % (finding["text"],
                                      tag(finding["provenance"],
                                          finding.get("confidence"))), 4))
                if finding.get("source"):
                    print(para("source: %s" % finding["source"], 6))
                if args.verbose and finding.get("check"):
                    print(para("to verify: %s" % finding["check"], 6))
    print()


def show_attr(data, args):
    wanted = args.attr
    matches = []
    for device, channel, attr in walk(data, args.device):
        parsed = sem.parse_attr_name(attr["name"], channel)
        if wanted in (attr["name"], parsed["sysfs_name"], parsed["info"]):
            matches.append((device, channel, attr, parsed))

    if not matches:
        print("No attribute matching '%s'. Try --tree to see what exists."
              % wanted)
        return 1

    shown = matches[:args.limit]
    for device, channel, attr, parsed in shown:
        print("\n" + rule())
        where = device.get("name") or device.get("id")
        if channel:
            where += " / " + channel.get("id")
        print("%s          %s" % (parsed["sysfs_name"], where))
        print(rule())

        info = sem.info_word_info(parsed["info"])
        if info:
            print()
            print(para(info["summary"], 2))
            print("\n  Its own unit   %s" % info["unit"])
            if info.get("detail"):
                print()
                print(para(info["detail"], 2))
        else:
            print()
            print(para("Not in the ABI tables. Nothing generic is known "
                       "about this attribute -- it is driver-specific.", 2))

        print("\n  From the name alone:")
        for label, key in (("direction", "direction"),
                           ("channel type", "channel_type"),
                           ("channel index", "channel_index"),
                           ("modifier", "modifier"),
                           ("role", "info")):
            value = parsed.get(key)
            if value is not None:
                print("    %-14s %s   %s" % (label, value, tag("parsed")))
        if parsed["differential"]:
            print(para("This is a differential attribute: it describes the "
                       "difference between two inputs, not one against "
                       "ground. %s" % tag("parsed"), 4))

        chan_type = sem.channel_type_info(parsed["channel_type"])
        if chan_type:
            print("\n  Channel type '%s' %s" % (parsed["channel_type"],
                                                tag("abi")))
            print(para("Measures %s. After scale and offset the unit is %s."
                       % (chan_type["quantity"], chan_type["unit"]), 4))
            if chan_type.get("note"):
                print(para("Watch out: %s." % chan_type["note"], 4))

        if attr.get("value") is not None:
            print("\n  Value right now   %s" % attr["value"])
        elif attr.get("read_error"):
            print("\n  Value right now   unreadable (%s)" % attr["read_error"])

        available = attr.get("available")
        if available:
            if available["kind"] == "range":
                print("  Legal values      %s to %s in steps of %s   [range]"
                      % (available["min"], available["max"],
                         available["step"]))
            else:
                values = available["values"]
                shown_values = " ".join(values[:12])
                if len(values) > 12:
                    shown_values += " ... (%d total)" % len(values)
                print("  Legal values      %s   [%d options]"
                      % (shown_values, len(values)))

        if channel and info and info.get("needs_conversion"):
            print("\n  Turning it into a measurement:")
            print(para("real = (raw + offset) * scale   -- offset first, "
                       "then scale. %s" % tag("abi"), 4))
            print_conversion(conversion_for(channel, device))

        reference = sem.abi_reference(parsed["sysfs_name"], attr.get("type"))
        if reference:
            print("\n  The kernel's own words %s" % tag("abi"))
            for paragraph in reference["description"][:2]:
                print()
                print(para(paragraph, 4))
            print("\n%s" % para("-- Linux ABI %s, since kernel %s"
                                % (reference["source"],
                                   reference["kernel_version"] or "?"), 4))
        else:
            print("\n" + para("Not documented in the kernel ABI files.", 2))

        use = sem.libm2k_use(parsed["info"])
        if use:
            print("\n  What drives it %s" % tag("libm2k"))
            if use["instruments"]:
                print(para("Part of the %s."
                           % " and ".join(use["instruments"]).lower(), 4))
            print(para("libm2k reaches it from %s."
                       % ", ".join(use["methods"][:3]), 4))
            print(para("So this is a knob you already know from Scopy, "
                       "under its sysfs name.", 4))

        note = iio_overlays.attr_note(device, parsed["info"])
        if note:
            print("\n  On this board %s" % tag("overlay", note["confidence"]))
            print(para(note["text"], 4))
            if note.get("source"):
                print(para("source: %s" % note["source"], 4))
            if note.get("check"):
                print(para("to verify: %s" % note["check"], 4))

    if len(matches) > len(shown):
        print("\n%d more match '%s'. Narrow with --device, or raise --limit."
              % (len(matches) - len(shown), wanted))
    print()
    return 0


def show_tree(data, args):
    print("Context: %s" % (data.get("description") or data.get("uri")
                           or "(default)"))
    for device in devices(data, args.device):
        print("\n" + rule("="))
        print(device.get("name") or device.get("id"))
        print(rule("="))
        for label, key in (("Device", "device_attrs"),
                           ("Buffer", "buffer_attrs"),
                           ("Debug", "debug_attrs")):
            attrs = device.get(key) or []
            if not attrs:
                continue
            print("\n  %s attributes (%d):" % (label, len(attrs)))
            for attr in attrs:
                print_tree_attr(device, None, attr, 4)
        for channel in device.get("channels", []):
            print("\n  %s:" % channel.get("id"))
            for attr in channel.get("attrs", []):
                print_tree_attr(device, channel, attr, 4)
    print()


def print_tree_attr(device, channel, attr, indent):
    pad = " " * indent
    value = attr.get("value")
    if value is not None and len(str(value)) > 40:
        value = str(value)[:37] + "..."
    print("%s%-30s = %s" % (pad, attr["name"],
                            value if value is not None else "<unreadable>"))
    parsed = sem.parse_attr_name(attr["name"], channel)
    info = sem.info_word_info(parsed["info"])
    if info:
        print(para(info["summary"], indent + 2))
    else:
        print(para("Not in the ABI tables -- driver-specific.", indent + 2))


def show_unknown(data, args):
    """Everything the semantic layer could not explain. The honest metric."""
    unknown = {}
    total = 0
    for device, channel, attr in walk(data, args.device):
        total += 1
        parsed = sem.parse_attr_name(attr["name"], channel)
        if sem.is_understood(parsed, attr.get("type")):
            continue
        key = parsed["info"]
        entry = unknown.setdefault(key, {"count": 0, "where": set(),
                                         "abi": None, "overlay": None})
        entry["count"] += 1
        entry["where"].add(device.get("name") or device.get("id"))
        if entry["abi"] is None:
            entry["abi"] = sem.abi_reference(parsed["sysfs_name"],
                                             attr.get("type"))
        if entry["overlay"] is None:
            entry["overlay"] = iio_overlays.attr_note(device, key)

    explained = total - sum(e["count"] for e in unknown.values())
    print(rule())
    print("Coverage")
    print(rule())
    print("  %d of %d attributes explained by the ABI tables (%.0f%%)"
          % (explained, total, 100.0 * explained / total if total else 0))

    covered = {k: v for k, v in unknown.items() if v["overlay"]}
    bare = {k: v for k, v in unknown.items() if not v["overlay"]}

    if covered:
        print("\n  Not generic, but the board pack explains them:\n")
        for name in sorted(covered, key=lambda k: -covered[k]["count"]):
            entry = covered[name]
            print("    %-28s x%-3d  %s   [overlay: %s]"
                  % (name, entry["count"], ", ".join(sorted(entry["where"])),
                     entry["overlay"]["confidence"]))

    if bare:
        print("\n  Nothing explains these yet:\n")
        for name in sorted(bare, key=lambda k: -bare[k]["count"]):
            entry = bare[name]
            print("    %-28s x%-3d  %s" % (name, entry["count"],
                                           ", ".join(sorted(entry["where"]))))
            if entry["abi"]:
                print(para("the kernel does document this -- add it to "
                           "INFO_WORDS in iio_semantics.py", 8))
    if not unknown:
        print("\n  Everything here is explained.")

    counts = iio_overlays.coverage()
    print("\n  Board-specific notes: %d total, %d sourced, %d unverified"
          % (counts.get("total", 0), counts.get("sourced", 0),
             counts.get("unverified", 0)))
    abi = sem.abi_data()
    if abi:
        print("  Kernel ABI cache: %d documented attribute names"
              % len(abi.get("index", {})))
    else:
        print("  Kernel ABI cache: MISSING -- run ./iio_abi_fetch.py")
    print()


def show_glossary(data, args):
    """Generate the participant handout as markdown on stdout."""
    out = []
    add = out.append
    add("# Reading IIO attribute names\n")
    add("Generated by `iio_explain.py --glossary`. Everything marked "
        "**[abi]** is true of every IIO device, not just the M2K.\n")

    add("## The one rule that matters\n")
    add("A `_raw` value is not a measurement. It is a count. To get a real "
        "number:\n")
    add("```\nreal value = (raw + offset) * scale\n```\n")
    add("Offset is added **before** scale, not after. Offset is in raw "
        "counts; scale converts counts into the channel's unit.\n")

    add("## The units are not the ones you expect\n")
    add("The IIO ABI fixes the unit per channel type, and they are "
        "deliberately sub-unit so integers stay useful:\n")
    add("| Channel type | Measures | Unit after scale |")
    add("| --- | --- | --- |")
    for name in sorted(sem.CHANNEL_TYPES):
        spec = sem.CHANNEL_TYPES[name]
        add("| `%s` | %s | %s |" % (name, spec["quantity"], spec["unit"]))
    add("")

    add("## How an attribute name is built\n")
    add("```\n{in|out}_{type}{index}[_{modifier}]_{info}\n```\n")
    add("| Part | Example | Means |")
    add("| --- | --- | --- |")
    add("| direction | `in_` | into the device (a measurement) |")
    add("| direction | `out_` | out of the device (a generator) |")
    add("| type | `voltage` | what is being measured |")
    add("| index | `0` | which channel |")
    add("| modifier | `_red` | narrows it further |")
    add("| info | `_raw` | what role this file plays |")
    add("")
    add("A dash means a differential pair: `in_voltage0-voltage1_raw` is "
        "the difference between two pins, not either one against ground.\n")

    add("## Info words\n")
    add("| Info word | Its own unit | Means |")
    add("| --- | --- | --- |")
    for name in sorted(sem.INFO_WORDS):
        spec = sem.INFO_WORDS[name]
        add("| `%s` | %s | %s |" % (name, spec["unit"], spec["summary"]))
    add("")

    add("## Modifiers\n")
    add("| Modifier | Means |")
    add("| --- | --- |")
    for name in sorted(sem.MODIFIERS):
        add("| `%s` | %s |" % (name, sem.MODIFIERS[name]))
    add("")

    add("## What `voltage0` actually is\n")
    add("Nothing in libiio says which pin a channel is wired to. Ask these "
        "in order:\n")
    add("1. **The channel name.** `iio_channel_get_name()` returns the "
        "driver's own name for the channel. Most drivers leave it empty; "
        "when it is set, believe it.")
    add("2. **The `label` attribute.** Same idea, settable from the device "
        "tree.")
    add("3. **The vendor library.** For the M2K, libm2k's `M2kAnalogIn` "
        "indexes `m2k-adc` channels directly as scope channels 1 and 2.")
    add("4. **The convention.** The kernel docs say an indexed channel "
        "corresponds to an externally available input, and that a driver "
        "should use a *named* channel when it does not. A strong hint, not "
        "a promise.\n")

    add("## Where to look it up yourself\n")
    add("- `Documentation/ABI/testing/sysfs-bus-iio` in the Linux source — "
        "the definitive description of every generic attribute. "
        "`./iio_abi_fetch.py --show in_voltage0_raw` prints it.")
    add("- The driver's `iio_chan_spec` table — says which index is which "
        "input.")
    add("- For the M2K: the libm2k source, which is what Scopy itself uses.")
    add("- The datasheet, for anything the software cannot know.\n")

    text = "\n".join(out)
    if args.output:
        with open(args.output, "w") as handle:
            handle.write(text)
        print("wrote %s" % args.output, file=sys.stderr)
    else:
        print(text)


# -------------------------------------------------------- machine output
#
# Everything above prints to a terminal. The browser in iio_browse.py
# needs the same facts as data. Rather than write the meaning down twice
# and let the two drift, the facts get assembled here once and rendered
# in two places.

def annotate_attr(device, channel, attr):
    """Everything known about one attribute, as a plain dict.

    The four sources answer independently and each keeps its own tag, so
    a reader can always see whether a claim came from the kernel, from
    the name, or from a person guessing.
    """
    parsed = sem.parse_attr_name(attr["name"], channel)
    info = sem.info_word_info(parsed["info"])
    chan_type = sem.channel_type_info(parsed["channel_type"])
    reference = sem.abi_reference(parsed["sysfs_name"], attr.get("type"))
    note = iio_overlays.attr_note(device, parsed["info"])
    use = sem.libm2k_use(parsed["info"])

    provenance = ["parsed"]
    if info or chan_type or reference:
        provenance.append("abi")
    if note:
        provenance.append("overlay:" + note["confidence"])

    return {
        "name": attr["name"],
        "sysfs_name": parsed["sysfs_name"],
        "type": attr.get("type"),
        "value": attr.get("value"),
        "read_error": attr.get("read_error"),
        "available": attr.get("available"),
        "info_word": parsed["info"],
        "understood": sem.is_understood(parsed, attr.get("type")),
        "libm2k": use,
        "parsed": {k: parsed[k] for k in
                   ("direction", "channel_type", "channel_index",
                    "modifier", "differential")},
        "summary": info["summary"] if info else None,
        "unit": info["unit"] if info else None,
        "detail": info.get("detail") if info else None,
        "needs_conversion": bool(info and info.get("needs_conversion")),
        "channel_type": ({"type": parsed["channel_type"],
                          "quantity": chan_type["quantity"],
                          "unit": chan_type["unit"],
                          "note": chan_type.get("note")}
                         if chan_type else None),
        "abi": ({"paragraphs": reference["description"],
                 "kernel_version": reference["kernel_version"],
                 "source": reference["source"]}
                if reference else None),
        "overlay": ({"text": note["text"], "confidence": note["confidence"],
                     "source": note.get("source"), "check": note.get("check")}
                    if note else None),
        "provenance": provenance,
    }


def annotate_channel(device, channel):
    """Everything known about one channel, as a plain dict."""
    return {
        "id": channel.get("id"),
        "name": channel.get("name"),
        "output": bool(channel.get("output")),
        "scan_element": bool(channel.get("scan_element")),
        "scan_index": channel.get("scan_index"),
        "description": sem.describe_channel(channel),
        "identity": sem.channel_identity(device, channel, iio_overlays),
        "data_format": sem.describe_data_format(channel.get("data_format")),
        # The device matters: without it the board's scale recipe -- the
        # only thing that says what an m2k-adc count is worth -- is looked
        # up against nothing and comes back empty.
        "conversion": conversion_for(channel, device),
        "attrs": [annotate_attr(device, channel, a)
                  for a in channel.get("attrs", [])],
    }


def annotate_device(device):
    """A whole device: its note, its channels, its non-channel attributes."""
    note = iio_overlays.device_note(device)
    groups = {}
    for group in ("device_attrs", "buffer_attrs", "debug_attrs"):
        groups[group] = [annotate_attr(device, None, a)
                         for a in device.get(group, [])]
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "label": device.get("name") or device.get("id"),
        "overlay": ({"text": note["text"], "confidence": note["confidence"],
                     "source": note.get("source"), "check": note.get("check")}
                    if note else None),
        # Hardware order, so the page lists channels the way the block
        # will number its ports.
        "channels": [annotate_channel(device, c)
                     for c in sorted(device.get("channels", []),
                                     key=sem.channel_sort_key)],
        "device_attrs": groups["device_attrs"],
        "buffer_attrs": groups["buffer_attrs"],
        "debug_attrs": groups["debug_attrs"],
        # The knobs the hardware itself published a list of legal values
        # for. Computed by the same function that builds the dropdowns in
        # a generated GRC block, so the page and the block cannot drift --
        # including its collapsing of one attribute repeated across many
        # channels into a single control.
        "settings": annotate_settings(device),
        "streaming": sum(1 for c in device.get("channels", [])
                         if c.get("scan_element")),
    }


def annotate_settings(device):
    """The device's real controls, collapsed the way a block would show them."""
    import iio_grc

    out = []
    for entry in iio_grc.dropdown_attrs(device):
        annotated = annotate_attr(device, entry["channel_dict"],
                                  entry["attr_dict"])
        out.append({
            "attr": entry["attr"],
            "label": entry["label"],
            "keys": entry["keys"],
            "channels": entry["channels"],
            "options": entry["options"],
            "value": entry["attr_dict"].get("value"),
            "summary": annotated["summary"],
            "understood": annotated["understood"],
            "libm2k": annotated["libm2k"],
        })
    return out


def annotate(data):
    """A whole capture, annotated. This is what the browser loads."""
    return {
        "uri": data.get("uri"),
        "description": data.get("description"),
        "context_attrs": [annotate_attr(None, None, a)
                          for a in data.get("context_attrs", [])],
        "devices": [annotate_device(d) for d in data.get("devices", [])],
    }


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", nargs="?",
                    help="JSON from `iio_discover.py --json`, or - for stdin")
    ap.add_argument("--uri", help="read hardware directly instead, e.g. usb:1.5.5")
    ap.add_argument("--local", action="store_true",
                    help="read the local IIO context directly")
    ap.add_argument("--device", help="only this device (id or name)")
    ap.add_argument("--tree", action="store_true",
                    help="the whole attribute tree, annotated")
    ap.add_argument("--channels", action="store_true",
                    help="what each channel measures (default)")
    ap.add_argument("--attr", metavar="NAME",
                    help="explain one attribute in depth")
    ap.add_argument("--unknown", action="store_true",
                    help="list attributes the tables cannot explain")
    ap.add_argument("--glossary", action="store_true",
                    help="generate the participant handout as markdown")
    ap.add_argument("--output", "-o", help="write --glossary here")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="show sample layouts and verification steps")
    ap.add_argument("--limit", type=int, default=4,
                    help="max matches for --attr (default 4)")
    args = ap.parse_args()

    # These outputs are long and people pipe them to head or less. Without
    # this, closing the pipe early raises BrokenPipeError instead of just
    # ending.
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    data = load(args)

    if args.attr:
        return show_attr(data, args)
    if args.tree:
        show_tree(data, args)
    elif args.unknown:
        show_unknown(data, args)
    elif args.glossary:
        show_glossary(data, args)
    else:
        show_channels(data, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
