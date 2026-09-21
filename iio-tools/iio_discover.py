#!/usr/bin/env python3
"""
iio_discover.py -- enumerate IIO devices, channels, and attributes.

Answers the three questions the GNU Radio IIO blocks assume you already know:
  1. What devices/channels/attributes does this hardware actually expose?
  2. What is each attribute set to right now?
  3. What values are legal?

Question 3 is answered by the IIO convention that an attribute FOO may have a
sibling attribute FOO_available holding either a "[min step max]" range or a
space-separated list of allowed values. This script folds those siblings into
their parent instead of listing them separately.

What this script does NOT do: tell you what an attribute *means*. libiio has
no description field. That is iio_explain.py's job, and it turns out most of
it need not be hand-written -- the kernel documents the generic half itself,
in Documentation/ABI/testing/sysfs-bus-iio. Only what is specific to a
particular board has to be written down by a person.

    ./iio_discover.py --json > m2k.json
    ./iio_explain.py m2k.json --channels

Usage:
    ./iio_discover.py --scan                 # list reachable contexts
    ./iio_discover.py                        # auto-connect, print tree
    ./iio_discover.py --uri usb:1.5.5        # explicit context
    ./iio_discover.py --device m2k-adc       # filter to one device
    ./iio_discover.py --json > m2k.json      # machine-readable dump

Requires the libiio Python bindings (pylibiio / python3-libiio), i.e. the
same `iio` module the libiio command line tools are built against.
"""

import argparse
import json
import sys

NO_IIO = (
    "Could not import the 'iio' module.\n"
    "Install the libiio Python bindings, e.g.:\n"
    "  Debian/Ubuntu:  sudo apt install python3-libiio\n"
    "  pip:            pip install pylibiio"
)

try:
    import iio
except ImportError:
    # Deliberately not fatal at import time. The parsing helpers below are
    # pure and get reused by iio_semantics.py and by the tests, which run
    # on machines with no libiio and no hardware. Anything that actually
    # touches a context re-raises this.
    iio = None


def _require_iio():
    if iio is None:
        sys.exit(NO_IIO)


# ---------------------------------------------------------------- reading

def _read(attr):
    """Read one attribute. Returns (value, error_string).

    A read error is normal and informative: write-only attributes and
    action-style attributes (fastlock_recall and friends) error on read.
    We record the error rather than dropping the attribute.
    """
    try:
        return attr.value, None
    except AttributeError:
        # Some binding versions hand back a plain string instead of an
        # attribute object, notably for context attributes. Take it as-is.
        if isinstance(attr, str):
            return attr, None
        return None, "no readable value"
    except (OSError, ValueError) as exc:
        return None, str(exc)


def parse_available(raw):
    """Interpret an *_available value into something structured."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    # "[min step max]" -- a continuous range
    if text.startswith("[") and text.endswith("]"):
        parts = text[1:-1].split()
        if len(parts) == 3:
            return {"kind": "range", "min": parts[0],
                    "step": parts[1], "max": parts[2]}

    # otherwise a space-separated list of discrete choices
    parts = text.split()
    if parts:
        return {"kind": "options", "values": parts}
    return None


def collect_attrs(attr_map, attr_type):
    """Turn a libiio attribute mapping into a list of dicts.

    attr_type is the category string ('device', 'channel', 'buffer',
    'debug', 'context') -- the same distinction the gr-iio attribute
    blocks make you specify.
    """
    if not attr_map:
        return []

    raw = {}
    for name in attr_map:
        value, error = _read(attr_map[name])
        raw[name] = (value, error)

    consumed = set()
    out = []

    for name in sorted(raw):
        if name.endswith("_available") or name.endswith("_range"):
            continue
        value, error = raw[name]

        available_raw = None
        for suffix in ("_available", "_range"):
            sibling = name + suffix
            if sibling in raw:
                available_raw = raw[sibling][0]
                consumed.add(sibling)
                break

        out.append({
            "name": name,
            "type": attr_type,
            "value": value,
            "read_error": error,
            "available_raw": available_raw,
            "available": parse_available(available_raw),
        })

    # any *_available with no matching parent still deserves a line
    for name in sorted(raw):
        if (name.endswith("_available") or name.endswith("_range")) \
                and name not in consumed:
            value, error = raw[name]
            out.append({
                "name": name,
                "type": attr_type,
                "value": value,
                "read_error": error,
                "available_raw": None,
                "available": None,
            })

    return out


def collect_data_format(chan):
    """Capture the on-the-wire sample layout of a streaming channel.

    This is not an attribute -- it comes from the scan element -- so
    nothing in the attribute tree tells you about it. It is exactly what
    gr-iio hands you: sample width, container width, shift, signedness,
    byte order. `iio_info` shows it as e.g. "le:s12/16>>0".
    """
    fmt = getattr(chan, "data_format", None)
    if fmt is None:
        return None

    flags = ("is_signed", "is_be", "with_scale")
    out = {}
    for field in ("length", "bits", "shift", "repeat", "scale") + flags:
        value = getattr(fmt, field, None)
        if value is None:
            continue
        out[field] = bool(value) if field in flags else value
    return out or None


# ------------------------------------------------------------ enumeration

def enumerate_context(uri=None, device_filter=None):
    """Walk a whole IIO context. Returns a plain nested dict.

    This is the function the GUI should import. It touches no printing
    and no argparse, so the tree view can be built straight off the
    return value.
    """
    _require_iio()
    ctx = iio.Context(uri) if uri else iio.Context()

    result = {
        "uri": getattr(ctx, "name", None) if uri is None else uri,
        "description": getattr(ctx, "description", None),
        "context_attrs": collect_attrs(getattr(ctx, "attrs", {}), "context"),
        "devices": [],
    }

    for dev in ctx.devices:
        dev_name = dev.name or dev.id
        if device_filter and device_filter not in (dev.id, dev.name):
            continue

        entry = {
            "id": dev.id,
            "name": dev.name,
            "label": dev_name,
            "device_attrs": collect_attrs(getattr(dev, "attrs", {}), "device"),
            "buffer_attrs": collect_attrs(getattr(dev, "buffer_attrs", {}), "buffer"),
            "debug_attrs": collect_attrs(getattr(dev, "debug_attrs", {}), "debug"),
            "channels": [],
        }

        for chan in dev.channels:
            entry["channels"].append({
                "id": chan.id,
                "name": chan.name,
                "output": bool(getattr(chan, "output", False)),
                "scan_element": bool(getattr(chan, "scan_element", False)),
                "scan_index": getattr(chan, "index", None),
                "data_format": collect_data_format(chan),
                "attrs": collect_attrs(getattr(chan, "attrs", {}), "channel"),
            })

        result["devices"].append(entry)

    return result


def scan():
    """List discoverable contexts.

    Note the word discoverable. This finds the local context and USB
    devices, plus network devices only if libiio was built with mDNS and
    the device advertises itself. A board sitting at a fixed address --
    which is what an M2K on its USB ethernet gadget is -- will NOT show
    up here. You have to name it with --uri.
    """
    _require_iio()
    try:
        return dict(iio.scan_contexts())
    except AttributeError:
        return {}


def uri_hint():
    """What to try when --scan did not turn up what you expected.

    Scanning misses more than people expect, and the failure is silent:
    you get a short list with your board absent and no clue why.
    """
    return "\n".join((
        "Not everything is discoverable. --scan finds the local context and",
        "USB devices, and network devices only if libiio was built with mDNS",
        "support and the device advertises itself. If your board is missing,",
        "name it directly:",
        "",
        "  --uri ip:192.168.2.1   an M2K over its USB ethernet gadget, which",
        "                         is the usual way an M2K appears. It is at a",
        "                         fixed address and does not advertise, so it",
        "                         never shows up in a scan.",
        "  --uri ip:ADDRESS       any board reachable over the network",
        "  --uri usb:1.5.5        a USB device by bus.device.interface",
        "  --uri local:           the IIO devices on this machine",
        "",
        "If ip:192.168.2.1 times out, check the interface exists first:",
        "  ip addr | grep -B2 192.168.2   # the host end of the M2K link",
        "  ping -c1 192.168.2.1",
    ))


# -------------------------------------------------------------- printing

def fmt_available(attr):
    avail = attr.get("available")
    if not avail:
        return ""
    if avail["kind"] == "range":
        return "  legal: %s to %s, step %s" % (
            avail["min"], avail["max"], avail["step"])
    values = avail["values"]
    if len(values) > 8:
        shown = " ".join(values[:8]) + " ... (%d total)" % len(values)
    else:
        shown = " ".join(values)
    return "  legal: " + shown


def print_attr(attr, indent):
    pad = " " * indent
    if attr["read_error"]:
        print("%s%-32s <unreadable: %s>" % (pad, attr["name"], attr["read_error"]))
    else:
        value = attr["value"]
        if value is not None and len(value) > 60:
            value = value[:57] + "..."
        print("%s%-32s = %s" % (pad, attr["name"], value))
    extra = fmt_available(attr)
    if extra:
        print("%s%s%s" % (pad, " " * 32, extra))


def print_tree(data):
    print("Context: %s" % (data["description"] or data["uri"] or "(default)"))
    if data["context_attrs"]:
        print("\n  Context attributes:")
        for attr in data["context_attrs"]:
            print_attr(attr, 4)

    print("\n%d device(s)\n" % len(data["devices"]))

    for dev in data["devices"]:
        header = dev["id"]
        if dev["name"] and dev["name"] != dev["id"]:
            header += "  (%s)" % dev["name"]
        print("=" * 70)
        print(header)
        print("=" * 70)

        for label, key in (("Device attributes", "device_attrs"),
                           ("Buffer attributes", "buffer_attrs"),
                           ("Debug attributes", "debug_attrs")):
            attrs = dev[key]
            if attrs:
                print("\n  %s (%d):" % (label, len(attrs)))
                for attr in attrs:
                    print_attr(attr, 4)

        if dev["channels"]:
            print("\n  Channels (%d):" % len(dev["channels"]))
        for chan in dev["channels"]:
            tags = ["output" if chan["output"] else "input"]
            if chan["scan_element"]:
                tags.append("streaming")
            title = chan["id"]
            if chan["name"] and chan["name"] != chan["id"]:
                title += "  (%s)" % chan["name"]
            print("\n    %s  [%s]" % (title, ", ".join(tags)))
            if not chan["attrs"]:
                print("      (no attributes)")
            for attr in chan["attrs"]:
                print_attr(attr, 6)
        print()


def print_summary(data):
    """One line per device -- the 'is this tree big or small' check."""
    for dev in data["devices"]:
        n_chan = len(dev["channels"])
        n_chan_attrs = sum(len(c["attrs"]) for c in dev["channels"])
        print("%-28s %2d dev attrs, %2d channels, %3d channel attrs, "
              "%2d buffer, %2d debug"
              % (dev["id"], len(dev["device_attrs"]), n_chan,
                 n_chan_attrs, len(dev["buffer_attrs"]),
                 len(dev["debug_attrs"])))


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", help="context URI, e.g. usb:1.5.5 or ip:192.168.2.1")
    ap.add_argument("--device", help="only show this device (id or name)")
    ap.add_argument("--scan", action="store_true", help="list reachable contexts and exit")
    ap.add_argument("--json", action="store_true", help="dump JSON instead of a tree")
    ap.add_argument("--summary", action="store_true", help="one line per device")
    args = ap.parse_args()

    if args.scan:
        contexts = scan()
        for uri, description in sorted(contexts.items()):
            print("%-24s %s" % (uri, description))
        if not contexts:
            print("No contexts found.")
        print("\n%s" % uri_hint())
        return 0 if contexts else 1

    try:
        data = enumerate_context(args.uri, args.device)
    except OSError as exc:
        print("Could not open context: %s" % exc, file=sys.stderr)
        print("Try --scan to see what is reachable.", file=sys.stderr)
        return 1

    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    elif args.summary:
        print_summary(data)
    else:
        print_tree(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
