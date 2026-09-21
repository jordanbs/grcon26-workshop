#!/usr/bin/env python3
"""Write the two digital block descriptions.

The Source and the Sink each carry sixteen pin dropdowns and sixteen
label fields, hidden past the pin count, which is around three hundred
lines of YAML per file that differs only in an index. Hand-maintaining
two copies of that is how the two blocks drift apart -- a dropdown fixed
on the Source and forgotten on the Sink is invisible until someone wires
a bus backwards.

So the YAML is generated and committed, and `test_grc_integration.py`
regenerates it to confirm the committed copy still matches. Edit this
file, run it, commit both.

    python3 gr-m2k/generate_digital_grc.py
"""

import os

PIN_COUNT = 16
HERE = os.path.dirname(os.path.abspath(__file__))
GRC = os.path.join(HERE, "grc")

# Every visible line's pin and name, sliced to the count the user chose.
# The hidden slots keep whatever they were last set to, so anything
# looking at the choices has to slice first or it will judge a block by
# fields nobody can see.
PINS = "[%s][:int(num_lines)]" % ", ".join(
    "pin%d" % index for index in range(PIN_COUNT))
NAMES = "[%s][:int(num_lines)]" % ", ".join(
    "name%d" % index for index in range(PIN_COUNT))


def yaml_list(key, items, indent=4):
    """A YAML list, wrapped and aligned the way the hand-written ones are.

    Breaks between items only. Wrapping inside `'12 pins'` still parses --
    YAML folds the newline to a space -- but it reads like a mistake and
    one stray edit turns it into one.
    """
    prefix = "%s%s: [" % (" " * indent, key)
    width = 79 - len(prefix)
    lines, line = [], ""
    for item in items:
        piece = item + ("" if item is items[-1] else ",")
        if line and len(line) + 1 + len(piece) > width:
            lines.append(line)
            line = piece
        else:
            line = piece if not line else "%s %s" % (line, piece)
    lines.append(line)
    pad = "\n" + " " * len(prefix)
    return prefix + pad.join(lines) + "]"


def line_parameters(verb):
    """The pin count, then a DIO choice and a label for each of sixteen."""
    counts = ["'1 pin'"] + ["'%d pins'" % (n + 1)
                            for n in range(1, PIN_COUNT)]
    blocks = ["\n".join([
        "-   id: num_lines",
        "    label: Number of pins",
        "    dtype: enum",
        "    default: '1'",
        yaml_list("options", ["'%d'" % (n + 1) for n in range(PIN_COUNT)]),
        yaml_list("option_labels", counts),
    ])]
    for index in range(PIN_COUNT):
        hide = "    hide: ${ 'none' if int(num_lines) > %d else 'all' }" % index
        blocks.append("\n".join([
            "-   id: pin%d" % index,
            "    label: Pin %d" % (index + 1),
            "    dtype: enum",
            "    default: '%d'" % index,
            yaml_list("options", ["'%d'" % p for p in range(PIN_COUNT)]),
            yaml_list("option_labels",
                      ["'DIO%d'" % p for p in range(PIN_COUNT)]),
            hide,
        ]))
        blocks.append("\n".join([
            "-   id: name%d" % index,
            "    label: Pin %d Label" % (index + 1),
            "    dtype: string",
            "    default: ''",
            hide,
        ]))
    return "\n\n".join(blocks)


MAKE_LINES = """    pins=[${ ", ".join(str(int(p)) for p in %s) }],
            names=[${ ", ".join(str(n) for n in %s) }],""" % (PINS, NAMES)


NAMING_DOC = """    Number of pins
      How many pins this block %s, and therefore how many ports it has.
      Choosing a count reveals that many pin dropdowns.

    Pin N
      Which DIO pin that port is. Any pin, in any order -- the pins need
      not be next to each other, and they need not ascend. Pin 1 is the
      first port whichever DIO you point it at, so a bus wired across
      DIO3, DIO7 and DIO1 because that is where the jumpers reached is
      spelled exactly that way.

      No DIO twice, and none shared with the other digital block: a pin
      is an input or an output, never both. Where two blocks claim the
      same pin, whichever starts last wins and the other silently
      %s nothing.

      The ports are numbered from zero, so Pin 1 is the port drawn
      `pin0`. GNU Radio Companion numbers cloned ports itself and will
      not take a template for it.

    Pin N Label
      Optional, and changes nothing about what the block does. A labelled
      pin reports itself as `MOSI (DIO7)` instead of `DIO7` when
      something is wrong, which is the difference between a wiring
      mistake you can see and one you have to go and look up.

      The label does not appear on the ports -- GNU Radio Companion draws
      port labels from the block description, not from a parameter, so
      they stay pin0, pin1, pin2. Downstream protocol blocks are where
      names show on the canvas: the SPI decoder's ports really are
      called sclk, mosi and cs, because for SPI those never change.

    This block knows nothing about protocols. Three pins are three pins,
    whether they are a clock, data and select or a latch strobe beside a
    data bus. What the pins mean is the business of whatever block reads
    them next.
"""


SOURCE = """id: m2k_digital_source
label: M2K Digital Source
category: '[ADALM2000]'
flags: [python, throttle]

parameters:
-   id: uri
    label: M2K address
    dtype: string
    default: ip:192.168.2.1

{lines}

-   id: sample_rate
    label: Sample rate
    dtype: enum
    default: '1000000'
    options: ['100000000', '10000000', '1000000', '100000', '10000', '1000']
    option_labels: ['100 MS/s', '10 MS/s', '1 MS/s', '100 kS/s', '10 kS/s',
                    '1 kS/s']

-   id: buffer_size
    label: Samples per buffer
    dtype: int
    default: '16384'

-   id: trigger_pin
    label: Trigger on
    dtype: enum
    default: 'off'
    options: ['off', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
              '10', '11', '12', '13', '14', '15']
    option_labels: ['Free running', 'DIO0', 'DIO1', 'DIO2', 'DIO3', 'DIO4',
                    'DIO5', 'DIO6', 'DIO7', 'DIO8', 'DIO9', 'DIO10', 'DIO11',
                    'DIO12', 'DIO13', 'DIO14', 'DIO15']

-   id: trigger_condition
    label: Trigger condition
    dtype: enum
    default: "'edge-rising'"
    options: ["'edge-rising'", "'edge-falling'", "'edge-any'",
              "'level-high'", "'level-low'"]
    option_labels: ['Rising edge', 'Falling edge', 'Either edge',
                    'While high', 'While low']
    hide: ${{ 'all' if trigger_pin == 'off' else 'none' }}

-   id: trigger_delay
    label: Trigger delay (samples)
    dtype: int
    default: '0'
    hide: ${{ 'all' if trigger_pin == 'off' else 'part' }}

outputs:
-   domain: stream
    dtype: short
    label: pin
    multiplicity: ${{ int(num_lines) }}

asserts:
- ${{ buffer_size > 0 }}
- ${{ len(set({pins})) == int(num_lines) }}
- ${{ trigger_pin == 'off' or trigger_pin in {pins} }}

templates:
    imports: from m2k_blocks.digital import digital_source
    make: |-
        digital_source(
            uri=${{uri}},
        {make}
            sample_rate=${{sample_rate}}, buffer_size=${{buffer_size}},
            trigger_pin='${{trigger_pin}}',
            trigger_condition=${{trigger_condition}},
            trigger_delay=${{trigger_delay}})

documentation: |-
    Read the M2K's digital pins. One output port per pin, in the order
    you list them.

    Each port carries one bit per sample, in a short. That is gr-iio's
    model rather than a choice made here: every DIO pin is its own IIO
    channel with a one-bit scan element.

{naming}
    Trigger on
      Which pin decides when a buffer starts. "Free running" captures
      whenever the buffer is ready, which is the default and is what you
      want unless you are lining a capture up with something.

      The pin has to be one this block is reading. A trigger pin this
      block does not read is a flowgraph error rather than a capture
      that silently never fires.

      This is the logic analyzer's own trigger, separate from the scope's.
      A digital trigger does not start an analog capture.

    Trigger condition
      Rising, falling or either edge, or a level held high or low.

    Trigger delay
      Samples between the trigger and the start of the buffer. Negative
      is pre-trigger -- the buffer starts that many samples BEFORE the
      edge -- and is exact to the sample.

      Positive delay is not. It moves the buffer the right way but lands
      tens of samples off, differently each run, on hardware that reads
      the attribute back correctly. Measured, not explained; see
      docs/bench-checklist.md section 8.

    A trigger that never fires and a trigger that is not set look exactly
    the same from the flowgraph -- one hangs, the other floods. If a
    triggered capture produces nothing, check the pin is actually moving
    before changing anything here.

    Unlike the scope and the generator, the digital side publishes no list
    of legal sample rates. The rates offered here are the decade divisions
    of the same 100 MS/s clock, and all six are confirmed on the bench --
    timed against the scope, not read back.

file_format: 1
"""


SINK = """id: m2k_digital_sink
label: M2K Digital Sink
category: '[ADALM2000]'
flags: [python, throttle]

parameters:
-   id: uri
    label: M2K address
    dtype: string
    default: ip:192.168.2.1

{lines}

-   id: sample_rate
    label: Sample rate
    dtype: enum
    default: '1000000'
    options: ['100000000', '10000000', '1000000', '100000', '10000', '1000']
    option_labels: ['100 MS/s', '10 MS/s', '1 MS/s', '100 kS/s', '10 kS/s',
                    '1 kS/s']

-   id: buffer_size
    label: Samples per buffer
    dtype: int
    default: '16384'

-   id: drive
    label: Pin drive
    dtype: enum
    default: "'push-pull'"
    options: ["'push-pull'", "'open-drain'"]
    option_labels: ['Push-pull', 'Open-drain']

-   id: idle_level
    label: Level when stopped
    dtype: enum
    default: "'low'"
    options: ["'low'", "'high'", "'leave'"]
    option_labels: ['Low', 'High', 'Leave as found']

-   id: cyclic
    label: When the buffer ends
    dtype: enum
    default: 'False'
    options: ['False', 'True']
    option_labels: ['Play once', 'Repeat forever']

inputs:
-   domain: stream
    dtype: short
    label: pin
    multiplicity: ${{ int(num_lines) }}

asserts:
- ${{ buffer_size > 0 }}
- ${{ len(set({pins})) == int(num_lines) }}

templates:
    imports: from m2k_blocks.digital import digital_sink
    make: |-
        digital_sink(
            uri=${{uri}},
        {make}
            sample_rate=${{sample_rate}}, buffer_size=${{buffer_size}},
            drive=${{drive}}, cyclic=${{cyclic}},
            idle_level=${{idle_level}})

documentation: |-
    Drive the M2K's digital pins. One input port per pin, in the order
    you list them.

    Each port carries one bit per sample, in a short: send 0 or 1, not a
    packed 16-bit word. Anything non-zero counts as a one, so a stream of
    counts will not quietly truncate.

    Only one of these per flowgraph. All sixteen pins share a single
    16-bit output word and a single DMA buffer, so two sinks would fight
    over both. Drive every pin you need from one block.

    This block does not use gr-iio's device_sink, which can drive exactly
    one pin -- with no error when you ask it for more. It packs the
    output word itself instead. `docs/gr-iio-multipin-sink.md` has the
    evidence if you want it.

    That packing is Python, once per buffer. At 1 MS/s with a 16384
    sample buffer that is 61 pushes a second and comfortable; 100 MS/s
    would be 6100 and will not keep up. High rates want a large buffer
    and, if it still stumbles, fewer lines.

{naming}
    Pin drive
      Push-pull drives both high and low. Open-drain only pulls low and
      needs a pull-up resistor, which is what a shared bus wants.

    Level when stopped
      An output pin has two sources of truth. The samples arriving here
      drive it while the flowgraph runs, and a separate register drives it
      the rest of the time -- so the pin snaps to this level the moment
      you hit stop, and holds it until you start again. Note that this is
      the opposite of the analog generator, which keeps playing its last
      cyclic buffer with the flowgraph stopped.

      This is also how you set a pin and leave it: a level here with the
      flowgraph never started is a static output and nothing else.

      "Leave as found" writes nothing, and the resting level is then
      whatever the last program to touch the board happened to set.

    Unlike the scope and the generator, the digital side publishes no list
    of legal sample rates. The rates offered here are the decade divisions
    of the same 100 MS/s clock, and all six are confirmed on the bench --
    timed against the scope, not read back.

file_format: 1
"""


def render(template, verb, reads):
    return template.format(lines=line_parameters(verb),
                           naming=NAMING_DOC % (reads, reads),
                           pins=PINS, make=MAKE_LINES)


def main():
    for name, template, verb, reads in (
            ("m2k_digital_source", SOURCE, "read", "reads"),
            ("m2k_digital_sink", SINK, "drive", "drives")):
        path = os.path.join(GRC, "%s.block.yml" % name)
        with open(path, "w") as handle:
            handle.write(render(template, verb, reads))
        print("wrote %s" % path)


if __name__ == "__main__":
    main()
