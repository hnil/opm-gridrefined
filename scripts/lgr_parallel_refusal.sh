#!/usr/bin/env bash
#
# A refused LGR input must stop the run on every MPI rank, not hang it.
# Reports REFUSED, RAN or HANG per deck on 2 and 3 ranks; exits 1 on a hang.
#
# Usage: lgr_parallel_refusal.sh [-f FLOW] [-d DECKDIR] [-w WORKDIR] [-t SECONDS]
set -u

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLOW="${WS}/builds/refined/opm-simulators/bin/flow_blackoil"
DECKS="${WS}/opm-tests/lgr"
WORK="${TMPDIR:-/tmp}/lgr_parallel_refusal"
TIMEOUT=120

while getopts "f:d:w:t:" opt; do
    case "$opt" in
        f) FLOW="$OPTARG" ;;
        d) DECKS="$OPTARG" ;;
        w) WORK="$OPTARG" ;;
        t) TIMEOUT="$OPTARG" ;;
        *) exit 2 ;;
    esac
done

# Decks refused at input, at grid build or at setup.
CASES=(
    SPE1CASE1_CARFIN_BLOCKACTNUM_EMPTY   # block ACTNUM empties a host
    SPE1CASE1_CARFIN1_AQUNUM_IN_LGR      # numerical aquifer inside a box
    SPE1CASE1_CARFIN_GR                  # box cannot be kept on one rank
    TLGR_SIDE_BAD                        # incompatible subdivisions
    SPE1CASE1_CARFIN1_NESTED             # nested box touching its parent
)

mkdir -p "$WORK"
hangs=0
for deck in "${CASES[@]}"; do
    for np in 2 3; do
        out="$WORK/$deck-np$np"
        rm -rf "$out"
        OMP_NUM_THREADS=1 mpirun --timeout "$TIMEOUT" -np "$np" "$FLOW" \
            "$DECKS/$deck.DATA" --output-dir="$out" > "$out.log" 2>&1
        rc=$?
        if grep -q "time limit" "$out.log"; then
            verdict=HANG
            hangs=$((hangs + 1))
        elif [ "$rc" -eq 0 ]; then
            verdict=RAN
        else
            verdict=REFUSED
        fi
        printf '%-38s np=%d  %s\n' "$deck" "$np" "$verdict"
    done
done

exit $(( hangs > 0 ))
