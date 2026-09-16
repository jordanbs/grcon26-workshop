# Put the M2K blocks on GNU Radio's search paths, for this shell only.
#
#     source gr-m2k/env.sh
#
# There are two paths and they do different jobs.
#
#   GRC_BLOCKS_PATH  where gnuradio-companion looks for block definitions.
#                    Decides whether [ADALM2000] appears in the block tree.
#   PYTHONPATH       where the generated flowgraph looks for the code behind
#                    them. Decides whether Run works.
#
# Set only the first and the failure is confusing: the blocks appear, the
# canvas validates, and the flowgraph dies on Run with an ImportError.
#
# Both are prepended -- GRC concatenates GRC_BLOCKS_PATH ahead of the
# system directories rather than replacing them, so the stock blocks stay.
# Both are idempotent. Nothing is written to disk, and nothing outside this
# shell changes. For an install that outlives the shell, see the pip route
# in gr-m2k/README.md.

if [ -z "${BASH_SOURCE[0]}" ]; then
    echo "env.sh needs bash. In another shell, export the two paths by hand:" >&2
    echo "  export GRC_BLOCKS_PATH=/path/to/gr-m2k/grc:\$GRC_BLOCKS_PATH" >&2
    echo "  export PYTHONPATH=/path/to/gr-m2k:\$PYTHONPATH" >&2
    return 1 2>/dev/null || exit 1
fi

_m2k_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Prepend $2 to the variable named $1, unless it is already in there.
_m2k_prepend() {
    local name=$1 dir=$2 current=${!1}
    case ":${current}:" in
        *":${dir}:"*) return 0 ;;
    esac
    if [ -n "${current}" ]; then
        export "${name}=${dir}:${current}"
    else
        export "${name}=${dir}"
    fi
}

_m2k_prepend GRC_BLOCKS_PATH "${_m2k_root}/grc"
_m2k_prepend PYTHONPATH "${_m2k_root}"

echo "M2K blocks: $(ls "${_m2k_root}"/grc/*.block.yml 2>/dev/null | wc -l) definitions from ${_m2k_root}/grc"

unset -f _m2k_prepend
unset _m2k_root
