"""Does GNU Radio actually accept what we generate?

Everything else in this suite checks our own reasoning about gr-iio. This
checks it against GNU Radio itself: GRC's real block loader, its real
flowgraph validator, and its real code generator.

It needs a Python with `gnuradio` importable, which is often not the one
running the tests -- distro packages build for the system interpreter. So
it hunts for one and skips if there is none, rather than failing on a
machine that simply has no GNU Radio.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

CANDIDATES = ["python3.12", "python3.11", "python3.10", "python3", sys.executable]


def _find_python_with_gnuradio():
    for name in CANDIDATES:
        path = shutil.which(name) if not os.path.isabs(name) else name
        if not path:
            continue
        probe = subprocess.run(
            [path, "-c", "import gnuradio.grc.core.platform"],
            capture_output=True)
        if probe.returncode == 0:
            return path
    return None


GR_PYTHON = _find_python_with_gnuradio()
needs_gnuradio = pytest.mark.skipif(
    GR_PYTHON is None, reason="no Python with gnuradio available")

# A few tests read the block and flowgraph YAML in THIS interpreter rather
# than in `GR_PYTHON`, and this project has no dependencies on purpose -- so
# PyYAML is only ever here by accident. GRC pulls it in, but for whichever
# interpreter the distro built gnuradio for, which is precisely the one
# `_find_python_with_gnuradio` exists because it is not us. Skip on the same
# rule as the rest of the file: a missing dependency is not a failure.
needs_yaml = pytest.mark.skipif(
    importlib.util.find_spec("yaml") is None,
    reason="no PyYAML in the interpreter running the tests")


def run_in_gr(script, *args):
    result = subprocess.run([GR_PYTHON, "-c", textwrap.dedent(script)] + list(args),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


@pytest.fixture(scope="session")
def generated_blocks(tmp_path_factory, repo_root, real_snapshot):
    """Write our generated block definitions somewhere GRC can find them."""
    import iio_grc
    out = tmp_path_factory.mktemp("blocks")
    for name, text in iio_grc.generate_all(real_snapshot).items():
        (out / name).write_text(text)
    return str(out)


LOAD = '''
    import json, logging, sys
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3", "10", "0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
    print(json.dumps({k: len(b.parameters_data)
                      for k, b in p.blocks.items() if k.startswith("m2k_")}))
'''


@needs_gnuradio
def test_generated_blocks_load_in_grc(generated_blocks):
    """Valid YAML is not the same as a block GRC will accept."""
    loaded = json.loads(run_in_gr(LOAD, generated_blocks))
    assert len(loaded) == 5, loaded
    assert "m2k_m2k_adc_source" in loaded
    assert "m2k_m2k_dac_a_sink" in loaded


BUILD = '''
    import ast, json, logging, sys, tempfile
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3", "10", "0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks"] + sys.argv[2:])
    fg = p.make_flow_graph(sys.argv[1])
    fg.rewrite(); fg.validate()
    errors = list(fg.iter_error_messages())
    out = tempfile.mkdtemp()
    p.Generator(fg, out).write()
    # An embedded Python block is written out as its own module beside the
    # flowgraph, so there is more than one .py here and listdir has no order.
    # Take the one named after the .grc.
    import os
    name = os.path.basename(sys.argv[1]).replace(".grc", ".py")
    source = open(os.path.join(out, name)).read()
    ast.parse(source)          # a flowgraph that will not compile is not valid
    # A make template can span several lines, so take the whole
    # constructor call, not just the line its name appears on.
    lines = source.splitlines()
    grabbed = []
    for i, line in enumerate(lines):
        if "iio." in line or "set_len_tag_key" in line:
            grabbed.extend(l.strip() for l in lines[i:i + 4])
    print(json.dumps({"valid": fg.is_valid(), "errors": errors,
                      "iio": grabbed, "make": source}))
'''


@needs_gnuradio
def test_stock_loopback_builds_and_generates(repo_root):
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback.grc")
    result = json.loads(run_in_gr(BUILD, path))
    assert result["valid"], result["errors"]
    joined = " ".join(result["iio"])
    # The two shapes we claim gr-iio has, straight from GRC's own codegen.
    assert "iio.device_source(uri, 'm2k-adc', ['voltage0'], ''" in joined
    assert "16384, 1 - 1)" in joined
    assert "iio.device_sink(uri, 'm2k-dac-a'" in joined
    assert "1 - 1, False)" in joined
    assert "set_len_tag_key" in joined


@needs_gnuradio
def test_generated_block_loopback_builds(repo_root, generated_blocks):
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback_generated.grc")
    result = json.loads(run_in_gr(BUILD, path, generated_blocks))
    assert result["valid"], result["errors"]
    joined = " ".join(result["iio"])
    assert "iio.device_source(uri, 'm2k-adc'" in joined
    assert "iio.device_sink(uri, 'm2k-dac-a'" in joined


@needs_gnuradio
def test_an_untouched_dropdown_writes_nothing(repo_root, generated_blocks):
    """"Shown" must never mean "set".

    Every dropdown defaults to empty, and the make template filters those
    out, so a block that has been opened and closed writes nothing to the
    hardware. Checked in GRC's generated code, not in ours.
    """
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback_generated.grc")
    result = json.loads(run_in_gr(BUILD, path, generated_blocks))
    joined = " ".join(result["iio"])
    assert "if v]" in joined
    assert "('calibrate', '')" in joined      # present, and filtered out
    assert "'sampling_frequency=1000000'" in joined   # the one we did set


@needs_gnuradio
@needs_yaml
def test_flowgraph_description_stays_single_line(repo_root):
    """GRC comments out only the first line of a description.

    A multi-line one drops the rest into the generated file as bare Python,
    which does not parse. Found the hard way; pinned so it stays fixed.
    """
    import yaml
    for name in ("m2k_loopback.grc", "m2k_loopback_generated.grc"):
        with open(os.path.join(repo_root, "flowgraphs", name)) as handle:
            doc = yaml.safe_load(handle)
        description = doc["options"]["parameters"].get("description", "")
        assert "\n" not in description.strip(), name


# ------------------------------------------------ the instrument blocks

M2K_GRC = "gr-m2k/grc"


@needs_gnuradio
def test_scope_block_loads_and_reads_plainly(repo_root):
    """Every parameter must say what it does and what its values are."""
    loaded = json.loads(run_in_gr('''
        import json, logging, sys
        logging.disable(logging.CRITICAL)
        from gnuradio.grc.core.platform import Platform
        p = Platform(version="3.10", version_parts=("3","10","0"), prefs=None)
        p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
        b = p.blocks["m2k_analog_source"]
        print(json.dumps({"label": b.label, "category": list(b.category),
                          "params": [{"id": q["id"], "label": q.get("label"),
                                      "options": q.get("option_labels")}
                                     for q in b.parameters_data
                                     if q.get("label")]}))
    ''', os.path.join(repo_root, M2K_GRC)))

    assert loaded["label"] == "M2K Analog Source"
    assert loaded["category"] == ["ADALM2000"]
    labels = {q["id"]: q["label"] for q in loaded["params"]}

    # Nothing a participant sees may be IIO vocabulary.
    forbidden = ("iio", "phy", "attr", "context", "uri", "oversampl", "sysfs")
    for name in labels.values():
        assert not any(word in name.lower() for word in forbidden), name

    # And the units belong in the label, not in the documentation.
    assert labels["trigger_level"] == "Trigger level (V)"
    assert labels["uri"] == "M2K address"


@needs_gnuradio
@needs_yaml
def test_option_labels_survived_yaml(repo_root):
    """YAML 1.1 reads On/Off/Yes/No as booleans.

    `option_labels: [On, Off]` silently becomes True/False on screen.
    """
    import yaml
    for name in os.listdir(os.path.join(repo_root, M2K_GRC)):
        with open(os.path.join(repo_root, M2K_GRC, name)) as handle:
            doc = yaml.safe_load(handle)
        for prm in doc["parameters"]:
            for label in prm.get("option_labels", []):
                assert isinstance(label, str), (name, prm["id"], label)


@needs_gnuradio
def test_scope_flowgraph_builds(repo_root):
    path = os.path.join(repo_root, "flowgraphs", "m2k_scope.grc")
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]


ASSERTS = '''
    import copy, json, logging, os, sys, tempfile, yaml
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3","10","0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
    base = yaml.safe_load(open(sys.argv[2]))
    out = {}
    for label, params in json.loads(sys.argv[3]).items():
        doc = copy.deepcopy(base)
        for blk in doc["blocks"]:
            if blk["id"] == "m2k_analog_source":
                blk["parameters"].update(params)
        path = tempfile.mktemp(suffix=".grc")
        yaml.safe_dump(doc, open(path, "w"))
        fg = p.make_flow_graph(path); fg.rewrite(); fg.validate()
        out[label] = fg.is_valid()
        os.unlink(path)
    print(json.dumps(out))
'''


@needs_gnuradio
def test_illegal_combinations_are_refused(repo_root):
    """A wrong setting should be refused in GRC, not discovered at run time.

    The trigger-level check is the one that matters: a level outside the
    selected input range can never fire, and nothing else would say so.
    """
    cases = {
        "ok": {},
        "no channels": {"ch1_enabled": "False", "ch2_enabled": "False"},
        "zero buffer": {"buffer_size": "0"},
        "40 V level on the 25 V range": {"trigger_level": "40.0"},
        "4 V level on the 2.5 V range": {"trigger_level": "4.0",
                                         "ch1_range": "'high'"},
    }
    result = json.loads(run_in_gr(
        ASSERTS, os.path.join(repo_root, M2K_GRC),
        os.path.join(repo_root, "flowgraphs", "m2k_scope.grc"),
        json.dumps(cases)))
    assert result["ok"] is True
    for label in cases:
        if label != "ok":
            assert result[label] is False, label


# Sixteen pin dropdowns and sixteen name fields, of which only the first
# `num_lines` are visible -- the rest keep whatever they were last set to.
# So every check the block makes has to slice, and this puts a block into
# a real flow graph one case at a time to prove that it does. A block
# alone on a canvas always has unconnected ports; those are not the
# errors we are asking about, so they are filtered out.

LINES = '''
    import json, logging, sys, tempfile, yaml
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3", "10", "0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
    out = {}
    for label, (key, params) in json.loads(sys.argv[2]).items():
        doc = {"metadata": {"file_format": 1},
               "options": {"states": {},
                           "parameters": {"id": "probe",
                                          "generate_options": "no_gui"}},
               "blocks": [{"id": key, "name": "b", "states": {},
                           "parameters": params}],
               "connections": []}
        path = tempfile.mktemp(suffix=".grc")
        yaml.safe_dump(doc, open(path, "w"))
        fg = p.make_flow_graph(path); fg.rewrite(); fg.validate()
        blk = [b for b in fg.blocks if b.key == key][0]
        ports = blk.sinks if key.endswith("sink") else blk.sources
        out[label] = {
            "errors": [e for e in blk.get_error_messages()
                       if "not connected" not in e],
            "ports": [q.name for q in ports],
            "make": blk.templates.render("make")}
    print(json.dumps(out))
'''

SOURCE, SINK = "m2k_digital_source", "m2k_digital_sink"


def lines(repo_root, cases):
    return json.loads(run_in_gr(LINES, os.path.join(repo_root, M2K_GRC),
                                json.dumps(cases)))


@needs_gnuradio
def test_the_pins_come_out_in_the_order_they_were_chosen(repo_root):
    """Scattered, descending, whatever the jumpers reached. Port 0 is
    whichever pin went in the first dropdown."""
    out = lines(repo_root, {"spi": (SOURCE, {
        "num_lines": "3", "pin0": "3", "pin1": "7", "pin2": "1",
        "name0": "SCLK", "name1": "MOSI", "name2": "CS"})})["spi"]
    assert out["errors"] == []
    assert out["ports"] == ["pin0", "pin1", "pin2"]
    assert "pins=[3, 7, 1]" in out["make"]
    assert "names=['SCLK', 'MOSI', 'CS']" in out["make"]


@needs_gnuradio
def test_the_sink_maps_pins_the_same_way(repo_root):
    """A source and a sink that disagreed here would wire a bus
    backwards, and both halves would run."""
    out = lines(repo_root, {"latch": (SINK, {
        "num_lines": "3", "pin0": "2", "pin1": "0", "pin2": "9",
        "name0": "DATA", "name1": "LE"})})["latch"]
    assert out["errors"] == []
    assert out["ports"] == ["pin0", "pin1", "pin2"]
    assert "pins=[2, 0, 9]" in out["make"]
    assert "names=['DATA', 'LE', '']" in out["make"]


@needs_gnuradio
def test_the_hidden_dropdowns_are_not_read(repo_root):
    """pin2..pin15 still hold whatever they were; a two-line block that
    counted them would refuse itself for pins it is not using."""
    out = lines(repo_root, {"two": (SOURCE, {
        "num_lines": "2", "pin0": "3", "pin1": "7"})})["two"]
    assert out["errors"] == []
    assert out["ports"] == ["pin0", "pin1"]
    assert "pins=[3, 7]" in out["make"]


@needs_gnuradio
def test_one_line_is_one_unnumbered_port(repo_root):
    """GRC only numbers a port when there is more than one of it."""
    out = lines(repo_root, {"one": (SOURCE, {
        "num_lines": "1", "pin0": "5"})})["one"]
    assert out["ports"] == ["pin"]
    assert "pins=[5]" in out["make"]


@needs_gnuradio
def test_a_pin_mapping_that_cannot_work_is_refused_on_the_canvas(repo_root):
    """Both of these produce a flowgraph that runs and is wrong: two
    ports on one pin, and a trigger on a pin the block never reads."""
    out = lines(repo_root, {
        "ok": (SOURCE, {"num_lines": "2", "pin0": "0", "pin1": "1",
                        "trigger_pin": "1"}),
        "same pin twice": (SOURCE, {"num_lines": "2", "pin0": "5",
                                    "pin1": "5"}),
        "trigger on an unread pin": (SOURCE, {"num_lines": "2", "pin0": "0",
                                              "pin1": "1",
                                              "trigger_pin": "9"}),
        "sink, same pin twice": (SINK, {"num_lines": "3", "pin0": "1",
                                        "pin1": "2", "pin2": "1"}),
    })
    assert out["ok"]["errors"] == []
    for label in ("same pin twice", "trigger on an unread pin",
                  "sink, same pin twice"):
        assert out[label]["errors"], label


@needs_gnuradio
def test_every_instrument_block_loads(repo_root):
    loaded = json.loads(run_in_gr(LOAD, os.path.join(repo_root, M2K_GRC)))
    assert set(loaded) == {"m2k_analog_source", "m2k_analog_sink",
                           "m2k_digital_source", "m2k_digital_sink",
                           "m2k_spi_decode", "m2k_spi_encode",
                           "m2k_power_supply"}


@needs_gnuradio
def test_no_block_exposes_iio_vocabulary(repo_root):
    """The whole point: a participant should never meet an IIO word."""
    out = json.loads(run_in_gr('''
        import json, logging, sys
        logging.disable(logging.CRITICAL)
        from gnuradio.grc.core.platform import Platform
        p = Platform(version="3.10", version_parts=("3","10","0"), prefs=None)
        p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
        skip = {"id","alias","affinity","minoutbuf","maxoutbuf","comment"}
        print(json.dumps({
            k: [q["label"] for q in b.parameters_data
                if q.get("label") and q["id"] not in skip]
            for k, b in p.blocks.items() if k.startswith("m2k_")}))
    ''', os.path.join(repo_root, M2K_GRC)))

    forbidden = ("iio", "phy", "attr", "context", "uri", "oversampl",
                 "sysfs", "scan", "voltage")
    for block, labels in out.items():
        assert labels, block
        for label in labels:
            assert not any(w in label.lower() for w in forbidden), \
                "%s: %r" % (block, label)


@needs_gnuradio
def test_native_loopback_builds(repo_root):
    """A loopback with no IIO anywhere on the canvas."""
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback_native.grc")
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    # The point of this flowgraph: gr-iio is reached only from inside the
    # instrument blocks, so the generated code has no iio call of its own.
    assert result["iio"] == [], result["iio"]
    assert "analog_source(" in result["make"]
    assert "analog_sink(" in result["make"]


@needs_gnuradio
@pytest.mark.parametrize("name", ["m2k_spi_loopback.grc",
                                  "m2k_spi_loopback_continuous.grc"])
def test_the_spi_loopback_builds(repo_root, name):
    """Both workshop flowgraphs, with the pins they actually ship:
    DIO0-2 driven, DIO4-6 read, and the trigger on the CS they read."""
    path = os.path.join(repo_root, "flowgraphs", name)
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    assert "pins=[0, 1, 2]" in result["make"]
    assert "pins=[4, 5, 6]" in result["make"]
    assert "names=['SCLK', 'MOSI', 'CS']" in result["make"]


@needs_gnuradio
def test_the_interactive_loopback_sends_once_and_aligns(repo_root):
    """The two settings that make send-on-demand work at all.

    A cyclic sink would repeat the message forever, and an unaligned
    frame can land across a DMA buffer seam and be torn in the middle.
    They go together: alignment only matters because the sink is not
    cyclic, and one without the other is a flowgraph that looks right
    and misbehaves on a bench.
    """
    path = os.path.join(repo_root, "flowgraphs", "m2k_spi_loopback.grc")
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    assert "cyclic=False" in result["make"]
    assert "align=buffer_len" in result["make"]
    assert "buffer_size=buffer_len" in result["make"]


@needs_gnuradio
def test_the_spi_encode_block_loads(repo_root):
    """The .yml and the class have to agree about the message port.

    GRC writes `msg_connect` from the port label in the .yml, so a
    block that registers the port under a different name compiles
    cleanly and then raises at run time.
    """
    out = json.loads(run_in_gr('''
        import json, logging, os, sys
        logging.disable(logging.CRITICAL)
        from gnuradio.grc.core.platform import Platform
        p = Platform(version="3.10", version_parts=("3","10","0"), prefs=None)
        p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
        b = p.blocks["m2k_spi_encode"]
        sys.path.insert(0, os.path.dirname(sys.argv[1]))
        import pmt
        from m2k_blocks.spi import MESSAGE
        print(json.dumps({
            "params": [q["id"] for q in b.parameters_data],
            "inputs": [q.get("id") for q in b.inputs_data],
            "outputs": [q.get("label") for q in b.outputs_data],
            "registered": pmt.symbol_to_string(MESSAGE),
        }))
    ''', os.path.join(repo_root, M2K_GRC)))
    # A message port's key is its id; a stream port's is its position,
    # so only the message port's name has to match the class.
    assert out["inputs"] == ["message"]
    assert out["registered"] == out["inputs"][0]
    assert out["outputs"] == ["sclk", "mosi", "cs"]
    assert "align" in out["params"]


@needs_gnuradio
def test_the_decoded_pdu_carries_the_text(repo_root):
    """The bytes and their reading, in one Message Debug print.

    This is the loopback's own proof: someone types M2K, and what comes
    back off the wire says M2K next to `4d 32 4b`. The text rides in the
    metadata, so the payload stays the bytes that were actually clocked.
    """
    out = json.loads(run_in_gr('''
        import json, os, sys
        sys.path.insert(0, os.path.dirname(sys.argv[1]))
        import pmt
        from m2k_blocks.spi import spi_decode

        def text(words, **kwargs):
            got = pmt.dict_ref(pmt.car(spi_decode(**kwargs)._pdu(words)),
                               pmt.intern("text"), pmt.PMT_NIL)
            return None if pmt.is_null(got) else pmt.symbol_to_string(got)

        print(json.dumps({
            "text": text([0x4d, 0x32, 0x4b]),
            "escaped": text([0x4d, 0x00, 0xff]),
            "off": text([0x4d], add_text=False),
            "wide": text([0x0141], bits_per_word=16),
            "bytes": list(pmt.u8vector_elements(
                pmt.cdr(spi_decode()._pdu([0x4d, 0x32, 0x4b])))),
        }))
    ''', os.path.join(repo_root, M2K_GRC)))
    assert out["text"] == "M2K"
    assert out["escaped"] == "M\\x00\\xff"
    assert out["bytes"] == [0x4d, 0x32, 0x4b]
    # No text where there is no text to give: a 16-bit word is not a
    # character, and a binary bus should not be told it is one.
    assert out["off"] is None
    assert out["wide"] is None


@needs_gnuradio
@needs_yaml
def test_flowgraph_parameter_names_are_real(repo_root):
    """A key a block does not define is silently ignored by GRC.

    Writing `samp_rate:` on a QT time sink (whose parameter is `srate`)
    left it on its default, which happened to resolve while a variable of
    that name existed and broke the moment one was renamed.
    """
    import yaml
    out = json.loads(run_in_gr('''
        import json, logging, sys
        logging.disable(logging.CRITICAL)
        from gnuradio.grc.core.platform import Platform
        p = Platform(version="3.10", version_parts=("3","10","0"), prefs=None)
        p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
        print(json.dumps({k: [q["id"] for q in b.parameters_data]
                          for k, b in p.blocks.items()}))
    ''', os.path.join(repo_root, M2K_GRC)))

    for name in os.listdir(os.path.join(repo_root, "flowgraphs")):
        if not name.endswith(".grc"):
            continue
        with open(os.path.join(repo_root, "flowgraphs", name)) as handle:
            doc = yaml.safe_load(handle)
        for blk in doc.get("blocks", []):
            known = out.get(blk["id"])
            if known is None:                 # a generated block, not loaded here
                continue
            if blk["id"] == "epy_block":
                # Its parameters are whatever the embedded source's __init__
                # takes, discovered when GRC rewrites the flowgraph. The block
                # library only knows the four every block has.
                continue
            for key in blk.get("parameters", {}):
                assert key in known, "%s: %s has no parameter %r" % (
                    name, blk["id"], key)


@needs_gnuradio
def test_the_ultrasonic_flowgraph_builds(repo_root):
    """The numbers in this one are measurements, not defaults.

    f0 is the swept resonance and not 40 kHz; the two rates come off
    different ladders and must not collapse to one `samp_rate`; the sink
    is not cyclic because a repeating buffer cannot carry a message that
    changes.
    """
    path = os.path.join(repo_root, "flowgraphs", "m2k_ultrasonic_fsk.grc")
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    make = result["make"]
    assert "f0 = 40755.0" in make
    assert "tx_rate = 750000" in make
    assert "rx_rate = 1000000" in make
    assert "rx_decim = 200" in make
    assert "sample_rate=750000" in make and "cyclic=False" in make
    assert "sample_rate=1000000" in make and "trigger_source='off'" in make
    # Typing a new message must reach the wire, and must not resize the frame.
    assert "self.blocks_vector_source_x_0.set_data(self.frame, [])" in make
    assert "ljust(self.msg_capacity)" in make


@needs_gnuradio
def test_the_colorimeter_flowgraph_builds(repo_root):
    """Every number in this one came off the bench.

    The three bins are not round frequencies; they are the whole-cycle
    counts that make a rectangular window correct. The sink idles HIGH
    because a DIO bit on that board steers rather than gates. And the
    Goertzel length has to match the capture buffer, or a measurement
    straddles two buffers and whatever gap sits between them.
    """
    path = os.path.join(repo_root, "flowgraphs", "m2k_colorimeter.grc")
    result = json.loads(run_in_gr(BUILD, path,
                                  os.path.join(repo_root, M2K_GRC)))
    assert result["valid"], result["errors"]
    make = result["make"]
    # 205, 246 and 287 whole cycles in 4096 samples at 100 kS/s.
    assert "samp_rate = 100000" in make
    assert "nfft = 4096" in make
    assert "bin_hz = samp_rate / nfft" in make
    for name, cycles in (("red", 205), ("green", 246), ("blue", 287)):
        assert "%s_bin = %d" % (name, cycles) in make
    # Chop and capture share one clock, which is what the whole demo rests on.
    # sample_rate on the M2K blocks is a dropdown, so it is a literal here.
    # A variable name in it reverts to 1 MS/s without complaining.
    assert make.count("sample_rate=100000,") == 2
    assert make.count("buffer_size=nfft,") == 2
    assert "sample_rate=1000000" not in make
    # The bit steers between risers; only J5 exists, so idle high is dark.
    assert "pins=[13, 14, 15]" in make
    assert "cyclic=True" in make and "idle_level='high'" in make
    # A square short source is 0/1, which is exactly a DIO line.
    assert "analog.GR_SQR_WAVE, (red_bin * bin_hz), 1, 0" in make
    # One bin, computed over exactly one capture buffer.
    assert make.count("fft.goertzel_fc(samp_rate, nfft,") == 6
    # No window to taper, because nothing lands between bins.
    assert "window.WIN_RECTANGULAR" in make
    # The empty beam is not 1.0. Dividing it out happens on the wire, not in
    # a display setting, so what reaches the decision block is real percent.
    assert "blank_red = 1.0053" in make
    assert "blank_green = 0.9757" in make
    assert "blank_blue = 0.9911" in make
    assert "blocks.multiply_const_ff((100.0 / blank_red))" in make
    assert make.count("blocks.multiply_const_ff") == 3
    # Three percentages in, one word out, into a text box on the GUI.
    assert "decide.blk(clear=85.0, opaque=5.0, margin=1.3)" in make
    for i, color in enumerate(("red", "green", "blue")):
        assert "((self.%s_pct, 0), (self.decide, %d))" % (color, i) in make
    assert "msg_connect((self.decide, 'decision'), (self.verdict, 'val'))" in make
    # Blanking on demand. The chain the button closes is: press -> average
    # the raw ratios -> set the variable -> the multiply block's own
    # set_k. That last hop is GRC's, and it is the one worth asserting,
    # because nothing in the flowgraph mentions it.
    assert "self.red_pct.set_k((100.0 / self.blank_red))" in make
    for color in ("red", "green", "blue"):
        assert "msg_connect((self.blanker, '%s'), (self.apply_%s, 'inpair'))" \
            % (color, color) in make
        assert "blocks.msg_pair_to_var(self.set_blank_%s)" % color in make
    assert "msg_connect((self.blank_button, 'pressed'), (self.blanker, 'blank'))" in make
    # It reads the ratios BEFORE the blank is divided out, or pressing the
    # button a second time would blank against the first blank.
    for i, color in enumerate(("red", "green", "blue")):
        assert "((self.%s_ratio, 0), (self.blanker, %d))" % (color, i) in make


@needs_gnuradio
def test_the_byte_boundary_is_found_without_a_sync_word(repo_root):
    """The receive chain, on synthetic FSK, started mid-bit.

    Over the air the capture begins wherever it begins, so a chain that
    only works from sample zero is a chain that works on a file. The
    skew here is deliberately not a multiple of anything.

    Nothing on the air says where a byte starts -- the transmitter sends
    the payload and nothing else. GNU Radio gets the bits out; finding
    the boundary in them is `ascii_scan`, which imports nothing and so
    runs here in the parent rather than in the borrowed interpreter.
    """
    bits = json.loads(run_in_gr('''
        import json, math, sys
        import numpy as np
        from gnuradio import gr, blocks, analog, digital
        from gnuradio import filter as gr_filter
        from gnuradio.filter import firdes

        RX, F0, DEV, BITLEN, DECIM = 1e6, 40755.0, 300.0, 5e-3, 200
        FRAME = b"GRCON26 "
        SKEW = 1373

        bits = np.unpackbits(np.frombuffer(FRAME * 12, dtype=np.uint8))
        n = int(round(RX * BITLEN))
        f = np.where(np.repeat(bits, n) == 1, F0 + DEV, F0 - DEV)
        x = 0.14 * np.sin(2 * np.pi * np.cumsum(f) / RX)
        rng = np.random.default_rng(7)
        x = x + rng.normal(0, 0.14 / math.sqrt(2) / 10 ** 0.5, x.size)
        volts = np.concatenate([np.zeros(SKEW), x])

        tb = gr.top_block()
        rate = RX / DECIM
        out = blocks.vector_sink_b()
        tb.connect(blocks.vector_source_f(volts.tolist(), False),
                   gr_filter.freq_xlating_fir_filter_fcf(
                       DECIM, firdes.low_pass(1.0, RX, 600.0, 600.0), F0, RX),
                   analog.quadrature_demod_cf(rate / (2 * math.pi * DEV)),
                   digital.symbol_sync_ff(
                       digital.TED_ZERO_CROSSING, rate * BITLEN, 0.045, 1.0,
                       1.0, 1.5, 1, digital.constellation_bpsk().base(),
                       digital.IR_MMSE_8TAP, 128, []),
                   digital.binary_slicer_fb(),
                   out)
        tb.run()
        print(json.dumps(list(out.data())))
    '''))
    assert len(bits) > 8 * 8, "the front end produced almost no bits"

    sys.path.insert(0, os.path.join(repo_root, "gr-m2k"))
    from m2k_blocks.ascii_scan import scan

    hits = scan(bits, min_chars=16)
    assert hits, "nothing in the demodulated bits reads as text"
    top = hits[0]
    assert b"GRCON26" in top.text, top.line()
    # The offset is what a participant types into `skip_bits`, so it has
    # to be a real byte offset rather than always zero.
    assert 0 <= top.offset < 8


BUFFER_TAGS = '''
import json, math, sys, time
import numpy as np
import pmt
from gnuradio import gr, blocks, analog, digital, pdu
from gnuradio import filter as gr_filter
from gnuradio.filter import firdes

RX, F0, DEV, BITLEN, DECIM = 1e6, 40755.0, 300.0, 5e-3, 200
FRAME = b"GRCON26 "
BUF, SKEW = 16384, 1373

bits = np.unpackbits(np.frombuffer(FRAME * 12, dtype=np.uint8))
n = int(round(RX * BITLEN))
f = np.where(np.repeat(bits, n) == 1, F0 + DEV, F0 - DEV)
x = 0.14 * np.sin(2 * np.pi * np.cumsum(f) / RX)
rng = np.random.default_rng(7)
x = x + rng.normal(0, 0.14 / math.sqrt(2) / 10 ** 0.5, x.size)
volts = np.concatenate([np.zeros(SKEW), x])

# What analog_source does to every buffer it hands over, via
# set_len_tag_key("packet_len"). A vector source emits none on its own,
# which is exactly why the chain looked fine until it met a board.
tags = []
for off in range(0, volts.size, BUF):
    t = gr.tag_t()
    t.offset = off
    t.key = pmt.intern("packet_len")
    t.value = pmt.from_long(BUF)
    tags.append(t)

tb = gr.top_block()
rate = RX / DECIM
gate = blocks.tag_gate(gr.sizeof_float, False)
gate.set_single_key("packet_len")
to_pdu = pdu.tagged_stream_to_pdu(gr.types.byte_t, "packet_len")
sink = blocks.message_debug()

chain = [blocks.vector_source_f(volts.tolist(), False, 1, tags)]
if sys.argv[1] == "gate":
    chain.append(gate)
chain += [
    gr_filter.freq_xlating_fir_filter_fcf(
        DECIM, firdes.low_pass(1.0, RX, 600.0, 600.0), F0, RX),
    analog.quadrature_demod_cf(rate / (2 * math.pi * DEV)),
    digital.symbol_sync_ff(
        digital.TED_ZERO_CROSSING, rate * BITLEN, 0.045, 1.0,
        1.0, 1.5, 1, digital.constellation_bpsk().base(),
        digital.IR_MMSE_8TAP, 128, []),
    digital.binary_slicer_fb(),
    blocks.pack_k_bits_bb(8),
    blocks.stream_to_tagged_stream(gr.sizeof_char, 1, 8, "packet_len"),
    to_pdu,
]
tb.connect(*chain)
tb.msg_connect(to_pdu, "pdus", sink, "store")
tb.run()
time.sleep(0.2)
print(json.dumps([list(pmt.u8vector_elements(pmt.cdr(sink.get_message(i))))
                  for i in range(sink.num_messages())]))
'''


@needs_gnuradio
def test_the_sources_buffer_tags_do_not_reach_the_pdu():
    """`packet_len` means two things, and one of them is 16384.

    `analog_source` labels every buffer with a `packet_len` tag and
    nothing in this repo reads it. `tagged_stream_to_pdu` keys on the
    same string, so on a board it saw 16384 where the flowgraph meant 8
    and waited eleven minutes for a message. On the bench the transducers
    looked right, the demod looked right, and no PDU ever came out.

    A vector source emits no tags, so the chain above this one cannot
    reach the bug. This one injects the tags the hardware really sends.
    """
    gated = json.loads(run_in_gr(BUFFER_TAGS, "gate"))
    assert gated, "no PDUs at all -- something other than the tags is wrong"
    # Length, not content. With no sync word the byte boundary is
    # arbitrary, so which eight bytes come out depends on where the
    # capture started -- and the claim here is about the 8 against the
    # 16384, which is exactly the length.
    assert all(len(p) == 8 for p in gated), [len(p) for p in gated[:4]]

    # The other half of the claim: without the gate this does not work.
    # If GNU Radio ever stops confusing the two, this fails and the gate
    # in the flowgraph can go.
    ungated = json.loads(run_in_gr(BUFFER_TAGS, "nogate"))
    assert not any(len(p) == 8 for p in ungated), (
        "the collision no longer happens -- recheck whether the tag gate "
        "in m2k_ultrasonic_fsk.grc is still needed")
