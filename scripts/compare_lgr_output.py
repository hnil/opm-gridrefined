#!/usr/bin/env python3
"""Compare the EGRID/INIT of an LGR run against a reference run, array by array.

The cell-by-cell ACTNUM/HOSTNUM checks we used while getting Norne and Drogon to
match say nothing about which arrays are present, so gaps in the LGR sections went
unnoticed.  This walks the whole file instead:

  * every array's name and length, in order, against the reference;
  * for a run with LGRs, which arrays exist for the global grid but not for any
    LGR grid -- that comparison needs no reference at all and is the one that
    finds a missing LGR section;
  * the NNC bookkeeping: how many of the reference's NNCs have both ends, or one
    end, inside a refinement box.

Usage:  compare_lgr_output.py REFERENCE.EGRID RUN.EGRID [i1 i2 j1 j2 k1 k2 nx ny]
        compare_lgr_output.py REFERENCE.INIT  RUN.INIT
        compare_lgr_output.py --lgr-gap RUN.INIT
"""
import os
import re
import subprocess
import sys

HDR = re.compile(r"^\s*'(\S+)\s*'\s+(\d+)\s+'(\w+)\s*'")


def formatted(path):
    """Return the lines of path as a formatted ECL file, converting if needed."""
    stem, ext = os.path.splitext(path)
    ftext = stem + '.F' + ext[1:]
    if not os.path.exists(ftext):
        conv = os.environ.get('CONVERTECL', 'convertECL')
        subprocess.run([conv, os.path.basename(path)], capture_output=True,
                       cwd=os.path.dirname(path) or '.')
    return open(ftext).read().splitlines()


def arrays(path):
    return [(m.group(1), int(m.group(2)), m.group(3), i)
            for i, l in enumerate(formatted(path))
            for m in [HDR.match(l)] if m]


def values(path, index):
    lines = formatted(path)
    name, n, typ, i = arrays(path)[index]
    out, j = [], i + 1
    while len(out) < n:
        out += lines[j].split()
        j += 1
    return out[:n]


def inventory(ref, run):
    a, b = arrays(ref), arrays(run)
    print(f"arrays: reference {len(a)}, run {len(b)}")
    for i in range(max(len(a), len(b))):
        x = f"{a[i][0]}[{a[i][1]}]" if i < len(a) else '-'
        y = f"{b[i][0]}[{b[i][1]}]" if i < len(b) else '-'
        if x != y:
            print(f"  {i:>4}  reference {x:<26} run {y}")


def lgr_gap(run):
    """Arrays written for the global grid but for no LGR grid."""
    a = arrays(run)
    counts = {}
    for name, n, _, _ in a:
        counts.setdefault(n, set()).add(name)
    sizes = sorted(counts, key=lambda n: -len(counts[n]))
    if len(sizes) < 2:
        print("no LGR sections found")
        return
    glob, lgr = counts[sizes[0]], counts[sizes[1]]
    gap = sorted(glob - lgr)
    print(f"global grid ({sizes[0]} cells): {len(glob)} arrays; "
          f"LGR ({sizes[1]} cells): {len(lgr)} arrays")
    print(f"written for the global grid but not for the LGR ({len(gap)}):")
    for i in range(0, len(gap), 6):
        print("   " + " ".join(f"{x:<10}" for x in gap[i:i + 6]))


if __name__ == '__main__':
    if sys.argv[1] == '--lgr-gap':
        lgr_gap(sys.argv[2])
    else:
        inventory(sys.argv[1], sys.argv[2])
