"""The vendor's own view of which attributes matter.

The kernel ABI says what an attribute means; it cannot say whether you
will ever need it. libm2k can, for this board: an attribute it reads or
writes is one that operating the M2K as an instrument requires.
"""

import iio_libm2k_fetch as lib
import iio_semantics as sem

SAMPLE = '''
double M2kAnalogInImpl::getScalingFactor(ANALOG_IN_CHANNEL ch)
{
	auto gain = m_m2k_fabric->getStringValue(channel, "gain");
	return 0.0;
}

void M2kHardwareTriggerImpl::setAnalogLevelRaw(unsigned int chnIdx, int level)
{
	m_analog_channels[chnIdx]->setDoubleValue("trigger_level", level);
}
'''


def test_scan_finds_attribute_and_its_caller():
    found = {(a, k, m) for a, k, m in lib.scan(SAMPLE)}
    assert ("gain", "M2kAnalogInImpl", "getScalingFactor") in found
    assert ("trigger_level", "M2kHardwareTriggerImpl",
            "setAnalogLevelRaw") in found


def test_build_maps_classes_to_instruments():
    attrs = lib.build([SAMPLE])
    assert attrs["gain"]["instruments"] == ["Oscilloscope"]
    assert attrs["trigger_level"]["instruments"] == ["Trigger"]
    assert "M2kAnalogInImpl::getScalingFactor" in attrs["gain"]["methods"]


def test_plumbing_classes_are_not_instruments():
    """DeviceGeneric is libm2k's own plumbing, not something on the front."""
    assert lib.instrument_for("DeviceGeneric") is None
    assert lib.instrument_for("M2kAnalogInImpl") == "Oscilloscope"


def test_cached_data_covers_the_knobs_the_workshop_uses():
    data = lib.load()
    assert data, ("run ./iio-tools/iio_libm2k_fetch.py to build "
                  "iio_libm2k_data.json")
    for name, instrument in [("gain", "Oscilloscope"),
                             ("oversampling_ratio", "Oscilloscope"),
                             ("trigger_level", "Trigger"),
                             ("direction", "Logic analyser and pattern "
                                           "generator")]:
        entry = lib.lookup(data, name)
        assert entry, name
        assert instrument in entry["instruments"], name


def test_absence_is_not_a_verdict_on_importance():
    """scale and offset are absent because libm2k computes the scope
    conversion itself rather than reading it back. They remain central to
    every other IIO device, so nothing may treat absence as 'ignore me'."""
    assert sem.libm2k_use("scale") is None
    assert sem.libm2k_use("offset") is None
    # ...while the ABI layer still explains them fully.
    assert sem.info_word_info("scale")["summary"]
    assert sem.abi_reference("in_voltage0_scale") is not None


def test_annotation_carries_it_to_the_browser(real_snapshot):
    import iio_explain
    annotated = iio_explain.annotate(real_snapshot)
    fabric = [d for d in annotated["devices"] if d["label"] == "m2k-fabric"][0]
    gain = [a for c in fabric["channels"] for a in c["attrs"]
            if a["name"] == "gain"][0]
    assert gain["libm2k"]["instruments"] == ["Oscilloscope"]
    assert any(s.get("libm2k") for s in fabric["settings"])


def test_every_touched_attribute_names_a_method():
    data = lib.load()
    for name, entry in data["attrs"].items():
        assert entry["methods"], name
