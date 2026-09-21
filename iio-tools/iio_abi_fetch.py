#!/usr/bin/env python3
"""
iio_abi_fetch.py -- pull the kernel's own descriptions of IIO attributes.

The question "is there somewhere that says what an attribute means in
plain English" has a real answer for the generic half: yes, and it ships
in the Linux source tree.

    Documentation/ABI/testing/sysfs-bus-iio

Every IIO attribute a driver may expose is documented there in a block
like:

    What:           /sys/bus/iio/devices/iio:deviceX/in_voltageY_raw
    What:           /sys/bus/iio/devices/iio:deviceX/in_voltage_raw
    KernelVersion:  2.6.35
    Contact:        linux-iio@vger.kernel.org
    Description:
                    Raw (unscaled no bias removal etc) voltage measurement
                    from channel Y. ...

That is written by the people who defined the interface, it is versioned,
and it is quotable. This script downloads it, parses it into
iio_abi_data.json, and iio_semantics.py then quotes it verbatim with a
citation rather than paraphrasing it from memory.

What it does NOT answer is which physical pin channel Y is wired to. The
kernel docs describe the interface, not your board. That half comes from
the driver, from libm2k, and from the datasheet -- see iio_overlays.py.

Usage:
    ./iio_abi_fetch.py                 # refresh iio_abi_data.json
    ./iio_abi_fetch.py --show in_voltage0_raw
"""

import argparse
import json
import os
import re
import sys
import urllib.request

RAW_BASE = ("https://raw.githubusercontent.com/torvalds/linux/master/"
            "Documentation/ABI/testing/")

# The core file plus the per-subsystem ones that describe attributes an
# ADI device is likely to expose.
SOURCES = [
    "sysfs-bus-iio",
    "sysfs-bus-iio-frequency-ad9523",
    "sysfs-bus-iio-frequency-adf4350",
    "sysfs-bus-iio-frequency-adf4371",
    "sysfs-bus-iio-trigger-sysfs",
    "sysfs-bus-iio-dac",
]

# The M2K runs Analog Devices' kernel fork, and a good deal of what it
# exposes comes from drivers that never went upstream. Their fork carries
# its own ABI documentation, so it answers attributes the mainline files
# have never heard of. Fetched second so mainline wins any collision.
ADI_BASE = ("https://raw.githubusercontent.com/analogdevicesinc/linux/main/"
            "Documentation/ABI/testing/")

ADI_SOURCES = [
    "sysfs-bus-iio",
    "sysfs-bus-iio-adc",
    "sysfs-bus-iio-dds",
    "sysfs-bus-iio-frequency-adf4350",
    "sysfs-bus-iio-timer-stm32",
]

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "iio_abi_data.json")

# Everything before the attribute name in a documented path.
_PREFIXES = (
    "/sys/bus/iio/devices/iio:deviceX/",
    "/sys/bus/iio/devices/triggerX/",
    "/sys/bus/iio/devices/",
    "/sys/bus/iio/",
    # The docs abbreviate the common prefix when describing event
    # attributes, e.g. /sys/.../events/in_voltage0_thresh_rising_en
    "/sys/.../",
)


# --------------------------------------------------------------- parsing

def normalize(name):
    """Collapse channel indices so a concrete name matches a documented one.

    The docs write in_voltageY_raw; a real device has in_voltage0_raw. Both
    normalize to in_voltage_raw. Differential pairs keep their dash, which
    is how in_voltage0-voltage1_raw finds in_voltage-voltage_raw.
    """
    if not name:
        return ""
    name = re.sub(r"(?<=[a-z])[XY](?=_|-|$)", "", name)
    name = re.sub(r"(?<=[a-z])\d+(?=_|-|$)", "", name)
    return name


def _strip_prefix(path):
    for prefix in _PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix):]
    return None


def parse_abi(text, source):
    """Split one ABI file into blocks of {paths, kernel_version, description}."""
    blocks = []
    current = None

    for line in text.splitlines():
        if line.startswith("What:"):
            if current and current.get("_in_description"):
                blocks.append(current)
                current = None
            if current is None:
                current = {"paths": [], "kernel_version": None,
                           "description": [], "source": source,
                           "_in_description": False}
            current["paths"].append(line.split(":", 1)[1].strip())
        elif current is None:
            continue
        elif line.startswith("KernelVersion:"):
            current["kernel_version"] = line.split(":", 1)[1].strip()
        elif line.startswith("Contact:") or line.startswith("Date:"):
            continue
        elif line.startswith("Description:"):
            current["_in_description"] = True
            tail = line.split(":", 1)[1].strip()
            if tail:
                current["description"].append(tail)
        elif current["_in_description"]:
            current["description"].append(line.strip())

    if current and current.get("_in_description"):
        blocks.append(current)

    out = []
    for block in blocks:
        text_lines = block["description"]
        while text_lines and not text_lines[-1]:
            text_lines.pop()
        # Collapse the tab-indented body into paragraphs.
        paragraphs, buf = [], []
        for line in text_lines:
            if line:
                buf.append(line)
            elif buf:
                paragraphs.append(" ".join(buf))
                buf = []
        if buf:
            paragraphs.append(" ".join(buf))

        attrs = []
        for path in block["paths"]:
            tail = _strip_prefix(path)
            if tail:
                attrs.append(tail)
        if not attrs or not paragraphs:
            continue

        out.append({
            "attrs": attrs,
            "keys": sorted({normalize(a) for a in attrs}),
            "kernel_version": block["kernel_version"],
            "description": paragraphs,
            "source": block["source"],
        })
    return out


def build_index(blocks):
    """Map normalized attribute name -> the block that documents it."""
    index = {}
    for position, block in enumerate(blocks):
        for key in block["keys"]:
            index.setdefault(key, position)
    return index


# --------------------------------------------------------------- fetching

def fetch(sources=None, base=RAW_BASE, label=""):
    blocks = []
    fetched, missing = [], []
    for name in (sources or SOURCES):
        url = base + name
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8", "replace")
        except Exception as exc:                  # noqa: BLE001 -- report and move on
            missing.append("%s (%s)" % (name, exc))
            continue
        found = parse_abi(text, label + name)
        blocks.extend(found)
        fetched.append("%s%s: %d documented blocks" % (label, name, len(found)))
    return blocks, fetched, missing


def save(blocks, path=DATA_FILE):
    payload = {
        "_source": "Linux kernel Documentation/ABI/testing/",
        "_upstream": RAW_BASE,
        "_note": "Generated by iio_abi_fetch.py. Descriptions are the "
                 "kernel's own words, quoted verbatim.",
        "blocks": blocks,
        "index": build_index(blocks),
    }
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return path


def load(path=DATA_FILE):
    """Read the cached ABI data. Returns None if it has not been fetched."""
    try:
        with open(path) as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


def lookup(data, name, attr_type=None):
    """Find the kernel's description of one attribute.

    Tries the bare name, then the subdirectory forms the docs use for
    buffer and scan-element attributes.
    """
    if not data:
        return None

    candidates = [name]
    if attr_type == "buffer":
        candidates.insert(0, "buffer/" + name)
    candidates.append("scan_elements/" + name)
    candidates.append("events/" + name)

    index = data.get("index", {})
    for candidate in candidates:
        position = index.get(normalize(candidate))
        if position is not None:
            return data["blocks"][position]
    return None


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", metavar="ATTR",
                    help="print the kernel's description of one attribute")
    ap.add_argument("--offline", action="store_true",
                    help="use the cached file, do not download")
    args = ap.parse_args()

    if args.show:
        data = load()
        if not data:
            print("No cached ABI data. Run ./iio_abi_fetch.py first.",
                  file=sys.stderr)
            return 1
        block = lookup(data, args.show)
        if not block:
            print("Not documented in the kernel ABI: %s" % args.show)
            return 1
        print("%s\n" % args.show)
        for paragraph in block["description"]:
            print("  %s\n" % paragraph)
        print("  -- Linux ABI %s, since kernel %s"
              % (block["source"], block["kernel_version"] or "?"))
        return 0

    if args.offline:
        data = load()
        print("cached: %d blocks" % len(data["blocks"]) if data else "no cache")
        return 0 if data else 1

    blocks, fetched, missing = fetch()
    adi_blocks, adi_fetched, adi_missing = fetch(ADI_SOURCES, ADI_BASE, "adi/")
    # Mainline first: build_index keeps the first block that claims a name,
    # so an upstream description always beats the fork's copy of it.
    blocks.extend(adi_blocks)
    fetched.extend(adi_fetched)
    missing.extend(adi_missing)
    if not blocks:
        print("Could not fetch any ABI documentation.", file=sys.stderr)
        for line in missing:
            print("  %s" % line, file=sys.stderr)
        return 1

    for line in fetched:
        print("  %s" % line)
    for line in missing:
        print("  skipped %s" % line)
    path = save(blocks)
    index = build_index(blocks)
    print("\n%d blocks, %d distinct attribute names -> %s"
          % (len(blocks), len(index), os.path.basename(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
