# LGR output status against the reference runs

2026-08-27. Every EGRID and INIT array in this tree that has a reference run,
compared array by array with `scripts/compare_ecl_files.py` and
`scripts/compare_ecl_nnc.py`.

This supersedes the earlier claims that the refined output "matched the
reference". Those checks compared ACTNUM, HOSTNUM and PORV cell by cell, and array
*names and lengths*. They never compared a transmissibility, and where they did
compare values I read medians, which hid the tails. The numbers below are the
whole arrays.

## Method, and two traps in it

- **Sections.** An LGR header opens a section; `ENDLGR` closes it in the EGRID and
  `LGRSGONE` in the INIT. Get this wrong and the global NNC block is attributed to
  the LGR, and a name that occurs at two lengths in one file -- as the region
  arrays do -- pairs against the wrong copy.
- **Tolerance.** `REAL` arrays are single precision, so a relative difference of
  ~2e-6 is the storage format, not a difference. At 1e-6 every one of Drogon's
  36453 coarse `TRANZ` values outside the box "differs"; at 1e-5, none do.
- **NNC lists are unordered**, and the two writers order each *pair* oppositely --
  the reference writes (3148, 2863) where OPM writes (2863, 3148). Compared by position
  they look 100 % different; matched on the sorted pair they agree exactly.

## Where each case stands

| | model2_lgr (3x3x2) | Norne (3x3x1) | Drogon (3x2x1) |
|---|---|---|---|
| grid: ACTNUM, HOSTNUM, ZCORN | identical | identical | identical |
| refined `COORD` | see below | see below | median 1.4 mm from the reference, tail to 6.7 m |
| refined `DX` / `DY` | identical | close | median 0.012 % / 0.007 %, 5.2 % / 1.0 % of cells over 1 % |
| refined `PORV` | identical | close | median 0.02 %, 6.7 % of cells over 1 % |
| refined `DZ`, `DEPTH`, `PORO`, `NTG`, `PERM*` | identical | identical | identical |
| refined `TRANX` | identical | median 1.0000 | **median 0.7632** |
| refined `TRANY` | identical | median 1.0000 | median 1.0000, p1 0.669 p99 1.98 |
| refined `TRANZ` | identical | median 0.9999 | median 0.9994 (was 0.054) |
| refined NNC transmissibilities | identical | median 1.0018 | **median 0.6775** |
| LGR<->global NNC transmissibilities | identical | median 1.0001 | median 0.9056 |
| global NNC list | 26 of 445 missing | 698 of 11287 missing | 5077 of 6247 missing |

model2_lgr is a near-Cartesian grid and matches the reference on everything except
the global NNCs inside the box. Norne and Drogon are faulted corner-point grids
with individually tilted pillars, and that is where the refined geometry parts
company.

## What this says

**The refined geometry is close, not different in kind.** Both files are
internally consistent: each one's `DX` matches the `DX` rebuilt from its own
`COORD` and `ZCORN` to 1e-4, so neither misdescribes its own grid. The refined
pillars agree to a median of **1.4 mm**, with a tail to 6.7 m concentrated at
faults; `DX` differs by a median of 0.012 % with 5.2 % of cells over 1 %. An
earlier version of this note said "56 % differ, to +-4 %" -- that was a ratio taken
on coordinate *values*, where a small absolute difference on a small x gives a
large ratio. There is no case here for a different pillar-placement algorithm: the
placement already agrees to millimetres, and matching the remaining tail would not
move the transmissibilities.

**`TRANX` is a convention difference, not a defect.** Summed across a parent
boundary, the reference's refined `TRANX` over the host's is 3.0000 -- the analytic TPFA
factor for 3x refinement -- for **74 % of cells to within 0.001**, with the
quartiles at 2.9996 and 3.0002. That is the host's transmissibility scaled by the
refinement ratio, not a geometric calculation on the child cells. OPM computes the
children's own TPFA transmissibility, and gets 1.84-1.94 on Drogon's twisted
cells. On near-regular grids the two coincide, which is why Norne and model2_lgr
match exactly and Drogon does not. Neither is wrong; they are different quantities,
and OPM's is the one that follows from the child geometry. It does mean the refined
region is ~24 % less transmissive laterally than the reference's, which is
consistent with the water still being short.

**The global NNC list is truncated wherever a box covers it** (D4a). Unchanged,
output only, and now measured on three cases.

## Wells

Checked at the one restart step the reference reached. In the **LGR section every
connection factor is identical to the reference** -- `EffConnTrans`, `ConnTrans`,
`EffectiveKH`, `SkinFactor`, `Diameter`, `Depth`, `EffectiveLength`, `CFDenom` --
and `ICON` matches on cell I/J/K, status, direction, completion number and
connection index. Two output defects were found and fixed (see below); a third is
open: in the **global** section the reference lists all of a well's connections mapped
back to their host cells (A4: 20 globally against 42 in the LGR) while OPM lists
one.

## Fixed today

- **Refined vertical transmissibility** (opm-gridrefined `546aea6a`).
  `faceCenterEcl` used the face-node average for refined-refined faces, which on a
  twisted cell fell through to the Dune face centroid, inconsistent with the cell
  centre `distanceVector_` measures from. Drogon's refined `TRANZ` went from a
  median of 0.054 of the reference to 0.999, and field water production at 212 days
  from 323 to 364 sm3/day (reference 439).
- **Saturation endpoints for each LGR** (opm-common `48c9ed649`). Norne's LGR
  section goes from 31 arrays to 48, Drogon's from 30 to 50; every added array is
  identical to the reference except `SOWCR`, `KRWR` and `PCW` on Drogon, which
  differ in the *global* section by the same fractions. Neither LGR section now
  lags its global section.
- **PINCH and MULTREGT connections a box swallows** are now counted and reported
  (opm-simulators `cf1d15214`). Untested against a case that makes them fire.
- **`ICON`/`SCON` under `RPTRST NORST=1`** (opm-common `07f3b320a`). They were
  gated off while `XCON` was still written, so the dynamic connection results had
  no geometry to attach to and a post-processor could not place the well. The reference
  writes both at NORST=1. Not LGR-specific -- any deck with `NORST=1` was affected,
  and Drogon asks for it.
- **The global `IWEL` connection count for an LGR well** (same commit). It carried
  the full count while the global `ICON` deliberately holds one connection, so a
  reader trusting the count read unfilled slots and placed connections in cell
  (0,0,0) with status zero.
- **`NNCTestsLGR`** asserted the pre-`9cc2e3dbf` count in an NNCL/NNCG header.

Regression check: the full suite fails 270 tests without today's changes and 269
with them. The one difference is `NNCTestsLGR`, which today's work fixes. Nothing
was broken. **The other 269 failures pre-date this work** and are not understood --
they are on this branch against the opm-tests references, and a sample
(`MULTFLT-01`) differs in restart `IWEL`, nothing to do with refinement. That
needs its own pass.

## Still open

| | |
|---|---|
| Drogon refined `TRANX` 0.763 and refined NNC 0.678 | a convention difference -- the reference scales the host's value by the refinement ratio, OPM computes the child's. Decide which we want |
| global `ICON` lists one connection for an LGR well | the reference lists all of them at their host cells |
| global NNC list truncated inside a box | D4a, output only |
| 6456 Drogon cells report `TRANZ` 0 where the reference bridges a `MINPV` gap | LGR NNC count is 8415 against 8408, so the connections are probably there and merely reported as NNCs |
| `MINPVV`, `MULTPV`, `TOPS`, `CON` written by neither grid | not LGR-specific |
| `GDORIENT` not written | cosmetic |

## How much of the Drogon water gap is the refinement? (2026-08-27)

`model2_lgr` has all four corners -- {reference, OPM} x {LGR, no LGR} -- on one deck,
so the gap can be decomposed. Cumulative water at 973 days:

| | no LGR | with LGR | refinement effect |
|---|---|---|---|
| reference | 62735 | 63428 | +1.11 % |
| OPM | 66480 | 66609 | +0.19 % |

The codes differ by **5.97 % with no refinement at all** and 5.01 % with it; their
*responses to refinement* differ by 0.91 percentage points. On a near-Cartesian
grid, refinement contributes essentially nothing to the gap -- and this is exactly
the case where the two codes' `TRANX` agrees.

Drogon has no coarse reference run, so it cannot be decomposed the same way, but the
lateral transmissibility convention can be measured directly. `MULTIPLY TRANX` over
the box reaches the faces a coarse face became -- the parent-boundary faces, one x-face
in three -- and does so exactly (1.3106 requested, 1.3106 delivered to 27252 of 27252
of them, nothing to the interior faces, which is correct: an interior face was not
part of any coarse face). Putting just that third onto the reference's convention:

| at 212 days | FWPR | FWPT |
|---|---|---|
| reference | 438.9 | 39326 |
| OPM | 364.0 | 30399 |
| OPM, boundary x-faces x1.31 | **405.0** | **34216** |

One third of the x-faces closes **55 %** of the remaining water gap. So on Drogon,
unlike model2, the gap is dominated by the refinement -- specifically by the
lateral transmissibility convention, not by a baseline difference between the codes.

For reference, OPM's own refinement effect on Drogon is +50 % on cumulative water
(coarse control 20263 against 30399 refined).

### Is a reference-compatible `TRANX` worth building?

Probably, as an **option** rather than the default.

For: it is worth 20-25 % of water production on a twisted grid, it makes a refined
run reproduce the coarse model's flow capacity -- which is what a history-matched
model wants and what anyone comparing against a reference expects -- and it would
make every future comparison legible.

Against: it discards the geometric information the refinement provides, which is
part of why one refines. And it is not well defined everywhere: a face *interior*
to a parent was never part of a coarse face, so there is nothing to inherit and the
analytic factor has to stand in, which amounts to treating the parent as locally
uniform. Graded refinement (`N*FIN`/`H*FIN`) and nested boxes need the rule spelled
out too.

The mechanism is settled enough to build on: the reference's refined `TRANX` summed across
a parent boundary is the analytic refinement factor to within 0.001 for 74 % of
cells, so it is scaling the host, and the host transmissibility is already to hand.

## The 269 failing regression tests

Not caused by this work: 270 fail without today's changes, 269 with them, the
difference being `NNCTestsLGR` which today fixes.

Every one of the 266 that classify is a restart **output** difference. The solution
vectors (`PRESSURE`, `SWAT`), the INIT and the EGRID all compare clean.

| | |
|---|---|
| 79 | `IWEL` item 12 (`PVTTab`) only |
| 182 | `IWEL` item 12 plus `XGRP` item 139 |
| 5 | other (`XWEL`, `TAB`, and three unclassified) |

`PVTTab` is the well's PVT table number; we write it, the stored references have 0.
The producing code is character-identical to upstream master, and the references are
current (opm-tests is 2 commits behind, and those two regenerate 602 files and still
carry 0). Our branch is **71 commits behind opm-common and 153 behind
opm-simulators**, so the likeliest reading is that the branch and the reference data
are out of step -- opm-common `dd8be7e85` "Store and restore well PVT table
to/from restart" (2026-07-07) changed `IWEL`, and the references for these cases were
last regenerated 2026-05-11.

**To fix: bring the branch up to date with upstream and re-run.** That is a
mechanical operation but not a small one, and it invalidates the build for a while,
so it is a deliberate decision rather than something to slip in. Until then the
regression suite gives no signal, which is its own cost -- it is why the two
restart-output defects fixed today had to be found by hand against a reference.
