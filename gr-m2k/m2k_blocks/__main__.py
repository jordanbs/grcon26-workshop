"""`python -m m2k_blocks` — the same CLI as the `m2k-blocks` script.

The console script pip installs is the nicer spelling, but it only works
if pip's script directory is on PATH, and a `pip install --user` on a
distro Python routinely puts it somewhere that is not. The setup scripts
in `install/` call this form instead, because the interpreter they just
installed into is the one thing they are certain of.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
