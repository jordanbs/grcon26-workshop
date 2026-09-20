"""The setup scripts, and the QR code that sends people to them.

None of this touches a network or installs anything. What it checks is
the class of mistake that only shows up in front of a room: a shell
script with a syntax error, a QR code encoding the wrong URL, four
documents disagreeing about where the repository is.

The Windows script cannot be executed here, so it gets a parse check
where PowerShell exists and a grep otherwise. That is a real gap and it
is marked as one -- see `test_the_windows_script_parses`.
"""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install")
SH = os.path.join(INSTALL, "m2k-setup.sh")
PS1 = os.path.join(INSTALL, "m2k-setup.ps1")

sys.path.insert(0, os.path.join(ROOT, "slides"))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# The scripts exist and are what they claim
# ---------------------------------------------------------------------------

def test_both_setup_scripts_are_present():
    """install/README.md names both by path, so both have to be there."""
    assert os.path.isfile(SH)
    assert os.path.isfile(PS1)


def test_the_unix_script_is_executable():
    """It is also documented as `bash m2k-setup.sh`, but a downloaded file
    somebody chmods is the other half of the instructions."""
    assert os.access(SH, os.X_OK)


def test_the_unix_script_parses():
    result = subprocess.run(["bash", "-n", SH], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_unix_script_prints_help_without_doing_anything():
    """--help has to work before the interpreter hunt, or a confused
    participant cannot even read the options."""
    result = subprocess.run(["bash", SH, "--help"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for flag in ("--yes", "--python", "--skip-drivers"):
        assert flag in result.stdout, flag
    # The header comment is the help text, so a stray line from the body
    # means the extraction range slipped.
    assert "set -euo pipefail" not in result.stdout


def test_an_unknown_option_is_refused():
    """Silently ignoring a typo'd flag is how --skip-driver installs a
    udev rule somebody did not want."""
    result = subprocess.run(["bash", SH, "--skip-driver"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "unknown option" in result.stderr


def test_the_unix_script_refuses_a_python_without_gnuradio():
    """The whole script rests on picking the right interpreter, so a
    wrong one named explicitly has to stop it rather than install
    somewhere useless."""
    result = subprocess.run(
        ["bash", SH, "--python", sys.executable],
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode != 0
    assert "cannot import gnuradio" in result.stderr


def test_the_windows_script_parses():
    """Skipped where PowerShell is absent, which includes CI.

    This is the gap in the coverage here and it is deliberate rather than
    forgotten: nothing in this repository can run the Windows path end to
    end, so the first real run is on a Windows machine.
    """
    pwsh = None
    for name in ("pwsh", "powershell"):
        from shutil import which
        if which(name):
            pwsh = which(name)
            break
    if pwsh is None:
        pytest.skip("no PowerShell here")
    script = (
        '$errs = $null; '
        '$null = [System.Management.Automation.Language.Parser]::ParseFile('
        '"%s", [ref]$null, [ref]$errs); '
        'if ($errs) { $errs | ForEach-Object { Write-Error $_.Message }; exit 1 }'
        % PS1.replace("\\", "\\\\"))
    result = subprocess.run([pwsh, "-NoProfile", "-Command", script],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Everything agrees about where the repository is
# ---------------------------------------------------------------------------

REPO = "https://github.com/livethisdream/grcon26-workshop"
# The part that survives both spellings: github.com/... in prose, and
# raw.githubusercontent.com/... in the download commands.
SLUG = "livethisdream/grcon26-workshop"


def test_the_qr_code_encodes_the_repository_url():
    import render_qr
    assert render_qr.URL == REPO


@pytest.mark.parametrize("path", [
    "install/m2k-setup.sh",
    "install/m2k-setup.ps1",
    "install/README.md",
    "README.md",
    "gr-m2k/README.md",
])
def test_every_document_names_the_same_repository(path):
    """Five documents carry this path and a QR code carries a sixth. One
    of them being stale sends a room somewhere that does not exist."""
    assert SLUG in read(os.path.join(ROOT, path)), path


@pytest.mark.parametrize("path", [
    "install/m2k-setup.sh",
    "install/m2k-setup.ps1",
    "install/README.md",
])
def test_the_scripts_and_their_readme_carry_the_full_url(path):
    """These three are the ones somebody copies and runs, so a bare slug
    is not enough -- the whole URL has to be right."""
    assert REPO in read(os.path.join(ROOT, path)), path


def test_the_deck_shows_the_url_it_encodes():
    """A QR code nobody can scan is still readable if the URL is printed
    beside it, so the printed one has to be the encoded one."""
    deck = read(os.path.join(ROOT, "slides", "index.html"))
    assert 'src="img/setup-qr.svg"' in deck
    assert "github.com/livethisdream/grcon26-workshop" in deck


def test_both_scripts_install_the_same_package():
    """`#subdirectory=gr-m2k` is easy to drop and the failure is a
    confusing pip error about the repository root."""
    spec = "#subdirectory=gr-m2k"
    assert spec in read(SH)
    assert spec in read(PS1)


# ---------------------------------------------------------------------------
# The code itself
# ---------------------------------------------------------------------------

def test_the_committed_qr_svg_is_current():
    """Same rule as the GRC figures: the picture is generated, so a stale
    one fails here rather than on a projector."""
    import render_qr
    assert render_qr.main(["--check"]) == 0


def test_the_qr_decodes_to_the_url_with_a_decoder_we_did_not_write():
    """The one figure in the deck nobody can proofread.

    segno agreeing with itself proves nothing, so this reads the code
    back with zxing-cpp -- the engine behind a great many phone scanners,
    and no relation to the encoder. Told the wrong URL it returns a
    different string, so the check could have failed.
    """
    segno = pytest.importorskip("segno")
    zxingcpp = pytest.importorskip("zxingcpp")
    Image = pytest.importorskip("PIL.Image")

    import io

    import render_qr

    code = segno.make(render_qr.URL, error=render_qr.ERROR)
    buf = io.BytesIO()
    # A quiet zone, because that is how a reader will meet it: the SVG
    # carries none and the slide's card supplies one.
    code.save(buf, kind="png", scale=8, border=4)
    buf.seek(0)
    found = zxingcpp.read_barcodes(Image.open(buf).convert("L"))
    assert found, "the generated code does not decode at all"
    assert found[0].text == render_qr.URL


def test_the_qr_carries_no_quiet_zone_of_its_own():
    """The card in frames.css supplies it. Baking one in as well would
    shrink the code inside a box of fixed width, which is backwards for
    somebody scanning from the back of the room."""
    import render_qr
    assert render_qr.BORDER == 0
    css = read(os.path.join(ROOT, "slides", "assets", "frames.css"))
    assert ".qr img" in css, "the card that supplies the quiet zone is gone"
    assert re.search(r"\.qr img \{[^}]*padding:", css, re.S)


# ---------------------------------------------------------------------------
# The CLI the scripts drive
# ---------------------------------------------------------------------------

def test_the_scripts_drive_the_cli_by_module_not_by_script_name():
    """`pip install --user` routinely puts the m2k-blocks script somewhere
    off PATH, and then the tool for diagnosing a bad install is itself
    missing. Naming the interpreter cannot miss."""
    for path in (SH, PS1):
        source = read(path)
        assert "m2k_blocks install" in source, path
        assert "m2k_blocks check" in source, path
        assert "m2k_blocks scan" in source, path


def test_the_module_entry_point_exists():
    """`python -m m2k_blocks` is what makes the line above work."""
    assert os.path.isfile(
        os.path.join(ROOT, "gr-m2k", "m2k_blocks", "__main__.py"))


def test_the_cli_offers_the_commands_the_scripts_call():
    sys.path.insert(0, os.path.join(ROOT, "gr-m2k"))
    from m2k_blocks import cli
    for name in ("path", "check", "scan", "install", "uninstall"):
        assert name in cli.COMMANDS, name


def test_scan_says_what_to_do_when_pylibiio_is_missing(monkeypatch, capsys):
    """The failure a participant hits before the setup script has run, and
    the one place that can name the fix."""
    sys.path.insert(0, os.path.join(ROOT, "gr-m2k"))
    from m2k_blocks import cli

    real = __import__

    def no_iio(name, *args, **kwargs):
        if name == "iio":
            raise ImportError("no module named iio")
        return real(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_iio)
    assert cli.cmd_scan([]) == 1
    out = capsys.readouterr().out
    assert "pylibiio" in out
    assert "install/README.md" in out


def test_scan_marks_the_m2k_among_whatever_else_is_plugged_in():
    """A laptop with another IIO device on it must not send somebody to
    the wrong address."""
    sys.path.insert(0, os.path.join(ROOT, "gr-m2k"))
    from m2k_blocks import cli
    line = cli._describe("usb:1.5.5", "ADALM2000 (M2k)")
    assert "<-- an M2K" in line
    assert "<-- an M2K" not in cli._describe("ip:10.0.0.2", "PlutoSDR")


# ---------------------------------------------------------------------------
# The macOS address, which is the finding most likely to be lost
# ---------------------------------------------------------------------------

def test_the_mac_address_caveat_is_written_down_where_people_will_hit_it():
    """Every block defaults to ip:192.168.2.1, which needs the USB
    ethernet gadget. macOS has not had that since HoRNDIS stopped
    loading, so a Mac has to use `usb:` and nothing in the block says so.
    """
    for path in ("install/README.md", "gr-m2k/README.md",
                 "slides/index.html"):
        source = read(os.path.join(ROOT, path))
        assert "usb:" in source, path
        assert re.search(r"mac(os)?\b", source, re.I), path
    assert "usb:" in read(SH)
