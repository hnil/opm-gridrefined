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

  * the values, not just the names -- an array can be present, the right length
    and still wrong, which is how a refined grid that had lost half its vertical
    transmissibility passed every check we ran on Drogon and Norne;
  * a reference-free sibling check: children of one coarse cell should have
    comparable transmissibilities, so one child at a fraction of a percent of its
    siblings is a defect, and HOSTNUM tells us who the siblings are.

Usage:  compare_lgr_output.py REFERENCE.EGRID RUN.EGRID [i1 i2 j1 j2 k1 k2 nx ny]
        compare_lgr_output.py REFERENCE.INIT  RUN.INIT
        compare_lgr_output.py --lgr-gap RUN.INIT
        compare_lgr_output.py --values REFERENCE.INIT RUN.INIT
        compare_lgr_output.py --siblings RUN.EGRID RUN.INIT
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


def _numbers(path, index):
    return [float(x) for x in values(path, index)]


def compare_values(ref, run, rtol=1e-3):
    """Compare the values of every array the two files share, in file order."""
    a, b = arrays(ref), arrays(run)
    common = [(i, x) for i, x in enumerate(a)
              if i < len(b) and (b[i][0], b[i][1]) == (x[0], x[1])]
    print(f"comparing {len(common)} arrays present in both with the same length")
    for i, (name, n, typ, _) in common:
        if typ not in ('REAL', 'DOUB'):
            continue
        x, y = _numbers(ref, i), _numbers(run, i)
        pairs = [(p, q) for p, q in zip(x, y) if abs(p) > 0.0]
        if not pairs:
            continue
        ratios = sorted(q / p for p, q in pairs)
        off = sum(1 for p, q in pairs if abs(q / p - 1.0) > rtol)
        if not off:
            continue
        mid = ratios[len(ratios) // 2]
        print(f"  {name:<10}[{n:>7}]  {off:>7} of {len(pairs)} differ by >{rtol:g}"
              f"   run/reference  p1 {ratios[len(ratios)//100]:.4f}"
              f"  median {mid:.4f}  p99 {ratios[-len(ratios)//100 - 1]:.4f}")


def siblings(egrid, init, floor=0.1):
    """Children of one coarse cell should have comparable transmissibilities.

    Needs no reference: HOSTNUM says which refined cells share a father, and a
    child whose TRAN* is a small fraction of its siblings' median is a sliver
    where a full face should be.

    Calibrate against a grid you trust before reading anything into a count.  A
    few per cent of the lateral faces are genuine slivers at fault
    juxtapositions -- on Drogon the reference run itself flags 2577 TRANX
    and 5335 TRANY children, against OPM's 2762 and 4788.  TRANZ is the sharp
    one: the reference flags none, and OPM flagged 82897 of 166848 while the
    refined-refined face centre was wrong.
    """
    ge = arrays(egrid)
    hosts = [i for i, (name, *_) in enumerate(ge) if name == 'HOSTNUM']
    if not hosts:
        print("no HOSTNUM: not a refined grid")
        return
    gi = arrays(init)
    for lgr, h in enumerate(hosts, start=1):
        hostnum = [int(v) for v in values(egrid, h)]
        ncell = len(hostnum)
        # PORV is written for every cell of the LGR, TRAN* only for the active ones.
        porv = next((_numbers(init, i) for i, (nm, n, *_) in enumerate(gi)
                     if nm == 'PORV' and n == ncell), None)
        if porv is None:
            print(f"LGR {lgr}: no PORV of length {ncell} in the INIT")
            continue
        active = [c for c, v in enumerate(porv) if v > 0.0]
        for kw in ('TRANX', 'TRANY', 'TRANZ'):
            tran = next((_numbers(init, i) for i, (nm, n, *_) in enumerate(gi)
                         if nm == kw and n == len(active)), None)
            if tran is None:
                continue
            family = {}
            for slot, c in enumerate(active):
                family.setdefault(hostnum[c], []).append(tran[slot])
            bad = tot = 0
            worst = None
            for vals in family.values():
                vals = [v for v in vals if v > 0.0]
                if len(vals) < 2:
                    continue
                vals.sort()
                mid = vals[len(vals) // 2]
                for v in vals:
                    tot += 1
                    if v < floor * mid:
                        bad += 1
                        if worst is None or v / mid < worst:
                            worst = v / mid
            note = " <-- vertical faces should not do this" if kw == 'TRANZ' else ""
            if bad:
                print(f"LGR {lgr} {kw}: {bad} of {tot} children below {floor:g} of "
                      f"their siblings' median (worst {worst:.4f}){note}")
            else:
                print(f"LGR {lgr} {kw}: {tot} children, none below {floor:g} of "
                      f"their siblings' median")


if __name__ == '__main__':
    if sys.argv[1] == '--lgr-gap':
        lgr_gap(sys.argv[2])
    elif sys.argv[1] == '--values':
        compare_values(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == '--siblings':
        siblings(sys.argv[2], sys.argv[3])
    else:
        inventory(sys.argv[1], sys.argv[2])
