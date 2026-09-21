# Setup

Do this before the session. It takes a few minutes and needs the internet,
which the room may not reliably have.

**What you need already:** GNU Radio, and `gnuradio-companion` working.
This installs the workshop's blocks into it; it does not install GNU Radio.

## One script

**Linux and macOS**

```
curl -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.sh
bash m2k-setup.sh
```

**Windows** — from the Radioconda Prompt:

```
curl.exe -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.ps1
powershell -ExecutionPolicy Bypass -File m2k-setup.ps1
```

Downloaded first, then run, rather than piped straight into a shell — it
wants your password for one step on Linux, and a script that asks for that
is a script worth reading first.

Options, both platforms: `--yes` / `-Yes` answers every prompt, `--python`
/ `-Python` names the interpreter, `--skip-drivers` / `-SkipDrivers` leaves
USB permissions alone.

## What it installs, and why each one

| | what it is | where it comes from |
| --- | --- | --- |
| **gr-iio** | the GNU Radio IIO blocks, `from gnuradio import iio` | ships with GNU Radio — not pip |
| **pylibiio** | the binding round the C library, `import iio` | `python3-libiio`, brew, or pip |
| **gr-m2k** | this workshop's blocks | pip, from this repository |
| **block path** | the line in `~/.gnuradio/config.conf` that makes GRC look | `m2k-blocks install` |
| **USB access** | permission, or a driver | per platform, below |

**The two `iio`s are different things and you need both.** `from gnuradio
import iio` is gr-iio, which streams samples. `import iio` is pylibiio,
which reads and writes attributes — the digital blocks and `m2k_config` use
it for the settings gr-iio has no block for. Neither one implies the other.

## The one thing that goes wrong

`pip install` has to land in the **same interpreter gnuradio-companion
uses**. On a distro GNU Radio that is the system Python; under radioconda it
is the environment's. A fresh venv on some other Python installs cleanly,
puts `m2k-blocks` on your PATH, and still leaves the block tree empty —
because GRC never looks there.

The script works this out from the shebang of `gnuradio-companion` before
it installs anything, and prints what it picked. If it picks wrong, pass
`--python` with the right one.

To check afterwards, at any time:

```
python -m m2k_blocks check
```

It prints the block directory, the interpreter, whether `m2k_blocks`
imports, and every directory GRC will search with ours marked. Exit status
0 means GRC will find the blocks.

## USB access, per platform

**Linux** — no driver needed; the kernel has both the USB ethernet gadget
and the raw USB interface. What it needs is permission. The script offers
to install ADI's udev rule:

```
sudo curl -fsSL https://raw.githubusercontent.com/analogdevicesinc/m2k-fw/master/scripts/53-adi-m2k-usb.rules \
  -o /etc/udev/rules.d/53-adi-m2k-usb.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

The rule grants the board to the **`plugdev`** group. Debian and Ubuntu
have that group; Fedora and Arch do not, and a rule naming a group that
does not exist grants nothing to nobody. Check you are in it:

```
id -nG | tr ' ' '\n' | grep -x plugdev
```

**Windows** — this is the one platform that needs a driver installed. ADI
ship one package covering both interfaces:

<https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases/latest>

Download `PlutoSDR-M2k-USB-Drivers.exe` and run it. The script points you
there rather than running it for you.

**macOS** — no kernel driver: libiio reaches the board through libusb. But
see the next section, because the address in every block is wrong for you.

## macOS: the address is `usb:`, not `ip:192.168.2.1`

Every block in `gr-m2k` defaults its **M2K address** to `ip:192.168.2.1`.
That is the board's USB ethernet gadget, and it needs the host to speak
RNDIS. Linux does. Windows does, once ADI's driver package is in. macOS
needed [HoRNDIS](https://github.com/jwise/HoRNDIS) for it, which is
unmaintained, is built for x86_64, and does not load on Apple silicon at
all.

So on a Mac, use the USB backend instead. Set **M2K address** to:

```
usb:
```

libiio resolves the bare `usb:` on its own when exactly one board is
plugged in, which at a workshop station it is. With more than one, it wants
`usb:<bus>.<address>.<interface>` — `m2k-blocks scan` prints the exact
string.

This is not a macOS-only escape hatch. `usb:` works on Linux and Windows
too once permissions and drivers are sorted, and it skips the network stack
entirely. It is just not the default the blocks were written with.

## Finding the board

```
python -m m2k_blocks scan
```

Prints every context libiio can see, marks the ones that name themselves an
ADALM2000, and gives you the address to paste. It falls back to probing
`ip:192.168.2.1` when nothing advertises itself, because a board at a
static address does not.

## Without the script

Four commands, if you would rather do it yourself. Substitute the
interpreter GRC uses for `python`:

```
python -m pip install pylibiio
python -m pip install "git+https://github.com/livethisdream/grcon26-workshop#subdirectory=gr-m2k"
python -m m2k_blocks install
python -m m2k_blocks check
```

On a distro Python, add `--user`; if pip refuses with
`externally-managed-environment`, add `--break-system-packages` too. Inside
a venv or a conda environment, add neither — pip rejects `--user` there
outright.

## Nothing to install, for one shell

If you have cloned the repository and only want to try the blocks:

```
source gr-m2k/env.sh
gnuradio-companion flowgraphs/m2k_scope.grc
```

`[ADALM2000]` appears in the block tree. Nothing is written to disk and
nothing outside that shell changes. `gr-m2k/README.md` covers the
difference between the two routes.

## Then

Restart `gnuradio-companion` — a running one will not pick up a block
directory it did not have at launch. The blocks appear under
**[ADALM2000]**.
