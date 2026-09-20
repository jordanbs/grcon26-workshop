"""The kernel ABI ingest -- parsing and lookup, using the cached file."""

import iio_abi_fetch as abi
import iio_semantics as sem

SAMPLE = """\
What:\t\t/sys/bus/iio/devices/iio:deviceX/in_voltageY_raw
What:\t\t/sys/bus/iio/devices/iio:deviceX/in_voltage_raw
KernelVersion:\t2.6.35
Contact:\tlinux-iio@vger.kernel.org
Description:
\t\tRaw voltage measurement from channel Y.

\t\tA second paragraph.

What:\t\t/sys/bus/iio/devices/iio:deviceX/buffer/length
KernelVersion:\t2.6.35
Contact:\tlinux-iio@vger.kernel.org
Description:
\t\tNumber of scans in the buffer.
"""


def test_parses_blocks_and_paragraphs():
    blocks = abi.parse_abi(SAMPLE, "test")
    assert len(blocks) == 2
    assert blocks[0]["description"] == ["Raw voltage measurement from "
                                        "channel Y.", "A second paragraph."]
    assert blocks[0]["kernel_version"] == "2.6.35"


def test_index_normalisation_matches_concrete_names():
    blocks = abi.parse_abi(SAMPLE, "test")
    data = {"blocks": blocks, "index": abi.build_index(blocks)}
    found = abi.lookup(data, "in_voltage0_raw")
    assert found is not None
    assert "Raw voltage" in found["description"][0]


def test_buffer_attrs_are_found_under_their_subdirectory():
    blocks = abi.parse_abi(SAMPLE, "test")
    data = {"blocks": blocks, "index": abi.build_index(blocks)}
    assert abi.lookup(data, "length", "buffer") is not None
    # Without the buffer hint the bare name is not documented at top level.
    assert abi.lookup(data, "nonsense") is None


def test_normalise_handles_indices_and_placeholders():
    assert abi.normalize("in_voltageY_raw") == "in_voltage_raw"
    assert abi.normalize("in_voltage0_raw") == "in_voltage_raw"
    assert abi.normalize("in_voltage0-voltage1_raw") == "in_voltage-voltage_raw"
    assert abi.normalize("sampling_frequency") == "sampling_frequency"


def test_cached_data_is_present_and_covers_the_basics():
    """The checked-in cache must actually answer the common attributes."""
    data = abi.load()
    assert data, "run ./iio-tools/iio_abi_fetch.py to build iio_abi_data.json"
    for name in ("in_voltage0_raw", "in_voltage0_scale", "in_voltage0_offset",
                 "sampling_frequency"):
        assert abi.lookup(data, name), name


def test_kernel_confirms_offset_before_scale():
    """Our central teaching claim must match the kernel's own wording."""
    block = sem.abi_reference("in_voltage0_offset")
    text = " ".join(block["description"]).lower()
    assert "prior to scaling" in text
