---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-11
container: cdocker
---
# Overview

Hands-on workshop material teaching GNU Radio with the ADALM2000 (M2K) as the input
device, for GRCon26 (September 2026). The M2K is the instrument; every other board sits
on its input side as a signal source. libiio / gr-iio is the interface layer for every
flowgraph in the workshop. Audience is ~20 participants with basic GNU Radio
familiarity, in a 90–120 minute session structured crawl (IIO intro, loopback) → walk
(IIO block anatomy, discovery tool) → run (application demos). Scope spans tooling (a
standalone Python IIO discovery program), demo applications (a React standing-wave
display), and the session material itself.

# Special Instructions

- Plan first, then execute. Show the plan before writing code.
- Crawl, walk, run. Get the smallest thing working before adding scope.
- If you find yourself fixated on one aspect, stop and ask whether that's the right
  thing to be focused on. Don't assume permission to stay there.
- Be curious, not judgmental. Don't guess at the next step or chase side quests.
- No jargon. Clear and concise.
- Don't end responses with leading questions. If you have a real question, ask it.
- Active working focus is code — tooling and demos. Slides, procurement, and session
  timing are tracked here but are not the current work.


# Traps

- **The M2K ADC always returns both channels, interleaved.** Ask for one and gr-iio
  splits the two-channel buffer as if it were one: channel 2 lands in channel 1, the
  time base is 2x slow, and it presents as a tone at exactly Nyquist.
- **The ADC front end comes up powered down** on an uninitialised board, and gives a
  plausible flat line rather than an error. Clear `powerdown` on `m2k-fabric`.
- **Cyclic buffers quantise frequency, and the DAC keeps holding them.** A repeating
  N-sample buffer only produces multiples of `rate/N`, so 10 kHz comes back as 9979.2 Hz
  and that is correct -- and it goes on producing it after the graph stops. The digital
  sink is the opposite: DIO pins snap back to `raw`.
- **Volts-per-count depends on the sample rate**, through the decimation filter's gain
  -- and the same correction applies to the trigger level, which otherwise sits 9% from
  where the scope says it is. The generator has the same problem, less regularly.
- **Reading trigger attributes back proves nothing.** A silently free-running trigger
  sets every one correctly and delivers every sample. Only alignment, a stall above the
  peak, and the edge's slope tell them apart.
- **The two directions never share a rate.** `-tx` and `-rx` hold separate
  `sampling_frequency`, so a Sink and a Source given different rates disagree about
  time; on the analog side the ladders differ outright, 75 MS/s decades against
  100 MS/s. Neither case complains.
- **The keep-alive means `tb.run()` never returns** -- it waits for every block and the
  updater never ends. A `head`-terminated graph looks like a hung board. Use
  `start`/`stop`/`wait`.
- **Positive digital `trigger_delay` is approximate.** Zero and negative are exact and
  repeat; positive lands tens of samples off, differently each run, reading back right.
- **Calibration mode reads the same counts on both ranges.** Its references and the
  generator loopback arrive past the input amplifier, so `volts_per_count()` mis-scales
  them by 4.7x. Convert at a fixed 0.29297 mV/count instead.
- **gr-iio's `device_sink` drives ONE DIO pin, silently.** Sixteen 1-bit fields share
  one 16-bit word; each channel's write is a full-width store that erases the last, so
  only the highest pin survives. No error. `docs/gr-iio-multipin-sink.md`.
- **GRC `dtype: enum` values are raw strings.** `'0' + '3'` concatenates, `int("'6'")`
  raises, and an assert that raises makes GRC fall back to defaults without saying so.
- **A triggered digital capture is gapped between buffers and re-arms per buffer**, so
  the trigger edge is a frame boundary. CS framed per byte makes every buffer start on
  an arbitrary byte: the stream prints rotations, every byte individually correct.
- **gr-iio's `device_source` ends itself on any refill error.** `work()` returns
  WORK_DONE on a timeout, so a triggered source waiting on a human never comes back,
  and `set_timeout_ms` never reaches libiio. Free-run the source; trigger the display.
- **A non-cyclic digital sink pushes one DMA buffer at a time and need not join them.**
  A frame lying across the seam tears mid-message. `m2k_spi_encode`'s "Align frames to"
  holds a queued frame until the next boundary; its sample count is the sink's position.
- **The pair does not resonate at 40 kHz.** Measured f0 is 40.755 kHz and the -6 dB
  width is only 1023 Hz, so the nominal frequency loses ~10 dB and presents as a bad
  demod rather than a bad frequency. Sweep before tuning anything to it.

# Decisions
- Closed and rotated to the archive, with the reasoning in full: the board-pack
  authoring rules, the digital-block, calibration, SPI and pin-list decisions the built
  blocks now embody, and the six that shaped `slides/`. Their live halves are traps,
  `docs/gr-iio-multipin-sink.md`, `slides/README.md` and `check_deck.py`.

- **2026-09-01** — Calibration is a standalone script run once per session, not block
  init. Reason: it seizes the whole analog front end, is a closed loop `attr_sink`
  cannot express, and its result persists on the device.
- **2026-09-01** — libm2k may check our numbers on the bench, but the workshop ships no
  libm2k dependency. Reason: the point is that IIO alone does not know what a sample is
  worth.
- **2026-09-01** — Writes to the instrument are allowed with per-write approval,
  superseding the read-only default of 2026-08-18.
- **2026-09-04** — Build a DC power supply block, reversing the 2026-09-02 "no supply
  block" decision. Reason: GNU Radio cannot control a power rail at all, and the
  setpoint spans four places including the context `cal,*` attributes.
- **2026-09-04** — Standing-wave / VSWR is out of the workshop. Reason: scope control
  with GRCon26 this month; it carried the most unbuilt work of the three.
- **2026-09-04** — Discovery tooling drops to "if we have time"; the intro gets one
  slide on what IIO is and which M2K attributes matter. Reason: the blocks need no
  overlays, and `iio_explain.py --glossary` generates the slide content.
- **2026-09-04** — Ultrasonic transmits at 750 kS/s and receives at 1 MS/s. Reason:
  DAC and ADC have different rate ladders, and 40 kHz needs the third rung of each.
- **2026-09-09** — Ultrasonic runs at the measured f0, 40.755 kHz, not 40 kHz nominal;
  tones 40.455 / 41.055. Reason: resonance is 755 Hz high and 40.0 kHz gives a third
  of the signal. Checked against a standing-wave artifact by re-sweeping at 2x spacing.
- **2026-09-09** — The receiver decimates 1 MS/s by 200 before the demod, where ECE448
  decimated by 1. Reason: 1 MS/s against a 1023 Hz channel is almost all empty spectrum;
  5 kS/s still leaves 25 samples per bit.
- **2026-09-11** — The booth CTF is the chained tier: decode the SPI bus for the
  ultrasonic parameters, then use them on the beacon. Reason: it is the only tier that
  makes the two halves of the workshop one story, and both halves already run.

# Plan

**Phase 1 — crawl:** six blocks built and bench-verified, absolute error closed. Open:
a DC power supply block, a capability GNU Radio does not have.

**Timing:** GRCon26 is this month. Phase 3's ultrasonic link is closed and the
colorimeter reads end to end; both are in the deck. Participants need a short setup
before the session: install the M2K drivers and download the flowgraphs.
**Phase 2 — walk:** IIO block anatomy, one intro slide from `iio_explain.py
--glossary`; `docs/reading-iio-attributes.md` is the participant-facing artifact.

**Phase 3 — run:** ultrasonic FSK, then the CN0363 colorimeter. The FSK link decodes
over the air on the bench at the measured f0; what is left is the participant-facing
`.grc` and the frames. Time-of-flight ranging is the stretch goal.

**Booth CTF:** chained — decode the SPI bus for the ultrasonic parameters, then the
beacon. Pico beacons, M2K as the attendee's receiver.

# Status

- **Repo:** branch `ultrasonic-fsk` off `main`; the SPI branch is merged.
- **Phase 1 is done and verified.** Six blocks in `gr-m2k/` — analog and digital,
  source and sink, SPI decode and encode — 390 tests, all 13 bench-checklist sections
  passing, absolute error closed and meter-verified. Detail in the archive; numbers in
  the checklist.
- **`slides/` — 55 frames**, read and present from one document. The present layer is
  bullets and pictures; the prose is in `.depth`. Every figure and both digital ymls
  are generated from source and a test fails when either drifts; `check_deck.py` gates
  titles, ids, alt text and the 40-word budget. Toolchain and its distro dependencies
  are in `slides/README.md`. Ultrasonic and the colorimeter both have real frames.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough. Calibrated and held; all 16 DIO pins inputs, triggers off.
- **Ultrasonic characterised and closed 2026-09-09.** f0 40.755 kHz, -6 dB band
  1023 Hz, level following 1/r: ~143 mV projected at 1 m over an 8.4 mV crosstalk
  floor. `bench/ultrasonic_fsk.py` sends from W1 and reads the message back off 1+,
  0 errors in 395 bits, no underruns. The receiver decimates by 200 to 5 kS/s,
  4015-tap 600 Hz low-pass, quadrature demod, 25 samples per bit; byte alignment comes
  from a sync word -- `correlate_access_code_tag_bb`, `tagged_stream_align`,
  `pack_k_bits_bb`. Sweep and three CSVs in `bench/`.
- **Also in hand:** one CN0363, 10x Pico, instructor ultrasonic mic board, 40 kHz
  TX/RX pairs. FSK source flowgraph: `~/USAFA/ECE448/L01_Intro/fsk_project.grc`.

# ToDo

**DC power supply block**
- [ ] Fetch `m2kpowersupply_impl.cpp` via `iio_libm2k_fetch.py` for the raw-to-rail
      expression; measure a two-point sweep against the meter and let the meter win.
- [ ] Block: float setpoint in volts, rate-limited writes, one instance per rail.
      Clears `powerdown` on both `m2k-fabric` user_supply and `ad5627`, applies the
      context `cal,*` corrections.
- [ ] Precision demo — rail to input 1, commanded vs measured.
- [ ] Then the PWM LED application off `digital_sink`.

**Ultrasonic**
- [x] Swept, then benched end to end 2026-09-09. f0 40.755 kHz, band 1023 Hz;
      0 errors in 395 bits; non-cyclic streaming holds at 750 kS/s, zero underruns.
      `bench/ultrasonic_sweep.py`, `bench/ultrasonic_fsk.py`.
- [ ] Port to `flowgraphs/m2k_ultrasonic_fsk.grc` with the benched parameters, plus the
      sync word so the receiver finds the byte boundary without knowing the message.
- [ ] Measure range and off-axis falloff, and run long enough for a real BER — 395 bits
      bounds it below 1/395, it does not measure it.

**Booth CTF (chained tier)**
- [ ] Pico beacon firmware: FSK at the measured tones, framed with the access code.
- [ ] Stage-one SPI payload: f0, baud, access code.
- [ ] Setup document for the booth: wiring, what the attendee is given, the flag.
- [ ] Decide the beacon duty cycle: 40 kHz is inside a dog's hearing range and the
      booth runs all day.

**Loose ends**
- [ ] Add `flowgraphs/m2k_digital_loopback.grc` — sink at DIO0, source at DIO1.
- [ ] Raise `samp_rate` on `m2k_spi_loopback.grc` from 100 kS/s a step at a time and
      record where send-on-demand stops holding. Nothing in the repo knows that rate.
- [ ] Run the sigrok check against a real M2K capture, not the encoder's arithmetic:
      `bench/spi_flowgraph.py M2K 8 --csv`, DIO0-2 wired to DIO4-6.
- [ ] Delete the merged `m2k-discovery-gui` branch.
- [ ] Decide which demo becomes the hands-on participant station.
- [ ] Write the participant setup: install the M2K drivers, download the
      flowgraphs. Short enough to do the morning of, and it is the only thing
      anyone installs.
- [ ] Turn on Settings -> Pages -> Source: GitHub Actions so `pages.yml` can publish.
- [ ] Fill the `#colorimeter` placeholder frames once that demo runs.

**If we have time**
- [ ] Overlay coverage (Tier 1 + Tier 2, ~104 attributes, 57% → ~90%) is parked. The
      full task list is in the archive under "Parked 2026-09-04".
