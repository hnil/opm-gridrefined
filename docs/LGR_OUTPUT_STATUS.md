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
| refined `COORD` | 33 % differ, to +7.8 % | 36 % differ, to +9.5 % | 56 % differ, to +3.8 % |
| refined `DX` / `DY` | identical | +-3.7 % / +-0.9 % | +-2.1 % / +-0.7 % |
| refined `PORV` | identical | +-3.9 % | +-2.5 % |
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

**The refined lateral geometry is not the reference's.** The two codes place the
refined pillars differently -- computing a corner's (x,y) at the same ZCORN depth
from each file's `COORD` puts them a median of 1 cm and up to 10.6 m apart on
Drogon. `ZCORN` is identical, so the *depths* agree; it is the pillars that do
not. `DX`, `DY` and `PORV` follow, each spread a couple of per cent with the
totals matching. Subdividing a corner-point cell laterally requires choosing where
the new pillars go and there is no unique answer, so neither is wrong on its face
-- but it is the likely root of the transmissibility differences below, and it is
worth deciding deliberately rather than inheriting.

**Drogon's refined lateral transmissibilities are ~25-32 % low; Norne's are not.**
`TRANX` at 0.763 and the refined NNCs at 0.678 are the same story from two
directions. Norne, refined 3x3x1, matches; Drogon, refined 3x2x1, does not. The
asymmetric refinement ratio is the obvious suspect and is not yet run down. Note
the reference's refined `TRANX` summed across a parent boundary is *exactly* 3.0000x the
host cell's, the analytic TPFA factor, so the reference distributes rather than
recomputes -- which means the two are not strictly measuring the same thing.

**The global NNC list is truncated wherever a box covers it** (D4a). Unchanged,
output only, and now measured on three cases.

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
| refined lateral geometry differs from the reference | pillars, hence DX/DY/PORV; decide the convention |
| Drogon refined `TRANX` 0.763 and refined NNC 0.678 | Norne is clean, so start from the 3x2x1 vs 3x3x1 difference |
| global NNC list truncated inside a box | D4a, output only |
| 6456 Drogon cells report `TRANZ` 0 where the reference bridges a `MINPV` gap | LGR NNC count is 8415 against 8408, so the connections are probably there and merely reported as NNCs |
| `MINPVV`, `MULTPV`, `TOPS`, `CON` written by neither grid | not LGR-specific |
| `GDORIENT` not written | cosmetic |
