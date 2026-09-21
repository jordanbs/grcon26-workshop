"""SPI mode 0, decoded from three streams of levels, with nothing imported.

Kept clear of GNU Radio and of numpy on purpose, the same way
`m2k_scale` is: this is the part that has to be right, and it should be
testable on a machine with no gnuradio, no libiio, no board and no
third-party packages at all.

Mode 0 only. CPOL=0, CPHA=0 means the clock rests low, the transmitter
puts a bit on MOSI while the clock is low, and the receiver samples it
on the rising edge -- so a rising edge with chip select asserted is a
bit, and that single sentence is the whole decoder. Modes 1-3 move
which edge samples, which is a two-line change, but no capture in this
repo contains one, and an untested dropdown is worse than no dropdown.

Chip select does the framing. A byte is only worth anything if you know
where it started, and on a bus there is no start bit to find -- the
falling edge of CS is the start, and the rising edge is the end. That
also means the decoder REFUSES to emit anything until it has seen a
falling CS. A capture that begins in the middle of a frame has some
unknown number of bits already gone, and eight of the remaining ones
make a byte that is real, plausible, and wrong.

Bits arrive MSB first, which is what SPI does unless a datasheet says
otherwise, and what every M2K bench capture in this repo used.

The decoder is fed in chunks and keeps its state between them, because
a GNU Radio work() call is handed whatever happened to be in the buffer
and a frame does not care where that lands. Everything a byte in
progress needs -- the last clock level, whether CS is asserted, the
bits so far -- lives on the instance rather than in the loop.

`as_text` is the one thing in here that is not decoding. A character
column beside the hex is there for one reason: what proves a loopback
worked is seeing the word you typed come back out, not doing the ASCII
lookup in your head.
"""


class SpiDecoder:
    """Streaming SPI mode 0 decoder. Feed it levels, get bytes back.

        dec = SpiDecoder()
        dec.feed(sclk, mosi, cs)     ->  [0xA5]

    `sclk`, `mosi` and `cs` are equal-length sequences of one sample
    each, and anything non-zero is a one. Plain lists: element-wise
    indexing of a numpy array is twenty times slower than of a list,
    which at 1 MS/s is the difference between 4% of real time and not
    keeping up. Callers holding arrays should `.tolist()` first.
    """

    def __init__(self, bits_per_word=8, cs_active_low=True):
        bits_per_word = int(bits_per_word)
        if bits_per_word < 1 or bits_per_word > 32:
            raise ValueError("bits per word must be between 1 and 32, got %r"
                             % bits_per_word)
        self.bits_per_word = bits_per_word
        self.cs_active_low = bool(cs_active_low)
        self.reset()

    def reset(self):
        """Forget everything, including that a frame was ever seen.

        Called at construction and again at flowgraph start, so a second
        run does not inherit half a byte from the first.
        """
        self._prev_clock = 0
        self._asserted = False
        self._armed = False
        self._word = 0
        self._bits = 0

        # Counters the block reports rather than the decode uses.
        self.frames = 0            # complete CS assertions seen
        self.partial_bits = 0      # bits dropped at a CS release

    def feed(self, sclk, mosi, cs):
        """Decode one chunk. Returns the words that completed in it.

        Words complete where they complete: a chunk boundary that lands
        mid-byte returns nothing for that byte, and the next chunk
        returns it.
        """
        out = []
        prev_clock = self._prev_clock
        asserted = self._asserted
        armed = self._armed
        word = self._word
        bits = self._bits
        active = 0 if self.cs_active_low else 1
        width = self.bits_per_word

        for index in range(len(sclk)):
            select = 1 if cs[index] else 0
            now = 1 if sclk[index] else 0

            if (select == active) != asserted:
                asserted = not asserted
                if asserted:
                    # Falling CS (or rising, on an active-high bus).
                    # This is the only thing that arms the decoder, and
                    # it is also where a part-built word is abandoned.
                    armed = True
                    word = 0
                    bits = 0
                else:
                    self.frames += 1
                    self.partial_bits += bits
                    word = 0
                    bits = 0

            if armed and asserted and now and not prev_clock:
                word = (word << 1) | (1 if mosi[index] else 0)
                bits += 1
                if bits == width:
                    out.append(word)
                    word = 0
                    bits = 0

            prev_clock = now

        self._prev_clock = prev_clock
        self._asserted = asserted
        self._armed = armed
        self._word = word
        self._bits = bits
        return out


def as_text(words):
    """Recovered words as the characters they stand for.

    Printable ASCII passes through; everything else comes out as
    `\\xNN`, so a byte that is not text still says which byte it was.
    A dot for every unprintable would be shorter and would throw away
    the only information the column had. A literal backslash is
    doubled, so the escapes cannot be confused with real backslashes.

    Only meaningful for byte-wide words. Nothing here checks that --
    the caller knows the bus width and this function does not.
    """
    out = []
    for word in words:
        if word == 0x5c:
            out.append("\\\\")
        elif 0x20 <= word < 0x7f:
            out.append(chr(word))
        else:
            out.append("\\x%02x" % word)
    return "".join(out)
