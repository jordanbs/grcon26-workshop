"""The two ways to get the blocks onto GNU Radio's paths.

There are two paths and they fail differently. A missing GRC_BLOCKS_PATH is
loud -- the block is not in the tree, so the flowgraph will not even open. A
missing PYTHONPATH is quiet: the blocks appear, the canvas validates, and
the flowgraph dies on Run with an ImportError. Both routes here set both,
and these tests are mostly about the second one not being forgotten.

Nothing here needs GNU Radio. `tests/test_grc_integration.py` covers the
half that does.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GR_M2K = os.path.join(ROOT, "gr-m2k")
GRC = os.path.join(GR_M2K, "grc")
ENV_SH = os.path.join(GR_M2K, "env.sh")
PYPROJECT = os.path.join(GR_M2K, "pyproject.toml")


def definitions():
    return sorted(f for f in os.listdir(GRC) if f.endswith(".block.yml"))


def sourced(before=None, times=1):
    """Source env.sh in a clean bash, report the two paths it leaves."""
    script = "; ".join(["source %s >/dev/null" % ENV_SH] * times)
    env = dict(os.environ)
    env.pop("GRC_BLOCKS_PATH", None)
    env.pop("PYTHONPATH", None)
    env.update(before or {})
    out = subprocess.run(
        ["bash", "-c", '%s; echo "$GRC_BLOCKS_PATH"; echo "$PYTHONPATH"' % script],
        cwd="/", env=env, capture_output=True, text=True, check=True)
    blocks, python = out.stdout.splitlines()[:2]
    return blocks.split(os.pathsep), python.split(os.pathsep)


# --- the shell route ------------------------------------------------------

def test_env_sh_sets_both_paths():
    blocks, python = sourced()
    assert blocks[0] == GRC
    assert python[0] == GR_M2K


def test_env_sh_works_from_any_directory():
    """It is sourced by path, and cwd is / above, so this is the real check."""
    blocks, _ = sourced()
    assert os.path.isdir(blocks[0])
    assert definitions(), "no block definitions to point at"


def test_env_sh_keeps_what_was_already_there():
    """Prepend, never replace -- GRC concatenates, so the stock blocks stay."""
    blocks, python = sourced({"GRC_BLOCKS_PATH": "/already/here",
                              "PYTHONPATH": "/already/too"})
    assert blocks == [GRC, "/already/here"]
    assert python == [GR_M2K, "/already/too"]


def test_sourcing_twice_does_not_double_the_entry():
    blocks, python = sourced(times=3)
    assert blocks.count(GRC) == 1
    assert python.count(GR_M2K) == 1


# --- the pip route --------------------------------------------------------

def test_pyproject_ships_every_block_definition():
    """The wheel carries grc/ as package data, mapped in from outside.

    The definitions stay at gr-m2k/grc/ because that is the path every
    README names. If that mapping is ever dropped, the wheel installs a
    package with no blocks in it and the only symptom is an empty tree.
    """
    tomllib = pytest.importorskip("tomllib")
    with open(PYPROJECT, "rb") as handle:
        conf = tomllib.load(handle)
    tools = conf["tool"]["setuptools"]
    assert "m2k_blocks.grc" in tools["packages"]
    assert tools["package-dir"]["m2k_blocks.grc"] == "grc"
    assert tools["package-data"]["m2k_blocks.grc"] == ["*.yml"]
    assert conf["project"]["scripts"]["m2k-blocks"] == "m2k_blocks.cli:main"


def test_every_definition_names_a_module_that_exists():
    """A yml importing a deleted module is a block that appears and cannot run.

    Two modules have been removed from this package over its life and their
    .pyc files outlived them, so this is not hypothetical.
    """
    yaml = pytest.importorskip("yaml")
    for name in definitions():
        with open(os.path.join(GRC, name)) as handle:
            block = yaml.safe_load(handle)
        imports = block["templates"]["imports"]
        for line in imports.splitlines():
            if not line.startswith("from m2k_blocks."):
                continue
            module = line.split()[1].split(".")[1]
            assert os.path.exists(
                os.path.join(GR_M2K, "m2k_blocks", module + ".py")), \
                "%s imports m2k_blocks.%s, which does not exist" % (name, module)


# --- the CLI --------------------------------------------------------------

def cli():
    if GR_M2K not in sys.path:
        sys.path.insert(0, GR_M2K)
    return pytest.importorskip("m2k_blocks.cli")


def test_the_cli_needs_nothing_but_the_standard_library():
    """`m2k-blocks check` has to run on the machine where GNU Radio is broken.

    That is the machine it exists for, so importing gnuradio at module scope
    would take the diagnostic down with the thing it diagnoses.
    """
    assert cli() is not None
    assert "gnuradio" not in sys.modules


def test_the_cli_finds_the_definitions_in_the_source_tree():
    """Installed they sit inside the package; here they sit beside it."""
    assert os.path.realpath(cli().grc_dir()) == os.path.realpath(GRC)
    assert len(cli().definitions()) == len(definitions())


def test_install_and_uninstall_leave_the_config_as_they_found_it(tmp_path):
    module = cli()
    home = tmp_path / "home"
    (home / ".gnuradio").mkdir(parents=True)
    conf = home / ".gnuradio" / "config.conf"
    conf.write_text("[grc]\nlocal_blocks_path = /someone/elses\n")
    before = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    # With GNU Radio importable, config_path() asks it, and it will not
    # consult HOME on every platform.
    real_config_path = module.config_path
    module.config_path = lambda: str(conf)
    try:
        assert module.cmd_install([]) == 0
        text = conf.read_text()
        assert module.grc_dir() in text
        assert "/someone/elses" in text, "clobbered a path that was not ours"
        assert module.cmd_install([]) == 0          # idempotent
        assert conf.read_text().count(module.grc_dir()) == 1
        assert module.cmd_uninstall([]) == 0
        text = conf.read_text()
        assert module.grc_dir() not in text
        assert "/someone/elses" in text, "took someone else's path with it"
    finally:
        module.config_path = real_config_path
        if before is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = before
