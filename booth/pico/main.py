"""Ultrasonic FSK beacon for the booth. Copy this to a Pico as main.py.

A 40 kHz transducer repeating an eight-character message, which an
attendee's M2K receives with flowgraphs/m2k_ultrasonic_fsk.grc and
nothing else. It is the ultrasonic half of the workshop, running on a
table instead of a bench.

    GP16 -> transducer +
    GP17 -> transducer -

Both pins drive. They are the A and B channels of one PWM slice with B
inverted, so the transducer sees 6.6 V peak to peak instead of the 3.3
one pin could manage. Being on the same slice is what keeps them exactly
antiphase; two slices would drift.

The output is a square wave, not a sine, because the RP2040 has no DAC
and does not need one. The pair is 1023 Hz wide at -6 dB around 40.755
kHz, so the transducer deletes the third harmonic at 122 kHz on its own,
and a square wave moves more air than a sine off the same rail.

Everything that can be worked out without a pin is in beacon.py, which
pytest runs under CPython against the flowgraph. What is left here is
the hardware: two pins, five registers and a clock.
"""
import machine
import os
import time

import beacon

# ---------------------------------------------------------------- setup

# Eight characters, which is msg_capacity in the flowgraph. Shorter is
# fine and gets space-padded; longer refuses at boot.
MESSAGE = "GRC-4A7F"

# 0 or 1. Two beacons in one booth transmit the same two tones, so they
# take turns: slot 1 starts half a period after slot 0. A burst is 1.76 s
# against a 2.5 s half period, so they cannot land on top of each other.
SLOT = 0

# Bursty rather than continuous, because the booth runs all day and 40
# kHz is inside a dog's hearing range. Three frames gives the receiver
# three chances at the correlation; a 5 s period means an attendee who
# has just finished wiring waits at most 3.2 s to see something.
BURST_FRAMES = 3
PERIOD_MS = 5000

PIN_A, PIN_B = 16, 17

# ------------------------------------------------------------ registers

# The PWM block, from the datasheet: RP2040 section 4.5.3, RP2350 section
# 12.5. Same register layout on both, different base.
PWM_BASE = 0x400A8000 if "RP2350" in os.uname().machine else 0x40050000
SLICE = (PIN_A >> 1) & 7
_BASE = PWM_BASE + 0x14 * SLICE
_CSR, _DIV, _CC, _TOP = _BASE + 0x00, _BASE + 0x04, _BASE + 0x0C, _BASE + 0x10

# CSR bit 3 inverts channel B. CSR bit 0 is the enable, which the PWM
# constructor below has already set.
_B_INV = 1 << 3

# The divider is 8.4 fixed point, so 0x010 is 1.0. Leaving it at 1 is
# what makes the frequency sysclk/(TOP+1) and nothing else.
_DIV_ONE = 0x010

SYSCLK = machine.freq()


def _tone(freq):
    """TOP and the CC word for a 50% square wave at `freq`.

    CC holds both channels: A in the low half, B in the high half. They
    get the same compare value, and B_INV turns B into A's mirror.
    """
    top = beacon.pwm_top(SYSCLK, freq)
    half = (top + 1) // 2
    return top, half | (half << 16)


TONE = (_tone(beacon.FSPACE), _tone(beacon.FMARK))

# Silence has to leave both pins low, not just stop the tone. Compare 0
# holds A low; compare TOP+1 holds B high, which B_INV turns into low.
# Anything else parks DC across the transducer for seconds at a time.
_QUIET_TOP = TONE[1][0]
_QUIET_CC = 0 | ((_QUIET_TOP + 1) << 16)

BIT_US = 1000000 // beacon.BAUD

if SLOT not in (0, 1):
    raise ValueError("SLOT is 0 or 1; there are two beacons")
if beacon.burst_ms(MESSAGE, BURST_FRAMES) > PERIOD_MS // 2:
    raise ValueError("a %d ms burst does not fit in half of a %d ms period, "
                     "so the two slots would overlap"
                     % (beacon.burst_ms(MESSAGE, BURST_FRAMES), PERIOD_MS))

# Precomputed once. The transmit loop allocates nothing, so a garbage
# collection cannot land in the middle of a bit.
PLAN = tuple(TONE[b] for b in beacon.burst(MESSAGE, BURST_FRAMES))


# ------------------------------------------------------------- the pins

def start_pwm():
    """Mux both pins to the slice, then take the slice over.

    machine.PWM does the part that is fiddly and undocumented -- the pad
    and function-select registers -- and its frequency is then thrown
    away. It picks a divider and a TOP to maximize duty resolution,
    which is the right trade for a servo and the wrong one here, where
    the only thing that matters is landing on the tone.
    """
    for pin in (PIN_A, PIN_B):
        pwm = machine.PWM(machine.Pin(pin))
        pwm.freq(40000)
        pwm.duty_u16(32768)
    machine.mem32[_DIV] = _DIV_ONE
    machine.mem32[_CSR] = machine.mem32[_CSR] | _B_INV
    silence()


def silence():
    machine.mem32[_TOP] = _QUIET_TOP
    machine.mem32[_CC] = _QUIET_CC


def transmit():
    """One burst, on absolute deadlines.

    Each bit ends at a time computed from when the burst started, never
    from when the last bit ended, so a slow iteration steals from itself
    instead of pushing everything after it late. Over 320 bits that is
    the difference between arriving on time and arriving a symbol adrift.

    Writing TOP while the counter is already past it wraps that one
    cycle early. It happens once per bit, at the boundary, and the
    receiver's 600 Hz filter never sees it.
    """
    mem32 = machine.mem32
    deadline = time.ticks_us()
    for top, cc in PLAN:
        mem32[_TOP] = top
        mem32[_CC] = cc
        deadline = time.ticks_add(deadline, BIT_US)
        while time.ticks_diff(deadline, time.ticks_us()) > 0:
            pass
    silence()


def report():
    print("beacon %r   slot %d   sysclk %d Hz" % (MESSAGE, SLOT, SYSCLK))
    for name, want, (top, _) in (("space", beacon.FSPACE, TONE[0]),
                                 ("mark ", beacon.FMARK, TONE[1])):
        got = beacon.pwm_freq(SYSCLK, top)
        print("  %s  want %9.1f   TOP %5d   got %9.1f  (%+.1f Hz)"
              % (name, want, top, got, got - want))
    print("  burst %d bits, %d ms, once every %d ms"
          % (len(PLAN), beacon.burst_ms(MESSAGE, BURST_FRAMES), PERIOD_MS))


def main():
    report()
    start_pwm()
    time.sleep_ms(SLOT * (PERIOD_MS // 2))
    while True:
        started = time.ticks_ms()
        transmit()
        rest = PERIOD_MS - time.ticks_diff(time.ticks_ms(), started)
        if rest > 0:
            time.sleep_ms(rest)


main()
