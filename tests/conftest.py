import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The IIO discovery suite lives in iio-tools/ rather than at the root: this
# repo teaches the gr-m2k blocks, and a root full of iio_*.py said otherwise.
# The directory name has a hyphen in it, so it can never be a package -- the
# scripts are imported by putting their directory on the path, which is also
# how they run from a shell.
TOOLS = os.path.join(ROOT, "iio-tools")
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

FIXTURE = os.path.join(TOOLS, "fixtures", "m2k-snapshot.json")
REAL = os.path.join(TOOLS, "fixtures", "m2k-real.json")


@pytest.fixture(scope="session")
def snapshot():
    with open(FIXTURE) as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def repo_root():
    return ROOT


@pytest.fixture(scope="session")
def tools_root():
    """iio-tools/, which is the working directory those scripts expect.

    They name their fixtures relatively (`fixtures/m2k-snapshot.json`), so a
    subprocess test runs them from here rather than from the repo root.
    """
    return TOOLS


@pytest.fixture(scope="session")
def real_snapshot():
    """The capture from actual hardware, if it is checked out.

    Skipped rather than required so the suite still runs for someone who
    only has the synthetic fixture.
    """
    if not os.path.exists(REAL):
        pytest.skip("no iio-tools/fixtures/m2k-real.json; capture one with "
                    "iio-tools/iio_discover.py --uri <uri> --json "
                    "> iio-tools/fixtures/m2k-real.json")
    with open(REAL) as handle:
        return json.load(handle)
