<#
.SYNOPSIS
    Set a Windows machine up for the GRCon26 GNU Radio + ADALM2000 workshop.

.DESCRIPTION
    Assumes you already have GNU Radio. On Windows that almost always means
    radioconda, and this script wants to run from a shell where
    `python -c "import gnuradio"` works -- the Radioconda Prompt, or a
    PowerShell with the environment activated.

    What it does, in order:

      1. works out which Python has GNU Radio in it
      2. checks gr-iio (`from gnuradio import iio`)
      3. installs pylibiio (`import iio`) if it is missing
      4. installs gr-m2k from GitHub
      5. registers the block directory with GRC, and verifies it
      6. checks for ADI's USB driver package, and offers to fetch it
      7. looks for the board and prints the address to paste into a block

    Nothing installs a driver without asking. -Yes answers yes to all of it.

.PARAMETER Yes
    Answer yes to every prompt.

.PARAMETER Python
    Use this interpreter instead of detecting one.

.PARAMETER SkipDrivers
    Do not check for or offer the USB driver package.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File m2k-setup.ps1
#>

[CmdletBinding()]
param(
    [switch] $Yes,
    [string] $Python = "",
    [switch] $SkipDrivers
)

$ErrorActionPreference = 'Stop'

$Repo       = 'https://github.com/livethisdream/grcon26-workshop'
$Pkg        = "git+$Repo#subdirectory=gr-m2k"
$DriversUrl = 'https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases/latest'

# ---------------------------------------------------------------------------
# Output. Steps are numbered because what people report back is "it stopped
# at 4", and a number makes that answerable.
# ---------------------------------------------------------------------------
$script:StepNo = 0
function Step($text) {
    $script:StepNo++
    Write-Host ""
    Write-Host ("[{0}/7] {1}" -f $script:StepNo, $text)
}
function Say  ($text) { Write-Host ("      " + $text) }
function Warn ($text) { Write-Host ("      WARNING: " + $text) -ForegroundColor Yellow }
function Die  ($text) { Write-Host ""; Write-Host ("FAILED: " + $text) -ForegroundColor Red; exit 1 }

function Ask($question) {
    if ($Yes) { return $true }
    $reply = Read-Host ("      " + $question + " [y/N]")
    return $reply -match '^(y|yes)$'
}

# Both of these expect the import to fail sometimes. Windows PowerShell 5.1
# turns redirected native stderr into error records, and under the
# script-wide 'Stop' the first traceback would end the script instead of
# returning false -- so each relaxes it for its own scope.
function ImportsGnuRadio($exe) {
    if (-not $exe) { return $false }
    $ErrorActionPreference = 'Continue'
    & $exe -c 'import gnuradio' 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function CanImport($module) {
    $ErrorActionPreference = 'Continue'
    & $PyExe -c "import $module" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

Write-Host 'GRCon26 workshop setup -- windows'

# ---------------------------------------------------------------------------
# 1. The interpreter
#
# The same trap as everywhere else: pip has to land in the interpreter
# gnuradio-companion imports from. On Windows that is the radioconda
# environment, and a stray python.exe from the Store or from python.org
# will install cleanly into the wrong one.
# ---------------------------------------------------------------------------
Step 'Finding the Python that GNU Radio uses'

if ($Python) {
    Say "using $Python, because you said so"
    if (-not (ImportsGnuRadio $Python)) { Die "$Python cannot import gnuradio" }
    $PyExe = $Python
} else {
    $candidates = @()
    # gnuradio-companion.exe sits in the same Scripts/ or env root as the
    # python.exe that runs it, so it is the best evidence available.
    $grc = Get-Command gnuradio-companion -ErrorAction SilentlyContinue
    if ($grc) {
        Say ("gnuradio-companion is " + $grc.Source)
        $dir = Split-Path -Parent $grc.Source
        $candidates += (Join-Path $dir 'python.exe')
        # In a conda env the scripts live in Scripts\ and python.exe in the
        # env root one level up.
        $candidates += (Join-Path (Split-Path -Parent $dir) 'python.exe')
    } else {
        Warn 'gnuradio-companion is not on your PATH'
        Say 'If you have radioconda, run this from the Radioconda Prompt.'
    }
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }

    $PyExe = $null
    foreach ($c in $candidates) {
        if ((Test-Path $c) -and (ImportsGnuRadio $c)) { $PyExe = $c; break }
    }
    if (-not $PyExe) {
        Die ("no Python here can 'import gnuradio'. Open the Radioconda " +
             "Prompt and run this again, or pass -Python with the path to " +
             "the right python.exe.")
    }
    Say "using $PyExe"
}

# No quotes inside the Python: 5.1 strips embedded double quotes from
# arguments to native programs.
$pyv = & $PyExe -c 'import platform; print(platform.python_version())'
Say "Python $pyv"

function PipInstall($what) {
    # No --user here. On Windows the interpreter is nearly always a conda
    # environment the user owns outright, and pip's --user directory is not
    # on that environment's import path -- installing there is the same
    # silent miss the whole script exists to avoid.
    & $PyExe -m pip install --upgrade $what
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------
# 2. gr-iio
# ---------------------------------------------------------------------------
Step 'Checking gr-iio'
if (CanImport 'gnuradio.iio') {
    Say 'gr-iio is there'
} else {
    Warn "'from gnuradio import iio' fails in this interpreter"
    Say 'gr-iio ships with GNU Radio; it does not come from pip. In'
    Say 'radioconda:  conda install -c conda-forge gnuradio-iio'
    Say 'Continuing -- but no flowgraph will run until this is fixed.'
}

# ---------------------------------------------------------------------------
# 3. pylibiio
#
# `from gnuradio import iio` is gr-iio, the blocks. `import iio` is
# pylibiio, the binding round the C library, which the digital blocks and
# m2k_config use for attributes gr-iio has no block for. Two different
# things with the same import name on one side.
# ---------------------------------------------------------------------------
Step 'Checking pylibiio'
if (CanImport 'iio') {
    Say 'pylibiio is there'
} else {
    Say 'pylibiio is missing -- the binding round libiio, not gr-iio'
    if (-not (PipInstall 'pylibiio')) { Warn 'pip could not install pylibiio' }
    if (CanImport 'iio') {
        Say 'pylibiio is there now'
    } else {
        Warn 'pylibiio still will not import.'
        Say 'The wheel is a wrapper and needs libiio itself alongside it.'
        Say 'The libiio Windows installer provides that:'
        Say '  https://github.com/analogdevicesinc/libiio/releases'
    }
}

# ---------------------------------------------------------------------------
# 4. The blocks
# ---------------------------------------------------------------------------
Step 'Installing gr-m2k'
Say "from $Repo"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Die ("git is not on your PATH, and pip needs it to fetch from GitHub. " +
         "Install git, or download the repository as a zip and run " +
         "`pip install .\gr-m2k` from inside it.")
}
if (-not (PipInstall $Pkg)) { Die 'could not install gr-m2k' }
Say 'installed'

# ---------------------------------------------------------------------------
# 5. Telling GRC where they are
# ---------------------------------------------------------------------------
Step 'Registering the blocks with GNU Radio Companion'
& $PyExe -m m2k_blocks install
Write-Host ''
& $PyExe -m m2k_blocks check
if ($LASTEXITCODE -eq 0) {
    Say 'GRC will find the blocks'
} else {
    Warn 'GRC will not find the blocks yet -- read the check output above'
}

# ---------------------------------------------------------------------------
# 6. The USB driver
#
# This is the one platform that genuinely needs a driver installed. ADI
# ship one package covering both the WinUSB interface libiio uses and the
# network interface behind ip:192.168.2.1.
# ---------------------------------------------------------------------------
Step 'USB drivers'
if ($SkipDrivers) {
    Say 'skipped, because you said -SkipDrivers'
} else {
    $installed = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
                 Where-Object { $_.DeviceName -match 'ADALM|PlutoSDR|M2k' }
    if ($installed) {
        Say 'an ADI USB driver is already present'
    } else {
        Say 'Windows needs ADI''s driver package for the M2K. It carries'
        Say 'both interfaces: the WinUSB one libiio uses directly, and the'
        Say 'network one behind ip:192.168.2.1.'
        Say ''
        Say "  $DriversUrl"
        Say ''
        Say 'Download PlutoSDR-M2k-USB-Drivers.exe from there and run it.'
        Say 'It is an installer with a UI; this script will not run it for'
        Say 'you, because installing a driver unattended is not something'
        Say 'to do to somebody''s laptop.'
        if (Ask 'open that page in your browser now?') {
            Start-Process $DriversUrl
        }
    }
}

# ---------------------------------------------------------------------------
# 7. Is it actually there
# ---------------------------------------------------------------------------
Step 'Looking for the board'
& $PyExe -m m2k_blocks scan
if ($LASTEXITCODE -ne 0) {
    Say 'No board yet. That is fine if it is not plugged in -- everything'
    Say 'above is installed either way. Run this to try again:'
    Say "  $PyExe -m m2k_blocks scan"
}

Write-Host @"

Done. Two things to know:

  * Restart gnuradio-companion. A running one will not pick up a block
    directory it did not have at launch.
  * The blocks appear under [ADALM2000] in the block tree.

If they do not:  $PyExe -m m2k_blocks check
"@
