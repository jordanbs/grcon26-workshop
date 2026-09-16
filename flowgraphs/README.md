# Loopback

The smallest end-to-end M2K flowgraph, and the first thing to run at a
station. **Wire W1 to 1+, and ground to 1-.**

| file | uses |
| --- | --- |
| `m2k_loopback.grc` | the stock gr-iio blocks — works with nothing installed |
| `m2k_loopback_generated.grc` | blocks `iio_grc.py` generated from a capture |

```
gnuradio-companion flowgraphs/m2k_loopback.grc
```

For the generated variant, point GRC at the blocks first:

```
uv run ./iio_grc.py fixtures/m2k-real.json --out blocks/
GRC_BLOCKS_PATH=$PWD/blocks gnuradio-companion flowgraphs/m2k_loopback_generated.grc
```

## The two conversion blocks are the lesson

gr-iio carries **short** samples in both directions — raw ADC counts, not
volts. So `Short To Float` gets you a number, and `Multiply Const` turns
that number into volts. That multiply is the entire counts-to-volts story
in one block, and `volts_per_count` is the variable it lives in.

Everything upstream of that multiply is counts. Everything downstream is
volts. If a participant remembers one thing about IIO, this is a good
candidate.

## What has been checked, and what has not

Verified without hardware, in the test suite (`tests/test_grc_integration.py`),
against GNU Radio 3.10 itself rather than against our own assumptions:

- GRC's real block loader accepts all five generated blocks
- both flowgraphs validate in GRC and generate Python that parses
- the emitted constructors are the shapes we claim:
  `device_source(..., buffer_size, decimation - 1)` and
  `device_sink(..., buffer_size, interpolation - 1, cyclic)`, each followed
  by `set_len_tag_key()`
- an untouched dropdown writes nothing — "shown" never means "set"
- run headless, both get as far as `RuntimeError: Unable to create context`,
  which is the only step that needs a board

Not checked, and the reason to run this at a bench:

- **`volts_per_count = 0.014525`** comes from libm2k's `getScalingFactor()`
  for the ±25 V range. No signal has confirmed it. Put a known amplitude in
  and see whether the plot agrees.
- **`oversampling_ratio` as decimation.** `samp_rate` assumes the ADC's
  100 MS/s divided by 100. If that is wrong, every frequency axis is wrong
  by the same ratio.
- **`amplitude_counts = 1000`** is a guess at a safe DAC level.

## A GRC trap worth knowing

Keep the flowgraph `description` to a single line. GRC comments out only its
first line when generating Python and drops the rest in as bare code, which
does not parse. Multi-line notes belong in `comment`. There is a test pinning
this.

---

# SPI loopback

A real SPI bus bit-banged out of three DIO pins and read back on three
more. There are two flowgraphs. They wire up the same way, decode the
same way, and differ only in what makes the waveform:

| | |
|---|---|
| `m2k_spi_loopback.grc` | **Send on demand.** Type in a box, press Enter, one transaction goes out. The bus rests at idle in between. |
| `m2k_spi_loopback_continuous.grc` | **Repeat forever.** One frame in a cyclic buffer, played by the hardware on a loop. |

Start with the interactive one — it is what a participant expects a bus
to do. The continuous one is the older of the two, is the one with
hardware evidence behind it, and is the better thing to leave running
while you talk over a trace.

**Three jumpers, both flowgraphs:**

```
DIO0 -> DIO4      SCLK
DIO1 -> DIO5      MOSI
DIO2 -> DIO6      CS
```

Those six pins are a choice, not a constraint — each line has its own
dropdown, so any six free DIO pins in any order work as well. Contiguous
is what the workshop ships because it is what twenty people can wire
without a diagram.

```
export GRC_BLOCKS_PATH=$PWD/gr-m2k/grc:$GRC_BLOCKS_PATH
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
gnuradio-companion flowgraphs/m2k_spi_loopback.grc
```

## Send on demand — `m2k_spi_loopback.grc`

**QT GUI Message Edit Box** → **M2K SPI Encode** → **Digital Sink**. Type
something, press Enter, and the message goes out exactly once. Encode
holds the whole waveform: it turns a message into three streams of levels
and produces idle — clock low, data low, CS released — for as long as the
sink asks, so the sink never starves between messages.

**The Digital Source here is free-running, not triggered.** That is the
one thing that differs from the continuous flowgraph, and it is not a
style choice. gr-iio's `device_source` returns `WORK_DONE` from `work()`
on *any* refill error, so an armed trigger that times out waiting for the
next message ends the source for good: the first message decodes, and
everything after it goes out on the wire with nothing left to read it
back. The block has a `set_timeout_ms` but in 3.10 the value is stored
and never handed to libiio, and no timeout would be long enough anyway —
the wait is however long it takes somebody to type.

Nothing is lost by dropping it. The decoder emits nothing until it has
seen a falling CS, so CS frames the stream in software, which is what
that rule was written for. The QT time sink does the display triggering
instead: normal mode, negative slope, on the CS channel.

Two more settings make send-on-demand work, and they go together:

- **The sink is not cyclic.** A cyclic buffer is pushed once and repeated
  by the hardware forever; nothing downstream can gate it. Send-on-demand
  needs streaming.
- **Encode's "Align frames to" is set to the sink's `buffer_len`.** A
  non-cyclic sink hands the board one DMA buffer at a time and the board
  need not join them seamlessly, so a frame lying across a buffer seam can
  be torn in the middle. Encode counts the samples it produces, and that
  count *is* the sink's position in its buffer, so it can hold a queued
  frame until the next boundary and start it there. The cost is up to one
  buffer of latency — 160 ms here, which nobody pressing a key notices.
  `buffer_len` must exceed the longest frame, `128 + 16*half*bytes`.

`samp_rate` is **100 kS/s**, not the 1 MS/s the continuous flowgraph uses.
Non-cyclic digital streaming underruns at 1 MS/s about half the runs. An
underrun while the bus is idle is harmless; one mid-frame corrupts the
message. At 100 kS/s the bus is still 6.25 kHz at `half = 8`.

`half`, the pin dropdowns and the four timing parameters behind
*Advanced* mean the same thing here as anywhere else.

## Repeat forever — `m2k_spi_loopback_continuous.grc`

Three vector sources hold one frame, repeating. A frame is one whole SPI
transaction: idle, CS low, every byte of `spi_message` clocked out back
to back, CS high again. The Digital Sink plays the three lists as one
cyclic buffer at 1 MS/s; with 8 samples per half-clock that is a 62.5 kHz
bus in SPI mode 0. The Digital Source triggers on **CS falling** on DIO6,
so every capture starts at the beginning of a message, and **M2K SPI
Decode** turns the three streams back into the bytes that went out.
Message Debug prints them.

**Type into the `SPI message` box while it runs.** Press Enter and the
string goes out on the next buffer -- GRC generates a callback that
recomputes the three sample lists and hands them to the vector sources
with `set_data()`.

That only works because the frame length is fixed. `spi_capacity` (8
bytes) sets it, not the message: a short message is padded out with idle
samples, CS already high, which the decoder skips. The sink's buffer
size is a constructor argument with no callback, so a frame that grew
with the message would stop dividing the buffer the moment someone typed
a longer one -- and a message spliced across a buffer boundary is the
section 11 failure again. Anything past `spi_capacity` is cut; raise it
and restart to send more.

**CS is asserted once per message, not once per byte.** Both decode, and
per-byte framing is what a first draft naturally produces -- but the M2K's
capture is gapped between buffers, and the source re-arms on each one. If
CS falls once per byte, the arming edge is a *byte* boundary, so every
buffer starts on whichever byte it happened to land on and Message Debug
prints rotations: `M2K`, then `2KM`, then `KM2`, every byte individually
correct. One assertion per message makes the only falling edge in the
frame the start of the message. Section 11 of `docs/bench-checklist.md`
has the numbers.

### The frame is a variable, which is the point

```python
spi_bytes = [ord(ch) for ch in str(spi_message)[:spi_capacity]]
spi_bits  = [[(byte >> (7 - i)) & 1 for i in range(8)] for byte in spi_bytes]
n, pad    = len(spi_bytes), 16*half*(spi_capacity - len(spi_bytes))
spi_sclk  = ([0]*72 + ([0]*half + [1]*half)*(8*n) + [0]*(56 + pad))
spi_mosi  = ([0]*64 + [spi_bits[0][0] if spi_bits else 0]*8
             + [b for bits in spi_bits for bit in bits for b in [bit]*(2*half)]
             + [0]*(56 + pad))
spi_cs    = ([1]*64 + [0]*(16 + 16*half*n) + [1]*(48 + pad))
```

Change `spi_message` and the waveform changes, live. Change `half` and the
bus speed changes — `frame` is `128 + 16*half*spi_capacity`, `repeats` is
`16384 // frame`, and the buffer stays a whole number of frames. `half`
still needs a restart, because `frame` moves with it. A participant can see
mode 0's rule — MOSI settles while the clock is low, the receiver samples
on the rising edge — directly in the list, which is harder to get from a
datasheet timing diagram.

The three lists are all the same length, and they have to be: they are
one buffer, and a short one would shift the others.

## Chip select is doing more than it looks like

The decoder emits **nothing** until it has seen a falling CS, and that
rule is worth a minute of the session. On a bus there is no start bit.
If a capture happens to begin in the middle of a frame, some unknown
number of bits are already gone — and the next eight still make a byte,
one that is real, plausible and wrong. Dropping the partial frame is the
only way to tell "I missed the start" from "here is your data."

Bits left over when CS releases go the same way rather than being padded
out to a byte.

## Reading the output

Message Debug prints the bytes twice — once as characters, once as hex:

```
((text . M2K))
pdu length =          3 bytes
pdu vector contents =
0000: 4d 32 4b
```

The payload is the words that were actually on the wire; the text rides
in the metadata, which is Scopy's text column and the quickest way for
somebody to see that what they typed is what came back. Bytes outside
printable ASCII show as `\xNN`. Turn *Text in metadata* off on a bus
that is not carrying text.

## What has been checked

On hardware, 2026-09-02: 0xA5 first try, then eight edge-case bytes,
then all 256 byte values in a single 65536-sample capture, three repeat
runs, 768 frames, zero errors — decoded offline by `bench/spi_loopback.py`.
Section 9 of `docs/bench-checklist.md` has the detail.

The in-flowgraph decoder passed section 11 on 2026-09-04: whole-message
frames at three bus speeds, about 6 M samples each, `M2K` repeating with
no rotation and no ragged chunk. `tests/test_spi_decode.py` evaluates the
continuous flowgraph's own variables to confirm the message it declares
is the message that comes back; `tests/test_spi_encode.py` round-trips
the encoder through the decoder, including the alignment rule.

The interactive flowgraph passed section 12 on the board on 2026-09-04:
twenty sends with varying text, one print per press, no rotations,
nothing dropped, no timeout. Non-cyclic streaming and frame alignment
both hold at 100 kS/s, and a free-running capture is *not* gapped
between rx buffers — the gap section 11 found belongs to the trigger
re-arming. The one number still missing is how far `samp_rate` can come
back up before it stops holding.

The continuous flowgraph must stay cyclic. Non-cyclic underruns at 1 MS/s
and loses about half its runs.

One Digital Sink per flowgraph — all sixteen pins share one output word
and one DMA buffer.

---

# Ultrasonic FSK

`m2k_ultrasonic_fsk.grc` — a 200-baud FSK link that leaves the board, goes
through the air, and comes back. Transmit and receive are in one flowgraph,
on one M2K.

```
W1  -> TX +      TX - -> GND
1+  <- RX +      RX - -> GND       1- -> GND
```

Input range **high** (±2.5 V). Point the two transducers at each other,
30 cm or so apart to start.

```
export GRC_BLOCKS_PATH=$PWD/gr-m2k/grc:$GRC_BLOCKS_PATH
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
gnuradio-companion flowgraphs/m2k_ultrasonic_fsk.grc
```

Type in the **Message** box and press Enter; the new text goes out on the
next frame and comes back in Message Debug.

## The two rates are different on purpose

`tx_rate` is 750 kS/s and `rx_rate` is 1 MS/s, and there is no `samp_rate`
variable to collapse them into. The DAC divides down from 75 MS/s and the
ADC from 100 MS/s, so the two ladders share no rung anywhere near 40 kHz.
A flowgraph that generates and captures at "the same rate" is not doing
that, and the arithmetic that depends on it — samples per bit, filter
design, demodulator gain — is wrong in a way nothing reports.

The same bit is 3750 samples going out and 25 coming back.

## The tones are measured, not nominal

`f0 = 40755.0`. The part says 40 kHz; this pair resonates 755 Hz above it
with a −6 dB width of only 1023 Hz, so driving 40.0 kHz throws away about
10 dB. It does not look like a frequency problem when it happens — it looks
like a demodulator that will not lock. `bench/ultrasonic_sweep.py` is where
that number came from, and it is the first thing to re-run on a different
pair or a different spacing.

Mark and space sit at f0 ± 300. At 200 baud with 600 Hz spacing, Carson's
rule puts the occupied bandwidth near 1000 Hz, which fits inside 1023 Hz
with nothing to spare. Widening the deviation makes the eye better and the
link worse.

## Decimate before you demodulate

The receiver mixes f0 to zero and decimates by 200 in one block, down to
5 kS/s, before the quadrature demod sees anything. Capturing at 1 MS/s and
demodulating there means spending all the work on empty spectrum — the
signal is 1 kHz wide inside a 500 kHz Nyquist. 5 kS/s still leaves 25
samples per bit.

The low-pass taps are designed at the **input** rate. `firdes` is not told
about the decimation that follows and will happily design a filter for the
wrong band if you hand it the output rate.

Mixing at f0 rather than at one of the tones puts space at −1 and mark at
+1 after the demod, so the slicer threshold is 0 and there is nothing to
tune.

## Where the byte boundary comes from

Over the air the capture starts wherever it starts. Two things have to be
recovered that a file-to-file flowgraph gets for free:

**Which sample in the bit.** `Symbol Sync` with a zero-crossing detector,
25 samples per symbol in and 1 out. Nothing about the message goes into it.

**Which bit starts the byte.** Every frame begins with a 32-bit sync word,
`0x1ACFFC1D` — the CCSDS attached sync marker, chosen because its
autocorrelation is good and it is somebody else's constant, not one we
picked to make our own test pass. `Correlate Access Code` tags the bit
*after* the code and `Tagged Stream Align` drops everything before that
tag. From there, `Pack K Bits` produces bytes that are the bytes that were
sent.

Threshold is **0**: no bit errors allowed inside the sync word. On a link
this clean a relaxed threshold buys false locks, not range.

`Keep M in N` then drops the next frame's four sync bytes so Message Debug
prints the payload alone. The frame length is fixed at `4 + msg_capacity`,
which is why the message is padded rather than sent at its natural length —
a frame that changed size when somebody typed would move the phase that
`Keep M in N` counts on.

## What has been checked, and what has not

On the bench, 2026-09-09, with `bench/ultrasonic_fsk.py` — the same
receive chain run offline on a live capture: **0 bit errors in 395 bits**,
zero DAC underruns at 750 kS/s non-cyclic, and every symbol dwelling
5.000 ms. That bounds the error rate below about 1/395. It does not
measure a BER, and nothing here has run long enough to.

In the test suite, without hardware (`tests/test_grc_integration.py`):

- the flowgraph validates in GRC and generates Python that parses
- the measured constants are still the ones in the file, and the two rates
  are still two numbers
- the sink is non-cyclic, the source is free-running
- typing a message reaches the vector source and does not resize the frame
- the receive chain recovers `GRCON26` from synthetic FSK started 1373
  samples mid-bit

Not checked: **this exact flowgraph on the board.** The bench script proves
the chain and the parameters; the `.grc` wires the same blocks with the same
numbers plus `Symbol Sync`, which the bench script did offline by searching
the eye instead. Run it at a station before it goes in front of anybody.

Also not checked: range, off-axis falloff, and how many stations can run at
once in one room. Twenty pairs of transducers on the same three tones is a
question the bench cannot answer.

# Colorimeter

`m2k_colorimeter.grc` — the M2k Colorimeter Accessory Board on the digital
header. LED riser in J5, photodiode risers in J3 and J4, V+ and V- powering
the board's op amp. Put a cuvette in the well silkscreened `Sample`.

It measures red, green and blue **at the same time**. Not one after another.

## Three colors, one beam, one FFT

Each color is chopped at its own frequency and all three shine through the
cuvette together. The photodiode sees one messy sum. An FFT pulls the three
apart again, because they were never actually mixed — they were only added.

That is the whole idea, and the frequency sink shows it directly: three
spikes on the reference trace, three on the sample trace. Slide a colored
filter into the sample well and one of the sample spikes drops while the
reference stays where it is.

The alternative — switch on red, measure, switch on green, measure — takes
three times as long and drifts in between. Frequency multiplexing is not a
trick to save time here. It is what makes the three numbers simultaneous.

## Why the frequencies are not round numbers

Red chops at 5004.9 Hz, green at 6005.9, blue at 7006.8.

The buffer is 4096 samples at 100 kS/s. 205, 246 and 287 whole cycles fit in
it exactly, which puts each tone on exactly bin 205, 246 and 287 of a
4096-point FFT at the same rate. Nothing lands between bins, so nothing
leaks, so the window is **rectangular** — the one place in this repo where
that is the right answer rather than the lazy one.

This only works because the pattern generator and the ADC run off one clock.
That was measured, not assumed: `bench/colorimeter.py coherence` puts every
peak on its own bin and holds phase to better than **0.02 ppm** over eight
consecutive blocks. Section 14 of `docs/bench-checklist.md` has the numbers.

Because each tone is periodic in exactly 4096 samples, *any* 4096-sample
window is coherent. There is no alignment to get right and no trigger.

## Goertzel is a lock-in amplifier

A lock-in multiplies the incoming signal by a reference at the chop
frequency and integrates. A single DFT bin is

    X[k] = sum over n of x[n] * exp(-j2*pi*k*n/N)

which is multiply-by-a-reference-and-integrate, written out. They are the
same operation. The `Goertzel` block computes one bin without computing the
other 2047, so six of them — three colors times two photodiodes — replace
two whole FFTs.

The frequency sink is there to *see* the idea. The Goertzels are there to
*use* it.

`buffer_size` on the analog source equals the Goertzel length on purpose.
Each measurement is then exactly one capture buffer and never straddles two.

## The blank is not 1.0

Transmittance is sample over reference, and with nothing in the beam that
ratio is **not** one: the beam splitter does not split evenly and the two
photodiodes are not the same part twice. Measured on this board:

| | red | green | blue |
|---|---|---|---|
| empty-beam ratio | 1.0053 | 0.9757 | 0.9911 |

Three `Multiply Const` blocks divide that out and scale to percent —
`100.0 / blank_red` and so on — so the wire past them carries percent
transmittance rather than a raw ratio. Putting it there instead of in the
number sink's display `factor` matters because the decision block reads the
same wire and its thresholds are in percent. Blanked, an empty beam reads
100.0% and holds it to about 0.06% peak to peak — roughly three decades of
usable range.

### Re-blanking without opening the editor

Those three numbers describe one afternoon's optical alignment. Reseat a
photodiode riser, knock the LED board, carry the thing to a conference, and
they are wrong — silently, as a tilt in every reading rather than an error.

So there is a **Blank** button on the GUI. Empty both wells, press it, and
whatever the two paths are doing right now becomes 100%. It averages the last
two seconds of the raw ratios, upstream of where the blank is divided out, and
sets the three variables through the stock `Message Pair to Var` block. GRC
already wires those variables to each `Multiply Const`'s `set_k`, so the new
blank reaches the wire without anything restarting.

**The check that it worked is already on the screen.** After a good blank all
three read 100.0% and the box says `nothing in the beam`. If it does not,
something was in the beam when you pressed it — press it again with the beam
clear.

Nothing about this sits in the measurement path. If the button is never
pressed, the variables keep the bench numbers and the flowgraph behaves
exactly as it did before the button existed. A blank of zero or infinity —
a reference gone dark, which means a loose riser — is refused rather than
published, because `100.0 / blank` is a live constant downstream.

To set the variables permanently instead, run `bench/colorimeter.py run`,
read the three numbers it prints, and edit `blank_red`, `blank_green` and
`blank_blue` in the flowgraph.

## Idle high, because the bit steers rather than gates

DIO13/14/15 are not on/off switches. They are the select lines of a triple
SPDT, and each one steers its color's current between LED riser 0 (J5) and
riser 1 (J6). Only J5 is populated on this board, so select low is lit and
select high is dark.

Which means `idle_level` must be **high**. Idling low parks all three colors
on J5 and leaves the LED sitting on white whenever the flowgraph is not
running. `docs/colorimeter-board.md` has the schematic detail.

## What has been checked, and what has not

At the bench, with `bench/colorimeter.py`:

- every tone peaks on its own bin, phase stable to 0.02 ppm
- DIO13 is red, DIO14 green, DIO15 blue, confirmed by eye
- analog 1 is the reference path and analog 2 is the sample path — blocking
  the sample well drops channel 2 to 0.8% and leaves channel 1 at 88%
- a green filter strip reads red 9.3% / green 66.0% / blue 24.4%, repeatable
  to 0.3% across half a dozen insertions

In the test suite, without hardware (`tests/test_grc_integration.py`):

- the flowgraph validates in GRC and generates Python that parses
- the three bin numbers, the rate and the buffer size are still what the
  coherence measurement said they had to be
- the sink is cyclic and idles high, on pins 13/14/15
- the Goertzel window is the same length as the capture buffer
- the blanks reach the scaling blocks, and those feed both the display and
  the decision block

On the board, running the flowgraph itself: the three bars track the bench
numbers and the verdict names the filter in the well.

The Blank button passed on 2026-09-16, tested the way that distinguishes it
from doing nothing. With the empty-beam constants only 0.3% stale, blanking a
clear beam moves the readings so little that success and failure look alike --
so the test blanks against the green strip instead. Pressed with the strip in
the well, all three walk to 100.0%; pull the strip and they go far above it,
which is only possible if the button rewrote the constants. Pressed again on a
clear beam, everything returns.

Two things to know before opening it in GRC. Saving from the editor rewrites
the file with every default spelled out, and in doing so resets the number
sink's `color2` and `color3` to black — the green and blue bars go the color
of the red one. And the whole file is hand-written and terse on purpose, so a
save from GRC triples its length. Neither breaks anything; both are worth
undoing before committing.

## Naming the color

Three percentages are a measurement. `Red` is a decision, and no block in
the library makes it, because none of them knows what your thresholds mean.
So the last block in the chain is an Embedded Python Block of about fifteen
lines: three float inputs, one message output, publishing a word only when
the word changes. It lands in a `QT GUI Message Edit Box` on its `val` port.

The rule is *which one is largest*, with a guard either side:

| reading | verdict |
|---|---|
| all three above `clear` (85%) | nothing in the beam |
| all three below `opaque` (5%) | opaque |
| winner under `margin` (1.3×) the runner-up | mixed |
| otherwise | Red, Green or Blue |

Without those guards an empty beam reports a color, and so does a closed
shutter, because something is always largest. The three thresholds are
block parameters, so they are adjustable from the flowgraph rather than
buried in the source.

## The exercises

**Replace the six `Goertzel` blocks with an explicit lock-in** — multiply by
a complex exponential at the chop frequency, low-pass, take the magnitude —
and get the same three numbers. More blocks and more arithmetic for an
identical answer, which is the point to arrive at yourself.

**Then make it name seven colors instead of three.** Magenta passes red and
blue and blocks green; yellow passes red and green; cyan passes green and
blue. That is a three-bit pattern rather than a winner, and the decision
rule becomes a lookup on which colors clear a threshold. The ADI exercise
this board comes with stops at a `# Purple Detector` comment with nothing
under it; this is that, finished.

## Running the tests

`uv run pytest` puts the project venv first on `PATH`, and the venv has no
`gnuradio` — so every test in `test_grc_integration.py` silently **skips**.
Run `.venv/bin/pytest` instead and they execute against the distro's
interpreter.
