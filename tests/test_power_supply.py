"""What the power supply block writes, and in what order.

The arithmetic is checked in test_m2k_scale.py with no hardware and no
GNU Radio. This checks the other half: that bringing a rail up, moving
it, and taking it down produce the right sequence of attribute writes on
the right devices.

No board is involved. `write_now` is replaced with a recorder, so these
run anywhere -- and because every write in this block goes through that
one function, the recording is the complete story. That is only true
while the block keeps its promise of writing directly and never through
an attr_updater; a keep-alive would be invisible here, which is a second
reason the tests below check for its absence explicitly.

The block imports gnuradio, so it cannot be exercised in the interpreter
running the suite. Same arrangement as test_grc_integration: find a
Python that has it, run the scenario there, bring back JSON.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from test_grc_integration import GR_PYTHON, needs_gnuradio

# Each scenario runs in a fresh interpreter, so the recorder is a module
# global rather than anything cleverer.
HARNESS = '''
    import json, sys
    sys.path.insert(0, sys.argv[1] + "/gr-m2k")

    from m2k_blocks import m2k_config

    WRITES = []
    def recorder(uri, device, channel, attr, value, output=False,
                 kind=m2k_config.ATTR_CHANNEL, keepalive=True):
        WRITES.append({"device": device, "channel": channel, "attr": attr,
                       "value": str(value), "keepalive": bool(keepalive)})
        return True
    m2k_config.write_now = recorder

    # The calibration lookup would go to a board that is not there.
    m2k_config.context_float = lambda uri, key, default: (
        {"cal,gain_pos_dac": 0.9986241178820292,
         "cal,offset_pos_dac": 0.0031,
         "cal,gain_neg_dac": 0.9998223185539246,
         "cal,offset_neg_dac": 0.0166}.get(key, default))
    m2k_config.channels_with_label = lambda *a, **k: []

    import m2k_blocks.power_supply as psmod
    # The module imported the originals by name at import time.
    psmod.write_now = recorder
    psmod.context_float = m2k_config.context_float
    psmod.channels_with_label = m2k_config.channels_with_label

    made = []
    def built(**kwargs):
        ps = psmod.power_supply(**kwargs)
        made.append(ps)
        return ps
'''


REPORT = '''
    print(json.dumps({"writes": WRITES,
                      "raw": [p.commanded_raw() for p in made]}))
'''


def scenario(repo_root, body):
    """Run `body` against the block and return the writes it produced."""
    # Each piece is dedented on its own. Dedenting the concatenation does
    # nothing useful, because the three of them are written at different
    # indents and the common prefix comes out empty.
    script = "".join(textwrap.dedent(part)
                     for part in (HARNESS, body, REPORT))
    result = subprocess.run([GR_PYTHON, "-c", script, repo_root],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout)


def steps(out):
    """The writes as terse tuples, for comparing whole sequences."""
    return [(w["device"], w["channel"], w["attr"], w["value"])
            for w in out["writes"]]


@needs_gnuradio
def test_bringing_a_rail_up_parks_the_dac_before_enabling_it(repo_root):
    """Reset code first, then the two enables.

    Out of order, the rail briefly carries whatever the last program left
    in the register -- which for a workshop room means the previous
    participant's voltage appearing on the header.
    """
    out = scenario(repo_root, '''
        built(uri="ip:0.0.0.0", rail="v+", voltage=5.0)
    ''')
    assert steps(out) == [
        ("ad5627", "voltage0", "raw", "2048"),
        ("ad5627", "voltage0", "powerdown", "0"),
        ("m2k-fabric", "voltage2", "powerdown", "0"),
        ("ad5627", "voltage0", "raw", "3396"),
    ]


@needs_gnuradio
def test_taking_a_rail_down_disables_before_parking(repo_root):
    """The mirror image: enable off first, register after."""
    out = scenario(repo_root, '''
        ps = built(uri="ip:0.0.0.0", rail="v+", voltage=5.0)
        WRITES.clear()
        ps.power_down()
    ''')
    assert steps(out) == [
        ("m2k-fabric", "voltage2", "powerdown", "1"),
        ("ad5627", "voltage0", "powerdown", "1"),
        ("ad5627", "voltage0", "raw", "2048"),
    ]
    assert out["raw"] == [None]


@needs_gnuradio
def test_nothing_is_kept_alive(repo_root):
    """Every write is direct, including the two powerdowns.

    A keep-alive on a powerdown is a keep-alive that turns the rail back
    on, one second after power_down(). This is the test that stops
    somebody restoring the updater pair for consistency with the other
    blocks.
    """
    out = scenario(repo_root, '''
        ps = built(uri="ip:0.0.0.0", rail="v-", voltage=-5.0)
        ps.power_down()
    ''')
    assert out["writes"], "no writes recorded at all"
    assert not any(w["keepalive"] for w in out["writes"])


@needs_gnuradio
def test_the_negative_rail_uses_its_own_channels(repo_root):
    """v- is ad5627 voltage1 and fabric voltage3, not the positive pair."""
    out = scenario(repo_root, '''
        built(uri="ip:0.0.0.0", rail="v-", voltage=-5.0)
    ''')
    assert steps(out)[-1] == ("ad5627", "voltage1", "raw", "3334")
    assert ("m2k-fabric", "voltage3", "powerdown", "0") in steps(out)


@needs_gnuradio
def test_a_labelled_fabric_channel_beats_the_hardcoded_index(repo_root):
    """The board says which channels are the rails; believe it over libm2k."""
    out = scenario(repo_root, '''
        psmod.channels_with_label = lambda *a, **k: ["voltage7", "voltage9"]
        built(uri="ip:0.0.0.0", rail="v-", voltage=-1.0)
    ''')
    assert ("m2k-fabric", "voltage9", "powerdown", "0") in steps(out)
    assert not [s for s in steps(out) if s[1] == "voltage3"]


@needs_gnuradio
def test_a_dragged_slider_collapses_to_one_write(repo_root):
    """Ten setpoints inside the interval cost one write, at the last value."""
    out = scenario(repo_root, '''
        import time
        ps = built(uri="ip:0.0.0.0", rail="v+", voltage=0.0)
        WRITES.clear()
        for step in range(10):
            ps.set_voltage(step * 0.5)
        time.sleep(0.4)
    ''')
    assert steps(out) == [("ad5627", "voltage0", "raw", "3057")]


@needs_gnuradio
def test_a_deferred_setpoint_cannot_land_after_teardown(repo_root):
    """power_down() cancels the limiter rather than racing it.

    Otherwise the rail is off but its register holds a live code, and the
    board's state disagrees with what the block says it is.
    """
    out = scenario(repo_root, '''
        import time
        ps = built(uri="ip:0.0.0.0", rail="v+", voltage=0.0)
        ps.set_voltage(5.0)
        ps.power_down()
        time.sleep(0.4)
    ''')
    assert steps(out)[-1] == ("ad5627", "voltage0", "raw", "2048")


@needs_gnuradio
def test_uncalibrated_gives_the_nominal_code(repo_root):
    """Turning calibration off is visible in the code, or it did nothing."""
    out = scenario(repo_root, '''
        built(uri="ip:0.0.0.0", rail="v+", voltage=5.0, calibrated=False)
    ''')
    assert steps(out)[-1] == ("ad5627", "voltage0", "raw", "3399")
