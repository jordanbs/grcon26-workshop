"""End-to-end runs of both tools against the fixture. No hardware."""

import os
import subprocess
import sys

import pytest

FIXTURE = "fixtures/m2k-snapshot.json"
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "golden", "channels-m2k-adc.txt")


def flat(text):
    """Collapse wrapping so prose assertions survive textwrap.

    The renderer hard-wraps at 78 columns, so any phrase long enough to be
    worth asserting on is likely to straddle a newline.
    """
    return " ".join(text.split())


def run(tools_root, *args):
    result = subprocess.run([sys.executable] + list(args), cwd=tools_root,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("verb", [
    [],                       # defaults to --channels
    ["--channels"],
    ["--tree"],
    ["--unknown"],
    ["--glossary"],
    ["--channels", "--verbose"],
])
def test_every_verb_runs(tools_root, verb):
    out = run(tools_root, "iio_explain.py", FIXTURE, *verb)
    assert out.strip()


def test_attr_lookup_by_bare_and_full_name(tools_root):
    bare = run(tools_root, "iio_explain.py", FIXTURE, "--attr", "raw",
               "--device", "m2k-adc", "--limit", "1")
    full = run(tools_root, "iio_explain.py", FIXTURE, "--attr",
               "in_voltage0_raw", "--device", "m2k-adc", "--limit", "1")
    assert "in_voltage0_raw" in bare
    assert "in_voltage0_raw" in full


def test_attr_shows_the_conversion_worked_out(tools_root):
    out = run(tools_root, "iio_explain.py", FIXTURE, "--attr", "raw",
              "--device", "m2k-adc", "--limit", "1")
    assert "(1234 + -2048) * 0.0625" in out
    assert "-50.875 mV" in out
    assert "-0.050875 V" in out


def test_attr_quotes_the_kernel(tools_root):
    out = run(tools_root, "iio_explain.py", FIXTURE, "--attr", "scale",
              "--device", "m2k-adc", "--limit", "1")
    assert "The kernel's own words" in out
    assert "Linux ABI sysfs-bus-iio" in out


def test_unverified_overlay_entries_are_always_marked(tools_root):
    out = run(tools_root, "iio_explain.py", FIXTURE, "--channels")
    # The ad9963 note is unverified and must never render as plain fact.
    assert "UNVERIFIED" in out


def test_missing_attr_exits_nonzero(tools_root):
    result = subprocess.run(
        [sys.executable, "iio_explain.py", FIXTURE, "--attr", "no_such_attr"],
        cwd=tools_root, capture_output=True, text=True)
    assert result.returncode == 1


def test_reads_from_stdin(tools_root):
    with open(os.path.join(tools_root, FIXTURE)) as handle:
        result = subprocess.run(
            [sys.executable, "iio_explain.py", "-", "--unknown"],
            cwd=tools_root, stdin=handle, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Coverage" in result.stdout


def test_glossary_is_markdown_with_the_central_rule(tools_root):
    out = run(tools_root, "iio_explain.py", FIXTURE, "--glossary")
    assert "# Reading IIO attribute names" in out
    assert "real value = (raw + offset) * scale" in out
    assert "| `voltage` |" in out


def test_discover_still_runs_without_libiio(tools_root):
    """The friendly libiio message must survive, just later than before."""
    result = subprocess.run([sys.executable, "iio_discover.py", "--summary"],
                            cwd=tools_root, capture_output=True, text=True)
    assert result.returncode != 0
    assert "libiio Python bindings" in (result.stdout + result.stderr)


def test_channels_output_matches_golden(tools_root):
    out = run(tools_root, "iio_explain.py", FIXTURE, "--channels",
              "--device", "m2k-adc")
    if os.environ.get("REGEN_GOLDEN"):
        with open(GOLDEN, "w") as handle:
            handle.write(out)
    with open(GOLDEN) as handle:
        assert out == handle.read(), \
            "output changed; review it, then REGEN_GOLDEN=1 pytest to accept"


def test_scan_hint_names_the_m2k_default_address():
    """--scan cannot discover a fixed-address board; it must say so."""
    import iio_discover

    hint = iio_discover.uri_hint()
    assert "ip:192.168.2.1" in hint
    assert "usb:" in hint
    # The reason matters more than the address -- it is why people give up.
    assert "does not advertise" in hint


STREAMING = "fixtures/streaming-channel.json"


def test_streaming_channel_explains_the_absent_raw(tools_root):
    """A buffered ADC has no _raw. That must be explained, not skipped."""
    out = run(tools_root, "iio_explain.py", STREAMING, "--channels")
    assert "no _raw attribute here, and that is expected" in flat(out)
    assert "this is a streaming channel" in flat(out)


def test_streaming_channel_still_shows_the_conversion(tools_root):
    out = run(tools_root, "iio_explain.py", STREAMING, "--channels")
    assert "real = (sample + -2048) * 0.007000" in flat(out)
    # The worked number must be flagged as illustrative, never as a reading.
    assert "an illustration, not a reading" in flat(out)


def test_streaming_channel_without_scale_says_so(tools_root):
    """voltage1 has no attributes at all -- do not silently show nothing."""
    out = run(tools_root, "iio_explain.py", STREAMING, "--channels")
    assert "nothing on this device tells you what they are worth" in flat(out)


def test_no_scale_falls_back_to_the_board_recipe(tools_root):
    """A real m2k-adc has no _scale, so the overlay has to supply it."""
    out = flat(run(tools_root, "iio_explain.py", STREAMING, "--channels"))
    assert "IIO will not tell you -- but libm2k computes it" in out
    assert "scale = 0.78 / (2048 * 1.3 * range_gain)" in out
    # The recipe reaches across to another device; say so.
    assert "gain` attribute on m2k-fabric" in out


def test_recipe_is_attributed_not_asserted(tools_root):
    out = flat(run(tools_root, "iio_explain.py", STREAMING, "--channels"))
    assert "[overlay: sourced]" in out
    assert "m2kanalogin_impl.cpp" in out


def test_unknown_device_gets_the_generic_fallback(tools_root):
    """No board pack means say so, not invent a recipe."""
    import json
    import os
    import tempfile

    with open(os.path.join(tools_root, STREAMING)) as handle:
        data = json.load(handle)
    data["devices"][0]["name"] = "some-other-adc"
    data["devices"][0]["id"] = "iio:device0"
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         dir=os.path.join(tools_root, "fixtures"))
    json.dump(data, handle)
    handle.close()
    try:
        out = flat(run(tools_root, "iio_explain.py",
                       os.path.relpath(handle.name, tools_root), "--channels"))
        assert "has to come from the datasheet or from a vendor library" in out
        assert "libm2k computes it" not in out
    finally:
        os.unlink(handle.name)
