#!/usr/bin/env bash
#
# Set a machine up for the GRCon26 GNU Radio + ADALM2000 workshop.
#
#     bash m2k-setup.sh
#
# What it assumes you already have: GNU Radio, and gnuradio-companion on
# your PATH. Everything else it either installs or tells you how to get.
#
# What it does, in order:
#
#   1. works out which Python gnuradio-companion actually runs on
#   2. checks gr-iio (`from gnuradio import iio`) in that interpreter
#   3. installs pylibiio (`import iio`) there if it is missing
#   4. installs gr-m2k there from GitHub
#   5. registers the block directory with GRC, and verifies it
#   6. checks the USB permissions / driver situation for this platform
#   7. looks for the board and prints the address to paste into a block
#
# Nothing here installs a kernel driver or a udev rule without asking
# first. Pass --yes to answer yes to all of it, which is what an
# unattended run wants.

set -euo pipefail

REPO="https://github.com/livethisdream/grcon26-workshop"
PKG="git+${REPO}#subdirectory=gr-m2k"
UDEV_URL="https://raw.githubusercontent.com/analogdevicesinc/m2k-fw/master/scripts/53-adi-m2k-usb.rules"
UDEV_DEST="/etc/udev/rules.d/53-adi-m2k-usb.rules"
DRIVERS_MAC="https://github.com/analogdevicesinc/libiio/releases"

ASSUME_YES=0
SKIP_DRIVERS=0
PYTHON=""

# ---------------------------------------------------------------------------
# Output. Steps are numbered because the thing people report back is "it
# stopped at 4", and a number makes that answerable.
# ---------------------------------------------------------------------------
STEP=0
step()  { STEP=$((STEP + 1)); printf '\n[%d/7] %s\n' "$STEP" "$1"; }
say()   { printf '      %s\n' "$1"; }
warn()  { printf '      WARNING: %s\n' "$1" >&2; }
die()   { printf '\nFAILED: %s\n' "$1" >&2; exit 1; }

ask() {
    # ask "question" -- 0 for yes. --yes answers yes; no tty answers no,
    # because a script being piped somewhere must not block on a prompt.
    [ "$ASSUME_YES" -eq 1 ] && return 0
    [ -t 0 ] || { say "not a terminal, so assuming no"; return 1; }
    local reply
    read -r -p "      $1 [y/N] " reply
    case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

usage() {
    # The header comment is the help text. Print it up to the first line
    # that is not a comment, so the two cannot drift apart.
    sed -n '2,${/^#/!q; s/^# \{0,1\}//; p;}' "$0"
    cat <<'EOF'

Options:
  --yes              answer yes to every prompt
  --python PATH      use this interpreter instead of detecting one
  --skip-drivers     do not touch udev rules, and do not ask
  -h, --help         this
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)      ASSUME_YES=1 ;;
        --skip-drivers) SKIP_DRIVERS=1 ;;
        --python)      PYTHON="${2:-}"; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

case "$(uname -s)" in
    Linux)  OS=linux ;;
    Darwin) OS=macos ;;
    *)      die "this script covers Linux and macOS. On Windows use m2k-setup.ps1." ;;
esac

printf 'GRCon26 workshop setup -- %s\n' "$OS"

# ---------------------------------------------------------------------------
# 1. The interpreter
#
# This is the step everything else rests on, and the one thing that
# actually goes wrong. `pip install` has to land in the same interpreter
# gnuradio-companion imports from. On a distro GNU Radio that is the
# system Python; under radioconda it is the environment's. A venv on some
# third Python installs cleanly, puts m2k-blocks on PATH, and still leaves
# the block tree empty.
#
# The shebang of gnuradio-companion is the most direct evidence there is,
# so read it before guessing.
# ---------------------------------------------------------------------------
step "Finding the Python that gnuradio-companion uses"

imports_gnuradio() {
    [ -x "$1" ] && "$1" -c 'import gnuradio' >/dev/null 2>&1
}

if [ -n "$PYTHON" ]; then
    say "using $PYTHON, because you said so"
    imports_gnuradio "$PYTHON" || die "$PYTHON cannot import gnuradio"
else
    GRC_BIN="$(command -v gnuradio-companion || true)"
    CANDIDATES=""
    if [ -n "$GRC_BIN" ]; then
        say "gnuradio-companion is $GRC_BIN"
        # A shebang, if it is a script rather than a binary.
        SHEBANG="$(head -c 256 "$GRC_BIN" 2>/dev/null | sed -n '1s/^#! *//p' \
                   | awk '{print $1}' || true)"
        # `#!/usr/bin/env python3` names env, not the interpreter.
        case "$SHEBANG" in
            */env) SHEBANG="$(command -v python3 || true)" ;;
        esac
        [ -n "$SHEBANG" ] && CANDIDATES="$SHEBANG"
        # radioconda and Homebrew both put python beside the script.
        CANDIDATES="$CANDIDATES $(dirname "$GRC_BIN")/python3"
    else
        warn "gnuradio-companion is not on your PATH"
        say "Install GNU Radio first. This script sets up the M2K blocks,"
        say "not GNU Radio itself."
    fi
    CANDIDATES="$CANDIDATES $(command -v python3 || true) /usr/bin/python3"

    for candidate in $CANDIDATES; do
        if imports_gnuradio "$candidate"; then
            PYTHON="$candidate"
            break
        fi
    done
    [ -n "$PYTHON" ] || die "no Python here can 'import gnuradio'. If \
gnuradio-companion runs, find its interpreter and pass --python."
    say "using $PYTHON"
fi

PYV="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
say "Python $PYV"

# What kind of interpreter it is decides how to install into it, and
# whether the distro's own packages are any use. `--user` is refused
# outright inside a virtualenv -- "User site-packages are not visible in
# this virtualenv" -- so getting this wrong is not a preference, it is a
# hard failure four steps later.
PY_KIND="$("$PYTHON" - <<'EOF'
import os
import sys
import sysconfig

if os.path.isdir(os.path.join(sys.prefix, "conda-meta")):
    print("conda")
elif sys.prefix != sys.base_prefix:
    print("venv")
elif os.access(sysconfig.get_paths()["purelib"], os.W_OK):
    print("writable")
else:
    print("system")
EOF
)"

case "$PY_KIND" in
    conda)    say "a conda environment" ;;
    venv)     say "a virtualenv" ;;
    writable) say "a Python you can write to directly" ;;
    system)   say "a system Python, so installs go to your user directory" ;;
esac

# ---------------------------------------------------------------------------
# pip, into that interpreter, coping with PEP 668.
#
# A distro Python is usually marked externally-managed, which makes pip
# refuse to write to it at all -- including with --user. That is a correct
# default and a real obstacle here, because the interpreter we have to
# install into is exactly the one the distro manages. So: try the polite
# form, and only reach for --break-system-packages when pip says that is
# the reason it stopped, having said out loud that we are doing it.
# ---------------------------------------------------------------------------
pip_install() {
    local what="$1" log
    log="$(mktemp)"
    # Into an environment we own, install straight into it. `--user` there
    # is not merely unnecessary, pip rejects it.
    local user_flag="--user"
    case "$PY_KIND" in
        conda|venv|writable) user_flag="" ;;
    esac
    # shellcheck disable=SC2086 # user_flag is one optional flag, not a list
    if "$PYTHON" -m pip install $user_flag --upgrade "$what" >"$log" 2>&1; then
        rm -f "$log"; return 0
    fi
    if grep -q 'externally-managed-environment' "$log"; then
        say "pip refused: this Python is managed by your distribution."
        say "The blocks have to live in it anyway -- it is the one GNU"
        say "Radio imports from. Installing into your user directory with"
        say "--break-system-packages, which touches nothing the package"
        say "manager owns."
        if ask "go ahead?"; then
            if "$PYTHON" -m pip install --user --break-system-packages \
                    --upgrade "$what" >"$log" 2>&1; then
                rm -f "$log"; return 0
            fi
        else
            rm -f "$log"
            die "nothing installed. Your distribution may package this \
already -- see install/README.md."
        fi
    fi
    sed 's/^/      | /' "$log" >&2
    rm -f "$log"
    return 1
}

# ---------------------------------------------------------------------------
# 2. gr-iio -- the blocks are built on it and it does not come from pip
# ---------------------------------------------------------------------------
step "Checking gr-iio"

if "$PYTHON" -c 'from gnuradio import iio' >/dev/null 2>&1; then
    say "gr-iio is there"
else
    warn "'from gnuradio import iio' fails in $PYTHON"
    say "gr-iio ships with GNU Radio; it does not come from pip. Install it"
    say "with the same package manager you installed GNU Radio with:"
    case "$OS" in
        linux) say "  sudo apt install gnuradio  (Debian/Ubuntu: gr-iio is in it)" ;;
        macos) say "  conda install -c conda-forge gnuradio-iio   (radioconda)" ;;
    esac
    say "Continuing, because the rest of the setup still works -- but no"
    say "flowgraph will run until this is fixed."
fi

# ---------------------------------------------------------------------------
# 3. pylibiio -- the other `iio`, and a different thing
#
# `from gnuradio import iio` is gr-iio, the GNU Radio blocks.
# `import iio` is pylibiio, the binding round the C library. The digital
# blocks and m2k_config use the second to read and write attributes that
# gr-iio has no block for. Both are needed and they are not related.
# ---------------------------------------------------------------------------
step "Checking pylibiio"

if "$PYTHON" -c 'import iio' >/dev/null 2>&1; then
    say "pylibiio is there"
else
    say "pylibiio is missing -- this is the binding round libiio, not gr-iio"
    if [ "$OS" = linux ] && [ "$PY_KIND" = venv ]; then
        # A plain virtualenv cannot see system site-packages, so apt would
        # install python3-libiio somewhere this interpreter will never look.
        # Say that rather than installing it and reporting success.
        say "This is a virtualenv, so the distro's python3-libiio would not"
        say "be visible to it. Either rebuild it with --system-site-packages,"
        say "or let pip install the wheel here -- which needs the native"
        say "libiio (apt install libiio0) present as well."
        pip_install pylibiio || warn "pip could not install pylibiio"
    elif [ "$OS" = linux ] && command -v apt-get >/dev/null 2>&1; then
        # The distro package is the right answer on Debian/Ubuntu: the pypi
        # wheel needs a matching libiio.so already present, and apt brings
        # both halves at once.
        say "Debian/Ubuntu package it as python3-libiio, which brings the"
        say "native library with it. That is the route that works."
        if ask "run: sudo apt-get install -y python3-libiio ?"; then
            sudo apt-get install -y python3-libiio \
                || warn "apt could not install it; falling back to pip"
        fi
    elif [ "$OS" = macos ] && command -v brew >/dev/null 2>&1; then
        say "The pypi wheel needs libiio itself present first; Homebrew has it."
        if ask "run: brew install libiio ?"; then
            brew install libiio || warn "brew could not install libiio"
        fi
    fi
    if ! "$PYTHON" -c 'import iio' >/dev/null 2>&1; then
        say "installing pylibiio with pip"
        pip_install pylibiio || warn "pip could not install pylibiio"
    fi
    if "$PYTHON" -c 'import iio' >/dev/null 2>&1; then
        say "pylibiio is there now"
    else
        warn "pylibiio still will not import."
        say "The wheel is a wrapper: it needs the native libiio installed"
        say "too. install/README.md lists the package name per platform."
    fi
fi

# ---------------------------------------------------------------------------
# 4. The blocks
# ---------------------------------------------------------------------------
step "Installing gr-m2k"
say "from $REPO"
pip_install "$PKG" || die "could not install gr-m2k"
say "installed"

# ---------------------------------------------------------------------------
# 5. Telling GRC where they are
#
# `python -m m2k_blocks` rather than the m2k-blocks script: a --user
# install puts that script somewhere that is often not on PATH, and the
# interpreter is the thing we are sure of.
# ---------------------------------------------------------------------------
step "Registering the blocks with GNU Radio Companion"
# Not allowed to abort the run: the remaining steps are diagnostics, and
# they are worth more when something has gone wrong than when nothing has.
"$PYTHON" -m m2k_blocks install || warn "could not write the block path"
echo
if "$PYTHON" -m m2k_blocks check; then
    say "GRC will find the blocks"
else
    warn "GRC will not find the blocks yet -- read the check output above"
fi

# ---------------------------------------------------------------------------
# 6. Getting at the board
# ---------------------------------------------------------------------------
step "USB access"

if [ "$SKIP_DRIVERS" -eq 1 ]; then
    say "skipped, because you said --skip-drivers"
elif [ "$OS" = linux ]; then
    if [ -e "$UDEV_DEST" ]; then
        say "the ADI udev rule is already installed"
    else
        say "Linux needs no driver for the M2K -- the kernel has both the"
        say "USB ethernet gadget and the raw USB interface. What it needs is"
        say "permission, so that libiio can open the board without root."
        if ask "install ADI's udev rule to $UDEV_DEST ?"; then
            tmp="$(mktemp)"
            if curl -fsSL "$UDEV_URL" -o "$tmp"; then
                sudo install -m 0644 "$tmp" "$UDEV_DEST"
                sudo udevadm control --reload-rules || true
                sudo udevadm trigger || true
                say "installed; unplug and replug the board"
            else
                warn "could not download the rule from $UDEV_URL"
            fi
            rm -f "$tmp"
        else
            say "skipped. Without it you will need sudo to open the board."
        fi
    fi

    # The rule grants the board to GROUP="plugdev", which Debian and Ubuntu
    # have and Fedora and Arch do not. A rule naming a group that does not
    # exist applies to nobody, and the failure reads as a broken board.
    if [ -e "$UDEV_DEST" ] || [ "$ASSUME_YES" -eq 1 ]; then
        if ! getent group plugdev >/dev/null 2>&1; then
            warn "there is no 'plugdev' group on this system"
            say "ADI's rule hands the board to that group, so on this distro"
            say "it grants nothing. Either create the group, or edit"
            say "$UDEV_DEST to name a group you are in."
        elif ! id -nG | tr ' ' '\n' | grep -qx plugdev; then
            say "you are not in the 'plugdev' group, which the rule grants to"
            if ask "run: sudo usermod -aG plugdev $USER ?"; then
                sudo usermod -aG plugdev "$USER"
                say "added. Log out and back in -- group membership is set"
                say "at login, so this shell still does not have it."
            fi
        fi
    fi
else
    # macOS. This is the platform where the workshop's default address is
    # wrong, and it is worth being explicit rather than letting twenty
    # people discover it at once.
    say "macOS needs no kernel driver for the USB backend -- libiio talks"
    say "to the board through libusb."
    say ""
    say "It does NOT get the USB ethernet gadget. That needed HoRNDIS, an"
    say "unmaintained kext that does not load on Apple silicon at all. So"
    say "'ip:192.168.2.1' -- the default in every block -- will not work"
    say "here. Use the USB backend instead: the address is 'usb:', which"
    say "libiio resolves on its own when one board is plugged in."
    say ""
    say "If libiio itself is missing: brew install libiio, or a release"
    say "from $DRIVERS_MAC"
fi

# ---------------------------------------------------------------------------
# 7. Is it actually there
# ---------------------------------------------------------------------------
step "Looking for the board"
if "$PYTHON" -m m2k_blocks scan; then
    :
else
    say "No board yet. That is fine if it is not plugged in -- everything"
    say "above is installed either way. Run this to try again:"
    say "  $PYTHON -m m2k_blocks scan"
fi

cat <<EOF

Done. Two things to know:

  * Restart gnuradio-companion. A running one will not pick up a block
    directory it did not have at launch.
  * The blocks appear under [ADALM2000] in the block tree.

If they do not:  $PYTHON -m m2k_blocks check
EOF
