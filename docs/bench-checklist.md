# What to check on hardware

Ordered so that each step makes the next one meaningful.

Nothing here needs the discovery tool. It needs an M2K, a wire, and
ideally a meter.

**State as of 2026-09-15:** every section passes. Section 4 was the last
open one -- it passed on everything relative and failed on absolute
accuracy -- and section 10 closes it with a metered gain and offset for
all four signal paths. Section 14 is new: it settles whether the
pattern generator and the ADC share a clock, which is what the
colorimeter demo rests on.

Section 9 is where the multi-pin digital sink got fixed. gr-iio's
`device_sink` can only drive one DIO pin -- silently -- so `digital_sink`
packs the 16-bit output word itself now. The whole story, with the
evidence, is in `docs/gr-iio-multipin-sink.md`.

Board used: Rev.D (Z7010), fw v0.33, reached at `ip:192.168.2.1`.

---

## 1. The blocks appear and load — PASSES

```
source gr-m2k/env.sh
gnuradio-companion flowgraphs/m2k_loopback_native.grc
```

`env.sh` sets `GRC_BLOCKS_PATH` and `PYTHONPATH` for that shell and nothing
else -- the two exports this checklist used to spell out at every step. For
an install that outlives the shell, `pip install` and `m2k-blocks install`;
if the block tree is empty, `m2k-blocks check` says why. See
`gr-m2k/README.md`.

- [x] `[ADALM2000]` is in the block tree with four blocks
- [x] the flowgraph opens with no red blocks

Loading is not constructing. All four blocks threw `Device not found`
the first time they met a board, because `device_phy` was passed as `""`
and gr-iio resolves that with `iio_context_find_device` exactly like the
streaming device. An empty string is not "no phy device"; it is a lookup
that always fails.

## 2. Loopback, raw counts first — PASSES

Wire **W1 to 1+**, and **ground to 1-**. Use
`flowgraphs/m2k_loopback_raw.grc`, which has none of our arithmetic in
the path.

- [x] a waveform appears at all
- [x] its frequency matches `tone_hz`
- [x] the counts stay inside ±2047

Two things had to be fixed before a waveform appeared, and neither
looked like what it was:

**A flat line at −12.5 counts, not an error.** The ADC's input stage
comes up powered down on a board nothing has initialised. `analog_source`
wrote the input range to `m2k-fabric` but not the `powerdown` sitting
next to it. libm2k does this in `M2kImpl::initialize`; nothing else
here would. The failure mode is the expensive kind — plausible-looking
data, no complaint.

**A strong tone at exactly 500 kHz.** That is Nyquist at 1 MS/s, which
should have been the tell. The ADC always delivers both channels,
interleaved, whatever you ask for. Request one and gr-iio de-interleaves
a two-channel buffer as if it were one, so channel 2's samples land in
channel 1's stream and the time base comes out 2× slow. First sixteen
samples were `[18, 41, 18, 41, ...]`; with the generator on, the even
samples had std 43.49 and the odd ones 0.22. The block now takes both
channels and publishes only the ports that were asked for, which is what
`M2kAnalogIn` does.

**Read the frequency carefully.** A 10 kHz request comes back as
9979.2 Hz, and that is correct, not error. A cyclic buffer of 16384
samples at 750 kS/s repeats at 45.78 Hz, so the tone can only land on a
multiple of that: 218 × 750000/16384 = 9979.2 exactly. The buffer holds
218.45 cycles and the repeat snaps it to 218. It also confirms the DAC
clock is exactly 750 kS/s.

## 3. Does the configuration actually get written? — PASS

Was the least-tested thing in the project. `attr_updater`/`attr_sink`
needs a live context to construct, so none of these writes had ever
executed.

```
./iio_discover.py --uri ip:192.168.2.1 --device m2k-fabric
./iio_discover.py --uri ip:192.168.2.1 --device m2k-adc-trigger
```

- [x] `m2k-fabric` `gain` matches the input range the block was set to
- [x] changing the block's range and restarting changes it
- [x] `sampling_frequency` on `m2k-adc` reads back what was asked for
- [x] `powerdown` is cleared on the channels in use
- [x] `m2k-adc-trigger` `voltage0/trigger` matches the trigger edge chosen
- [x] `voltage4/mode` is `analog` when triggered, `always` when free running
- [x] `voltage6/logic_mode` is `a` for channel 1, `b` for channel 2

**The trigger works, and reading back the attributes is not how you
know.** A trigger that is silently free-running sets every attribute
correctly and delivers every sample. Three things separate them, and
all three were run against a 4989.6 Hz sine at 1.0 V, `high` range,
1 MS/s, 4096-sample buffers:

| check | free-running | triggered |
|---|---|---|
| spread of `buffer[0]` over 36 buffers | 1.8793 V | **0.0288 V** |

0.0288 V is one sample step at this slew rate (2*pi*4990 V/s x 1 us =
31 mV), so the alignment is as tight as the sample clock allows.

- **A level above the peak must stall.** +2.0 V against a 1.0 V peak
  produced zero samples in six seconds, and
  `Unable to refill buffer: Connection timed out (110)`. That warning
  is the trigger working. A capture that runs anyway means the trigger
  is not in the path.
- **`edge-falling` must fall.** At 0 V it starts at the same voltage
  rising does; only the slope tells them apart. Measured -0.0886 V over
  the first three samples.
- **The level is in volts the scope agrees with.** Asked +0.500 V above
  the 0 V case, got +0.5007 V — 0.14%. The decimation filter's
  correction belongs on the trigger level too: leave it out and this
  lands 9% off. (The shared ~15 mV zero offset appears in both cases and
  is the ADC's, not the trigger's.)

Also found: `set_len_tag_key("packet_len")` on a sink puts it in
tagged-burst mode against an untagged stream and it refuses with
`Input stream not tagged!`. The `Unable to refill buffer: Connection
timed out (110)` that came with it was downstream, not a second bug —
the ADC was waiting for a signal the failed sink never produced.

On a source it fails much later and much more quietly. `analog_source`
and the digital source both call it unconditionally, so every buffer
carries a `packet_len` tag that nothing in this repo reads. That is
inert right up until a downstream tagged-stream block keys on the same
string: in `m2k_ultrasonic_fsk.grc`, `tagged_stream_to_pdu` read the
source's 16384 where the flowgraph meant 8 and waited eleven minutes
per message. Over the air the transducers, the spectrum and the
demodulated eye all looked correct and no PDU ever came out. A
`tag_gate` with single key `packet_len` ahead of the receive chain is
what that flowgraph does about it;
`test_the_sources_buffer_tags_do_not_reach_the_pdu` holds the line.

**Fixed: `CONFIG_INTERVAL_MS = 1000` in `m2k_config.py`.** `attr_sink`
republishes on a timer, so for the first second of any flowgraph *no
setting was in force*. A short capture could finish before its own
configuration arrived. This produced a nonsense range comparison — 0.3
counts on one range against 72.3 on the other — until the test scripts
were changed to skip two seconds of samples. `m2k_config` now writes
each attribute directly with libiio at construction time, before
`start()`, and keeps the updater as a keep-alive. Verified by planting
`gain=low, powerdown=1`, asking for the high range, and capturing 4096
samples starting 100 ms in — one tenth of the interval. The planted
state was gone before `start()` and the capture read +635.19 counts,
the high-range value. The two-second skip is no longer needed.

**Benign but noisy:** `device_sink: Unable to push buffer: Device or
resource busy (16)` on every cyclic run. libiio permits exactly one
`iio_buffer_push` on a cyclic buffer; the hardware repeats it from then
on and further pushes return `-EBUSY`. Expected, but it reads like a
failure and should be explained or suppressed.

## 4. The volts number — RELATIVE PASSES, ABSOLUTE CLOSED IN SECTION 10

Method: hold W1 at a DC level, read it with a meter on 1+/1−, capture
counts, fit a line through three points. Requested 0.0 / 1.0 / 2.0 V,
meter 0.049 / 1.217 / 2.383 V, counts on ±25 V −10.95 / +57.05 / +125.43.
One further point on ±2.5 V at +1.0 V requested gave +737.13 counts.

- [x] switching range does not change the reading of the same input
- [x] the two ranges agree on their correction to 0.34%
- [ ] ±25 V range: reading matches the meter within a few percent
- [ ] ±2.5 V range: same

The third box was called the real test and it passes: the ranges agree
to 0.01%, and their ratio is 10.53 against a predicted 10.526. The scale
*is* being applied per range rather than by luck.

What failed was absolute accuracy, by 17.6%. Two separate causes:

**Most of it was a missing table, now fixed.** Reaching a rate below
100 MS/s means decimating, and the decimation filter does not have unity
gain. libm2k multiplies volts-per-count by a per-rate correction —
1.00 at 100 MS/s, 1.05, **1.10 at 1 MS/s**, 1.15, 1.20, 1.26 at 1 kS/s —
and `m2k_scale.py` did not have it. Applying it accounts for 10 of the
17.6 points.

**The rest is calibration, and is real.** The residual is a gain of
about 1.07, i.e. the ADC reads roughly 7% low. Section 10 measures it
per channel: x1.0674 on input 1, x1.0730 on input 2. The x1.0675 in the
table below was taken on channel 1, which is why it matches input 1
rather than splitting the difference. `m2k-adc voltage0` and
`voltage1` both carry `calibbias = 2048` and `calibscale = 1.000000`,
the driver's uncalibrated defaults — 2048 is the neutral value that
turns offset binary into signed, not an offset of 2048 counts. There is
also a fixed **−13.9 count** offset, the same on both ranges.

Measured constants, for checking a calibration routine against:

| | formula says | measured | correction |
| --- | --- | --- | --- |
| ADC ±25 V, 1 MS/s | 0.015977 V/count | 0.017114 | ×1.0711 |
| ADC ±2.5 V, 1 MS/s | 0.001518 V/count | 0.001620 | ×1.0675 |
| ADC offset | 0 | −13.9 counts | same on both ranges |

Note the board publishes factory constants as context attributes —
`cal,gain_pos_adc = 0.99906`, `cal,gain_neg_adc = 0.99581`, and five
more. They are all within 0.5% of unity, so they are a fine trim and do
**not** explain the 7%.

**How calibration will work** (decided 2026-09-01, not yet built): a
standalone `m2k_calibrate.py`, run once per session, not block init. It
seizes the whole front end via `m2k-fabric calibration_mode`
(`none adc_ref1 adc_ref2 adc_gnd dac`) and the `ad5625` calibration DAC,
it is a closed loop that `attr_sink` structurally cannot express, and
its result persists on the device — so repeating it per run is waste.
The blocks then *read* `calibscale`/`calibbias` and apply them, because
libm2k applies the gain in software (`getScalingFactor` multiplies by
`m_adc_calib_gain`) rather than the driver correcting the samples.

The `ad5625` publishes `scale = 0.292968750` mV/count, so raw 2048 is
exactly 600.0 mV and full scale is 1.2 V. That is a genuinely
independent chain for zero, linearity and range ratio — but not for
absolute traceability, because the path gain between `adc_ref1` and the
front end is unknown. A meter is still the only external reference.

## 5. Sample rate is really the rate — PASSES

- [x] a known tone reads back at the right frequency at 1 MS/s
- [x] and at 100 kS/s
- [x] `sampling_frequency` on `m2k-adc` reads back what was asked for

Writing `sampling_frequency` directly, from the list of six values the
hardware publishes, is right. The earlier version that computed it from
`oversampling_ratio` got the list wrong.

The 5% amplitude difference seen between 1 MS/s and 100 kS/s was
recorded here as unexplained. It is the filter correction from section
4: 1.15 / 1.10 = 1.045.

## 6. The generator — PASS, WITH A PER-CHANNEL OFFSET

- [x] the waveform is not inverted
- [x] Repeat forever keeps generating with the flowgraph idle
- [x] a 1.0 V amplitude request measures ~1.0 V on a meter
- [x] W2 works and is independent of W1

The amplitude box failed first: the meter fit gave

```
actual = 1.1670 x requested + 0.0493 V
```

16.7% high. That is the generator's own filter correction, which
`M2kAnalogOut::getScalingFactor` divides by and we did not have. At
750 kS/s — the loopback's rate — libm2k's table says **1.164153**. The
meter said 1.1670. Fixed in `m2k_scale.DAC_FILTER_COMP`.

The DAC's table is not a smooth roll-off and cannot be guessed:
1.00, 1.525879, **1.164153**, 1.776357, 1.355253, 1.033976, from
75 MS/s down to 750 S/s.

The remaining offset is calibration, like the ADC's — and it is
**per channel**, which W2 is what showed.

**W2 works, and the offsets do not match.** W1 to input 1, W2 to
input 2, both `high` range at 1 MS/s, three cases: `W1 +1.0 / W2 -0.5`,
the same swapped, and `W1 0.0 / W2 held`. The swap is the part that
matters — two outputs that both work but land on the wrong inputs pass
a single case and fail this one.

| path | gain | offset |
|---|---|---|
| W1 to input 1 | 0.9401 | **+25 mV** |
| W2 to input 2 | 0.9335 | **+169 mV** |

Gains agree to 0.7% here, which read at the time as one shared error.
Section 10 shows it is not: metering each generator separately puts both
DAC gains at unity and leaves the two ADC gains 0.52% apart, which is
per channel. The composite numbers below are right; the attribution was
not. The offsets are 6.8x apart. On the +/-2.5 V range 169 mV
is 6.8% of full scale, which is not a trim — it is the thing
`calibbias` exists for, and it has to be measured per channel rather
than derived once and applied everywhere.

These are composite DAC-times-ADC figures. Splitting them needs the
meter on each output, which is section 10.

Independence is clean: moving W1 by -939.5 mV moved channel 2 by
-1.1 mV.

**Why the loopback said everything was fine.** It read 1.0010 V for a
1.0 V request. The generator was 16.7% high, the scope 15.4% low, and
the product is 0.9905 against 0.988 measured. Two errors that cancel
look exactly like no error. This is the argument for the meter, and it
is worth showing rather than asserting.

## 7. Digital — PASSES

Wire **DIO0 to DIO1** and **DIO0 to 1+**, with **1- to ground**. The
scope leg is what makes the digital result trustworthy: it reads the
same pin in volts, on a clock section 5 already verified.

Use the **`'low'`** range for the scope. 3.3 V logic clips flat on
`'high'`, which is the +/-2.5 V one.

- [x] Digital Sink drives DIO0, confirmed with a meter or an LED
- [x] Digital Source reads a pin driven externally
- [x] `m2k-logic-analyzer` `direction` reads `in`/`out` to match the block
- [x] a rate from the dropdown is accepted

**A loopback needed the two blocks to claim different pins before it
could exist.** `pins_for` counted from DIO0 upward and took no offset, so
a sink and a source in one flowgraph always claimed the same pins and
fought over `direction` -- whichever was built last won and the other
silently did nothing. Each block now takes its own pin list, and the sink
at `pins=[0]` with the source at `pins=[1]` share nothing. `direction`
afterwards read `out` on DIO0, `in` on DIO1, and `in` on the untouched
DIO2.

**The pin drives a real 3.3 V.** A 16384-sample square at 1 MS/s --
61.04 Hz, one buffer per cycle -- measured on the scope:

| | measured | corrected |
|---|---|---|
| swing | 3.1100 V | **3.33 V** at the known -6.5% |
| high | 2.9028 V | |
| low | **-0.2073 V** | |
| duty | 49.9% | |
| period | 16384.0 samples | 61.04 Hz, exact |

The low rail is the interesting number. Input 1's offset is -21.4 mV on
the `'high'` range, and -0.2073 V is 9.7x that -- near enough the 10x
between the ranges to say the offset is a fixed *count* error that
scales with range, which is what `calibbias` being a raw attribute
predicts. Worth confirming deliberately when `m2k_calibrate.py` gets
written.

Reading DIO1 back through the Digital Source gave values `{0, 1}`, duty
49.9%, and a period of exactly 16384 samples.

**All six dropdown rates are real.** Not read back -- measured. Each
drove a 1024-sample square, whose frequency is rate/1024, timed against
the scope:

| requested | expected | measured | error |
|---|---|---|---|
| 100 MS/s | 97656.25 Hz | 97796.89 Hz | +0.14% |
| 10 MS/s | 9765.62 Hz | 9765.63 Hz | +0.00% |
| 1 MS/s | 976.56 Hz | 976.56 Hz | -0.00% |
| 100 kS/s | 97.66 Hz | 97.66 Hz | +0.00% |
| 10 kS/s | 9.77 Hz | 9.77 Hz | +0.00% |
| 1 kS/s | 0.98 Hz | 0.98 Hz | +0.00% |

The 100 MS/s error is edge quantisation -- the scope had 102 samples per
period -- not a rate error. `DIGITAL_SAMPLE_RATES` is now measured
rather than assumed.

**`-tx` and `-rx` hold separate `sampling_frequency` attributes.** Every
run above left `m2k-logic-analyzer-rx` at 1 MS/s while `-tx` followed
the request. That is correct -- two devices, each block writes its own
-- but a Sink and a Source given different rates in one flowgraph will
disagree about time and neither will complain.

## 8. Digital idle level and trigger — PASSES

Same jumpers as section 7: `DIO0 -> DIO1`, `DIO0 -> 1+`, `1- -> GND`.

- [x] the idle level really drives the pin
- [x] "leave as found" really leaves it
- [x] a trigger that cannot fire stalls the capture
- [x] the trigger lands the buffer on the edge

### The idle level

An output pin has two sources of truth. The stream drives it while the
flowgraph runs; `raw` on `m2k-logic-analyzer` drives it the rest of the
time. Constructing a sink and never starting it is therefore a static
output — Scopy's Digital IO, with no flowgraph running at all.

Measured on input 1, `high` range, no flowgraph started:

| `idle_level` | `raw` reads | DIO0 measures |
| --- | --- | --- |
| `high` | 1 | **+2.8387 V** |
| `low` | 0 | **-0.0212 V** |
| `leave` | 1, unchanged | +2.8387 V |

The `leave` row is the one that proves the point: it ran straight after a
`high`, wrote nothing, and the pin stayed high. So "leave as found" is
genuinely a no-write, and the resting level of a board nobody has
configured is whatever the last program left behind.

**This is the opposite of the analog generator.** Section 6 records the
DAC holding its last cyclic buffer with the flowgraph stopped. The DIO
pins do not hold theirs — they snap back to `raw` the moment you stop.

### The trigger is real

A trigger you cannot satisfy must hang, or it is not a trigger. Sink
drives DIO0, source reads DIO1, six seconds each:

| DIO0 driven | trigger | result |
| --- | --- | --- |
| low | `level-high` on DIO1 | **STALLED — no samples in 6 s** |
| low | `level-low` on DIO1 | 512 samples |
| high | `level-high` on DIO1 | 512 samples |
| square | off | 512 samples, all zeros |

The last row is worth reading twice. Free-running fills its buffer
immediately at start, before the generator has begun playing, so it
captures the idle level and never sees the square at all. Triggered, it
waits. That contrast is the clearest evidence the trigger works.

### The buffer lands on the edge

200-sample square at 1 MS/s, so a transition every 100 samples:

| trigger | `buffer[0]` | first transition |
| --- | --- | --- |
| `edge-rising` | 1 | sample 100 |
| `edge-falling` | 0 | sample 100 |

Exact, and identical across every repeat.

### Trigger delay: negative is exact, positive is not

`trigger_delay` in samples, same square, `edge-rising`:

| requested | first transition | repeats |
| --- | --- | --- |
| 0 | 100 | 100, 100, 100 — **exact** |
| -50 | 50 | 50, 50, 50 — **exact** |
| -100 | 100 | pre-trigger, `buffer[0]` = 0 |
| +20 | 90 | 80, 60, 60 — **jitters** |
| +40 | 70 | 80, 80, 80 |

Negative delay is real pre-trigger and is repeatable to the sample.
Positive delay moves the buffer the right way but lands tens of samples
off, differently each run. The attribute reads back exactly what was
written in every case, so this is the hardware and not a lost write. Not
explained; treat positive delay as approximate.

## 9. Several pins at once, and a bus on them — PASSES

Everything up to here moved one pin. A bus needs three moving together
and staying together, which is a different question.

Wire three jumpers:

```
DIO0 -> DIO4      SCLK
DIO1 -> DIO5      MOSI
DIO2 -> DIO6      CS
```

### 9a. Are the ports even coherent?

Before decoding anything, check that ports captured together belong to
the same instant. Send four patterns of period 2, 4, 8 and 16 out on
DIO0-3, read DIO4-7 back, and look for ONE rotation of the 16-sample
word that fits all of them. If each pin needs a different rotation, the
ports have slipped past each other and any bus decoded off them is
fiction.

This is the check that failed first, and it failed for a real reason —
see the sink note above. After the fix:

```
cyclic       4/4 runs coherent
non-cyclic   2/4 runs coherent
```

Two rotations fit rather than one, because the three wired pins do not
differ in DIO3's period-16 pattern and DIO3 is unwired. That is the test
being loose, not the hardware.

Use a big transmit buffer. At 1 MS/s a 512-sample buffer is 1953 refills
a second over the network, and a dropped one looks exactly like skew.

**Non-cyclic is not reliable at 1 MS/s.** It underruns. When it does,
all three pins break at the same sample — they gap together rather than
drift apart — so the failure is honest, but half the runs lose samples.
Use cyclic for anything timed.

### 9b. A real SPI frame

Mode 0, bit-banged: MOSI settles while SCLK is low, the receiver samples
on the rising edge, CS frames the byte. At 1 MS/s with 8 samples per
half-clock that is a 62.5 kHz bus. One frame is 256 samples:

```
lead-in   64   CS high, clock idle low
setup      8   CS low, MOSI on bit 7, no clock yet
8 clocks 128   16 samples each: low half, high half
tail       8   CS still low
post      48   CS back high
```

Push it as one cyclic buffer, and trigger the capture on **CS falling**
on DIO6 so every capture starts at a frame boundary. Decode by sampling
MOSI on each SCLK rising edge between a CS fall and the next CS rise.

Results:

```
0xA5                       first try, no adjustment
8 edge-case bytes          0x00 0xFF 0x01 0x80 0xAA 0x55 0x0F 0xF0
all 256 byte values        one 65536-sample capture, 3/3 repeats,
                           768 frames, zero errors
```

That last run is the one worth quoting: every byte a byte can be, sent
and recovered, three times over.

### What this says about the workshop

One bit per sample per port is a workable way to teach a bus. It is
verbose — 256 samples to move 8 bits — but the frame is written as plain
Python lists in the flowgraph's variables, which is exactly the kind of
thing a participant can change and immediately see.

The flowgraph is `flowgraphs/m2k_spi_loopback_continuous.grc`.

## 10. Splitting the composite, per channel — PASSES

Every figure up to here is a composite: a generator and an input in
series, and a product cannot say which factor is wrong. Two metered
points on each signal path separates them.

Wire one path at a time, meter in parallel with the input:

```
W2 -> 2+, 2- -> GND, meter across W2 and GND     --output w2
W1 -> 1+, 1- -> GND, meter across W1 and GND     --output w1
```

Then, per path, capture at a requested 0.0 V and 1.0 V and read the
meter at each:

```
python3 bench/dc_point.py 0.0 --output w2
python3 bench/dc_point.py 1.0 --output w2
```

Conditions have to match the data this joins: generator 750 kS/s
(`DAC_FILTER_COMP` 1.164153), scope 1 MS/s (1.10), both inputs `'high'`,
which is the +/-2.5 V range. The generator holds its last cyclic buffer
after the graph stops, so the meter reading never races the capture.

- [x] each generator's own gain and offset, against a meter
- [x] each input's own gain and offset
- [x] the composite reconstructs the section 6 fit

| | gain | offset | counts | correction |
|---|---|---|---|---|
| W1 | **1.00250** | +48.5 mV | — | offset only |
| W2 | **0.99990** | +112.1 mV | — | offset only |
| input 1 | 0.93686 | -20.9 mV | -13.8 | x1.0674 |
| input 2 | 0.93199 | +61.9 mV | +40.8 | x1.0730 |

**The generators need no gain correction.** Both land within 0.25% of
unity once `DAC_FILTER_COMP` is applied, so the whole ~6.5% belongs to
the ADC. What the DAC needs is an offset trim, and the two differ 2.3x.

**The ADC needs gain per channel, not once.** 0.93686 against 0.93199 is
0.52% apart. The meter reads to about 1 mV at the top of the range, so
each gain is good to ~0.1% and the difference is roughly 4x that. This
is the finding that corrects section 6.

**Everything cross-checks.** The composite implied for W1 to input 1 is
gain 0.93920 / offset +24.5 mV against section 6's independent fit of
0.9401 / +25 mV. W2's zero metered 112.1 mV against 114.5 mV a session
earlier, W1's 48.5 against 49.4. Both ADC offsets arrived twice by
different routes -- solved from the two-point fit, and read straight off
a disconnected input -- agreeing to 0.2 and 0.3 mV. Input 1's -13.8
counts is a third independent arrival at section 4's -13.9.

**A disconnected input does not look disconnected.** Metering W1 with
the old jumper still feeding `2+`, input 1 read a clean and stable -13.9
counts through a full-volt sweep. That is a real number -- its own
offset, and one section 4 had correctly measured -- so nothing looked
wrong. The tell was arithmetic: W1 metered +48.5 mV while input 1
reported as though its input were at zero. Sweep the source and watch
for no response; a dead wire and a real reading are otherwise identical.

**What is still open.** `calibbias`'s sign convention around its 2048
neutral is not established, and `m2k_calibrate.py` must not write until
it is checked against libm2k's `calibrateADC()`.

## 11. The decoder in the flowgraph — PASSES

Section 9 proved the bus. It decoded the capture *offline*, in
`bench/spi_loopback.py`, after the run finished. `M2K SPI Decode` does
the same arithmetic inside the running flowgraph, and that is a
different claim: it has to hold its state across `work()` calls that
land wherever the scheduler puts them, and it has to keep up.

It does, at half = 4, 8 and 16 — 62.5 kHz down to 31.25 kHz and up to
125 kHz, ~6 M samples captured per run, `M2K` repeating with no
underruns. `python3 bench/spi_flowgraph.py` is the headless version:
same three blocks, a collector standing in for Message Debug.

```
source gr-m2k/env.sh
gnuradio-companion flowgraphs/m2k_spi_loopback_continuous.grc
```

Three jumpers, DIO0-2 to DIO4-6. `bench/dio_continuity.py` walks a single
1 across the driven pins and prints the 3x3 table, if a jumper is in
doubt. What to look for:

- Message Debug prints `M2K` over and over, and nothing else.
- Type into the `SPI message` box and press Enter. The printed string
  changes without a restart, and the three vector sources stay the same
  length -- `spi_capacity` fixes the frame, and a short message pads with
  idle. A message longer than `spi_capacity` is cut, not wrapped.
- Watch for a length mismatch after a live change: GRC recomputes the
  variables in dependency order, so `spi_pad` is fresh before the three
  waveforms use it. If that ever stopped being true the symptom would be
  three vector sources of different lengths, which shifts the bus.
- Change `half` to 4 and then 16. The bus speed changes, the frame
  length follows it, and the string still comes back. This is the part
  the old flowgraph could not do -- `frame` was hard-coded at 256, so
  any other `half` silently mismatched the buffer.
- Nothing prints between the flowgraph starting and the first CS falling
  edge. A byte appearing before the first frame boundary would mean the
  decoder is emitting from a partial frame, which is exactly the failure
  the arming rule exists to prevent.

The thing to watch for is not wrong bytes. It is the flowgraph falling
behind: Python decodes 1 MS/s in about 4% of real time when the samples
are a list, but twenty times slower if anything hands it a numpy array
element by element. If the source starts reporting underruns, that is
where to look first.

### What this section found: CS framed per byte prints rotations

The first run failed, and the way it failed is worth keeping.

Every byte was correct. `M2K` was there, `2KM` was there, `KM2` was
there. The diagnostic counted 1978 chunks, 5958 bytes, **zero bytes that
were not in the message** — chunk sizes `{3: 1975, 6: 2, 21: 1}`, chunk
starts `M 689 / 2 649 / K 640`. Uniform. That is not corruption; that is
a fair coin deciding where each capture begins.

The cause is the two halves of the design meeting. The M2K's non-cyclic
digital capture is **gapped between buffers** — it fills one, hands it
over, and re-arms. A triggered source re-arms on the trigger, so every
buffer starts at a CS falling edge. The frame, at that point, put a CS
falling edge in front of *every byte*. So each buffer began on an
arbitrary byte of the message, and the decoder — correctly — reported
what it was handed. Section 9 never saw it because it captured a single
buffer and stopped.

The fix is the waveform, not the code: hold CS low across the whole
message, so one frame is one transaction and the only falling edge in
the frame is the message start. That is also what real SPI does, so the
fix costs nothing pedagogically. `SpiDecoder` needed no change — it
already abandons a part-built word at CS release and clocks straight
through a multi-byte window.

`tests/test_spi_decode.py::test_the_frame_asserts_chip_select_exactly_once`
now pins it. It is the only test that would have caught this without a
board, and it did not exist until the board found it.

## 12. Send on demand, non-cyclic — PASSES

Section 11 settled the decoder against a buffer the hardware repeats
forever. `flowgraphs/m2k_spi_loopback.grc` asks a different question:
can the sink *stream*, so a message goes out once when somebody presses
Enter and the bus rests in between?

**2026-09-04: it can.** Twenty sends with varying text, one print per
press, no rotations, nothing dropped, no timeout. So at 100 kS/s:

- **non-cyclic digital output holds** across repeated sends, and frame
  alignment keeps every frame off the DMA buffer seam;
- **a free-running capture is not gapped between rx buffers** the way
  the triggered one in section 11 is. That was the open question, and
  the answer is that the gap belongs to the trigger re-arming, not to
  the buffers.

The message also comes back readable:

```
((text . M2K))
pdu length =          3 bytes
pdu vector contents =
0000: 4d 32 4b
```

`m2k_spi_decode` puts the bytes in the metadata as text as well, which
is the check a participant can make at a glance.

### Why the source is not triggered

The first run of this flowgraph decoded one message and then printed:

```
device_source :warning: Unable to refill buffer: Connection timed out (110)
```

**That warning is fatal.** gr-iio's `device_source::work()` returns
`-1` — `WORK_DONE` — on *any* refill error, so the block ends
permanently. An armed trigger waiting for the next message will always
time out eventually: the wait is however long it takes a person to
type. `set_timeout_ms` is not a way out; in 3.10 it stores the value
and never hands it to libiio.

Free-running the source and letting CS frame the stream in software is
what the decoder's arming rule was written for. The QT time sink
triggers the display instead — normal mode, negative slope, CS channel.
The continuous flowgraph keeps its hardware trigger, which it needs and
which section 11 verified.

If a `Connection timed out (110)` appears again, something is arming a
trigger. Check `trigger_pin` is `off` on the Source, and note that pin
triggers are board state that outlives the program: a previous run can
leave one set. `_apply_trigger` writes `none` to every pin it reads, so
simply running this flowgraph clears them.

### Running it

```
source gr-m2k/env.sh
gnuradio-companion flowgraphs/m2k_spi_loopback.grc
```

Three jumpers, DIO0-2 to DIO4-6 — the same wiring as section 11.

- Message Debug prints `M2K` once at startup — the edit box emits its
  default value on `start()` — and then stays silent.
- **Press Enter, do not click away.** The box is wired to
  `returnPressed`, deliberately, so losing focus sends nothing.
- One print per press. A second print means something is repeating.
- Key to print should be under about a third of a second: up to one
  buffer waiting for the alignment boundary (16384 / 100000 = 164 ms)
  plus one buffer of capture.
- A long message — `ADALM2000 at GRCon26` — and a single character both
  come back whole. The only constraint is `buffer_len` ≥
  `128 + 16*half*bytes`, which at half = 8 is 127 bytes.
- CS falls **once** per message on the MOSI trace, whatever its length.

If a message ever comes back corrupted, the order to try things in is:
raise `buffer_len` (32768) — that is the output seam and the capture
seam at once — then drop `samp_rate` to 50 kS/s, then set `half = 16`.
Capture a run with `bench/spi_flowgraph.py` before changing more.

### Still to find

**How fast this goes.** 100 kS/s is a tenth of what the continuous
flowgraph uses, chosen because non-cyclic output underran 2 of 4 runs
at 1 MS/s in section 9. Raise `samp_rate` one step at a time and record
where it stops holding. That number is the answer to "how fast can a
GNU Radio flowgraph drive this bus on demand," which nothing in the
repo currently knows.

## 13. An independent decoder — PASSES (no board needed)

Every SPI test before this one sends through `SpiEncoder` and reads back
with `SpiDecoder`. They all pass, and they prove the two halves agree
with each other. They cannot prove either agrees with SPI: both were
written from the same three sentences about mode 0, and a shared
misreading — LSB first, sampling the falling edge, CS moving a half
clock early — round-trips perfectly and is still wrong on a real bus.

So the waveform goes to libsigrokdecode's `spi` decoder, the one
PulseView uses, written by people who have never seen this repo.
`tests/test_spi_sigrok.py` writes the three lines to a CSV and shells
out to `sigrok-cli`:

```
sudo apt install sigrok-cli
pytest tests/test_spi_sigrok.py -q
```

23 tests, all passing against sigrok-cli 0.7.2 / libsigrokdecode 0.5.2.
They skip cleanly where it is not installed. Nothing here touches the
board — `SpiEncoder` imports nothing, so this runs anywhere.

**What it reads.** `M2K` comes back `4D 32 4B`, and so does all 256
bytes in one transaction, four bus speeds (`half` 2/4/8/16), an
active-high chip select, 12- and 16-bit words, and a frame with 4096
idle samples either side — which also says our idle levels really are
idle, since sigrok finds no bytes in them.

**Both decoders on the same samples.** Six frames built with every half
clock a different random length — something our encoder never emits —
and ours and sigrok's read the same words. A decoder quietly counting
samples instead of watching edges fails this; ours does not.

**The negative control.** A harness that cannot fail has not checked
anything, so four runs deliberately tell sigrok the wrong thing, and
each one has to return something other than `4D 32 4B`:

| told | reads |
| --- | --- |
| `bitorder=lsb-first` | `B2 4C D2` |
| `cpha=1` | `9A 64 96` |
| `cpol=1` | `9A 64 96` |
| `cs_polarity=active-high` | nothing |

An unknown option name exits 1 and decodes nothing, which would
otherwise look like a quiet bus, so the harness asserts on the exit
code rather than on empty output.

### Still to find

This checks the encoder, not the board. `bench/spi_flowgraph.py` now
takes `--csv PATH` and writes what the M2K actually captured in the
same format, so the hardware half is the same command against a real
capture. Needs DIO0-2 wired to DIO4-6.

---

## 14. Chop and sample on one clock — PASSES

The colorimeter's whole argument is that an FFT bin *is* a lock-in
output. That is only true if the LED chop and the ADC sampling come from
the same clock, and the two sit on different sides of the M2K -- the
pattern generator runs off the fabric clock, the ADC off its own divider
from 100 MS/s. Nothing in a block diagram settles it.

```
python3 bench/colorimeter.py coherence
```

Three square waves at 205, 246 and 287 cycles per 4096-sample cyclic
buffer, played at 100 kS/s and captured at 100 kS/s. One contiguous
32768-sample capture, split into eight blocks, tracking the phase of
each color's bin from block to block.

- [x] every tone peaks at exactly the bin it was generated for
- [x] phase is constant across all eight blocks
- [x] drift below 0.02 ppm on all six color/channel pairs

Measured 2026-09-15, analog 1 (analog 2 identical):

```
  red   bin 205 ( 5004.9 Hz)  peak at 205  leak  1.6%  drift -0.0 ppm
  green bin 246 ( 6005.9 Hz)  peak at 246  leak  0.0%  drift +0.0 ppm
  blue  bin 287 ( 7006.8 Hz)  peak at 287  leak  0.0%  drift +0.0 ppm
```

A drift that prints as exactly zero is worth distrusting, so the raw
per-block phases were dumped as well: stable to about 2e-4 radians over
the 0.33 s capture, with bin magnitudes of 307-434 (roughly 70 dB of
bin SNR) and slopes between -1.4e-05 and +2.0e-05 rad/block. That is a
drift between -0.011 and +0.011 ppm. These are not two clocks that
happen to agree; it is one clock.

Red's 1.6% is not noise -- the bin's SNR is around 70 dB. Roughly a
third of it is the generator: 4096/205 is not an integer, so the square
wave's edges land a sample early or late and put a 5% spur at bins 201
and 209. It is four bins away from anything that gets read, and it is
identical on both channels, so it divides out of a transmittance ratio.

**The trap in this section is not electrical.** The first three attempts
segfaulted in a worker thread several seconds after start, with an
`AttributeError: 'str' object has no attribute 'history'` from inside
gr's own `gateway.py`. The cause: the script built the digital sink into
a local variable. A `top_block` keeps its blocks alive on the C++ side
only, and `digital_sink` wraps a *Python* block -- so the last Python
reference went away at the end of the function and the scheduler kept
calling into a half-collected object. GRC-generated code never hits this
because every block is stored on the flowgraph object. Hand-written
scripts must hold their own references.

## 15. Promote what passes

Each entry in `iio_overlays.py` carries a `check` field describing how to
confirm it. 58 of 74 are still `UNVERIFIED`. As they check out, change
`confidence` to `MEASURED`, and `./iio_explain.py fixtures/m2k-real.json
--unknown` will show the count moving.

Worth re-capturing at the end, so the fixture reflects a board whose
settings you understand:

```
./iio_discover.py --uri ip:192.168.2.1 --json > fixtures/m2k-real.json
```

---

## Things known to be assumptions

| assumption | status |
| --- | --- |
| `volts_per_count` from libm2k | **measured** — right to 7%, the rest is calibscale |
| the filter corrections | **measured** — DAC's confirmed to 0.25% |
| DAC `vlsb` = 10/4095 | **measured** — right, once the filter term is in |
| the sign inversion on the DAC | **measured** — real, and correctly applied |
| `attr_updater`/`attr_sink` applies config | **measured** — yes, after a 1 s delay |
| `calib_gain` and `calibbias` are 1.0 and 0 | **wrong** — the post-calibration case, not the fresh-board one |
| digital sample rates | **measured** — all six, timed against the scope |
| the digital trigger fires | **measured** — an impossible condition stalls |
| digital `trigger_delay` in samples | **measured** — exact at 0 and below, approximate above |
| `oversampling_ratio` is decimation | only in the overlay text now, not in code |
| gr-iio can drive several DIO pins | **wrong** — one pin only, silently; see `docs/gr-iio-multipin-sink.md` |
| three pins stay sample-aligned | **measured** — cyclic 4/4; non-cyclic underruns at 1 MS/s, 2/4 |
| `raw` reads an input pin | **measured** — Digital IO works both directions, no flowgraph |
| the decoder keeps up in the flowgraph | **measured** — three bus speeds, ~6 M samples each, no rotation |
| non-cyclic digital output joins its buffers seamlessly | **not needed** — aligned frames never cross a seam; 20/20 sends whole at 100 kS/s |
| an untriggered digital capture is gapped between rx buffers | **no** — 20 sends, no tear; the gap in section 11 is the trigger re-arming |
| a gr-iio source survives a refill timeout | **wrong** — `work()` returns WORK_DONE on any refill error, and the block is done |

---

## Scripts

The hardware runs in sections 9, 10 and 11 are reproducible:

```
source gr-m2k/env.sh
python3 bench/digital_coherence.py cyclic       # 9a
python3 bench/spi_loopback.py 0xA5              # 9b
python3 bench/spi_loopback.py $(seq 0 255)      # every byte
python3 bench/spi_flowgraph.py                  # 11, headless, three speeds
gnuradio-companion flowgraphs/m2k_spi_loopback_continuous.grc  # 11
gnuradio-companion flowgraphs/m2k_spi_loopback.grc             # 12
python3 bench/dc_point.py 0.0 --output w1       # 10, one point
python3 bench/dc_point.py 1.0 --output w1 --meter 1.051
python3 bench/spi_flowgraph.py M2K 8 --csv /tmp/bus.csv     # 13, on hardware
python3 bench/colorimeter.py coherence          # 14, needs the colorimeter board
```

Both want a gnuradio interpreter. The project `.venv` does not have one,
so run them with the system python that does.
