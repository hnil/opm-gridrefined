# LGR on CpGrid — status

Status of the local-grid-refinement (CARFIN/LGR) rebuild across the OPM modules.
Companion docs: `lgr_review.md` (review), `PLAN.md` (roadmap), `LGR_GAPS.md`
(gap list), `REDISTRIBUTION-status.md`/`-requirements.md`, `WELLTRAJ_LGR_STATUS.md`,
`NESTED_LGR_PLAN.md`/`NESTED_LGR_TESTING.md`, `REFINE_BEFORE_REDISTRIBUTE.md`,
`DESIGN-parallel-octree.md`/`DESIGN-builder.md` (AdaptiveCpGrid design),
`REFINEMENT-ALGORITHM.md` (builder pipeline, file:line walk-through),
`GRADED-REFINEMENT.md` (what NXFIN/HXFIN would take),
`UPSTREAM_TEST_PORTING.md` (which upstream LGR tests transfer and why), and
`RUNNING.md` (workspace root, full build/run/test guide).

Last updated: 2026-08-19 (branch `dynamic-refinement`; Norne section below).

## Approach

Route A: **strip the LGR layer out of CpGrid and rebuild static refinement as a
separate builder** under `opm/grid/cpgrid/refinement/` (`GrdeclRefinement`
resamples COORD/ZCORN onto sub-pillars; `LevelGridAssembler` runs the
preprocessor per block so faults inside a block are matched by `findconnections`;
`LeafGridAssembler` / `assembleNestedLeafGrid` merge into the leaf;
`ConformingBlockBuilder` is the registered backend). opm-simulators gets only
minimal additive hooks. The parallel model is **rank-interior** (distribute level
0 first, then each rank refines the boxes it owns), with
**refine-before-redistribute** as an optional path for better load balance.

### Geometry note (precise)
Refinement is the **corner-point-native** resampling of COORD/ZCORN (refined
corners lie on straight sub-pillars — ECLIPSE LGR semantics), which conserves the
parent cell's volume and volume-weighted centre of mass. The per-cell **trilinear
map** of a hex's 8 corners refines that single cell's interior correctly for any
hexahedron, and across a **matching, non-faulted** shared face the two neighbours'
refined sub-faces are automatically conformal (both restrict to the same bilinear
surface) — i.e. trilinear alone suffices for **hexes not touching a fault**. Where
a cell touches a fault the two sides are *different* surfaces, so the interface is
matched by intersection via the preprocessor (`findconnections`), not assumed from
the trilinear map. See `LESSONS.md` item 12 and `DESIGN-builder.md`.

## Active branch: `adaptive-cpgrid-class` (off `new_lgr`)

`new_lgr` is the consolidated trunk (nested + refine-before + field-props/solver +
welltraj + conformity + design docs, on every repo). **`adaptive-cpgrid-class`
builds on top of it in opm-gridrefined** and is the branch this doc now describes:
it adds the `AdaptiveCpGrid` class, the A2 compatible sub-face mosaic, the A5
box↔box faulted interface, and the `globalRefine`/`autoRefine` builder wiring (see
the dated section at the end). Only **opm-gridrefined** diverges from `new_lgr`;
the other three repos stay on `new_lgr`. Pushed to the hnil fork.

### Branches / commits to compile

| Repo | Branch | code HEAD | fork remote | upstream |
|---|---|---|---|---|
| opm-common      | `new_lgr` | `6291b8165` | `git@github.com:hnil/opm-common.git` | `OPM/opm-common` |
| opm-gridrefined | **`adaptive-cpgrid-class`** | `fd2ffe97` | `git@github.com:hnil/opm-gridrefined.git` | `OPM/opm-grid` |
| opm-simulators  | `new_lgr` | `8970d1b92` | `git@github.com:hnil/opm-simulators.git` | `OPM/opm-simulators` |
| opm-tests       | `new_lgr` | `3b86809c`  | `git@github.com:hnil/opm-tests.git` | `OPM/opm-tests` |

Build order: opm-common → opm-gridrefined(as opm-grid) → opm-simulators.
opm-gridrefined is the fork of `OPM/opm-grid`. For the flow-level
`flow_blackoil_adaptive` executable, use the opm-simulators `adaptive-cpgrid-class`
branch (separate, not pushed in this round).

## Capability status (on `adaptive-cpgrid-class`)

| Capability | Status | Notes |
|---|---|---|
| Serial static LGR, bit-identical to master | ✓ | CARFIN1 = 52 Newton |
| Volume/CoM-conserving corner-point refinement | ✓ | more correct than master on skewed/faulted cells |
| Faults inside a CARFIN block | ✓ | preprocessor matches per block |
| **Inactive parent cells inside a CARFIN box** | ✓ | refined cells inherit the father's ACTNUM; box need not be fully active (Norne 27-37/54-64/1-22: 623/2662 inactive) |
| **Faulted box boundary on a low (I-/J-/K-) side** | ✓ | synthetic face normals now follow CpGrid's +axis convention; previously mislabelled the face side |
| **`CARFIN...ENDFIN` block scoping** | ✓ | a block's keywords no longer apply to the global grid; block-*local* properties still unimplemented (refined cells inherit the father) |
| **Parent intersection across a faulted LGR boundary** | ✓ | matched by level-0 ancestor pair, not by face side |
| **Graded refinement (`N*FIN`/`H*FIN`)** | ✓ | per-parent column counts and widths; Norne matches the reference's sub-pillar spacing. Refused for box-to-box interfaces and `geometryInFather()` |
| Block-*local* properties (a CARFIN block's `MINPV`, `PORO`, …) | ✗ | scoped out of the global grid and warned about; refined cells inherit the father |
| Edge/face-sharing (touching) boxes | ✓ | `CARFIN`, `CARFIN_FLEX` |
| Touching-box conformity check | ✓ | equal in-face subdivisions; **compatible (multiple) now builds via sub-face mosaic (A2)**; only incompatible→clear error |
| **A2 compatible sub-face mosaic** (different in-face subdivisions, no fault) | ✓ | finer side tiles the coarser cell; `TLGR_VSTACK_HCOMPAT` now runs (was rejected) — branch `adaptive-cpgrid-class` |
| **A5 box↔box interface across a fault** (equal + compatible) | ✓ | staggered sub-faces assembled conformally; was silently non-conformal |
| **AdaptiveCpGrid** (post-construction local refinement) | ✓ first-cut | mark→adapt == static LGR; re-adapt + cell-by-cell; full-rebuild oracle (in-place mutation deferred) |
| **Dune `globalRefine`/`autoRefine`** | ✓ | wired to the builder: `globalRefine(n)`=whole-grid 2^n; `autoRefine(nxnynz)`=arbitrary odd division as one LGR |
| Parallel rank-interior single-level LGR | ✓ | CARFIN1 np2; mass balance matches serial |
| LGR ECL output (serial + parallel cell/restart) | ✓ | EGRID/INIT/UNRST consistent, ResInsight-ready |
| **INIT/restart LGR arrays on a grid with inactive cells** | ✓ | active-sized arrays now use the father's *active* index; PORV stays Cartesian |
| **Field-props correct on refined cells** | ✓ | EQLNUM/PVTNUM/SWATINIT (equil), FIPNUM/FPR, datum-region pressure — via LookUpData leaf-mapping |
| THPRES + LGR | ✓ | global restart vectors copied per level |
| Nested LGR (serial, fully contained): build+solve+output | ✓ | `*_NESTED_CONTAINED` 54 Newton |
| Nested LGR (parallel rank-interior) | ✓ | np2 writes EGRID/INIT/UNRST |
| refine-before-redistribute (grid+props+solve+output) | ✓ | `--refine-before-redistribute=true` |
| WELTRAJ/COMPTRAJ on LGR (single-LGR/well, serial) | ✓ | reproduces COMPDATL <0.3%; see `WELLTRAJ_LGR_STATUS.md` |
| Non-black-oil (solvent/polymer/biofilm/MICP) + LGR | ✗→err | clear error; black-oil is the supported scope |
| Whole-grid (box==grid) LGR in parallel | ✗→err | needs distributed refinement; rank-interior refuses clearly |
| Nested boundary-touching child | ✗→err | rejected with containment message |
| Redistribution / rebalancing a distributed grid | ✗ | CpGrid-level gap; belongs to dynamic AMR (`REDISTRIBUTION-status.md`) |
| Dynamic AMR | ◐ | `AdaptiveCpGrid` first cut (refine-after-construction, re-adaptable); no coarsening / cross-adapt data transfer / parallel adapt yet (`DESIGN-parallel-octree.md`) |

## New / notable run options

- `--refine-before-redistribute=true` — refine the full grid on rank 0 then
  distribute the leaf (better balance for big LGRs). Default off = rank-interior
  (each rank refines the boxes it owns; a box must fit one rank).
- **Parallel-LGR linear solver** — the rank-interior partition is often very
  unbalanced (whole refined region on one rank), which can empty an AMG coarse
  level. Use one of: `--linear-solver=ilu0` (simplest); a cprw JSON with
  `coarsenTarget` ≥ the first coarse level size (~2000); or a cprw JSON with a
  HYPRE coarse solver (build with `-DUSE_HYPRE=ON`). An empty-partition now throws
  a clear actionable error instead of segfaulting.
- **WELTRAJ/COMPTRAJ** wells are post-processed against the refined leaf so a
  trajectory perforates the correct LGR cells (one LGR per well; keep the
  perforation inside the box). No `--enable-lgr` needed — CARFIN auto-enables.
- **Nested CARFIN** — a box may name a parent LGR; its I/J/K are parent-LGR-local.
- `OPM_LGR_POISON_REFINED=1` — opt-in diagnostic canary (poisons refined cells'
  global Cartesian index to catch any late re-derivation; default off, zero
  impact).
- All CARFIN decks need `--parsing-strictness=low` on any flow build.

## How to run a case

```
# build (dependency order); enable HYPRE if you want the HYPRE coarse solver
ninja -C builds/refined flow_blackoil          # opm-common + opm-grid + flow

FLOW=builds/refined/opm-simulators/bin/flow_blackoil

# serial LGR
$FLOW opm-tests/lgr/SPE1CASE1_CARFIN1.DATA --parsing-strictness=low --output-dir=/tmp/c1

# parallel LGR (rank-interior)
mpirun -np 2 $FLOW opm-tests/lgr/SPE1CASE1_CARFIN1.DATA \
    --parsing-strictness=low --linear-solver=ilu0 --output-dir=/tmp/c1p

# nested LGR
$FLOW opm-tests/lgr/SPE1CASE1_CARFIN1_NESTED_CONTAINED.DATA --parsing-strictness=low --output-dir=/tmp/nest

# refine-before-redistribute
mpirun -np 2 $FLOW opm-tests/lgr/SPE1CASE1_CARFIN1.DATA \
    --parsing-strictness=low --linear-solver=ilu0 --refine-before-redistribute=true --output-dir=/tmp/rbr

# welltraj on LGR
$FLOW opm-tests/weltraj/WELTRAJ-01_CARFIN.DATA --parsing-strictness=low --output-dir=/tmp/wt
```
The workspace `RUNNING.md` has the full build-tree map, the local model2 decks,
the regression harness, and comparison tools.

## Verification (2026-06-25, on `new_lgr` / `builds/refined`)

Grid tests all green on `adaptive-cpgrid-class`/`builds/refined`:
`conforming_builder_test` (20 cases incl. A2 stacked/side-by-side mosaic and A5
equal/compatible faulted box↔box), `grdecl_refinement_test`, `adaptive_cpgrid_test`
(mark→adapt == static LGR, re-adapt, cell-by-cell), `faulted_boundary_test`,
`edge_conformal_refinement_test`, `level_grid_assembler_test`,
`refined_structure_comparison_test`, `refinement_seam_test`,
`global_refine_via_builder_test` (6: globalRefine 2^n + autoRefine odd division ==
whole-grid LGR), and the 3 ported upstream tests (`lgr_cartesian_idx`,
`consistent_vertex_order_in_face`, `getParentIntersectionFromLgrBoundaryFace`).
Flow: serial CARFIN1 = 52 Newton (unchanged); parallel CARFIN1 np2 = 71 Newton;
nested contained = 54 Newton; refine-before np2 = End of simulation; model2
welltraj vs COMPDATL ≤0.3%; WELTRAJ-01_CARFIN = 88 / model5 = 251 Newton;
**`TLGR_VSTACK_HCOMPAT` (compatible 4-vs-2, previously rejected) now runs to
completion (58 Newton)**; incompatible touching still rejects with a clear message.

## Norne (first full-field case, 2026-08-19)

`lgrtests/NORNE_LGR_NOFIN.DATA` — Norne with `CARFIN 'LGR1' 27 37 54 64 1 22 33 33 22`,
2039 active parents of 2662, 18351 refined cells — runs the whole 247-step history:
439 timesteps, 2532 Newton, no wasted iterations. It needed three fixes, all of
which only a real field grid can reach:

1. **Inactive parents** (opm-common `create_lgr_cells_tree`) — threw
   "Input argument does not correspond to an active cell". Now the father list
   covers the active parents and the child grid inherits their ACTNUM.
2. **Active vs Cartesian father index** in the INIT LGR sections and in
   `fatherReplicatedSolution` — read the wrong father cell (PORO 0.2477 for a
   father holding 0.2391, PERMX 325 for 120, FIPNUM 11 for 5), and out of bounds
   for a high-index box.
3. **Synthetic faulted-boundary face normals** (`LeafGridAssembler`) — oriented
   box→neighbour rather than +axis, so on a box's low side both neighbours
   reported the opposite face of themselves. It threw only where the coarse cell
   had no face on that side at all (Norne (26,57,19)); elsewhere
   `getParentIntersectionFromLgrBoundaryFace` silently matched a wrong-side
   level-0 face. Fixing it moved the fully-active reduced box from 423 steps /
   2358 Newton to 429 / 2363 — i.e. it was affecting existing all-active faulted
   cases too.

`NORNE_LGR.DATA`, graded `NXFIN/HXFIN` and all, runs as written: 434 timesteps,
2463 Newton. See `GRADED-REFINEMENT.md`.

Two further fixes followed (B4, B6 in `LGR_GAPS.md`), and with them the run is
432 timesteps / 2380 Newton and the global grid matches the reference exactly
(44431 active, 496 removed by MINPV, 0.015 % of pore volume):

4. **`ENDFIN` was not honoured**, so the CARFIN block's `MINPV 0.1` replaced the
   field's `MINPV 500` for the whole grid. A block's keywords now carry an LGR
   scope and stay out of the global view and out of every DeckSection. Honouring
   it made MINPV bite, which exposed the LGR tree caching its refined ACTNUM and
   father lists from before the change — `resetACTNUM` re-derives them now.
5. **`getParentIntersectionFromLgrBoundaryFace` matched on the face's side
   alone**, which a faulted coarse cell does not determine uniquely. It matches
   on the two cells' level-0 ancestors now, with a new faulted regression deck.

## Remaining gaps (details in `LGR_GAPS.md`)

- **Redistribution** of an already-distributed grid — unsupported (CpGrid-level);
  belongs to the dynamic-AMR class, not a static add-on.
- **Whole-grid LGR in parallel** — needs distributed refinement (box across ranks).
- **refine-before deep reconstruction** for highly irregular leaves — rank-interior
  is the working path for big/faulted cases.
- **Parallel solver empty-partition** — handled by workarounds (ilu0 / coarsenTarget
  / HYPRE); a true min-per-rank AMG redistribution is upstream Dune work.
- **MINPV in the parallel output grid** — not yet handled.
- **Incompatible (non-multiple) touching subdivisions** — clear error (genuinely
  non-conformal). Compatible (A2) and faulted box↔box (A5) now build; only the
  edge/corner 1-D mosaic and mixed nesting remain unimplemented.
- **Recursive nested `globalRefine(n>1)` as n levels** — produces the 2^n leaf as
  one level instead; true multi-level recursion needs the adaptive rebuild path.
- **Dune adapt lifecycle (`mark`/`adapt`)** — stubbed on CpGrid; the refine engine
  exists (`AdaptiveCpGrid`), only adapter glue + coarsening missing (see
  `UPSTREAM_TEST_PORTING.md`).
- **Parallel (np>1) welltraj-LGR** — untested.

## 2026-06-26 — branch `adaptive-cpgrid-class` (off `new_lgr`, pushed to hnil fork)

Adds, on top of `new_lgr`: the `AdaptiveCpGrid` class (mark→adapt refinement after
construction, re-adaptable, cell-by-cell == one-go; verified bit-identical to
static LGR) and its benchmark; the **A2 compatible sub-face mosaic** and **A5
box↔box faulted interface** (equal + compatible) in the builder; `CpGrid::
globalRefine`/`autoRefine` wired to the builder (no Dune mark/adapt machinery
revived); 3 ported upstream LGR unit tests (`lgr_cartesian_idx`,
`consistent_vertex_order_in_face`, `getParentIntersectionFromLgrBoundaryFace`) +
`global_refine_via_builder_test`; and the docs `REFINEMENT-ALGORITHM.md` and
`UPSTREAM_TEST_PORTING.md`. All refinement unit suites green; SPE1 CARFIN1 still
52 Newton; `TLGR_VSTACK_HCOMPAT` (previously rejected) now runs to completion.
