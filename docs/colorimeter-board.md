# The colorimeter board, and what is actually on it

Written 2026-09-15, because this identification has been made from
scratch more than once.

## It is not the CN0363

The board that plugs into the M2K for the colorimeter demo is **not** the
EVAL-CN0363-PMDZ, whatever the sticker or the shelf label says. The two
share a cuvette holder and nothing else.

| | EVAL-CN0363-PMDZ | the board we have |
|---|---|---|
| header | 2x6 PMOD | **2x15, mates with the M2K directly** |
| LED select | ADG704 4:1 mux, one color at a time | 3 DIO lines, all three colors at once |
| ADC | **onboard AD7175-2** | none |
| power | green screw terminal | M2K V+/V- |
| driver needed | yes | **none** |

It is `analogdevicesinc/education_tools`, branch **`master`** (not
`main` -- that 404s), path `experiment-boards/m2k-colorimeter`, titled
"M2k Colorimeter Accessory Board". Four PCBs: a main board, one or two
RGB LED risers, two photodiode risers, and a cuvette holder "adapted
from the CN0363". The Readme's theory and usage sections are `TODO`,
which is why everything below had to come out of the KiCad sources.

The matching exercise scripts are Thoren Scientific's
`gnuradio_projects/colorimeter` -- `colorimeter_functions.py`,
`colorimeter_script.py`, `colorimeter_excercise.py` (sic). They drive
DIO 13/14/15 at 500/600/700 Hz and read analog 1 and 2. They target this
board, not the CN0363.

## How the netlist below was obtained

`kicad-cli` is not installed, so there is no exported netlist. The
connectivity was recovered by parsing `board-main.kicad_sch` directly:
union-find over `wire` segment endpoints, then attaching `global_label`
positions and symbol pin positions (library pin offsets rotated by the
instance `at` angle and `mirror`) to the resulting point classes. Snap
tolerance 0.05 mm.

Two things will bite a re-run. Multi-unit symbols must be split by the
instance's `unit` field or all three units of the AD8656 collapse onto
one net. And the schematic's own y-axis is inverted relative to the
symbol library's, so pin offsets are added in x and **subtracted** in y.

If `kicad-cli` ever lands, prefer it.

## Main board

### LED drive

```
V+ --> LED common anode (J5.1 / J6.1)
         |
       R / G / B die
         |
    J5 or J6 pin 2/3/4
         |
     MAX4619 (U2)  <-- DIO 13/14/15 select
         |
    Rsw / Gsw / Bsw
         |
     Q2 / Q3 / Q4 collector      (current mirror, see below)
```

| DIO | U2 pin | selects switch | common | riser 0 (J5) | riser 1 (J6) |
|---|---|---|---|---|---|
| **13** | 11 (A) | X | `Rsw` -> Q2.C | X0 = `R0` | X1 = `R1` |
| **14** | 10 (B) | Y | `Gsw` -> Q3.C | Y0 = `G0` | Y1 = `G1` |
| **15** | 9 (C) | Z | `Bsw` -> Q4.C | Z0 = `B0` | Z1 = `B1` |

Silkscreen 13/14/15 = R/G/B is therefore correct, and confirmed by eye
on 2026-09-15: hold one select low and the other two high and the LED
shows exactly the color the silkscreen names.

**Our board has only riser 0 (J5) populated.** Verified by driving all
three selects together at about 0.1 Hz for 45 seconds: the light blinks
on and off at J5 and never appears at J6. So on this board a select low
is lit, a select high is dark, and a square wave chops that color --
which is what the demo's frequency plan assumes. A board with both
risers fitted would be a dual-beam instrument and nothing would ever be
dark; the plan would still work, but the two channels would then be two
beams rather than one beam and one reference.

Riser numbering is a place to trip: this document indexes them 0 and 1
to match the MAX4619's X0/X1, so **riser 0 is J5 and riser 1 is J6**,
while anyone at the bench counts them 1 and 2.

**The DIO bit does not switch an LED on and off -- it steers that
color's current sink between the two LED risers.** Select low picks
riser 0, select high picks riser 1. With only one riser populated the
empty position is the off half, so a square wave chops that color at the
square wave's frequency. With both risers populated it alternates two
beams and nothing is ever dark.

U2 is a single MAX4619CPE+ (triple SPDT). ENABLE (pin 6) is tied to GND,
i.e. permanently enabled. VCC = V+, VEE = V-.

### Current sink

Q1..Q4 are 2N3904. Q1 is diode-connected (base tied to collector) and
fed from V+ through R11; its base node is decoupled by C10 and drives
the bases of Q2, Q3, Q4. Each emitter goes through its own 100 ohm
resistor (R7..R10) to a common rail, and **JP8 ties that rail to either
GND or V-**. Sitting it on V- buys headroom and raises the current.

So it is a three-output current mirror. R11 has no value in the
schematic; measure it if the drive current ever matters.

### Transimpedance amplifiers

U1 is an **AD8656** dual op-amp, powered from V+ / V-. Both non-inverting
inputs go to ground through JP10 and JP12.

| photodiode riser | cathode -> | feedback | output |
|---|---|---|---|
| **J3** | U1.2 (-A) | JP4 -> 100k (R2) ∥ 2pF (C1), JP5 -> **1M** (R1) ∥ 2pF (C3) | `Out1` |
| **J4** | U1.6 (-B) | JP6 -> 100k (R5) ∥ 2pF (C2), JP7 -> **1M** (R6) ∥ 2pF (C4) | `Out2` |

**Gain is jumper-selected: 100 kOhm or 1 MOhm.** Fit exactly one of each
pair. With 1M ∥ 2pF the pole is about 80 kHz, comfortably above the
500--700 Hz chop.

Photodiode anodes (J3.3, J4.3) both go to `Vbias`, and **JP3 picks
`Vbias` = GND (photovoltaic) or V- (photoconductive)**.

### Where the signals reach the M2K

| M2K | via | carries |
|---|---|---|
| **1+** | JP1: W1 / **Out1** | TIA 1 |
| **2+** | JP2: W2 / **Out2** | TIA 2 |
| 1- | JP9 | GND |
| 2- | JP11 | GND |
| V+, V- | header 23, 24 | rails -- see below |
| TI, TO | header 17, 18 | trigger, passed straight through |

JP1 and JP2 also let W1/W2 be jumpered in instead of the TIA outputs,
for injecting a known signal. Coax jacks J7 and J8 monitor `Out1` and
`Out2`.

Which TIA is the reference and which is the sample is **mechanical, not
electrical** -- it depends on which riser sits behind the cuvette.
Thoren's scripts assume channel 1 = reference, channel 2 = sample.
Confirm it on the bench rather than inheriting the assumption.

### Idle is not dark

`digital_sink(idle_level="low")` parks all three selects at 0 between
runs, which steers all three colors to J5 and leaves the LED white
whenever the flowgraph is not running. It looks like the board is stuck
on. Use `idle_level="high"` on this board -- it puts every color on the
empty riser, which is off.

The same thing shows up as a white flash if a script stops one flowgraph
and starts another, because the pins idle between the two. One
flowgraph that never stops has no gap to flash in.

## The holder and the optical path

The fourth PCB in the kit has no electrical function and is easy to
dismiss, but it is what makes two photodiodes mean anything. It is a
40 mm plate with **two 13.2 mm square cuvette wells set at right angles
to each other**, silkscreened `Sample` and `Reference`, and a **2 mm
slot running diagonally at 45 degrees across the elbow between them**.

The slot is the beam splitter. One LED fires along one axis; the
splitter passes part of the beam straight through to the `Reference`
well and reflects the rest through 90 degrees into the `Sample` well.
Each well has its own photodiode riser behind it. That is the CN0363's
optical arrangement, which the kit's readme says the holder was adapted
from -- the optics are inherited even though none of the electronics is.

The slot is not a sample position. Nothing goes in it but the splitter.

Measured 2026-09-15 by loading the `Sample` well opaque and leaving an
empty cuvette in `Reference`:

| | red | green | blue |
|---|---|---|---|
| analog 1 keeps | 87.8% | 87.2% | 89.0% |
| analog 2 keeps | 0.87% | 0.59% | 0.96% |

So **analog 2 is the sample and analog 1 is the reference**, matching
what Thoren's script assumed.

The reference channel losing 12% is the empty cuvette itself, about 4%
of Fresnel reflection at each of two interfaces. It is the reason a
colorimeter blanks against an empty cuvette rather than against an empty
slot. The 0.8% left on the sample channel is still 80 times the noise
floor, so there is about 2 OD of range before the measurement runs out.

## Two traps

**V+ powers the LEDs, not just the op-amp.** The LED common anodes sit
directly on V+. Nothing on this board lights up or amplifies until the
rails come up. `m2k_power_supply` is not optional garnish here; it is the
first block in the flowgraph.

**DIO 4, 5, 6 and 7 are shorted together** and run to coax jack J9 --
four junctions on one net in the published schematic. Whether that is
intentional or a drawing error, driving any of 4..7 as an output on this
board is a pin collision. Leave them as inputs.

## Still unknown

- R11's value, so the LED current is unknown.
- Reference vs sample channel, as above.
- What J9 is for.
