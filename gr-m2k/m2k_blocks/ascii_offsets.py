"""The GNU Radio wrapper around `ascii_scan`.

Thirty lines of buffering around a module that imports nothing, the
same split `spi.py` has over `spi_decode.py`. Everything here is window
management; the search itself is in `ascii_scan.scan`.

Windows overlap by `min_chars` bytes so a run straddling a boundary
stays whole. That same run is then found twice, once in each window, so
a hit covering bits already reported is dropped. Position decides it,
not the text -- the next burst says exactly the same thing, and watching
it arrive is half of why anyone runs this.
"""

import numpy

from gnuradio import gr

from .ascii_scan import MIN_CHARS, scan


class ascii_offsets(gr.sync_block):
    """Print whatever reads as text, at whichever byte offset it reads at.

    A sink: it consumes bits and prints, and has no output port. Wire it
    off a Binary Slicer, in parallel with whatever else is reading the
    same bits.
    """

    def __init__(self, min_chars=MIN_CHARS, window_bits=2048,
                 try_inverted=True, max_lines=4):
        gr.sync_block.__init__(self, name="ascii_offsets",
                               in_sig=[numpy.uint8], out_sig=[])
        self.min_chars = int(min_chars)
        self.window_bits = int(window_bits)
        self.try_inverted = bool(try_inverted)
        self.max_lines = int(max_lines)
        self._buf = []
        self._base = 0          # absolute bit index of _buf[0]
        self._prev = []         # (start, end) of the previous window's hits

    def _report(self, hits):
        lines = 0
        for hit in hits:
            if any(hit.overlaps(start, end) for start, end in self._prev):
                continue
            print(hit.line())
            lines += 1
            if lines >= self.max_lines:
                break
        self._prev = [(h.start, h.end) for h in hits]

    def work(self, input_items, output_items):
        self._buf.extend(input_items[0].tolist())
        # Overlap by min_chars bytes, so nothing is cut in half.
        advance = self.window_bits - 8 * self.min_chars
        while len(self._buf) >= self.window_bits:
            self._report(scan(self._buf[:self.window_bits], self._base,
                              self.min_chars, self.try_inverted))
            self._buf = self._buf[advance:]
            self._base += advance
        return len(input_items[0])
