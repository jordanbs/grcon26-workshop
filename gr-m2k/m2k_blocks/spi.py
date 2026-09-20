"""The two SPI blocks -- messages to three DIO streams, and back again.

The arithmetic is `spi_encode.SpiEncoder` and `spi_decode.SpiDecoder`,
which import nothing and are tested on their own. This file is the GNU
Radio wrapper around both, and the wrapper is where the decisions live
that the pure classes have no opinion about.

The first is why the decoder's output is a message and not a stream. A
frame is hundreds of samples and carries however many bytes the message
had, so the output rate is a small fraction of the input rate -- and it
is not fixed, because CS decides how long a frame is. A sync_block
cannot express
that, and the general_work/forecast version of it spends its whole life
explaining to the scheduler how many samples it might consume. A
message port sidesteps the arithmetic entirely: bytes come out when
there are bytes, and Message Debug prints them.

The encoder's side of the same question is why it is a source with no
stream input at all. It produces idle for as long as anyone asks, which
means the Digital Sink downstream never starves between messages, and
the sink's blocking push is what paces the graph. A message arriving
mid-buffer is queued and goes out at the start of the next one.

The second is `.tolist()`. GNU Radio hands work() numpy arrays, and
element-wise indexing of a numpy array from Python is about twenty
times slower than of a list -- measured at 0.84 s versus 0.04 s per
million samples. At 1 MS/s that is the difference between using 4% of
real time and not keeping up. The conversion itself costs 0.03 s per
million, so it pays for itself many times over.
"""

import numpy
import pmt

from gnuradio import gr

from .spi_decode import SpiDecoder, as_text
from .spi_encode import SpiEncoder

SCLK, MOSI, CS = 0, 1, 2

# The decoder's output and the encoder's input are different ports with
# different names, and the names are not cosmetic: GNU Radio Companion
# uses the port label from the .yml when it writes msg_connect, so a port
# registered under some other name is a connection that fails at runtime.
PORT = pmt.intern("bytes")
MESSAGE = pmt.intern("message")
TEXT = pmt.intern("text")


class spi_decode(gr.sync_block):
    """Decode an SPI mode 0 bus from three digital streams.

    Ports are SCLK, MOSI and CS in that order, one bit per sample in a
    short, which is what M2K Digital Source produces. Wire the three
    pins the bus actually uses; the block does not know or care which
    DIO numbers they came from.

    With `add_text` the outgoing PDU's metadata carries the bytes as
    characters as well -- a text column beside the hex. Ignored for
    words wider than eight bits.
    """

    def __init__(self, bits_per_word=8, cs_active_low=True, add_text=True):
        gr.sync_block.__init__(
            self, name="m2k_spi_decode",
            in_sig=[numpy.int16] * 3, out_sig=[])
        self.decoder = SpiDecoder(bits_per_word=bits_per_word,
                                  cs_active_low=cs_active_low)
        self.add_text = bool(add_text)
        self.message_port_register_out(PORT)

    def start(self):
        """Start clean, so a second run inherits no half-built word."""
        self.decoder.reset()
        return True

    def work(self, input_items, output_items):
        count = len(input_items[SCLK])
        words = self.decoder.feed(input_items[SCLK].tolist(),
                                  input_items[MOSI].tolist(),
                                  input_items[CS].tolist())
        if words:
            self.message_port_pub(PORT, self._pdu(words))
        return count

    def _pdu(self, words):
        """Words as a PDU: metadata and a vector of the values.

        The vector width follows the word width, because a u8vector
        cannot hold a 16-bit SPI word and pmt will not say so politely.

        The metadata carries the same words as text, which is what
        makes the loopback self-evident: type M2K, get `4d 32 4b` and
        `M2K` in the same Message Debug print. It is metadata rather
        than the payload because the bytes are what was actually on the
        wire and the text is a reading of them -- and above eight bits
        a word is not a character at all, so there is nothing to read.
        """
        width = self.decoder.bits_per_word
        if width <= 8:
            vector = pmt.init_u8vector(len(words), words)
        elif width <= 16:
            vector = pmt.init_u16vector(len(words), words)
        else:
            vector = pmt.init_u32vector(len(words), words)
        meta = pmt.make_dict()
        if self.add_text and width <= 8:
            meta = pmt.dict_add(meta, TEXT, pmt.intern(as_text(words)))
        return pmt.cons(meta, vector)


class spi_encode(gr.sync_block):
    """Build an SPI mode 0 bus on three digital streams from messages.

    Outputs are SCLK, MOSI and CS in that order, one bit per sample in
    a short, which is what M2K Digital Sink expects. Between messages
    all three sit at idle, so this block is a source that never runs
    dry -- wire it straight into the Sink and the bus rests until you
    send something.

    Set `align` to the Sink's buffer size when the Sink is not cyclic.
    See `spi_encode.SpiEncoder` for why.
    """

    def __init__(self, bits_per_word=8, cs_active_low=True, half=8,
                 lead=64, setup=8, tail=8, gap=48, align=0):
        gr.sync_block.__init__(
            self, name="m2k_spi_encode",
            in_sig=[], out_sig=[numpy.int16] * 3)
        self.encoder = SpiEncoder(bits_per_word=bits_per_word,
                                  cs_active_low=cs_active_low, half=half,
                                  lead=lead, setup=setup, tail=tail, gap=gap,
                                  align=align)
        self.message_port_register_in(MESSAGE)
        self.set_msg_handler(MESSAGE, self.queue)

    def start(self):
        """Start clean, so a second run does not resume the first."""
        self.encoder.reset()
        return True

    def queue(self, message):
        """Accept text or a byte vector and queue it as one frame.

        The GUI edit box sends a symbol, the PDU blocks send a pair, and
        a bare vector is what a script writing straight to the port will
        reach for. All three mean the same thing here.
        """
        words = self._words(message)
        if words is None:
            return
        try:
            self.encoder.send(words)
        except ValueError as exc:
            # A word too wide for the bus is the sender's mistake, not a
            # reason to take the flowgraph down mid-run.
            gr.log.warn("m2k_spi_encode dropped a message: %s" % exc)

    @staticmethod
    def _words(message):
        """The values to clock out, or None if this is not a message."""
        if pmt.is_pair(message) and not pmt.is_vector(message):
            message = pmt.cdr(message)
        if pmt.is_symbol(message):
            return list(pmt.symbol_to_string(message).encode())
        for is_vector, to_list in ((pmt.is_u8vector, pmt.u8vector_elements),
                                   (pmt.is_u16vector, pmt.u16vector_elements),
                                   (pmt.is_u32vector, pmt.u32vector_elements)):
            if is_vector(message):
                return list(to_list(message))
        gr.log.warn("m2k_spi_encode ignored a message it cannot send: %s"
                    % pmt.write_string(message))
        return None

    def work(self, input_items, output_items):
        count = len(output_items[SCLK])
        lines = self.encoder.pull(count)
        for port, line in enumerate(lines):
            output_items[port][:] = line
        return count
