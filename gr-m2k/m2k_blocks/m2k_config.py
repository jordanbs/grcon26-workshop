"""Setting attributes on devices other than the one you are streaming.

Every M2K instrument needs this. The scope's input range lives on
m2k-fabric; the DIO direction lives on m2k-logic-analyzer; neither is the
device carrying the samples. gr-iio's device_source and device_sink apply
their `params` to exactly one device, so anything else needs another way
in.

gr-iio's own way in is a pair of blocks: attr_updater emits {attr: value}
on an interval, attr_sink writes whatever arrives. Two blocks to set one
string, and no one-shot write anywhere in the API -- a slow updater is
the only thing on offer.

Which is a problem, and it cost us a bench session. An updater on a
1000 ms interval writes nothing at t=0. For the first second of every
flowgraph the hardware is in whatever state the last program left it,
and a short capture can finish before its own configuration arrives. It
does not fail; it returns confident numbers for settings that were never
applied. Comparing two input ranges this way gave 0.3 counts against
72.3, which looks like a broken range and is actually a race.

So each attribute is written twice, deliberately:

    once, immediately, with libiio directly -- before the flowgraph is
    even started, so the setting is in force before the first sample

    then repeatedly, by the updater/sink pair, which keeps it in force if
    something else changes it underneath us

The direct write is what makes the configuration true. The updater is a
keep-alive, which is what it was always good at.

One consequence, and it looks exactly like a hung board: the updater
never finishes, so a flowgraph holding one of these never finishes
either. `tb.run()` on a graph terminated by a `head` block will sit
there forever after the head has all its samples, because run() waits
for every block. Use `tb.start()`, wait, `tb.stop()`, `tb.wait()`
instead. The board is fine; the graph is just never done.
"""

import sys

from gnuradio import iio

# gr-iio takes the attribute category as a number, matching its own
# Attribute Sink block: 0 Channel, 1 Device, 2 Buffer, 3 Debug.
ATTR_CHANNEL = 0
ATTR_DEVICE = 1

# How often the keep-alive rewrites. No longer the thing that decides
# whether a setting is applied at all -- see the direct write below.
CONFIG_INTERVAL_MS = 1000

# libiio contexts are expensive to open and there is no reason to hold
# more than one per board. Keyed by URI.
_CONTEXTS = {}


def usb_backend(uri):
    """Whether this URI reaches the board over raw USB rather than the net.

    It decides who is allowed to hold a context, which on USB is a
    question with one answer -- see `release` below.
    """
    return str(uri).startswith("usb:")


def release(uri):
    """Drop our libiio context so something else can claim the interface.

    Only the USB backend cares, and it cares absolutely. A libusb
    interface can be claimed by exactly one context at a time, and
    `usb:0.5.5` is one interface: the pylibiio context this module keeps
    and the context gr-iio opens behind its own blocks are two claims on
    it, and the second one loses with `Unable to claim interface ...
    Permission denied (13)`. The network backend multiplexes contexts
    happily, which is why this was invisible until the first board was
    driven over USB.

    So on USB the rule is that whichever library carries the SAMPLES
    owns the context, and everything else gets out of its way. A block
    whose data path is gr-iio's device_source or device_sink calls this
    after its direct writes and before building that block. The digital
    sink does not call it, because its data path is pylibiio's Buffer
    and the context it needs is this one.
    """
    if usb_backend(uri):
        _CONTEXTS.pop(uri, None)


def context(uri):
    """A libiio context for this URI, opened once and reused.

    This is pylibiio (`import iio`), not gr-iio (`from gnuradio import
    iio`). Different modules with the same name; gr-iio is built on the
    same C library, so having one implies having the other, but the
    Python bindings are a separate package and can be missing.
    """
    if uri not in _CONTEXTS:
        import iio as pyiio
        _CONTEXTS[uri] = pyiio.Context(uri)
    return _CONTEXTS[uri]


def write_now(uri, device, channel, attr, value, output=False,
              kind=ATTR_CHANNEL, keepalive=True):
    """Write one attribute straight away, returning whether it landed.

    Never raises. A board that is unreachable, or bindings that are not
    installed, leave the updater/sink pair to do the job a second later
    -- worse, but not broken. The warning says which happened, because a
    silent fallback here is exactly the failure this module exists to
    stop.

    `keepalive` only changes that warning. It says whether the caller is
    going to follow this up with an updater/sink pair, so the message can
    say "a second late" or "not at all" and be telling the truth. Some
    attributes must NOT be kept alive -- see the digital sink's idle
    level, where a keep-alive would spend the whole run rewriting a
    register the stream is deliberately overriding.
    """
    try:
        dev = context(uri).find_device(device)
        if dev is None:
            raise LookupError("no device %r in the context at %s"
                              % (device, uri))
        if kind == ATTR_DEVICE:
            dev.attrs[attr].value = str(value)
        else:
            chan = dev.find_channel(channel, output)
            if chan is None:
                raise LookupError(
                    "no %s channel %r on %s"
                    % ("output" if output else "input", channel, device))
            chan.attrs[attr].value = str(value)
        return True
    except Exception as exc:                      # noqa: BLE001
        # Drop the cached context; if it went stale, the next call rebuilds.
        _CONTEXTS.pop(uri, None)
        where = device if kind == ATTR_DEVICE else "%s/%s" % (device, channel)
        if keepalive:
            after = ("falling back to the %d ms updater, so it will not be "
                     "in force for the first %.1f s"
                     % (CONFIG_INTERVAL_MS, CONFIG_INTERVAL_MS / 1000.0))
        else:
            after = "and nothing else will set it, so it is not in force"
        print("m2k_config: could not set %s %s=%s immediately (%s); %s"
              % (where, attr, value, exc, after), file=sys.stderr)
        return False


def write_channel_attr(block, keep, uri, device, channel, attr, value,
                       output=False):
    """Set one channel attribute on any device the context can reach.

    `keep` is a list the caller holds on to. A hier block that lets these
    go loses them to garbage collection and the write silently stops
    happening.
    """
    if usb_backend(uri):
        # No keep-alive on USB: the pair would open a second context on
        # an interface that only has room for one. The direct write is
        # the whole configuration here, which is stricter than the
        # network path rather than looser -- it lands before start(),
        # with no first-second window at all.
        write_now(uri, device, channel, attr, value, output, ATTR_CHANNEL,
                  keepalive=False)
        return None
    write_now(uri, device, channel, attr, value, output, ATTR_CHANNEL)
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, channel, ATTR_CHANNEL, output)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink


def write_device_attr(block, keep, uri, device, attr, value):
    """Set one device-level attribute on any device."""
    if usb_backend(uri):                      # see write_channel_attr
        write_now(uri, device, "", attr, value, False, ATTR_DEVICE,
                  keepalive=False)
        return None
    write_now(uri, device, "", attr, value, False, ATTR_DEVICE)
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, "", ATTR_DEVICE, False)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink


def context_attr(uri, key, default=None):
    """One context-level attribute as a string, or `default`.

    Context attributes are where the board keeps its calibration -- the
    four `cal,*_dac` pairs the power supply conversion needs. They sit on
    no device at all, so neither device_source's `params` nor attr_sink
    can reach them. They are read once, here, and never written.

    pylibiio has changed what Context.attrs holds between releases: older
    bindings hand back an object with a `.value`, newer ones the string
    itself. Both are handled, because getting it wrong turns a
    calibration coefficient into the repr of an object and the rail into
    a voltage nobody can account for.
    """
    try:
        raw = context(uri).attrs[key]
    except Exception:                                  # noqa: BLE001
        _CONTEXTS.pop(uri, None)
        return default
    return getattr(raw, "value", raw)


def context_float(uri, key, default):
    """A `cal,*` coefficient as a float, falling back loudly.

    An unreachable board or a missing coefficient gives `default` and
    says so. That matters more here than elsewhere: the fallbacks are
    gain 1.0 and offset 0.0, which are not wrong so much as uncalibrated,
    and the resulting rail is off by the percent or so the calibration
    was there to remove. Silence would make that indistinguishable from a
    working board.
    """
    text = context_attr(uri, key)
    if text is None:
        print("m2k_config: no context attribute %r at %s; using %g"
              % (key, uri, default), file=sys.stderr)
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        print("m2k_config: context attribute %r is %r, not a number; using %g"
              % (key, text, default), file=sys.stderr)
        return default


def channels_with_label(uri, device, label, output=True):
    """Channel ids on `device` whose `label` attribute reads `label`.

    The power rails are the case this exists for. libm2k reaches them by
    hardcoded channel index -- 2 and 3 on m2k-fabric -- but the board
    says which they are itself: both carry a `label` attribute reading
    `user_supply`. Asking the hardware rather than assuming is the whole
    thesis of this workshop, so this asks, and the caller keeps the
    index as a fallback for when it cannot.

    Returns ids in device order, so the first is the positive rail and
    the second the negative, matching libm2k's 2 then 3. An unreachable
    board gives an empty list rather than raising.
    """
    found = []
    try:
        dev = context(uri).find_device(device)
        if dev is None:
            return []
        for chan in dev.channels:
            if bool(chan.output) != bool(output):
                continue
            attr = chan.attrs.get("label")
            if attr is None:
                continue
            if getattr(attr, "value", attr) == label:
                found.append(chan.id)
    except Exception:                                  # noqa: BLE001
        _CONTEXTS.pop(uri, None)
        return []
    return found
