"""Where the block definitions went, and how to tell GRC about them.

Installed by `pip install` as `m2k-blocks`. Four subcommands, of which
exactly two write anything:

    m2k-blocks path        print the installed grc directory
    m2k-blocks check       say whether GRC will find the blocks, and why not
    m2k-blocks install     add that directory to ~/.gnuradio/config.conf
    m2k-blocks uninstall   take it back out

`check` is the one that earns its place at a bench. "The blocks are not in
the tree" has two unrelated causes -- a block path GRC never saw, and a
`m2k_blocks` it cannot import -- and from the block tree they look
identical. One of them is invisible until you press Run.

Nothing here imports GNU Radio at module scope, so `path` and `install`
still work on a machine where GNU Radio itself is broken.
"""

import configparser
import glob
import os
import shutil
import sys

CONFIG = os.path.join("~", ".gnuradio", "config.conf")

# GRC reads this file for the `[grc] local_blocks_path` key. The other file
# in that directory, grc.conf, is GUI state and says so in its own first
# line -- it is not the one to edit.
HEADER = """\
# GNU Radio user configuration.
#
# local_blocks_path is where gnuradio-companion looks for out-of-tree block
# definitions, in addition to the system directories. Written by
# `m2k-blocks install`; `m2k-blocks uninstall` removes it again.
"""


def grc_dir():
    """The directory of .block.yml files, wherever pip put them.

    Two layouts, because the source tree and the wheel differ. Installed,
    the definitions sit inside the package at `m2k_blocks/grc`. In the
    source tree -- a git clone, or `pip install -e` -- they sit beside it
    at `gr-m2k/grc`, where every README and the bench checklist name them.
    Prefer the installed one, fall back to the sibling, so `check` tells
    the truth in both.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    inside = os.path.join(here, "grc")
    if os.path.isdir(inside):
        return inside
    return os.path.join(os.path.dirname(here), "grc")


def definitions():
    return sorted(glob.glob(os.path.join(grc_dir(), "*.block.yml")))


def config_path():
    return os.path.expanduser(CONFIG)


def _entries(parser):
    raw = parser.get("grc", "local_blocks_path", fallback="")
    return [e for e in raw.split(os.pathsep) if e]


def _save(parser, path, existed):
    if existed:
        # configparser rewrites the whole file and drops comments, so leave
        # the original where it can be found.
        shutil.copy2(path, path + ".bak")
        print("kept a copy at %s.bak" % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        if not existed:
            handle.write(HEADER)
        parser.write(handle)


def cmd_path(argv):
    """Print the grc directory. One line, for scripts to consume."""
    print(grc_dir())
    return 0


def cmd_install(argv):
    """Put the grc directory in ~/.gnuradio/config.conf, for every terminal."""
    target, path = grc_dir(), config_path()
    parser = configparser.ConfigParser()
    existed = os.path.exists(path)
    if existed:
        parser.read(path)
    have = _entries(parser)
    if target in have:
        print("already installed: %s" % path)
        return 0
    if not parser.has_section("grc"):
        parser.add_section("grc")
    parser.set("grc", "local_blocks_path", os.pathsep.join([target] + have))
    _save(parser, path, existed)
    print("added %s to %s" % (target, path))
    print("Restart gnuradio-companion; a running one will not pick up a new "
          "directory.")
    return 0


def cmd_uninstall(argv):
    """Take it back out. Leaves any other path in the key alone."""
    target, path = grc_dir(), config_path()
    if not os.path.exists(path):
        print("nothing to do: %s does not exist" % path)
        return 0
    parser = configparser.ConfigParser()
    parser.read(path)
    have = _entries(parser)
    if target not in have:
        print("nothing to do: %s is not in %s" % (target, path))
        return 0
    keep = [e for e in have if e != target]
    parser.set("grc", "local_blocks_path", os.pathsep.join(keep))
    _save(parser, path, True)
    print("removed %s from %s" % (target, path))
    return 0


def cmd_check(argv):
    """Answer 'why are the blocks not in the tree' without guessing."""
    ok = True
    found = definitions()
    print("definitions   %s" % grc_dir())
    print("              %d block%s" % (len(found), "" if len(found) == 1 else "s"))
    if not found:
        print("              -- nothing here, so the install is broken")
        ok = False

    # The import side. This is the half that is invisible until Run.
    print("interpreter   %s" % sys.executable)
    try:
        import m2k_blocks.m2k_scale  # noqa: F401
        print("m2k_blocks    imports")
    except Exception as problem:            # pragma: no cover - install fault
        print("m2k_blocks    DOES NOT IMPORT: %s" % problem)
        ok = False

    # The block-path side.
    try:
        from gnuradio import gr
        from gnuradio.grc.core.Config import Config
        paths = Config(version="3.10", prefs=gr.prefs()).block_paths
    except Exception as problem:
        print("GNU Radio     not importable from this interpreter: %s" % problem)
        print("              If gnuradio-companion runs, it is using a "
              "different Python than this one, and that is the bug: install "
              "into that one.")
        return 1

    mine = os.path.realpath(grc_dir())
    seen = False
    print("GRC searches")
    for entry in paths:
        here = os.path.realpath(entry) == mine
        seen = seen or here
        print("              %s%s" % (entry, "   <-- ours" if here else ""))
    if not seen:
        print("              -- ours is not on the list. Run `m2k-blocks "
              "install`, or source gr-m2k/env.sh.")
        ok = False

    print("verdict       %s" % ("GRC will find the blocks" if ok
                                else "GRC will not find the blocks"))
    return 0 if ok else 1


COMMANDS = {"path": cmd_path, "check": cmd_check,
            "install": cmd_install, "uninstall": cmd_uninstall}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        sys.stderr.write(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
