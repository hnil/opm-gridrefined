# Example: LGRON / LGROFF driving dynamic refinement

Status: 2026-08-08. Uses the merged Schedule support
([opm-common#5263](https://github.com/OPM/opm-common/pull/5263), on upstream
master; cherry-picked onto `dynamic-refinement` as the two commits
`Schedule: handle LGRON / LGROFF` + the review follow-up).

## What it shows

`flow_blackoil_adaptive_dynamic` now watches the deck's LGR activation:
whenever `ScheduleState::lgr_active()` changes for any deck CARFIN at a report
step, the driver fires the same rebuild seam as `--adaptive-rebuild-step`
(extract state by stable cell id → tear down → rebuild with only the *active*
CARFINs refined → remap → inject). LGROFF therefore coarsens the region
mid-run and LGRON re-refines it — entirely deck-driven, no command-line
adaptation parameters.

Wiring (all in `opm-simulators/flow/flow_blackoil_adaptive_dynamic.cpp`):

- `AdaptiveDynamicVanguard::addLgrs()` — with every deck LGR active it defers
  to the unchanged base path; with an LGROFF in effect it refines only the
  active subset of the deck CARFINs (non-nested only), then does the same
  post-refinement bookkeeping as the base deck path.
- The driver computes the activation map per report step from the snapshot
  Schedule and rebuilds when it differs from the map the current world was
  built with. Step-0 activation is honoured for world #1.

## Deck

`opm-tests/lgr/SPE1CASE1_CARFIN1_LGRONOFF.DATA` — SPE1CASE1 with the two
standard CARFINs (LGR1 at 5-6/5-6/1-3, LGR2 at 8-9/8-9/1-3; both wells outside
the refined boxes) and this SCHEDULE timeline:

| report steps | keyword before them | grid |
|---|---|---|
| 0–2  | —                    | LGR1 + LGR2 (deck default) |
| 3–5  | `LGROFF 'LGR2' /`    | LGR1 only (LGR2 region coarsened) |
| 6–8  | `LGROFF 'LGR1' /`    | fully coarse |
| 9–11 | `LGRON` both         | LGR1 + LGR2 again |

Three rebuild events: refined→refined-less, →coarse, →refined.

Verified 2026-08-08 (`builds/refined`, commits opm-simulators `704a16b93` +
`0d8d5040b`, opm-common cherry-picks `ec65488a8` + `bb1839469`): all three
events fire ("LGRON/LGROFF change at report step 3/6/9; rebuilding the
grid"), every step converges in 2-4 Newton iterations, exit 0. The final
world's VTK frames have 924 leaf cells (300 coarse − 24 parents + 2·324
children), i.e. both LGRs are genuinely back after the LGRON.

The first run also flushed out a state-transfer bug: the nested-refinement
guard tested `maxLevel() > 1`, but sibling LGRs each get their own level, so
any deck with two CARFINs was rejected. Fixed by testing
`father().hasFather()` per refined cell (commit `704a16b93`).

## Run

```bash
./builds/refined/opm-simulators/bin/flow_blackoil_adaptive_dynamic \
  opm-tests/lgr/SPE1CASE1_CARFIN1_LGRONOFF.DATA \
  --parsing-strictness=low --output-dir=/tmp/lgronoff_ecl
```

**ECL output works on this route** — see "Viewing the results" below. It is
the `--adaptive-lgr` route (no deck CARFIN) that still needs
`--enable-ecl-output=false`.

- VTK (`--enable-vtk-output=true`): each rebuilt world restarts its frame
  sequence at `-00000` in the same output dir, so later phases overwrite
  earlier frames (known S9-adjacent numbering gap). Use the ECL output for
  the full history; VTK only to inspect one phase.

## Viewing the results (ResInsight)

Verified 2026-08-11 on both example decks: the run writes a **complete,
coherent ECL case** that ResInsight opens normally — open the `.EGRID`.

Why it works here (and not for `--adaptive-lgr`): the ECL output path is
driven by the LGRs *declared in the deck*, and LGRON/LGROFF only changes
their activation, never the declaration. So the file layout is static even
though the simulation grid changes:

| file | content |
|---|---|
| `.EGRID` | global grid + an `LGR1` (`LGRPARNT`/`HOSTNUM`) section, **always** — 300 + 324 cells here |
| `.INIT`  | global static props + a full `LGR1` property section (PORV/PERM/…), **always** |
| `.UNRST` | `SEQNUM` 0…12 with correct dates and an `LGR1` solution section in **every** step |

What you see stepping through time in ResInsight:

- The **LGR sub-grid is in the case for the whole run** (it comes from the
  deck, not the simulation grid) and now carries data at every step. In the
  LGRON steps those are the true refined values; in the off steps each child
  holds its father coarse cell's value, so the region renders piecewise
  constant — visually flat where the run was actually coarse.
- The **coarse grid is fully populated at every step, including the refined
  ones**: flow writes each refined parent cell as the average of its children
  (checked at SEQNUM 8: parent (5,5,1) = 5514.80 psia = mean of its 27
  children, range 5476–5558). So the main-grid view is continuous across
  LGRON/LGROFF, and the LGR view adds detail where it exists.

**This needed a fix** (opm-simulators `fa97b2372`). Writing the LGR section
only in the refined steps produced a case where ResInsight showed **no dynamic
results at all** — not merely blank LGR cells. Its reader filters result
keywords by an exact modulo test on the *total* value count
(`RifEclipseOutputFileTools::validKeywordsForPorosityModel`,
`ApplicationLibCode/FileInterface/RifEclipseOutputFileTools.cpp:801`): a
keyword survives only if its total is a whole multiple of the active cell
count. With LGR data in 3 of 13 steps that total was
13·300 + 3·324 = 4872, and 4872 % 624 = 504 → PRESSURE and every other dynamic
array silently dropped. Emitting the section in every step (father-replicated
when the LGR is off) gives 13·624 = 8112, exactly 13 × the cell count. To see
the grid *actually* change resolution, use the VTK output in ParaView instead;
the ECL case always shows the deck's LGR geometry.
- Missing relative to a static-LGR run: `NNCHEAD`/`NNCL`/`NNCG` in the EGRID
  (LGR↔host non-neighbour connections), so ResInsight's NNC/flux display
  across the LGR boundary has nothing to draw. Cell properties are unaffected.

### Restriction: all declared LGRs must switch together

ECL output requires the active set to be **all** or **none** of the declared
LGRs. Refining a strict subset (the two-CARFIN deck at steps 3–5, where LGR2
is off but LGR1 is on) aborts — now with an explicit error, previously with an
out-of-bounds read.

The cause is a genuine impedance mismatch, worth knowing before extending
this: both writers address the simulator's per-LGR data **positionally by deck
LGR index** — `simProps[deckIdx + 1]` in `WriteInit.cpp:909` and
`values[deckIdx + 1]` in `RestartIO.cpp:1124` — while the simulator sizes that
vector by **grid level** (`outputTrans_->resize(maxLevel + 1)`,
`EclGenericWriter_impl.hpp:545`). With every declared LGR refined the two
coincide; with none refined the writers take their existing
father-replicated fallback; with a subset they disagree and index past the
end. Fixing it properly means building the per-LGR vector in deck order with
explicit holes, and deciding what an inactive-but-declared LGR's INIT and
restart sections should contain (father-replicated coarse values is the
natural answer, and is what the writers already do when no per-LGR data is
supplied at all).

Until then the two-CARFIN deck must run with `--enable-ecl-output=false`; the
single-CARFIN well deck has no such restriction.

For the `--adaptive-lgr` (no deck CARFIN) route the writer still aborts at the
first output after a topology change — `Incorrectly sized solution vector
PRESSURE. Expected 300 elements, but got 336`, thrown inside the TaskletRunner:
opm-common's EclipseGrid has no LGR to route the extra cells into. That is the
remaining S9 work, and this finding narrows it: the fix is to give the writer a
declared LGR for the adaptive region (or a level-0-only reporting mode), not to
rebuild the writer machinery.

## Wells inside a toggled LGR

Second deck: `opm-tests/lgr/SPE1CASE1_LGRONOFF_WELL.DATA` (one CARFIN, LGR1 at
5-6/5-6/1-3 with 3x3x3 factors):

| report steps | keywords before them | PROD2 connections |
|---|---|---|
| 0–5  | `LGROFF 'LGR1'` at SCHEDULE start | (well not open yet) |
| 6–8  | `LGRON 'LGR1'` **and** WELSPECS/COMPDAT/WCONPROD of PROD2 at 5,5,1-3 | 9 on the refined children, (2,2,1)–(2,2,9) in LGR1 |
| 9–11 | `LGROFF 'LGR1'` with PROD2 open | back to 3 coarse cells (5,5,1)–(5,5,3), LGR tag cleared |

Verified 2026-08-08: exit 0, 2–5 Newton iterations per step, no time-step
chops. Mechanism (commits opm-simulators `065d10937`, opm-common `ca81cd0b9` +
`e6ea3f893`):

- The dynamic vanguard synthesizes an equivalent trajectory for every COMPDAT
  well (once) and replays all trajectory wells against the current leaf after
  each rebuild — refined **or coarse** (`recomputeWellTrajectoriesInLgr_`
  gained a `replayOnCoarse` flag).
- The Schedule replay now *un*-flags an LGR well whose replay lands entirely
  on unrefined cells and restores a global-grid well head
  (`Well::unflag_lgr_well()`), mirroring the flag branch.
- A real intersection bug was flushed out and fixed: the synthesis nudged both
  lateral directions by the same 1e-3 fraction, putting the axis-aligned
  polyline exactly on the face *diagonal* — a shared fan-triangle edge in the
  ResInsight hex intersection, where the barycentric hit test fails
  erratically. Multi-connection vertical wells lost all but their first
  refined cell (single-connection wells, as in the earlier S6b tests, mostly
  survived by luck). The nudge is now a distinct irrational fraction per
  direction, clear of face centres, diagonals and child-face planes.

## Limitations (by design of the phase-1 demonstrator)

- Nested CARFIN + LGRON/LGROFF throws (subset refinement would need the
  parent-before-child ordering machinery).
- MSW and pre-existing COMPDATL (deck-LGR) wells get no synthesized
  trajectory and do not follow the toggling (warned at synthesis).
- DeckValue CF/Kh are copied, not apportioned by length (plan S6c).
- WTEST history restarts empty at each rebuild (existing seam limitation),
  and well rates restart from a fresh well model (XGRP cumulatives deviate).
- Wells re-derived per rebuild must stay within a single LGR (trajectory
  replay restriction).
