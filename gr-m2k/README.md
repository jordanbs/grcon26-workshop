# The M2K as an instrument

GNU Radio blocks that treat the ADALM2000 as a scope and a signal
generator, rather than as fourteen IIO devices you have to understand
first.

## What it needs

Nothing here compiles: the blocks are Python, so there is no CMake step
and no `gnuradio-dev`. That is not the same as having no dependencies, and
the difference is where people get stuck.

| | import | comes from | used by |
| --- | --- | --- | --- |
| **GNU Radio** | `gnuradio.gr` | your distro, or radioconda | everything |
| **gr-iio** | `from gnuradio import iio` | ships inside GNU Radio, not pip | every block that streams |
| **pylibiio** | `import iio` | `python3-libiio`, brew, or pip | `digital.py`, `m2k_config.py` |
| **numpy, pmt** | | GNU Radio brings both | the digital and SPI blocks |

**The two `iio`s are different libraries.** `from gnuradio import iio` is
gr-iio, the GNU Radio blocks that move samples. `import iio` is pylibiio,
the binding round the C library, which is what reads and writes the
attributes gr-iio has no block for -- `direction` on a DIO pin, the
trigger registers, the supply's calibration constants. Having one does not
give you the other, and they fail differently: gr-iio missing breaks the
block at construction, pylibiio missing breaks it at the first attribute
write.

Neither is in `pyproject.toml`. gr-iio cannot be -- it does not exist on
any package index, and naming it would make every install fail. pylibiio
deliberately is not either: it wraps a native library, so a pip install
without the matching `libiio.so` gives you an import that fails at run
time instead of at install time, which is worse than not having it.
`install/README.md` covers getting both, per platform.

The hardware needs nothing installed on Linux or macOS beyond permissions.
Windows needs ADI's USB driver package. Also in `install/README.md`.

## Installing

Two routes, and a script that does the second one for you.

**The script**, if you just want it working -- see `install/README.md`:

```
bash install/m2k-setup.sh
```

**For this shell only**, from a clone of the workshop repo:

```
source gr-m2k/env.sh
gnuradio-companion flowgraphs/m2k_scope.grc
```

`[ADALM2000]` appears in the block tree. Nothing is written to disk and
nothing outside that shell changes, which makes it the right choice for
trying the blocks out and for CI.

**For every terminal**, straight from GitHub, no clone:

```
pip install "git+https://github.com/livethisdream/grcon26-workshop#subdirectory=gr-m2k"
m2k-blocks install
```

`m2k-blocks install` adds the installed block directory to
`~/.gnuradio/config.conf` under `[grc] local_blocks_path`, which is GNU
Radio's own supported place for out-of-tree blocks. It appends rather than
replaces, keeps a `.bak` if the file already existed, and `m2k-blocks
uninstall` takes it back out. Restart gnuradio-companion afterwards -- a
running one will not pick up a directory it did not have at launch.

### Which Python

This is the one thing that actually goes wrong. `pip install` has to land in
the **same interpreter gnuradio-companion uses**, which on a distro GNU
Radio is the system Python and not a fresh venv:

```
pip install --user "git+https://github.com/..."     # usually right
```

A venv only works if it can see the system packages *and* was built from the
system interpreter -- `uv venv --system-site-packages --python /usr/bin/python3`.
A venv on a different Python installs cleanly, puts `m2k-blocks` on your
`PATH`, and still leaves the block tree empty, because GRC never sees it.

### When the blocks are not in the tree

```
m2k-blocks check          # or: python -m m2k_blocks check
```

The `python -m` spelling is the one to reach for when things are wrong: a
`pip install --user` routinely puts the `m2k-blocks` script somewhere that
is not on PATH, and then the tool for diagnosing a bad install is itself
missing. Naming the interpreter cannot miss.

It prints the block directory, the interpreter it is running under, whether
`m2k_blocks` imports, and the full list of directories GRC will search with
ours marked. Exit status 0 means GRC will find the blocks.

That list is worth understanding once. GRC concatenates four sources, in
order, dropping the ones that do not exist:

| | |
| --- | --- |
| `~/.grc_gnuradio` | always first |
| `GRC_BLOCKS_PATH` | the environment, what `env.sh` sets |
| `[grc] local_blocks_path` | `~/.gnuradio/config.conf`, what `m2k-blocks install` writes |
| `[grc] global_blocks_path` | `/etc/gnuradio/conf.d/grc.conf`, the system blocks |

It **prepends**; it does not replace. Do not put block paths in
`~/.gnuradio/grc.conf` -- that file is GUI state and says so in its own
first line.

### Two paths, two different failures

`GRC_BLOCKS_PATH` decides whether the block appears in the tree.
`PYTHONPATH` decides whether the generated flowgraph can import the code
behind it. Set only the first and the failure is quiet: the blocks appear,
the canvas validates, and the flowgraph dies on Run with an ImportError.
`env.sh` sets both; `pip install` makes the second one stop existing as a
thing to forget.

`m2k_calibrate.py` and `generate_digital_grc.py` sit beside the package
rather than inside it, so they come with a clone and not with a wheel. They
are development tools, not part of the block library.

## Why not the stock IIO Device Source

Eight parameters, of which about two can be guessed:

| stock parameter | the problem |
| --- | --- |
| IIO context URI | no example of a legal value |
| Device Name/ID | which devices exist, spelled how? |
| PHY Device Name/ID | "PHY" means nothing here |
| Channels | a Python list of strings you must already know |
| Decimation | factor, or samples dropped? |
| Parameters | free-text `key=value` with an unguessable naming rule |
| Packet Length Tag | opaque, and irrelevant to most flowgraphs |

## M2K Analog Source

Every parameter says what it does and what its values are:

| parameter | values | quietly becomes |
| --- | --- | --- |
| M2K address | `ip:192.168.2.1` — the default is the example | context uri |
| Channel 1 (1+) / Channel 2 (2+) | On / Off | the channel list |
| Sample rate | 100 MS/s … 1 kS/s | `sampling_frequency` on `m2k-adc` |
| Channel N input range | ± 25 V / ± 2.5 V | `gain` on `m2k-fabric` |
| Output | Volts (float) / Raw counts (short) | the output port's type |
| Samples per buffer | 16384 | buffer size |
| Trigger on | Free running / Channel 1 / Channel 2 | `m2k-adc-trigger` |
| Trigger when signal is | Rising / Falling / Above / Below level | `trigger` |
| Trigger level (V) | volts | `trigger_level`, in counts |

The last two appear only once the trigger is on. The range fields appear
only for channels that are enabled.

**`ip:192.168.2.1` is not universal.** It is the board's USB ethernet
gadget, which Linux provides natively and Windows provides once ADI's
driver package is in. macOS does not provide it at all any more -- the
RNDIS kext it needed is unmaintained and does not load on Apple silicon.
On a Mac the address is `usb:`, which libiio resolves by itself when one
board is plugged in. `m2k-blocks scan` prints the right string for
whatever machine it is run on:

```
python -m m2k_blocks scan
```

Those settings live on **three different IIO devices**, which is why a
stock Device Source cannot express them: its `params` go to exactly one.

### Illegal combinations are refused in GRC

Not discovered at run time:

- no channels enabled
- a zero buffer
- a trigger level outside the input range you picked — which could never
  fire, and nothing else would tell you

## M2K Digital Source / Sink

Sixteen DIO pins, and a block claims however many of them it needs. Set
**Number of pins** to 3 and three dropdowns appear; set each one to
whatever DIO the jumper reached.

| parameter | values | what it means |
| --- | --- | --- |
| Number of pins | 1-16 | how many ports the block has |
| Pin N | DIO0-DIO15 | which DIO that port is |
| Pin N Label | text | what to call it in an error |

**The list is the port order, not a range.** Pin 1 is whichever DIO you
put in the first dropdown, so `DIO3, DIO7, DIO1` is a supported thing to
ask for rather than an accident. They need not ascend and need not be
adjacent.

**The parameters count from 1, the ports from 0.** Pin 1 is the port
drawn `pin0`. GRC numbers cloned ports itself and will not take a
template for it, so this one is a wart rather than a decision.

**Nothing here is protocol-aware.** Three pins are three pins, whether
they are SPI's clock, data and select or a latch strobe beside a data
bus. Which of those it is belongs to whatever block reads them next.

**The labels change no behaviour whatever.** GRC draws a port's label
from the block definition and will not evaluate it, so labelling Pin 2
`MOSI` does not rename `pin1` on the canvas — the canvas naming happens
at the protocol block, whose ports are `sclk`, `mosi` and `cs` because
they can be nothing else. What a label buys is that a mistake reports
itself as `MOSI (DIO7)` instead of `DIO7`.

**A pin is an input or an output, never both.** Each block writes
`direction` for its own pins at construction, so a source and a sink that
share a pin fight over it: whichever is built last wins, and the other
silently reads or drives nothing. GRC refuses a block that lists the same
pin twice, but it cannot see across two blocks. That one is yours.

Both ymls are generated by `generate_digital_grc.py` — sixteen pins and
sixteen names, twice over, is six hundred lines that differ only by an
index, and a source and a sink that drifted apart there would wire a bus
backwards with both halves running. The generated files are committed and
a test fails if they stop matching.

## M2K SPI Decode

The odd one out: it holds no context, writes no attribute and never
touches the board. Three digital streams in — SCLK, MOSI, CS — and the
bytes that were on the bus out, as a message.

| parameter | values | what it means |
| --- | --- | --- |
| Bits per word | 8 | 12 and 16 are real widths; 8 is a byte |
| Chip select | Active low / Active high | active low unless a datasheet says otherwise |
| Text in metadata | Yes / No | the bytes as characters, beside the hex |

SPI mode 0 only, MSB first. The clock rests low and the bit is read on
the rising edge, so a rising edge with chip select asserted is a bit,
and that sentence is the whole decoder. Modes 1-3 sample on a different
edge — a two-line change, deliberately not offered, because no capture
in this repo contains one and an untested dropdown is worse than none.

That mode 0 is the same mode 0 as everyone else's, and not just the one
this repo agrees with itself about: `tests/test_spi_sigrok.py` hands the
encoder's waveform to libsigrokdecode — PulseView's SPI decoder, no
relation to anything here — and gets the queued bytes back, across four
bus speeds, both chip-select polarities and 8/12/16-bit words. Told the
wrong bit order or the wrong clock phase, it reads different bytes, so
the check is one that could have failed. See checklist section 13.

**The message carries the bytes and their reading.** The payload is the
words that were on the wire; the metadata carries the same words as
text, so a Message Debug prints

```
((text . M2K))
pdu length =          3 bytes
pdu vector contents =
0000: 4d 32 4b
```

which is the text column Scopy shows and the quickest proof a loopback
carried what someone typed. Bytes outside printable ASCII come out as
`\xNN`, not as dots, so nothing is thrown away. Above 8 bits per word
there is no text to give and none is added.

Two things about it are worth more than the block itself:

**Chip select is the framing, and the decoder refuses to guess.** It
emits nothing until it has seen a falling CS. A capture that starts
mid-frame has lost an unknown number of bits, and the next eight still
make a byte — a real, plausible, wrong one. Bits left over at the end of
a frame are dropped the same way rather than padded.

**The decode itself is a separate module that imports nothing.**
`m2k_blocks/spi_decode.py` is plain Python — no gnuradio, no numpy — so
it is tested in the ordinary interpreter, the same arrangement
`m2k_scale.py` has. The GNU Radio wrapper is thirty lines around it.
That split also bought the one performance fact that matters here:
indexing a numpy array element by element from Python costs 0.84 s per
million samples against 0.04 s for a list, so the wrapper calls
`.tolist()` first and 1 MS/s stays comfortable.

## M2K SPI Encode

The mirror of the decoder, and the other block that never touches the
board. A message in, three digital streams out — SCLK, MOSI, CS — ready
to wire into a Digital Sink.

| parameter | values | what it means |
| --- | --- | --- |
| Bits per word | 8 | text is bytes whatever this says; wider widths are for PDU input |
| Chip select | Active low / Active high | active low unless a datasheet says otherwise |
| Samples per half clock | 8 | the bus speed: the clock is `sample_rate / (2 * half)` |
| Align frames to | 0 | the sink's buffer size when that sink is not cyclic; 0 otherwise |
| Idle before / CS to first clock / Last clock to CS / Idle after | 64/8/8/48 | the quiet stretches around the clocked bits, in samples |

It is a source with no stream input, which is the design decision worth
explaining. Between messages it produces idle — clock low, data low, CS
released — for as long as anyone asks, so the Digital Sink downstream of
it never starves and the sink's blocking push is what paces the graph. A
message that arrives mid-buffer is queued, not dropped.

**One frame is one whole transaction.** CS falls once, every byte of the
message is clocked out back to back, CS rises once. Not once per byte:
the M2K's triggered capture re-arms on each buffer, so per-byte framing
makes every capture start on an arbitrary byte and the decoded message
comes back rotated. Section 11 of `docs/bench-checklist.md` is where that
was found.

**`Align frames to` is the one parameter that exists because of the
hardware.** A non-cyclic Digital Sink hands the board one DMA buffer at a
time and the board need not join them seamlessly, so a frame lying across
a buffer seam can be torn in the middle. Nothing downstream can see where
those seams are — but the encoder's sample count *is* the sink's position
in its buffer, because every sample it produces reaches the sink in order
and the sink pushes every `buffer_size` of them. So it holds a queued
frame until the next boundary and starts it there. Set this to the sink's
buffer size whenever the sink is not cyclic, and leave it 0 otherwise.

A word too wide for the bus is dropped with a warning rather than raised
as an error: a mistyped message should not end a run somebody is halfway
through.

**Pair it with an untriggered Digital Source.** gr-iio's `device_source`
returns `WORK_DONE` on any refill error, so a source armed on CS falling
ends itself the first time nobody sends anything for a moment — one
message decodes and the capture never comes back. Send-on-demand means
unbounded gaps between frames, and `m2k_spi_decode` frames on CS in
software anyway. Trigger the display, not the board.

Like the decoder, the arithmetic lives in a module that imports nothing
— `m2k_blocks/spi_encode.py` — so a message that survives a round trip
through both halves has been checked against an independent reading of
the same three rules, on a machine with no gnuradio and no board.

## ASCII at Every Offset

Neither this block nor the next one touches the board. Both are about
finding where a byte begins in a stream of bits, which is the thing that
goes wrong after the demodulator is already working.

| parameter | values | what it means |
| --- | --- | --- |
| Shortest run to print | 16 | how many printable characters in a row to believe |
| Also try inverted | Yes / No | covers a demodulator that handed the tones back upside down |
| Window (bits) | 2048 | how much is searched at once |
| Lines per window | 4 | longest first, so the payload leads |

Use it when the transmitter sends no sync word. `Pack K Bits` still has
to pick a boundary and picks the arbitrary one, right about an eighth of
the time; the other seven eighths are mojibake, and mojibake reads as a
broken link rather than as bad framing. People go and move the antenna.

So this does not pick. It packs the same bits eight ways -- sixteen with
inversion -- and prints what reads as text, with the offset it read at:

```
offset 4   96 chars  A=00000 B=XXXXXX C=example      A=00000 B=...
```

The offset is the useful part. It stays put for as long as the flowgraph
runs, so it is the number to put into a `Skip Head` ahead of `Pack K
Bits` when you want a File Sink or a Message Debug to agree with the
console.

**Sixteen characters, and eight is the tempting wrong answer.** Random
bytes are printable about 37% of the time, so eight in a row turns up
roughly once in every 3500 positions -- constantly, across sixteen
offset-and-polarity combinations scanning every position. Sixteen in a
row is about one in five million, which works out to silence between
bursts. That is the property worth having: silence on the console then
means silence on the air, not a wrong guess about framing.

## Sync-to-Sync Framer

The other answer, for a signal that *does* carry a marker. Put it
downstream of `Correlate Access Code - Tag` with the same tag key.

| parameter | values | what it means |
| --- | --- | --- |
| Tag key | `sync` | must match the correlator's Tag Name |
| Sync word (bits) | 32 | how much of the span the closing marker takes |
| Shortest / Longest payload | 64 / 1024 | bounds, not a length |
| Preamble byte | `0xAA` | a span ending in this crossed a burst boundary; -1 turns the check off |

**Use it instead of `Tagged Stream Align` plus `Keep M in N` whenever the
transmitter stops and starts.** Keep M in N is handed an alignment once
and from then on it counts: every N items it keeps the first M, forever.
That is exact while the transmitter never stops. A transmitter that
bursts breaks it on the second burst -- the counter runs through the
silence, the silence is not a whole number of frames, and nothing
re-aligns. The error is permanent, and it arrives as bit-perfect garbage.

This block throws the counter away. The correlator tags the first bit
after each marker, so a payload is whatever lies between one tag and the
next, less the marker that closes it. Nothing counts across the gap
because nothing counts at all.

That buys the property the counter never had: **it never needs to know
how long a payload is.** One instance decodes an eight-byte frame and a
thirty-two-byte frame in the same run, untouched.

A transmitter using it has to send a trailing sync word after its last
frame, or that frame has no closing delimiter and is dropped.

**The bounds are bounds.** A span longer than the maximum is the gap
between two bursts; a span shorter than the minimum is the join where one
burst's trailing marker meets the next one's preamble. Both are thrown
away, and both are tallied rather than logged -- at 200 baud the
rejections are the normal shape of a bursty link, and a line each would
bury the frames.

Like the SPI blocks, the logic in both of these lives in a module that
imports nothing -- `ascii_scan.py` and `sync_frames.py` -- so it is
tested in an ordinary interpreter with no GNU Radio present.

## What has been checked


Against GNU Radio 3.10 itself, with no hardware
(`tests/test_grc_integration.py`, `tests/test_m2k_scale.py`):

- GRC's real loader accepts the block; its parameters carry no IIO
  vocabulary at all — asserted, not eyeballed
- a flowgraph using it validates and generates Python that parses
- run headless, it reaches `RuntimeError: Unable to create context` —
  everything but the board
- the arithmetic is tested with no GNU Radio present, including that the
  sample-rate list matches what a real M2K publishes

## What has not

**The volts conversion.** `volts_per_count` comes from libm2k's
`getScalingFactor()` and no signal has confirmed it. Right shape, wrong
amplitude means suspect this — and switch Output to **Raw counts**, which
are untouched by it.

**The configuration path.** gr-iio's `attr_sink` needs a live context to
construct, so range and trigger writes cannot be exercised here. They are
built from libm2k's own attribute usage, but they have never run.

## Two things the build turned up

**The hardware publishes its own sample rates.** An earlier version
computed them as 100 MS/s ÷ `oversampling_ratio` and produced a dropdown
that wrongly excluded 1 kS/s. `sampling_frequency_available` lists six
exact rates; when the hardware publishes a list, the list wins.

**`option_labels: [On, Off]`** silently becomes `True / False` — YAML 1.1
reads those as booleans. Quote every option label. There is a test.
