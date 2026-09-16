---
name: "#grcon26-workshop"
dateModified: 2026-09-11
---
# Superseded Decisions

- **2026-09-01** — The filter corrections are arithmetic, not calibration, and live in
  `m2k_scale.py`. Reason: fixed property of the converters, same on every board.
  Rotated 2026-09-11, settled -- the arithmetic is in `m2k_scale.py` and tested.

- **2026-09-04** — Ultrasonic reuses ECE448's `fsk_project.grc` (AFSK, 200 baud,
  600 Hz deviation) retuned to 40 kHz. Reason: already end to end; only the endpoints
  and the rates change, which is itself the lesson.
  Rotated 2026-09-11, executed -- the port is benched and the tuning is now the
  2026-09-09 f0 entry.

- **2026-09-06** — The deck is ECE444's frame view, ported standalone into `slides/`.
  Reason: one document serves the projector, the participant's notes and the printed
  handout, and nothing in it can be lost by presenting it. No book, no generator: one
  HTML file and three assets, published to Pages by a workflow.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.

- **2026-09-06** — Slides are written for the demos that run, with the two that do not
  as labelled placeholders. Reason: the SPI half is bench-verified end to end and
  gating the whole deck on the ultrasonic link would leave nothing written this month.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.

- **2026-09-08** — The deck's prose follows ECE444's `VOICE.md`, and
  `check_deck.py` gates the unambiguous rules. Reason: it is a calibration set
  built from Neil's own review corrections, not a style opinion, and the deck
  was written without reading it -- it broke rules 1, 2, 3 and 9 throughout.
  Figures now carry a key only; explanation moved to the caption and bullets.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.

- **2026-09-07** — Present blocks are bullets and pictures, never paragraphs.
  Reason: Neil talks to and about the slide rather than reading it, and a
  paragraph on screen is one the room reads instead of listening. Running prose
  moves to `.depth`, which is the notes and the printed handout. Documented in
  `slides/README.md`.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.

- **2026-09-07** — The SPI waveforms are rendered from `SpiEncoder` by
  `slides/render_spi.py`, the same way the blocks come from GRC. Reason: the
  three SPI concept frames had no picture at all, and a drawing of mode 0 is a
  claim about mode 0 rather than the thing the board actually puts on the pins.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.

- **2026-09-06** — Block and flowgraph figures are rendered from GRC's own canvas
  code, not drawn and not screenshotted by hand. Reason: a drawing is a second copy
  of the flowgraph that drifts on the next parameter change, and it teaches
  recognising a picture rather than the canvas participants will sit in front of.
  The hand-drawn schematic is kept for the one thing GRC cannot draw: the three
  jumper wires that close the loop outside the software.
  Rotated 2026-09-11, settled — the deck is built to this and `check_deck.py` gates it.


- **2026-09-04** — One SPI frame is one whole transaction, CS asserted once across all
  bytes. Reason: the capture re-arms per buffer, so per-byte CS framing starts each
  buffer on a random byte -- and one assertion is what real SPI does anyway. Rotated 2026-09-09, settled — built and verified; bench checklist section 9
  runs all 256 byte values with zero errors.

- **2026-09-04** — Digital blocks take a pin list plus an optional name per line, not a
  count and an offset. Reason: a bus is not always contiguous, and a name only has to
  make an error legible — GRC will not evaluate a port label. Rotated 2026-09-09, settled — shipped in the two generated ymls.

- **2026-09-04** — SPI sends on demand through a new `m2k_spi_encode` block; the cyclic
  version is kept as `m2k_spi_loopback_continuous.grc`. Reason: a cyclic buffer is
  repeated by the hardware and nothing downstream can gate it. Rotated 2026-09-09, settled — bench checklist section 12, 20 clean sends at
  100 kS/s.

- **2026-09-04** — The decoded PDU carries the bytes as text in its metadata,
  not as the payload. Reason: the loopback's own proof, the way Scopy shows a text
  column, while the payload stays what was on the wire. Rotated 2026-09-09, settled — shipped in `spi_decode.py`.

- **2026-09-04** — SPI mode 0 is checked against libsigrokdecode, not only against
  our own decoder. Reason: encoder and decoder were written from the same sentences, so
  a shared misreading round-trips clean and is still wrong on a real bus. Rotated 2026-09-09, settled — bench checklist section 13 passes, off the board.

- **2026-09-04** — `m2k_spi_encode` aligns frames to the sink's buffer size. Reason: a
  non-cyclic sink's DMA buffers need not join seamlessly, and the encoder's sample
  count is the sink's position in its buffer. Rotated 2026-09-04: not reversed, said in
  full by the Traps bullet that names the "Align frames to" parameter. Section 12 of the
  bench checklist has the measurement, 20/20 sends whole at 100 kS/s.

- **2026-09-02** — Blocks are named on the analog/digital axis, not by
  instrument. Reason: the four cover nine Scopy instruments between them. Rotated
  2026-09-04, settled — the six blocks are built and named. The same entry's
  "no supply block" half was reversed the same day; see below.

- **Rotated 2026-09-04 (trap)** — GRC will not template a port label. `dtype`,
  `vlen`, `multiplicity` and `hidden` are evaluated; `label` is set once. Naming a
  line changes error text, not the canvas. Out of the hot note because the ymls it
  applies to are written and generated.

- **Rotated from Traps 2026-09-04** — **`'low'` is the WIDE +/-25 V range, `'high'` is
  +/-2.5 V.** The name is the amplifier gain, not the volts, and it is backwards from
  every guess. Still true; rotated because `gr-m2k/README.md` and checklist section 4
  both carry it now and Traps was at its budget.

- **2026-09-04 (rotated trap)** — *A disconnected input reads as a clean, stable,
  plausible number* — its own offset. Input 1 sat at -13.9 counts through a full-volt
  swing on a generator wired to the wrong socket, three runs, and -13.9 was a genuinely
  correct prior measurement. Only sweeping the source and watching for *no* response
  tells a dead wire from a real reading. Rotated out because analog bring-up is closed
  and calibrated; the evidence is in `docs/bench-checklist.md` section 10 and
  `bench/dc_point.py`.

**Rotated 2026-09-04 from Traps, because the code already carries it.** `calibbias` is
storage; `calibscale` is not. Write `calibbias`, read it back, and it holds the value
while changing nothing in the samples -- the ADC's offset trim is really `ad5625`
channels 2 and 3. `calibscale` is the opposite: the driver applies it before you see the
sample, so a block that reads it back and multiplies again is wrong by exactly that
factor. Both are spelled out at the top of `gr-m2k/m2k_calibrate.py` and in
`m2k_scale.volts_per_count()`.

- **2026-09-02 — `first_pin`, superseded 2026-09-04.** Both digital blocks took a pin
  count and a first pin, giving a sink and a source disjoint contiguous ranges. Replaced
  by a per-line pin list: the range was never the real constraint, only "no shared pin"
  was, and a contiguous range cannot describe a bus wired where the jumpers reached.

**Rotated 2026-09-04 — closed, the code shipped and is hardware-verified.** The three
decisions that shaped the digital blocks. Their live consequences are carried by the
Traps section, the block docstrings and `docs/gr-iio-multipin-sink.md`; the reasoning
is here.

- **2026-09-02** — Both digital blocks take `first_pin`, and a sink and source in one
  flowgraph get disjoint ranges. Reason: `pins_for` counted from DIO0 only, so any pair
  fought over `direction` and the loser did nothing silently.
- **2026-09-02** — `digital_sink` defaults `idle_level` to `'low'` rather than leaving
  `raw` alone. Reason: the resting level was otherwise leftover state from whatever
  last touched the board.
- **2026-09-02** — `digital_sink` packs the 16-bit output word itself with pylibiio
  instead of using `iio.device_sink`. Reason: device_sink can only drive one pin;
  patching gr-iio upstream is deferred.

**Rotated 2026-09-04 — reversed.** "Blocks are named on the analog/digital axis, not
by instrument, and the supply (`ad5627`) gets no block for now. Reason: the four cover
nine Scopy instruments between them; nothing planned needs the supply." The naming half
stands and stays in the hot note; the supply half is reversed by the 2026-09-04
decision to build a supply block. The 2026-09-03 rotation above, which recorded the
supply as "deferred and unneeded", is superseded on the same point.

**Rotated 2026-09-04 — closed, calibration is done and meter-verified.** Four decisions
that shaped `m2k_calibrate.py`. The script exists, `--apply` has run against the board,
and the live constraints they imply are now carried by the Traps section and by the code
itself. Kept here because the reasoning explains why the script is shaped as it is.

- **2026-09-03** — `m2k_calibrate.py` trims DAC offset only, and ADC gain *and* offset,
  both per channel. Reason: two-point meter runs put both DAC gains within 0.25% of
  unity while the two ADC gains differ 0.52%.
- **2026-09-03** — Calibration lands on the `ad5625` trim DAC and `m2k-adc calibscale`;
  blocks apply neither. Reason: `calibbias` is inert and the driver applies `calibscale`
  itself, so a block re-applying it double-counts the gain. (The live half is the
  `calibbias`/`calibscale` trap.)
- **2026-09-03** — Calibration-mode captures convert at a fixed 0.29297 mV/count, not
  `volts_per_count()`. Reason: the internal references bypass the input range amplifier,
  which is why libm2k forces `hw_gain` to 1 there. (Duplicated verbatim as a trap.)
- **2026-09-03** — Generator offset comes from a five-point sweep's zero crossing, not
  libm2k's single capture through a 9.06 divider. Reason: a crossing needs no scale
  factor at all, and this board's loopback measures 8.34.

**Parked 2026-09-04 — two discovery-tooling ToDo items.** They belong with the
overlay work below, not with Phase 1:

- Commit the real capture alongside the synthetic fixture (not over it) and point
  README demos at it. Decide whether to scrub `hw_serial` and `cal,*` first.
- Confirm whether `ctx.attrs` returns strings or objects on the installed libiio --
  `iio_discover._read()` handles both, neither observed.

**Parked 2026-09-04 — overlay coverage, from ToDo.** The board-pack work dropped to
"if we have time" on 2026-09-04: the four blocks need no overlays, and the intro slide
comes from `iio_explain.py --glossary`. Real-hardware ABI coverage stands at 57%, with
58 of 74 overlay entries still `UNVERIFIED`. Pick this up from here.

- Confirm `attr_note()` reaches these attributes first — `in_voltage0_trigger_delay`
  must reduce to `trigger_delay`, and device attrs must hit the same flat
  `pack["attrs"]`. Otherwise entries get written and never displayed.
- Tier 1 (96 attributes) — new packs for `m2k-logic-analyzer` and `-rx`, plus the
  shared trigger attributes on `-tx` and both DACs. Checklist section 8 measures most
  of the `-rx` trigger set, so those go in as `MEASURED`.
- Tier 2 (8 attributes) — `m2k-adc-trigger` as a new pack, `m2k-fabric`
  `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate`. The existing `calibrate`
  entry is wrong: it is `setCalibrateHDL`, FPGA interface training, not a rewrite of
  `calibscale`/`calibbias`.
- Then the bookkeeping: tests for the new entries; re-run coverage (57% → ~90%
  expected); read the `channels-m2k-adc.txt` golden diff by hand rather than
  `REGEN_GOLDEN=1`; correct the README's "95%" claim to report synthetic and real
  separately; sweep the remaining `[overlay: UNVERIFIED]` entries via each `check`.

**Rotated 2026-09-03 — settled, still binding.** The three board-pack authoring rules
that had governed the Decisions section since August. Nothing here has changed; they
are out of the hot note because they are no longer under review, and the first is now
enforced by the overlay schema and its tests. The hot note keeps a one-line stub.

- Overlay entries come from read-only evidence plus libm2k source tracing, each with a
  `check` field. Confidence is `MEASURED` only for what a capture proves, `SOURCED`
  where behaviour traces to libm2k, `UNVERIFIED` for anything inferred from a name.
- The real capture goes in alongside `fixtures/m2k-snapshot.json`, not over it.
  Reason: the fixture keeps goldens stable; participants should explain real data.
- `pll` / `ad9963` internals, `dma_sync_start`, `raw_enable` and `trigger_status` are
  deferred from the board pack. Reason: chip plumbing, no evidence to write from.

**Rotated 2026-09-03 — closed, from Plan.** "Scope check: no Phase 3 demo needs a new
M2K block, and the four cover every Scopy instrument except the supply (`ad5627`),
which is deferred and unneeded." The question it answered — whether block-building was
finished — is answered, and Phase 1 says so.

**Rotated 2026-09-03 — corrected by the board itself.** "**2026-09-01** — Blocks read
`calibscale`/`calibbias` and apply them. Reason: libm2k applies the gain in software,
so the driver does not correct the samples for us." Both halves are wrong. `--probe`
set `calibscale` to 2.0 and the same input came back at twice the counts, so the driver
does apply it and a block applying it again double-counts. `calibbias` moved nothing at
1948, 2048 or 2148 — it is stored and ignored, and the ADC's real offset trim is the
`ad5625`. Replaced by the 2026-09-03 entry.

**Rotated 2026-09-03 — retired from Traps.** "Offset AND gain are per channel on the
ADC; neither is on the DAC. Two-point meter runs put both generator gains within 0.25%
of unity, but the two input gains differ 0.52% and their offsets differ in sign."
Still true, but now stated as the 2026-09-03 Decision it produced and implemented in
`gr-m2k/m2k_calibrate.py`, which trims all four paths per channel.

**Rotated 2026-09-03 — retired from Traps.** Both still true; neither returns a
confident wrong number any more, which is what that section is for.

- "The scope and generator clocks are 100 and 75 MS/s; no rate is legal for both." A
  fact rather than a trap, and `analog_sink`'s docstring leads with it.
- "A loopback cannot check absolute accuracy -- errors at the two ends multiply and two
  wrong numbers can look right." This was the argument for putting a meter on the
  bench. Section 10 has now done that and measured every path separately, so the
  warning has been acted on rather than merely noted.

**Rotated 2026-09-03 — founding premises, not open choices.** These four have governed
the project since it started and are not under review; they are here so the hot note
does not carry them every session. They are still in force.

- Every flowgraph uses libiio / gr-iio as its source. Reason: the workshop teaches the
  IIO path specifically; no flowgraph uses a different source block.
- No live software installs during the session. Reason: setup instructions go out two
  weeks prior instead.
- Demos must run before any slides get written.
- Hardware scarcity is solved by architecture — one instructor unit, many receive-only
  stations. Reason: works for ultrasonic and standing-wave, not CN0363.

**Rotated 2026-09-03 — corrected by measurement.** The residual absolute error was
recorded as "~6.5%, one shared gain error", on the strength of the two loopback paths
agreeing on gain to 0.7%. Two-point meter runs on 2026-09-03 show that framing was
wrong in both halves: the generators contribute no gain error at all (W1 1.00250,
W2 0.99990, both within 0.25% of unity after `DAC_FILTER_COMP`), and the two ADC gains
differ 0.52% — about 4x the meter's resolution, so per channel rather than shared. The
composite figures were right; attributing them was not. Current numbers are in Status.

**Rotated 2026-09-03 — retired from Traps.** "One `iio_buffer_push` per cyclic buffer;
later pushes return `-EBUSY` and the `Device or resource busy (16)` warning is
expected." Still true, still seen on every cyclic run, but it announces itself in
plain text and costs a moment's reading. Traps is for the ones that return confident
wrong numbers.

**Rotated 2026-09-02 — closed, not reversed.** All three are now permanent
implementation rather than open choices; the code and its docstrings carry them.

- **2026-09-01** — Attributes are written directly with libiio at construction; the
  `attr_updater` pair stays only as a keep-alive. Reason: a timer left the board
  unconfigured for the first second of every flowgraph. Now documented at length in
  `gr-m2k/m2k_blocks/m2k_config.py`.
- **2026-09-01** — Calibration offsets are measured per channel, never derived once.
  Superseded as a decision by the Traps entry that states the same thing as a fact.
- Attribute meaning is quoted verbatim from the kernel IIO ABI, every line tagged
  `[abi]`/`[parsed]`/`[driver]`/`[overlay: ...]`. Reason: no guesswork taught as fact.
  Now enforced by the overlay schema and its tests.

- **2026-08-18** — "Overlay entries are written from read-only evidence; the instrument
  is not written to." Superseded 2026-09-01: bench work required writes, taken with
  per-write approval. The read-only default still holds for enumeration.

- The IIO discovery tool is a standalone Python program, optionally packaged
  out-of-tree — not a GRC patch. Reason: GRC can't do dropdowns populated from live
  hardware.
- Enumeration and explanation are separate tools; `iio_explain.py` never imports
  libiio. Reason: a snapshot captured once on the bench explains anywhere, on any
  laptop, with no hardware — which is also how one M2K serves twenty people with no
  installs during the session. The architecture absorbs the hardware-scarcity
  constraint instead of the logistics doing it.

# Session Log

## 2026-09-10 — Phase 1 detail rotated out of Status

Rotated because Phase 1 is closed; Status now carries the one-line verdict. The
detail, still accurate:

- **`gr-m2k/` — six blocks**: `analog_source`, `analog_sink`, `digital_source`,
  `digital_sink`, `spi_decode`, `spi_encode`, plus `m2k_calibrate.py`, `m2k_scale.py`
  and `spi_decode.py`/`spi_encode.py` (arithmetic, import nothing) and `m2k_config.py`.
  390 tests pass. Decoded messages carry the bytes as text in the PDU metadata.
- **The two digital ymls are generated** by `gr-m2k/generate_digital_grc.py`; a test
  fails if the committed copy drifts.
- **Bench checklist sections 1-13 all pass**, including a real SPI mode-0 bus over all
  256 byte values, live send-on-demand, and the libsigrokdecode cross-check.
- **Absolute error is closed and meter-verified.** Inputs within 0.31%, generators keep
  ~10-17 mV. Numbers: checklist section 10.


## 2026-08-18 — discovery tooling, first real capture

- **Repo:** `main` = 269d203, the merge of `claude/m2k-iio-parameter-discovery-12g30y`
  into the scaffold. All tooling is now on `main`. **4 commits ahead of `origin/main`
  and unpushed.** The merge hit the expected add/add conflict on `.gitignore`, resolved
  to the union of both sides.
- **Venv:** in-tree `.venv/` (uv, Python 3.12.13, pytest 9.1.1), gitignored per the
  WSL-native convention.
- **Two-tool split.** `iio_discover.py` (12 KB) enumerates — needs libiio and
  hardware. `iio_explain.py` (23 KB) explains meaning — needs neither. Workflow is
  `./iio_discover.py --json > m2k.json` on the bench, `./iio_explain.py m2k.json`
  anywhere else.
- **`iio_semantics.py`** (33 KB) — ABI knowledge: name grammar, units, conversion.
- **`iio_abi_fetch.py` + `iio_abi_data.json`** — parses the kernel's
  `Documentation/ABI/testing/sysfs-bus-iio` into a checked-in cache of 826 documented
  attribute names, so the tools work offline.
- **`iio_overlays.py`** — board-specific knowledge, confidence-tagged. 20 board notes
  total: 3 sourced, 17 unverified. M2K entries are traced to libm2k. Unverified
  entries each carry a `check` field describing how to confirm them.
- **Channel identity:** four sources consulted in order — driver channel name, `label`
  attribute, board pack, then the ABI convention that an indexed channel is an
  externally available input. Output reports which one answered.
- **`fixtures/m2k-snapshot.json`** — hand-authored synthetic capture, labelled as such
  in the file. Everything runs with no hardware against it.
- **Tests:** 73 passing locally in ~1.1 s (`.venv/bin/python -m pytest tests -q`), with
  no hardware and no libiio.
- **Live M2K reachable from WSL over the network backend** at `ip:192.168.2.1`
  (Rev.D Z7010, fw v0.33). No USB passthrough needed — `lsusb` is empty and `--scan`
  finds only `local:`, so the URI must be given explicitly.
- **First real capture, 2026-08-18** (154 KB, not yet committed): 14 devices, 98
  channels (36 scan elements), 317 attributes = 39 device + 260 channel + 10 buffer +
  8 debug. 112 channel attributes carry a folded `*_available` sibling — that is the
  dropdown-populating count, and the number that sizes the GUI work. Against the
  synthetic fixture's 44 attributes, real hardware is 7.2× larger.
- **ABI coverage on real hardware is 57%** (181 of 317), not the 95% the README
  reports from the synthetic fixture — that figure was an artifact of a fixture built
  mostly from generic attributes. 136 attributes are unexplained, and 86 of them are
  logic-analyzer trigger/direction attrs (`trigger_delay`, `trigger_logic_mode`,
  `trigger_mux_out` ×18 each; `direction`, `outputmode` ×16 each). The gap is
  concentrated, not diffuse.
- **The capture lives at `/tmp/m2k-real.json` and is not committed** — it will not
  survive a reboot. Re-capture with
  `./iio_discover.py --uri ip:192.168.2.1 --json > <file>` if it is gone.
- **`m2k-logic-analyzer` has no board-pack entry at all** — that single omission is 33
  of the unexplained attributes. `m2k-logic-analyzer-rx` and `-tx` have entries with
  empty `channels` and `attrs`.
- **The folded `*_available` lists are strong evidence for the missing entries**, read
  straight off hardware: `trigger_mux_out` offers
  `trigger-logic / trigger-in / -and- / -or- / -xor- / disabled` (a combining stage, not
  a selector); `trigger_logic_mode` is `or / and`; `direction` is `in / out`;
  `outputmode` is `push-pull / open-drain`; `rate_mux` is
  `logic_analyzer / oscilloscope`; `trigger_src` differs between the DACs
  (`trigger-Ti`) and the TX path (`trigger-i_0`, `trigger-i_1`).
- **Overlay work is planned but not started.** Tier 1 = `m2k-logic-analyzer` (new pack),
  `m2k-logic-analyzer-rx`, and the shared trigger vocabulary on `-tx` / `m2k-dac-a` /
  `m2k-dac-b` — 96 attributes. Tier 2 = `m2k-adc-trigger` (new pack), `m2k-fabric`
  `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate` — 8 more. Awaiting go.
- **`standing_wave_view.jsx`** — described in the seed but **not in the repo, not on
  either branch, and not anywhere on disk.** Treat as lost unless it turns up.
- **Hardware:** ADALM2000 (possibly one per station), one CN0363 colorimeter, 10×
  Raspberry Pi Pico, instructor wideband ultrasonic mic board. 40 kHz ultrasonic
  TX/RX pairs on order.

## 2026-09-01 — first bench session with a live M2K

Ran `docs/bench-checklist.md` sections 1-6 against the board. Found four bugs that
stopped anything working, one that is still open, and two arithmetic omissions that a
loopback could never have caught. Full detail, measured constants and method are in
`docs/bench-checklist.md`; the fixes are in commits 2a6e5cf and 5224133.

Absolute calibration was done with a handheld meter against three DC levels, because
the M2K's own voltmeter is the same ADC through the same scaling factor and cannot
check itself. The `ad5625` internal reference chain was investigated as an alternative
and is good for zero, linearity and range ratio, but not for absolute accuracy -- the
path gain between `adc_ref1` and the front end is unknown.

## 2026-09-01 — second bench session: the race, the trigger, and W2

Closed bench-checklist sections 3 and 6. Three commits (8599190, 74f69ae, c24304d),
pushed; `origin/main` at c24304d.

`m2k_config` now writes each attribute directly with libiio at construction time,
keeping `attr_updater`/`attr_sink` as a keep-alive. Proved by planting `gain=low,
powerdown=1`, asking for the high range, and capturing 4096 samples 100 ms in — one
tenth of the old interval. The two-second skip workaround is gone from every test.

The trigger passes all four checks, including the two that a silently free-running
trigger would also fail: a level above the peak stalls, and `edge-falling` falls.
Alignment spread went 1.8793 V free-running to 0.0288 V triggered, which is one sample
step at that slew rate.

W2 works, is independent (939.5 mV on W1 moves channel 2 by 1.1 mV), and lands on the
right input under a swap. The finding is in the fit: both paths share the same gain to
0.7%, but the offsets are +25 mV and +169 mV. Meter at 0 V requested gave W1 49.4 mV
and W2 114.5 mV, so input 1 contributes -21.4 mV of its own and partly cancels W1's,
which is why channel 1 looked clean. Channel 2's split is still open — it needs one
meter reading of W2 at +1.0 V.

Also installed `pyyaml` in `.venv`; all 184 tests pass, including three that had never
run. Board left powered down.

## 2026-09-02 — two traps retired from the hot note

Both fail loudly with a clear message, so they cost minutes, not a session. Traps is
for the ones that return confident wrong numbers.

- **`set_len_tag_key` on a sink** demands a tagged stream and refuses without one.
  Harmless on a source.
- **gr-iio's `device_phy` must name a real device.** `""` is not "none" -- it goes
  through `iio_context_find_device` and always fails with `Device not found`.

## 2026-09-03 — the calibration set, closed per channel

Two metered points per signal path, driven by `bench/dc_point.py`: hold a DC level
through `analog_sink` at 750 kS/s, capture in counts at 1 MS/s on the `high` range,
convert in the script so the raw number and our volts both print. The generator holds
its last cyclic buffer after the graph stops, so the meter reading never races the
capture.

| | gain | offset | counts |
|---|---|---|---|
| W1 | 1.00250 | +48.5 mV | — |
| W2 | 0.99990 | +112.1 mV | — |
| input 1 | 0.93686 | -20.9 mV | -13.8 |
| input 2 | 0.93199 | +61.9 mV | +40.8 |

Every number cross-checks. The composite implied for W1 to input 1 is gain 0.93920,
offset +24.5 mV, against 2026-09-01's independent fit of 0.9401 / +25 mV. W2's zero
metered 112.1 mV against 114.5 mV last session, W1's 48.5 against 49.4. Both ADC
offsets came out twice by different routes — solved from the fit, and read directly
off a disconnected input — agreeing to 0.2 and 0.3 mV. Input 1's -13.8 counts is the
third independent arrival at the -13.9 counts section 4 measured.

**A jumper in the wrong socket cost the middle of the session, and paid for itself.**
Metering W1 while the old jumper still ran W1 into `2+`, input 1 read a clean, stable
-13.9 counts across a full-volt swing. That is a real number — input 1's own offset,
and one a previous session had correctly measured — so nothing looked broken. What
gave it away was arithmetic: W1 metered +48.5 mV, and input 1 was reporting as though
its input were 0 V. Sweeping the source and watching for no response confirmed it.
The accident then served as an independent test of input 2, whose freshly derived
calibration predicted its readings to 0.3 mV at the low end and 1.6 mV at the high.
Now a Trap.

Board parked cold afterwards: both DAC registers at 0, all four fabric powerdowns set,
triggers back to `always`.

# Ruled Out

- **The factory `cal,*` context attributes explain the absolute error.** They do not.
  `cal,gain_pos_adc = 0.99906`, `cal,gain_neg_adc = 0.99581` and the other six are all
  within 0.5% of unity; the error was 17.6%.
- **`9979.2 Hz` instead of 10 kHz is a rate bug.** It is cyclic-buffer quantisation:
  218 x 750000/16384 = 9979.2 exactly. It confirms the DAC clock rather than
  questioning it.
- **The loopback reading 1.0010 V for 1.0 V means the volts path is correct.** The
  generator was 16.7% high and the scope 15.4% low; the product is 0.99.

- **The residual gain error is per channel.** It is not. W1-to-input-1 and
  W2-to-input-2 agree to 0.7% (0.9401 vs 0.9335), so the ~6.5% is one shared error.
  The *offsets* are per channel; the gain is not.
- **The trigger comparator sees pre-decimation samples, so the filter correction should
  not be applied to the trigger level.** Applying it agrees to 0.14%; omitting it would
  put the trigger 9% off where the scope reads.
