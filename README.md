# GNU Radio and the ADALM2000

Workshop material for GRCon26. GNU Radio blocks that treat the ADALM2000 as
a scope, a signal generator, a logic analyzer and a power supply — rather
than as fourteen IIO devices you have to understand first.

90 minutes, crawl / walk / run, and one short setup beforehand.

## Before the session

```
curl -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.sh
bash m2k-setup.sh
```

Windows, from the Radioconda Prompt:

```
curl.exe -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.ps1
powershell -ExecutionPolicy Bypass -File m2k-setup.ps1
```

It wants GNU Radio already installed and finds the rest itself: gr-iio,
pylibiio, the blocks, the GRC block path, USB permissions, and the address
of your board. **[install/README.md](install/README.md)** says what each
piece is for, what to do when it goes wrong, and why a Mac has to type
`usb:` where everyone else types `ip:192.168.2.1`.

That is the only thing anyone installs. Nothing gets installed in the room.

## The blocks

Seven, in `gr-m2k/`. Every parameter says what it does and what its values
are, and none of them says "IIO" anywhere.

| block | what it is |
| --- | --- |
| **M2K Analog Source** | the scope — two channels, ranges, sample rate, trigger |
| **M2K Analog Sink** | the generator |
| **M2K Digital Source / Sink** | the sixteen DIO pins, however many you claim |
| **M2K Power Supply** | a rail, in volts. GNU Radio cannot otherwise set one |
| **M2K SPI Encode / Decode** | bytes to three wires and back. Touches no hardware |

The argument for them is one table. This is GNU Radio's stock **IIO Device
Source**, which is correct, general, and unusable without a datasheet open:

| stock parameter | the problem |
| --- | --- |
| IIO context URI | no example of a legal value |
| Device Name/ID | which devices exist, spelled how? |
| PHY Device Name/ID | "PHY" means nothing here |
| Channels | a Python list of strings you must already know |
| Decimation | factor, or samples dropped? |
| Parameters | free-text `key=value` with an unguessable naming rule |

Against **M2K Analog Source**, where the same settings — which live on
three different IIO devices, so a stock Device Source cannot express them
at all — read as: channel on or off, ± 25 V or ± 2.5 V, a sample rate from
the six the hardware publishes, volts or raw counts, trigger on a channel
at a level in volts.

Illegal combinations are refused on the canvas, not at run time: no
channels enabled, a zero buffer, a trigger level outside the range you
picked. **[gr-m2k/README.md](gr-m2k/README.md)** is the full parameter
reference — every field, and what it quietly becomes.

## The flowgraphs

```
gnuradio-companion flowgraphs/m2k_scope.grc
```

| | |
| --- | --- |
| `m2k_blinky.grc`, `m2k_led_pwm.grc` | an LED on DIO0, then the same LED dimmed |
| `m2k_scope.grc`, `m2k_loopback*.grc` | the generator into the input, four ways |
| `m2k_spi_loopback*.grc` | an SPI bus on the digital pins, decoded |
| `m2k_ultrasonic_fsk.grc` | 40 kHz FSK across the room |
| `m2k_colorimeter.grc` | three chopped LEDs, separated in one FFT |

`flowgraphs/README.md` says what each one needs wired up.

## The deck

```
xdg-open slides/index.html
```

Published at <https://livethisdream.github.io/grcon26-workshop/>. One HTML
file. **Read** mode is continuous notes; **present** mode is one frame a
screen with the detail collapsed behind *More detail +* — the same
document, so presenting cannot lose it. Printing gives the notes back, one
frame per sheet.

The block and flowgraph figures are rendered from GNU Radio Companion's own
canvas code by `slides/render_grc.py`, so a slide and a participant's
screen cannot drift apart. `slides/README.md` has the authoring rules and
`slides/check_deck.py` enforces the ones that are invisible until they are
wrong in front of people.

## Where the blocks came from

The dropdowns, the units and the documentation in those blocks were not
written by hand. They came out of the hardware's own published values, via
the tooling in **[iio-tools/](iio-tools/README.md)** — capture a board
once, explain it anywhere, generate a GRC block definition from the
capture. None of it is needed to run the workshop. It is there because
"where did that value come from" deserves an answer, and because the
generated blocks are the honest comparison: correct, general, and still
speaking IIO.

`docs/reading-iio-attributes.md` is the participant handout it generates —
how to read an attribute name, and the unit the kernel guarantees.

## Layout

```
gr-m2k/       the blocks, their GRC definitions, and the install CLI
flowgraphs/   the .grc files those blocks are used in
install/      one setup script per platform, and what they do
slides/       the deck -- one HTML file, read or present
docs/         handout, bench checklist, and the multi-pin sink note
iio-tools/    the IIO discovery suite the blocks were built from
booth/        the GRCon booth beacon -- a Pico transmitting FSK
bench/        scripts that produced the measurements, and their CSVs
project/      working notes, decisions and traps
tests/        pytest, no hardware required
```

## Tests

```
uv sync
uv run pytest
```

Everything runs without libiio and without an M2K; the tests that need GNU
Radio skip without it. `REGEN_GOLDEN=1` accepts intentional changes to the
golden output.

## Still open

- `bench/colorimeter.py filter` on more than the one green strip the
  85 / 5 / 1.3 thresholds were sized to.
- Range and off-axis falloff for the ultrasonic link, and a long enough run
  for a real bit error rate. 395 bits bounds it below 1/395 rather than
  measuring it.
- Every `[overlay: UNVERIFIED]` entry in `iio-tools/iio_overlays.py`.
