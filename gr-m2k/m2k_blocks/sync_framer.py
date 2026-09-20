"""The GNU Radio wrapper around `sync_frames`.

Tags in, PDUs out. Everything here is tag bookkeeping; the judgement
about what is a frame and what is the gap between two bursts lives in
`sync_frames.SyncFramer`, which imports nothing.
"""

import numpy
import pmt

from gnuradio import gr

from .sync_frames import SyncFramer

# GRC writes msg_connect from the port label in the .yml, so a port
# registered under a different name is a connection that fails at run
# time rather than on the canvas. Same trap as spi.py's `bytes`.
PORT = pmt.intern("pdus")


class sync_framer(gr.sync_block):
    """One PDU per sync-delimited payload.

    Wire it downstream of Correlate Access Code - Tag, on the same bit
    stream, and give it the tag key that block writes.
    """

    def __init__(self, tag_key="sync", sync_bits=32, min_bits=64,
                 max_bits=1024, preamble_byte=0xAA):
        gr.sync_block.__init__(self, name="sync_framer",
                               in_sig=[numpy.uint8], out_sig=[])
        self.framer = SyncFramer(sync_bits=sync_bits, min_bits=min_bits,
                                 max_bits=max_bits,
                                 preamble_byte=preamble_byte)
        self._key = pmt.intern(tag_key)
        self.message_port_register_out(PORT)

    @property
    def stats(self):
        """Why spans were thrown away. A tally, not a log -- at 200 baud
        the rejections are the normal shape of a bursty link."""
        return self.framer.stats

    def work(self, input_items, output_items):
        inp = input_items[0]
        base = self.nitems_read(0)
        tags = [int(t.offset - base)
                for t in self.get_tags_in_window(0, 0, len(inp), self._key)]
        for payload in self.framer.push(inp.tolist(), tags):
            data = list(bytearray(payload))
            self.message_port_pub(
                PORT, pmt.cons(pmt.PMT_NIL,
                               pmt.init_u8vector(len(data), data)))
        return len(inp)
