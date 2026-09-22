# Setup

Do this before the session. It takes a few minutes and needs the internet,
which the room may not reliably have.

**What you need already:** GNU Radio, and `gnuradio-companion` working.
This installs the workshop's blocks into it; it does not install GNU Radio.

## One script

Download the repository as a zip — **Code → Download ZIP** on GitHub, or
<https://github.com/livethisdream/grcon26-workshop/archive/refs/heads/main.zip>
— unzip it, and run the script from its `install` folder. Everything the
script would otherwise download is already in there, so after the zip it
needs no internet and no git.

**Windows** — from the Radioconda Prompt, in the unzipped `install` folder:

```
powershell -ExecutionPolicy Bypass -File m2k-setup.ps1
```

**Linux and macOS** — in the unzipped `install` folder:

```
bash m2k-setup.sh
```

The script reads well before it runs — it wants your password for one step
on Linux, and a script that asks for that is a script worth reading first.

### Just the script

The script also works on its own, and downloads what it would have found
beside it:

```
curl.exe -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.ps1
curl -fsSLO https://raw.githubusercontent.com/livethisdream/grcon26-workshop/main/install/m2k-setup.sh
```

### If PowerShell refuses to run it

```
m2k-setup.ps1 cannot be loaded because running scripts is disabled on this system
```

That is Windows' execution policy, not the script. `-ExecutionPolicy
Bypass` sets the policy for one process and is the whole reason the
command above is written that way, so this error means the script was
started some other way — double-clicked, or `.\m2k-setup.ps1` from a
prompt. Run it exactly as written.

Refused even from the documented command means the policy comes from
Group Policy, which `-ExecutionPolicy` cannot override:

```
Get-ExecutionPolicy -List
```

`MachinePolicy` or `UserPolicy` at anything other than `Undefined` is a
managed machine, and there is no user-level way round it. Two ways past:

```
Get-Content .\m2k-setup.ps1 | powershell -NoProfile -Command -
```

A piped command is not a script file and is not governed by the script
policy. Or do it by hand — **Without the script**, below — which
involves PowerShell not at all, and is the better answer on a laptop
whose policy you do not control.

One smaller case: `RemoteSigned` blocks a file carrying the mark of the
web, which a downloaded one does. `Unblock-File .\m2k-setup.ps1` clears
it. Unzipping with Explorer marks every file it extracts, so the zip
route needs this too.

## What is in this folder

| file | what it is |
| --- | --- |
| `m2k-setup.ps1`, `m2k-setup.sh` | the setup scripts |
| `gr_m2k-0.1.0-py3-none-any.whl` | the workshop's blocks, built from `gr-m2k/`. Rebuild it when `gr-m2k/` changes — `tests/test_packaging.py` fails until you do |
| `PlutoSDR-M2k-USB-Drivers.exe` | ADI's Windows driver package, v0.9 (the current release), signed by Analog Devices. SHA-256 `C53DAC79BE6AF8E268B2B5460856D46501F3A61C7B820CBFC3FE24288960550D`. From <https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases> |
| `53-adi-m2k-usb.rules` | ADI's udev rule for Linux, from `analogdevicesinc/m2k-fw` `scripts/` |

To rebuild the wheel from what is committed — not the working tree, which
on Windows has CRLF line endings — with the interpreter GRC uses:

```
git -c core.autocrlf=false archive --format=zip -o gr-m2k-src.zip HEAD gr-m2k
```

then unzip it and run `python -m pip wheel --no-deps -w install <unzipped>/gr-m2k`
from the repository root.

Options, both platforms: `--yes` / `-Yes` answers every prompt, `--python`
/ `-Python` names the interpreter, `--skip-drivers` / `-SkipDrivers` leaves
USB permissions alone.

## What it installs, and why each one

| | what it is | where it comes from |
| --- | --- | --- |
| **gr-iio** | the GNU Radio IIO blocks, `from gnuradio import iio` | ships with GNU Radio — not pip |
| **pylibiio** | the binding round the C library, `import iio` | `python3-libiio`, brew, or pip. On Windows pip brings the wrapper only, and `libiio` itself has to come from somewhere else — see below |
| **gr-m2k** | this workshop's blocks | pip, from the wheel in this folder |
| **block path** | the line in GNU Radio's `config.conf` that makes GRC look (`%APPDATA%\.config\gnuradio\` on Windows) | `m2k-blocks install` |
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

### Which interpreter was it, and undoing it

When `check` says

```
GNU Radio     not importable from this interpreter: ...
```

the install landed somewhere GRC will never look. The `interpreter` line
printed just above is where — that is `sys.executable`, the Python that
ran the command. If the scrollback is gone, `python -m pip show gr-m2k`
prints the same answer as its `Location:`, and `Get-Command python -All`
lists every `python.exe` on PATH in the order Windows resolves them. On a
fresh Windows machine the usual culprits are the Store stub in
`%LOCALAPPDATA%\Microsoft\WindowsApps` and a python.org install in
`%LOCALAPPDATA%\Programs\Python`, either of which shadows radioconda's
when the prompt is a plain PowerShell rather than the Radioconda Prompt.

Undo it before installing again:

```
<wrong-python.exe> -m m2k_blocks uninstall
<wrong-python.exe> -m pip uninstall gr-m2k pylibiio
```

`uninstall` is the one that matters. `install` writes a block path into
GNU Radio's `config.conf`, and on an interpreter without GNU Radio it
cannot ask where that is, so it falls back to `~/.gnuradio/config.conf`
— which is not the file radioconda reads. The entry is both wrong and
invisible, and the next `check` will not mention it.

Then run the script again with `-Python` / `--python` naming the right
interpreter, which skips the detection entirely.

## pylibiio installs, and `import iio` still fails

Step 3 of the script warns rather than stops. It is the step that most
often warns on Windows, and the reason is that pylibiio is a `ctypes`
wrapper: the wheel carries no library of its own, and `import iio` loads
`libiio` from the system. Distribution packages and Homebrew install the
two together. Pip on Windows installs only the wrapper.

Get the real error first, because pip failing and the library missing
look the same from the script's warning:

```
python -c "import iio"
```

An `OSError` naming `libiio` is the missing library. Anything raised by
pip itself — a proxy, TLS interception, `externally-managed-environment`
— is a different problem with a different fix.

ADI ship a Windows installer for the library:
<https://github.com/analogdevicesinc/libiio/releases>. **Check the major
version before taking the top of that page.** pylibiio tracks the 0.x C
API; 1.x is not the same API, and a 1.x DLL leaves `import iio` failing
in a way indistinguishable from having no DLL at all.

On radioconda, installing the library through conda is worth trying
first. It lands inside the environment, where a system-wide DLL left by
some other Python cannot shadow it, and conda matches the wrapper to the
library rather than leaving you to do it by version number.

Either way the test is the same: `import iio` returns silently, and then
`python -m m2k_blocks scan` sees the board.

**Not yet confirmed on a machine.** Neither the version rule nor the
conda route has been watched working on the venue laptop; both are
written from the failure mode. Whoever hits this next should replace this
paragraph with what actually worked.

## USB access, per platform

**Linux** — no driver needed; the kernel has both the USB ethernet gadget
and the raw USB interface. What it needs is permission. The script offers
to install ADI's udev rule, which is in this folder:

```
sudo install -m 0644 53-adi-m2k-usb.rules /etc/udev/rules.d/
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

`PlutoSDR-M2k-USB-Drivers.exe` is in this folder. The script offers to
start it; it opens its own window and asks for administrator rights, so
nothing installs without you clicking through it. Windows may warn that
the file came from the internet — it is signed by Analog Devices.

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
python -m pip install --force-reinstall --no-deps install/gr_m2k-0.1.0-py3-none-any.whl
python -m m2k_blocks install
python -m m2k_blocks check
```

Without the repository, the second line becomes
`python -m pip install "gr-m2k @ https://github.com/livethisdream/grcon26-workshop/archive/refs/heads/main.zip#subdirectory=gr-m2k"`.

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
