#!/usr/bin/env python3
"""
iio_libm2k_fetch.py -- which attributes the vendor's own library drives.

The kernel ABI says what an attribute means. It does not say whether you
will ever need it. On an M2K that question has a good answer sitting in
libm2k, the library Scopy itself is built on: every attribute libm2k
reads or writes is one that operating the board as an instrument actually
requires, and the method that touches it says which instrument.

    gain                -> M2kAnalogIn::setRange        -> Oscilloscope
    trigger_level       -> M2kHardwareTrigger::setAnalogLevelRaw -> Trigger
    oversampling_ratio  -> M2kAnalogIn::setOversamplingRatio     -> Oscilloscope

That is a translation table between the knobs a person already knows from
Scopy and the sysfs names a GNU Radio flowgraph needs -- which is exactly
the gap the workshop exists to close.

Two cautions on reading the result.

  * "libm2k never mentions it" means "not part of the M2K instrument
    abstraction", NOT "unimportant". scale and offset are in that list
    because libm2k computes the scope's conversion itself rather than
    reading it back; they remain central to every other IIO device.
  * This is a text scan of vendor source, not an API contract. Treat it
    as a strong hint about relevance, which is what it is.

Usage:
    ./iio_libm2k_fetch.py                 # refresh iio_libm2k_data.json
    ./iio_libm2k_fetch.py --show gain
"""

import argparse
import collections
import json
import os
import re
import sys
import urllib.request

RAW_BASE = "https://raw.githubusercontent.com/analogdevicesinc/libm2k/main/"

# The implementation files that actually talk to IIO.
SOURCES = [
    "src/analog/m2kanalogin_impl.cpp",
    "src/analog/m2kanalogout_impl.cpp",
    "src/analog/m2kpowersupply_impl.cpp",
    "src/digital/m2kdigital_impl.cpp",
    "src/m2khardwaretrigger_impl.cpp",
    "src/m2khardwaretrigger_v0.24_impl.cpp",
    "src/m2kcalibration_impl.cpp",
    "src/m2k_impl.cpp",
    "src/context_impl.cpp",
    "src/utils/devicegeneric.cpp",
    "src/utils/devicein.cpp",
    "src/utils/deviceout.cpp",
    "src/utils/channel.cpp",
]

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "iio_libm2k_data.json")

# libm2k reaches IIO through a small set of typed accessors, and every one
# of them names its attribute as a string literal.
CALL = re.compile(
    r'\b(getStringValue|setStringValue|getLongValue|setLongValue|'
    r'getDoubleValue|setDoubleValue|getBoolValue|setBoolValue|'
    r'hasAttribute|getAvailableAttributeValues)\s*\(([^;]*?)\)', re.S)
LITERAL = re.compile(r'"([a-z][a-z0-9_]*)"')
FUNC = re.compile(
    r'^[A-Za-z_][\w:<>,*&\s]*?\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(', re.M)

# The class doing the touching is the instrument the attribute belongs to.
# This is the part a participant can actually use: they know these names
# from Scopy's tabs even if they have never seen an IIO attribute.
INSTRUMENTS = [
    ("M2kAnalogIn", "Oscilloscope"),
    ("M2kAnalogOut", "Signal generator"),
    ("M2kPowerSupply", "Power supply"),
    ("M2kDigital", "Logic analyser and pattern generator"),
    ("M2kHardwareTrigger", "Trigger"),
    ("M2kCalibration", "Calibration"),
    ("M2kImpl", "Board setup"),
    ("ContextImpl", "Board setup"),
]


def instrument_for(class_name):
    for prefix, label in INSTRUMENTS:
        if class_name.startswith(prefix):
            return label
    return None            # DeviceGeneric and friends are plumbing


def scan(text):
    """Yield (attribute, Class, method) for every attribute access."""
    funcs = [(m.start(), m.group(1), m.group(2)) for m in FUNC.finditer(text)]
    for match in CALL.finditer(text):
        klass = method = None
        for pos, k, m in funcs:
            if pos < match.start():
                klass, method = k, m
            else:
                break
        for attr in LITERAL.findall(match.group(2)):
            yield attr, klass, method


def build(texts):
    attrs = collections.defaultdict(
        lambda: {"methods": set(), "instruments": set()})
    for text in texts:
        for attr, klass, method in scan(text):
            if not klass:
                continue
            entry = attrs[attr]
            entry["methods"].add("%s::%s" % (klass, method))
            label = instrument_for(klass)
            if label:
                entry["instruments"].add(label)
    return {name: {"methods": sorted(v["methods"]),
                   "instruments": sorted(v["instruments"])}
            for name, v in sorted(attrs.items())}


def fetch(sources=None, base=RAW_BASE):
    texts, got, missing = [], [], []
    for path in (sources or SOURCES):
        try:
            with urllib.request.urlopen(base + path, timeout=30) as response:
                texts.append(response.read().decode("utf-8", "replace"))
            got.append(path)
        except Exception as exc:                  # noqa: BLE001
            missing.append("%s (%s)" % (path, exc))
    return texts, got, missing


def save(attrs, sources, path=DATA_FILE):
    payload = {
        "_source": "libm2k, the library Scopy is built on",
        "_upstream": RAW_BASE,
        "_note": "Generated by iio_libm2k_fetch.py. An attribute listed "
                 "here is one libm2k reads or writes to operate the board. "
                 "Absence means 'not part of the instrument abstraction', "
                 "not 'unimportant'.",
        "_files": sources,
        "attrs": attrs,
    }
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return path


def load(path=DATA_FILE):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError):
        return None


def lookup(data, attr_name):
    """What libm2k does with this attribute, or None if it never touches it."""
    if not data or not attr_name:
        return None
    return data.get("attrs", {}).get(attr_name)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", metavar="ATTR")
    args = ap.parse_args()

    if args.show:
        data = load()
        if not data:
            print("No cached data. Run ./iio_libm2k_fetch.py first.",
                  file=sys.stderr)
            return 1
        entry = lookup(data, args.show)
        if not entry:
            print("libm2k never touches '%s'." % args.show)
            return 1
        print("%s\n" % args.show)
        if entry["instruments"]:
            print("  part of: %s" % ", ".join(entry["instruments"]))
        print("  driven by:")
        for method in entry["methods"]:
            print("    %s" % method)
        return 0

    texts, got, missing = fetch()
    if not texts:
        print("Could not fetch libm2k sources.", file=sys.stderr)
        for line in missing:
            print("  %s" % line, file=sys.stderr)
        return 1
    for line in missing:
        print("  skipped %s" % line)

    attrs = build(texts)
    save(attrs, got)
    instruments = collections.Counter()
    for entry in attrs.values():
        for label in entry["instruments"]:
            instruments[label] += 1
    print("%d source files -> %d attributes libm2k drives\n"
          % (len(got), len(attrs)))
    for label, count in instruments.most_common():
        print("  %-38s %d" % (label, count))
    print("\n-> %s" % os.path.basename(DATA_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
