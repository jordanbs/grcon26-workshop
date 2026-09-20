# The beacon

A Pico driving a 40 kHz transducer with the same FSK the workshop's
ultrasonic section builds. It repeats an eight-character message, and
an attendee receives it with `flowgraphs/m2k_ultrasonic_fsk.grc`.

This is the booth demo: the ultrasonic half of the workshop running on
a table instead of a bench, so somebody who did not attend the session
can still watch bits cross a room. Nothing is hidden and nothing has to
be unlocked -- the flowgraph has f0, the baud rate and the sync word in
it already. The receiver is the exercise.

Two files go on the board:

| file | what it is |
|---|---|
| `beacon.py` | frame layout and PWM arithmetic. No hardware in it, so `tests/test_beacon.py` runs it under CPython against the flowgraph. |
| `main.py` | the pins, the registers and the burst loop. Runs only on a Pico. |

## Wiring

```
GP16 ----------------+
                   [ transducer ]
GP17 ----------------+
```

Both pins drive. They are channels A and B of PWM slice 0 with B
inverted, so the transducer sees 6.6 V peak to peak rather than the 3.3
one pin could manage, and being on one slice is what holds them exactly
antiphase. Nothing else connects — no ground reference, no series
resistor, no amplifier.

## Flashing

1. Hold BOOTSEL, plug the Pico in, and drop a MicroPython `.uf2` on the
   drive that appears. Any build from 1.20 on.
2. Copy both files to the board with `mpremote`:

   ```
   mpremote cp booth/pico/beacon.py :beacon.py
   mpremote cp booth/pico/main.py :main.py
   ```

3. Reset. `main.py` runs on power-up from then on, so the beacon needs
   nothing but a USB charger at the booth.

## Setting a board up

Everything to change is at the top of `main.py`.

| constant | default | what to do with it |
|---|---|---|
| `MESSAGE` | `"GRC-4A7F"` | Eight characters or fewer, printable ASCII. Shorter gets space-padded; longer refuses at boot rather than transmitting a truncated one. |
| `SLOT` | `0` | `0` on the first beacon, `1` on the second. |
| `BURST_FRAMES` | `3` | Frames per burst. Three gives the receiver three chances at the correlation. |
| `PERIOD_MS` | `5000` | How often a burst goes out. |

Both beacons carry the same message by default. Giving them different
ones is a one-line edit and tells you which station somebody stood at.

**`SLOT` is why two beacons in one room work.** They transmit the same
two tones, so they take turns: slot 1 starts half a period after slot 0.
A burst is 1760 ms against a 2500 ms half period, so they cannot land on
top of each other. `main.py` refuses to boot if a change to
`BURST_FRAMES` or `PERIOD_MS` breaks that.

## Checking one before the doors open

Watch the console on reset. A healthy board prints:

```
beacon 'GRC-4A7F'   slot 0   sysclk 125000000 Hz
  space   want   40455.0   TOP  3089   got   40453.1  (-1.9 Hz)
  mark    want   41055.0   TOP  3044   got   41050.9  (-4.1 Hz)
  burst 352 bits, 1760 ms, once every 5000 ms
```

The two `got` figures are what the hardware will actually radiate. The
divider stays at 1, so the tone is quantized to `sysclk/N` and lands a
few hertz low; the demodulator's gain maps 300 Hz onto 1.0, so 4 Hz is
about one percent of a full-scale eye. Anything tens of hertz out is a
different problem and worth chasing before the room fills up.

Then point an M2K at it, run the flowgraph, and read the message out of
Message Debug. That is the same thing an attendee does, and it is the
only check that covers the transducer.

## Things worth knowing

**The output is a square wave, not a sine.** The RP2040 has no DAC and
does not need one here. The pair is 1023 Hz wide at −6 dB around 40.755
kHz, so the transducer deletes the third harmonic at 122 kHz by itself,
and a square wave moves more air than a sine off the same rail.

**A burst ends with a second sync word.** Tagged Stream Align hands on a
stream that begins at the first payload byte, so Keep M in N sees
payload, sync, payload, sync, and keeps the first eight of every twelve.
The last payload needs the four bytes after it to exist before it
completes a group. Without the trailing sync word the receiver decodes
two frames out of three, which reads as a marginal link and is not one.

**The preamble is thirty-two bits of `0xAA`.** The bench link never
needed one, because it transmits forever and `symbol_sync` can converge
whenever it likes. A burst starts from silence, and at a loop bandwidth
of 0.045 the loop takes roughly twenty symbols. The receiver discards
the preamble for free —
`correlate_access_code_tag` ignores everything until the marker.

**Bursty, not continuous.** 40 kHz is inside a dog's hearing range and
the booth runs all day. At the defaults a beacon is quiet 65% of the
time and an attendee who has just finished wiring waits at most 3.2 s.

**Nothing here has run on a board yet.** `tests/test_beacon.py` checks
the frame against the flowgraph and runs the beacon's own bits through
the real receive chain, so the bits and the arithmetic are covered. The
PWM register writes, the differential drive and the transducer are not.
