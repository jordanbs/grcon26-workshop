# The colorimeter demo

The hardware is `docs/colorimeter-board.md`. This is what the demo does
and why it is the last one in the deck.

## What it measures

Shine red, green and blue light through a cuvette, compare what comes
out against a reference beam that does not pass through it, and you have
the transmittance of the liquid at three wavelengths. Food colouring is
a sharp enough demonstration; so is tea.

The interesting part is not the chemistry. It is that the three colours
are measured **at the same time, on one photodiode**, by giving each one
its own chop frequency and separating them afterwards. Room light,
sunlight through a window, the 120 Hz from the ceiling fixture and the
op-amp's own 1/f noise all land somewhere other than those three
frequencies and are simply not read.

That is a lock-in amplifier, three of them, and none of it is hardware.

## Why it closes the workshop

It is the only demo that needs all three of the Phase 1 capabilities at
once, and each for a reason that is hard to fake:

- **`m2k_power_supply`** — V+ feeds the LED anodes as well as the
  AD8656. Without the rails the board is dark and deaf. This is not a
  block you add for completeness; it is the first one in the flowgraph.
- **`m2k_digital_sink`** — three different square waves on DIO 13, 14
  and 15, which are three bit fields of one 16-bit word. This is exactly
  the case gr-iio's stock sink gets silently wrong
  (`docs/gr-iio-multipin-sink.md`).
- **`m2k_analog_source`** — two TIA outputs, simultaneously, in volts.

By this point in the workshop nobody has to be told what those blocks
are. They get used.

## Lineage

Analog Devices' CN0363 is the reference design: a dual-photodiode
colorimeter with a synchronous detector. The board that plugs into the
M2K borrows its cuvette holder and nothing else -- no ADC, no mux, no
driver. Thoren Scientific's `gnuradio_projects/colorimeter` is the
libm2k exercise written against that board, and it is the direct
ancestor of this demo. What changes here is that it becomes a flowgraph,
and that the frequency plan is chosen rather than inherited.

## The frequency plan

The excitation buffer is **4096 samples at 100 kS/s**, pushed once as a
cyclic buffer so the hardware repeats it forever. A colour driven at
exactly *K* whole cycles per buffer is therefore a tone at
`K * 100000 / 4096` Hz, and a 4096-point FFT of the captured signal at
the same rate puts it in **bin K exactly**.

| colour | DIO | cycles per buffer | frequency | bin |
|---|---|---|---|---|
| red | 13 | 205 | 5004.9 Hz | 205 |
| green | 14 | 246 | 6005.9 Hz | 246 |
| blue | 15 | 287 | 7006.8 Hz | 287 |

4096/205 is not an integer, so the square wave's duty cycle wobbles by a
sample from period to period. That puts a little extra energy in the odd
harmonics and none at all near any of the three fundamentals, which are
the only bins that get read. No harmonic of any colour lands on another
colour's fundamental.

Bin width is 24.4 Hz and the record is 41 ms long, so each measurement
is a lock-in with a 41 ms integration time.

### A note on Thoren's numbers

`colorimeter_functions.py` says `red_freq = 500`, and the script reads
bins 202--207 of a 4096-point FFT taken at 100 kS/s -- which is 4930 to
5053 Hz. Both are right. The buffer is *generated* against 10 kS/s and
*played* at 100 kS/s, so every frequency comes out ten times higher than
the variable names claim. The five-bin sum is there because 5000 Hz
falls at bin 204.8, between two bins, and leaks. Picking 205 instead
removes the need for both the window and the sum.

## Why an FFT is a lock-in here — and the part that is not yet proven

A lock-in multiplies the input by a reference at the excitation
frequency and integrates. The DFT at bin *k* is

    X[k] = sum over n of  x[n] * exp(-j 2 pi k n / N)

which is multiply-by-reference-and-integrate, for a reference of exactly
*k* cycles across the record. They are the same operation. `|X[k]|` is
the magnitude a lock-in would report and `arg X[k]` is its phase.

This holds **only if the excitation really is exactly *k* cycles across
the record** — that is, only if the clock generating the LED chop and
the clock sampling the photodiode are the same clock. On the M2K the
digital output is timed off the fabric clock and the ADC off its own
divider from 100 MS/s. Whether those are coherent in practice is an open
question, and the workshop is not allowed to assert it from a block
diagram.

`bench/colorimeter.py coherence` measures it: it takes one contiguous
capture, splits it into eight blocks, and tracks the phase of each
colour's bin from block to block. Constant phase means one clock. A
steady slope is a frequency offset, reported in ppm.

If it turns out they are not coherent, the demo still works -- it
becomes Thoren's version, a Blackman window and a sum over five bins --
but the slide has to say so.

## Setting the board up

Jumpers, before anything is powered:

| jumper | set to | why |
|---|---|---|
| JP1 | `Out1` | TIA 1 to analog input 1 |
| JP2 | `Out2` | TIA 2 to analog input 2 |
| JP9, JP11 | fitted | 1- and 2- to ground |
| JP5, JP7 | fitted (**not** JP4/JP6) | 1 MOhm transimpedance gain |
| JP3 | GND | photovoltaic; quieter, slower, fine at 7 kHz |
| JP8 | GND | LED sink rail |
| JP10, JP12 | fitted | op-amp + inputs to ground |

Fit exactly one of JP4/JP5 and one of JP6/JP7. Two fitted puts the
resistors in parallel; none fitted leaves the amplifier open-loop.

With 1 MOhm and the 2 pF feedback cap the pole is about 80 kHz, ten
times the highest chop frequency. Dropping to 100 kOhm costs a factor of
ten in signal and buys nothing here.

Then: one LED riser, two photodiode risers, cuvette holder, and the
board pressed onto the M2K header. **Do not drive DIO 4--7** — they are
shorted together on this board.

## Running it

From the repo root, with a GNU Radio interpreter:

    python3 bench/colorimeter.py coherence   # is an FFT a lock-in here?
    python3 bench/colorimeter.py pins        # which pin is which colour
    python3 bench/colorimeter.py channels    # which channel is the sample
    python3 bench/colorimeter.py run         # transmittance, continuously
    python3 bench/colorimeter.py supply      # rails against a meter

Run them in that order the first time. `pins` and `channels` exist
because two of the four things this demo depends on cannot be read out
of a schematic: the LED riser is a separate board on a symmetric 6-pin
connector, and which photodiode sees the cuvette is a matter of which
slot it is in.

`run` assumes analog 1 is the reference and analog 2 the sample, which
is what Thoren's script assumes. `channels` is how you find out whether
it is true of the board in front of you.

## Still open

- Coherence, as above. Everything in this document downstream of the
  frequency plan depends on it.
- R11 has no value in the schematic, so the LED drive current is
  unknown, so the optical power is unknown. It only matters if the
  photodiode saturates or the signal is too small to see.
- The `.grc` participants will open does not exist yet.
