---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-19
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
  time base is 2x slow, and it shows up as a tone at exactly Nyquist.
- **The ADC front end comes up powered down** on an uninitialised board, giving a
  plausible flat line rather than an error. Clear `powerdown` on `m2k-fabric`.
- **Cyclic buffers quantise frequency, and the DAC keeps holding them.** A repeating
  N-sample buffer only makes multiples of `rate/N`, so 10 kHz comes back as 9979.2 Hz --
  correctly -- and goes on doing so after the graph stops. The digital sink is the
  opposite: DIO pins snap back to `raw`.
- **Volts-per-count depends on the sample rate**, through the decimation filter's gain
  -- and so does the trigger level, which otherwise sits 9% from where the scope says
  it is. The generator has the same problem, less regularly.
- **Reading trigger attributes back proves nothing.** A silently free-running trigger
  sets every one correctly and delivers every sample. Only alignment, a stall above the
  peak, and the edge's slope tell them apart.
- **The two directions never share a rate.** `-tx` and `-rx` hold separate
  `sampling_frequency`, so a Sink and a Source at different rates disagree about time;
  on the analog side the ladders differ outright, 75 against 100 MS/s. No complaint.
- **The keep-alive means `tb.run()` never returns** -- it waits for every block and the
  updater never ends, so a `head`-terminated graph looks like a hung board. Use
  `start`/`stop`/`wait`.
- **gr-iio's `device_sink` drives ONE DIO pin, silently.** Sixteen 1-bit fields share one
  16-bit word and each write is a full-width store, so only the highest pin survives --
  with no error. `docs/gr-iio-multipin-sink.md`.
- **GRC `dtype: enum` values are raw strings.** `'0' + '3'` concatenates, `int("'6'")`
  raises, and an assert that raises makes GRC fall back to defaults without saying so.
- **gr-iio's `device_source` ends itself on any refill error.** `work()` returns
  WORK_DONE on a timeout, so a triggered source waiting on a human never comes back,
  and `set_timeout_ms` never reaches libiio. Free-run the source; trigger the display.
- **The pair does not resonate at 40 kHz.** Measured f0 is 40.755 kHz with a -6 dB
  width of 1023 Hz, so the nominal frequency loses ~10 dB and presents as a bad demod
  rather than a bad frequency. Sweep before tuning anything to it.
- **A canvas parameter beats an `epy_block`'s `__init__` default**, so a test that
  builds the class bare tests a block nobody runs. The colorimeter's drift test passed
  happily while the `.grc` said something different. Read the values out of the `.grc`.
- **The two GRC path mechanisms behave oppositely.** `GRC_BLOCKS_PATH` *prepends* to
  the system directories; `Platform.build_library([...])` -- called by `render_grc.py`
  and the integration tests -- *replaces* them, which is why those name
  `/usr/share/gnuradio/grc/blocks`. Persistent paths go in `~/.gnuradio/config.conf`
  under `[grc] local_blocks_path`, never `grc.conf`, which is GUI state.
- **Saving the colorimeter from the GRC editor damages it.** The number sink's
  `color2`/`color3` come back black and the file triples in length. Edit the `.grc` as
  text, or read the diff before committing a save.

# Decisions
- Closed and rotated to the archive with the reasoning in full: the board-pack rules,
  the digital-block / calibration / SPI / pin-list decisions the built blocks embody,
  the six that shaped `slides/`, and the ultrasonic rate and f0 choices. Live halves:
  Traps, `docs/gr-iio-multipin-sink.md`, `slides/README.md`, `check_deck.py`.

- **2026-09-01** — libm2k may check our numbers on the bench, but the workshop ships no
  libm2k dependency. Reason: IIO alone does not know what a sample is worth.
- **2026-09-01** — Writes to the instrument are allowed with per-write approval,
  superseding the read-only default of 2026-08-18.
- **2026-09-04** — Build a DC power supply block, reversing the 2026-09-02 "no supply
  block" decision. Reason: GNU Radio cannot control a rail at all, and the setpoint
  spans four places including the context `cal,*` attributes.
- **2026-09-11** — The booth CTF is the chained tier: decode the SPI bus for the
  ultrasonic parameters, then use them on the beacon. Reason: it is the only tier that
  makes the two halves of the workshop one story, and both halves already run.
- **2026-09-16** — The colorimeter board is ADI's **M2k Colorimeter Accessory Board**
  from `education_tools`, not the CN0363. Reason: it borrows the CN0363's cuvette
  holder and nothing else — no ADC, no mux, no driver.
- **2026-09-16** — The color-naming rule is written twice, in the flowgraph's embedded
  block and in `bench/colorimeter.py`, guarded by a drift test rather than shared by an
  import. Reason: importing out of the repo would put a `PYTHONPATH` on the demo's
  critical path.
- **2026-09-16** — `gr-m2k` ships two install routes, `env.sh` and a pip
  `#subdirectory=` install; the CMake OOT is deferred. Reason: the blocks are pure
  Python, and a CMake route costs every participant a compiler for nothing.

# Plan

**Phase 1 — crawl:** six blocks built and bench-verified, absolute error closed. Open:
a DC power supply block, a capability GNU Radio does not have.

**Timing:** GRCon26 is this month. Phases 1 and 3 are closed and merged; the deck
covers everything that runs and is published. Participants need a short setup before
the session: install the M2K drivers and download the flowgraphs.

**Phase 2 — walk:** IIO block anatomy, one intro slide from `iio_explain.py
--glossary`; `docs/reading-iio-attributes.md` is the participant artifact.

**Phase 3 — run:** ultrasonic FSK and the colorimeter, both closed on the bench with
participant-facing `.grc` files merged. Time-of-flight ranging and the seven-color
exercise are the stretch goals.

**Booth CTF:** chained — decode the SPI bus for the ultrasonic parameters, then the
beacon. Pico beacons, M2K as the receiver.

**`gr-m2k` packaging:** crawl (`env.sh`) and walk (pip from GitHub) done. The run tier
— its own repo with a gr-modtool `CMakeLists.txt` — is post-workshop, and the only
tier that costs participants a compiler.

# Status

- **Repo:** `main`, everything merged — SPI, ultrasonic (PR #4), colorimeter (PR #5,
  `13cbbc7`). 456 tests.
- **Phase 1 is done and verified.** Six blocks in `gr-m2k/`, all 15 bench-checklist
  sections passing, absolute error closed against the meter. Detail in the archive.
- **`gr-m2k` is installable two ways** as of 2026-09-16: `source gr-m2k/env.sh` for one
  shell, or a pip `#subdirectory=gr-m2k` install plus `m2k-blocks install` for every
  terminal. No CMake. `m2k-blocks check` diagnoses an empty block tree, which has two
  unrelated causes that look identical until Run. `gr-m2k/README.md`.
- **Ultrasonic closed 2026-09-09**, merged 2026-09-16. f0 40.755 kHz, 0 errors in
  395 bits over the air; `flowgraphs/m2k_ultrasonic_fsk.grc`. Numbers in the archive.
- **Colorimeter closed 2026-09-16.** Three colors chopped at 5004.9 / 6005.9 /
  7006.8 Hz and separated in one FFT; blanked empty beam holds 0.06% peak to peak, the
  green strip repeats to 0.3%, and color naming and the Blank button both passed on the
  board. `flowgraphs/m2k_colorimeter.grc`, `bench/colorimeter.py`; numbers in the
  archive. Provisional: the 85 / 5 / 1.3 thresholds rest on one filter.
- **`slides/` — 57 frames**, 44 cut, 47 carrying depth, no placeholders left, published
  at <https://livethisdream.github.io/grcon26-workshop/> on every push to `slides/`.
  Figures are generated from source and a test fails on drift; `check_deck.py` gates
  titles, ids, alt text, the 40-word budget and the title register.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough. Calibrated and held; all 16 DIO pins inputs, triggers off.
- **Also in hand:** colorimeter accessory board, 10x Pico, instructor ultrasonic mic
  board, 40 kHz TX/RX pairs.

# ToDo

**DC power supply block**
- [ ] Fetch `m2kpowersupply_impl.cpp` via `iio_libm2k_fetch.py` for the raw-to-rail
      expression; sweep two points against the meter and let the meter win.
- [ ] Block: float setpoint in volts, rate-limited writes, one per rail. Clears
      `powerdown` on `m2k-fabric` user_supply and `ad5627`, applies `cal,*`.
- [ ] Precision demo, rail to input 1. Then PWM LED off `digital_sink`.

**Colorimeter**
- [x] Benched end to end 2026-09-16: color naming and the Blank button both verified.
- [ ] `bench/colorimeter.py filter --name "<sample>"` on four or five strips. The
      85 / 5 / 1.3 thresholds are sized to one green strip; nothing else is measured.
- [ ] Stretch: seven colors — a three-bit pattern, not winner-takes-all.

**Deck**
- [ ] Add a resources card for installing the blocks afterwards — the deck says
      "nothing to install in the room" and never says how to get them later.

**Ultrasonic**
- [x] Swept, benched, ported to `flowgraphs/m2k_ultrasonic_fsk.grc` and merged.
- [ ] Measure range and off-axis falloff, and run long enough for a real BER — 395 bits
      bounds it below 1/395 rather than measuring it.

**Booth CTF (chained tier)**
- [ ] Pico beacon firmware: FSK at the measured tones, framed with the access code.
- [ ] Stage-one SPI payload: f0, baud, access code.
- [ ] Booth setup doc: wiring, what the attendee gets, the flag.
- [ ] Decide the beacon duty cycle — 40 kHz is in a dog's hearing range and the booth
      runs all day.

**Loose ends**
- [ ] Write the participant setup: install the M2K drivers, download the flowgraphs.
      Short enough to do the morning of, and the only thing anyone installs. The pip
      route is what to send them.
- [ ] Decide which demo is the hands-on participant station.
- [ ] Add `flowgraphs/m2k_digital_loopback.grc` — sink at DIO0, source at DIO1.
- [ ] Raise `samp_rate` on `m2k_spi_loopback.grc` from 100 kS/s step by step and record
      where send-on-demand stops holding. Nothing in the repo knows that rate.
- [ ] Run the sigrok check against a real M2K capture, not the encoder's arithmetic:
      `bench/spi_flowgraph.py M2K 8 --csv`, DIO0-2 wired to DIO4-6.

**If we have time**
- [ ] Overlay coverage (~104 attributes, 57% → ~90%) is parked; see the archive,
      "Parked 2026-09-04".
