# LGR (corner-point local grid refinement) — known gaps & test decks

Status of the `opm-gridrefined` LGR rebuild plus its `opm-simulators` /
`opm-common` output integration, as of **2026-08-20** (section D is the
most recent pass; a deck index is at the end of it). "Works" = exercised and
verified this far; "gap" = throws, is skipped, or produces wrong output.

What already works (for reference):
- Serial LGR: grid build, solve, summary/PRT, EGRID/INIT/UNRST cell output,
  fault crossing an LGR box boundary (`SIMPLE_2PH_W_FAULT_LGR`).
- Parallel LGR (rank-interior boxes): solve (bit-identical global mass
  balance vs serial), summary, **and cell/restart output** (EGRID/INIT/UNRST
  per-grid arrays match serial — added 2026-06-16).
- Wells completed inside an LGR (`COMPDATL`), serial and parallel.

---

## A. Refinement topology (opm-gridrefined `ConformingBlockBuilder`)

These fail at grid build with a clear message. Each already has a *grid-unit*
test in `tests/cpgrid/conforming_builder_test.cpp`; a *flow-level* deck is only
useful as an end-to-end smoke test.

| # | Gap | Where it throws | Deck |
|---|-----|-----------------|------|
| A1 | **Nested LGR** (an LGR refined inside another LGR, `parentGridName != GLOBAL`) — **partially landed 2026-06-16**, see `docs/NESTED_LGR_PLAN.md`. Phase A (simulator parent pass-through + topological ordering) and Phase B (build each nested level grid over its parent LGR) are done and the GLOBAL path is byte-identical; the recursive **leaf** assembly (Phase C) and parallel nested (Phase D) remain, so the builder now throws a precise *"Nested LGR leaf assembly is not implemented"* after building the nested level grids (was an immediate throw at `ConformingBlockBuilder.cpp`). | `ConformingBlockBuilder.cpp` (post-level-grid Phase-C guard) | `opm-tests/lgr/SPE1CASE1_CARFIN1_NESTED.DATA` (CARFIN inside `LGR1`); unit tests `nestedRefinementReachesLeafBoundary`, `nestedChildBeforeParentThrows`. Master supports it. |
| A2 | **Touching boxes, different in-face subdivisions** (different `cellsPerDim` in a *shared/overlap* direction). **Compatible** (one factor a multiple of the other) on a **face-sharing pair with one box uniformly finer** is now **SUPPORTED (2026-06-26)** via a sub-face mosaic on the coarser side — see the note below. Still rejected: **incompatible** (non-multiple) subdivisions, **edge/corner** contact (1-D mosaic), and **mixed nesting** (each box finer in a different in-face direction). | `ConformingBlockBuilder.cpp` (guard relaxed to compatible+cleanly-nested face share); `LeafGridAssembler.cpp` (`assembleLeafGrid` finer-emits / coarser-suppresses mosaic) | unit tests `stackedCompatibleInFaceMosaicBuilds`, `sideBySideCompatibleInFaceMosaicBuilds`, `adaptiveStackedCompatibleInFaceMosaic` (build conformal leaves); `faceSharingNonMatchingSubdivisionsThrow`, `TLGR_SIDE_BAD.DATA` (incompatible 3-vs-2 → still rejected). Flow deck `TLGR_VSTACK_HCOMPAT.DATA` (compatible 4-vs-2) now **runs to completion**. |
| A3 | **Box that cannot be kept on one rank** (spans whole grid, or would empty another rank) — parallel only | `ConformingBlockBuilder.cpp:97` (classifyBox) / `CpGridVanguard::applyLgrPartitionCellGroups_` | `opm-tests/lgr/SPE1CASE1_CARFIN_GR.DATA` (`LGR1` spans the entire grid) — runs serial, throws an actionable error in parallel. Master supports it (distribute-then-refine). |
| A4 | **A refinement box crossing a coarse fault that is *not* on the box boundary in some configs** | — | covered by `SIMPLE_2PH_W_FAULT_LGR` (boundary-crossing fault works); deep fault/pinch interactions inside a box are not separately tested. |
| A5 | **Two refined boxes meeting side-by-side across a *fault*** (a shared vertical I/J face that is itself the fault throw), **equal OR compatible (multiple) subdivisions. SUPPORTED (2026-06-26).** Unlike a box↔*coarse* faulted boundary, the faulted-side rebuild used to skip a neighbour that was "refined away", silently producing a non-conformal leaf. Now `faultedBoundaryConnections` also reports the neighbour cell's sub-position within its parent, and `assembleLeafGrid` maps a refined-away neighbour to the neighbour box's child cell, emitting each interface face once (the FINER box owns it — equal factors → the lower box index). For *unequal* (compatible) factors the finer box's shell is over-refined, so one box-cell face can split into pieces that all land in the same coarser child; those are grouped by (box cell, neighbour child) and merged back into the box cell's whole face, so the pair shares exactly one face. Only **incompatible** (non-multiple) factors across a fault remain unsupported (geometrically non-conformal). | `FaultedBoundaryFaces.{hpp,cpp}` (`coarseNeighborSub`); `LeafGridAssembler.cpp` (`assembleLeafGrid` synthetic-face grouping + `emitWholeBoxFace` merge) | unit tests `faceSharingAcrossFaultEqualSubdiv`, `faceSharingAcrossFaultCompatibleSubdiv` (conforming_builder): build, closure ≈ 0, every interior face two-sided (count==2), A↔B connections across the throw. |

Note: `CARFIN.DATA`/`CARFIN_FLEX.DATA` (diagonal, edge/corner-touching) now build
and are bit-identical to master. `CARFIN_FAULTS.DATA` / `*XYZ-NON.DATA` fail in
opm-common `FAULTS` parsing **on master too** — not a refinement gap.

### A2 detail — compatible touching boxes via a sub-face mosaic (IMPLEMENTED 2026-06-26)

> **Status:** the **compatible** case below is now implemented for a face-sharing
> pair where one box is uniformly the finer side (the common "refine region A more
> than the adjacent region B" pattern). The guard in `ConformingBlockBuilder.cpp`
> was relaxed from "equal" to "equal **or** compatible + cleanly nested on a shared
> face"; `assembleLeafGrid` then has the finer box emit every interface sub-face
> with the coarser covering cell as its outside, while the coarser box suppresses
> its own interface faces — so each coarser interface cell becomes a >6-face hex
> tiled by the finer sub-faces, exactly as at a box↔coarse boundary. The corner
> pool already merges the shared corners by exact coordinate (the coarser corners
> are a subset of the finer ones), so no new geometry is constructed. **Still
> unsupported:** incompatible (non-multiple) factors, edge/corner contact (a 1-D
> mosaic), and mixed nesting (each box finer in a different in-face direction) —
> all still throw. The historical analysis below is retained for context.


Two refinement boxes that share a 2-D face are conformal only if their
subdivisions match in the **in-face** directions (the two directions *parallel*
to the shared face); the **touch direction** (perpendicular to it) is free. So:

- *Stacked* boxes (touch at a horizontal face): the in-face directions are I,J.
  A different **vertical** (K) factor is fine (e.g. K = 4 vs 2 builds); a
  different **I or J** factor is the constrained case.
- *Side-by-side* boxes (touch at a vertical face): the in-face directions are
  the other two; the along-touch factor is free.

For the constrained (in-face) directions the builder currently demands the two
factors be **equal**. But there are two distinct sub-cases:

- **Compatible** — the finer factor is an integer multiple of the coarser
  (4 vs 2). Geometrically this *is* conformalizable: subdivide the coarser
  side's interface faces into a matching `hi/lo × hi/lo` mosaic so each fine
  cell meets exactly one sub-face. The interface cells on the coarse side become
  hexes with a **split top/bottom (or side) face** — i.e. >6-face cells, exactly
  the multi-face-hex the leaf already uses at a box↔*coarse-neighbour* boundary
  (see [DESIGN-parallel-octree.md](DESIGN-parallel-octree.md) §2/§10). **This is
  a real, supportable case the builder rejects today.**
- **Incompatible** — neither factor divides the other (3 vs 2). The sub-faces
  cannot be aligned by any straight subdivision; the interface is genuinely
  non-conformal and **must** be rejected.

The error message now distinguishes the two (commit on `adaptive-cpgrid`):
*"…different but compatible subdivisions … a sub-face mosaic on the coarser side
… not implemented yet"* vs *"…incompatible subdivisions … neither is a multiple
of the other …"*.

**Why it's not done yet:** the existing mosaic machinery in the leaf assembler
splits a refined box's boundary face against the **parent-level (unrefined)**
neighbour — a single one-level jump. A box↔box interface with a *compatible*
factor needs a mosaic between **two refined levels** (match the finer to the
coarser), which the assembler doesn't construct.

**Implementation effort — medium (a few days), self-contained.** The leaf
representation already permits >6-face cells (no container change). Concretely:
(1) relax the A2 guard from "equal" to "equal **or** the in-face factor of one is
a multiple of the other" in the shared directions; (2) at the shared face,
generate the sub-face mosaic on the coarser box's interface cells by reusing the
parameter-space pillar clip used for the box↔coarse boundary, now matching the
finer box's sub-pillars instead of the parent pillars; (3) wire the resulting
sub-faces into `face_to_cell_`/`cell_to_face_` (variable-length rows already
support it) and dedup the shared corners via the existing exact-coordinate pool.
Risks: only the **compatible** ratios; degenerate/fault cells at the interface
are out of scope (Restriction A); parallel (rank-interior boxes never touch
across ranks) is unaffected. A good first cut is **2-D-in-face mosaics for a
single compatible ratio** (e.g. 2×), validated that a 4-vs-2 stacked pair builds
a conformal leaf and matches a uniformly-4-refined reference where they overlap.

---

## B. Output (opm-simulators / opm-common) — has flow-level test decks

New decks live in `opm-tests/lgr/`, all derived from `SPE1CASE1_CARFIN1.DATA`.

| # | Gap | Where | Test deck | Observed |
|---|-----|-------|-----------|----------|
| B1 | **MINPV with parallel LGR cell output.** The I/O-rank output grid is built with `processEclipseFormat(input_grid, nullptr)` (no `EclipseState`), so the post-MINPV pruning is not applied; for a deck that prunes cells the output grid (full) mismatches the simulation grid (pruned). | `opm-simulators/.../GenericCpGridVanguard.cpp` (outputGrid_ construction) | **`SPE1CASE1_CARFIN1_MINPV.DATA`** (one coarse cell PORO=0 + `MINPV 1.0`, prunes 300→299) | serial fine; **parallel restart PRESSURE differs from serial** (compareECL: 280 errors). Fix: build the output grid through the post-MINPV path. |
| B2 | **RFT output for LGR is skipped.** | `opm-common/.../EclipseIO.cpp:1223` ("RFT file is currently skipped for LGR grids") | **`SPE1CASE1_CARFIN1_RFT.DATA`** (adds `WRFTPLT`) | run completes, **no `.RFT` file written** for the refined grid. |
| B3 | **Restarting (reading) a refined-grid restart is rejected.** | `opm-simulators/.../FlowProblemBlackoil.hpp:1295` (`readEclRestartSolution_`) | **`SPE1CASE1_CARFIN1_RESTART.DATA`** (run `SPE1CASE1_CARFIN1` first, then this — needs `UNIFIN`) | throws *"Refined grids are not yet supported for restart"*. |
| ~~B0~~ | **MPI_RANK in parallel LGR INIT — FIXED (2026-06-16).** Two parts: (a) *sizing* — `MPI_RANK` was written at the full refined-leaf size in the *main-grid* INIT slot (e.g. 924 where the main grid has 300); fixed in `EclGenericWriter_impl.hpp` writeInit (commit a2176e09d) by reducing the leaf `globalRanks_` to level-0 via `getOrigin()`. (b) *per-grid* — the simulator integer maps (incl. `MPI_RANK`) were written only for the main grid via `writeIntegerMaps()`, so the array was absent on refined LGR cells (ResInsight showed it only on the coarse region). Fixed in opm-common `WriteInit.cpp` (commit 2c2e859a5): `writeLGRLocalProperties` now mirrors each integer map onto every LGR via `filterArray(value, global_fathers)`, so each refined cell inherits its father's rank (= the box's owning rank). Verified CARFIN1 np=2: INIT `MPI_RANK` present in all 3 grid sections (main 300 with ranks 0/1, each LGR 324 uniformly its box rank); serial unchanged; parallel UNRST matches serial. |
| B4 | **Parallel LGR trans/NNC in INIT.** The 2026-06-16 fix routes only the *cell-data gather* through the refined output grid; transmissibility/NNC still use the coarse `equilGrid_`. Inter-level `TRANNNC` in the parallel INIT is therefore not yet verified to match serial. | `EclGenericWriter` (equilGrid_ used by `computeTrans_`/`exportNncStructure_`) | reuse any LGR deck; **compare INIT `TRAN*`/`TRANNNC` serial vs np=2** | not yet checked — likely gap. |
| B5 | **Block summary vectors at refined cells** — CONFIRMED 2026-08-20, see D3c. A `B*` vector naming a cell inside a box reads **zero for the whole run**; the global block lookup is gated on `element.level() == 0`, so a refined cell never fills the slot. Now reported at setup. | `OutputBlackoilModule.hpp` | `SPE1CASE1_CARFIN_GR.DATA` (refines its whole grid — 11 of its own vectors were silently zero) | warns; use the `LB*` vectors with the LGR name and its local IJK. |

---

## B4-B6 — found on Norne

**B4 `ENDFIN` block scoping — FIXED 2026-08-19** (opm-common `90e172848`, and
`6f92f6e18` for the consequence). `CARFIN ... ENDFIN` brackets keywords meant for
the refined block only; OPM did not recognise `ENDFIN`, so they applied to the
whole global grid — `NORNE_LGR.DATA`'s block `MINPV 0.1` overrode the field's
`MINPV 500`, keeping the 496 cells the reference deactivates (44927 active vs the
reference EGRID's 44431). Now the block's keywords carry an LGR scope
(`DeckKeyword::lgrScope`) and are left out of the deck's global view and of every
`DeckSection`, so both kinds of consumer — those that walk a section
(`FieldProps`) and those that ask the deck for the last `MINPV` (`EclipseGrid`) —
skip them. Norne now matches the reference: 44431 active, 496 removed, 0.015 %
pore volume.

That exposed a latent problem it had been hiding: the LGR tree recorded its
refined ACTNUM and father lists once, at construction, while the grid the output
code writes is a copy with MINPV applied. `EclipseGrid::resetACTNUM` now
re-derives them (`inheritActiveCellsFromFather`, recursing through nested LGRs).

**Block-local properties are still not implemented** — the block's keywords are
scoped out, not applied to the refined cells, which inherit their father's
values. Norne's `MINPV 0.1` inside the block is therefore ignored rather than
honoured locally, so the refined region keeps ~97 more parent cells inactive than
the reference does. The keywords remain in the deck's own keyword list, tagged,
which is where an implementation should pick them up.

**B5 Graded refinement — IMPLEMENTED 2026-08-19** (opm-common `9eecad109`,
opm-gridrefined `f6eea97b`, opm-simulators `b4bee6824`). `N*FIN`/`H*FIN` now
subdivide a CARFIN box column by column; `NORNE_LGR.DATA` runs as written and the
graded parent's sub-pillar spacing matches the reference EGRID exactly. See
[`GRADED-REFINEMENT.md`](GRADED-REFINEMENT.md). Refused rather than answered
wrongly: box-to-box interfaces involving a graded box, and
`Entity::geometryInFather()` on a graded level.

**Block-local `MINPV` — IMPLEMENTED 2026-08-19** (opm-common `42d7f07e9`) as part
of the same feature: a refined cell takes its share of the father's pore volume
by volume and drops out below the block's threshold. With it, Norne's refined
grid matches the reference simulator's exactly — 19206/23958 active, zero
cell-by-cell differences in LGR ACTNUM and HOSTNUM. Nested blocks' MINPV is
warned about, not applied.

**B6 parent-intersection ambiguity — FIXED 2026-08-19** (opm-gridrefined
`1320af28`). `getParentIntersectionFromLgrBoundaryFace` searched for a level-0
face with the same `indexInInside()`; a faulted coarse cell has several, so the
first match could be a face shared with a different cell, whose centre then set
the interface's transmissibility. It now matches on the two cells' level-0
ancestors, falling back to the side only where both leaf cells descend from one
level-0 cell (no level-0 face exists between them). Regression test:
`parentIntersectionFaultedLowSideBoundary` — two columns offset by half a cell
with the LGR on the right — which fails 17 assertions against the old search.

**B7 parallel LGR on a field grid — FIXED 2026-08-19** (opm-gridrefined
`d42b7530`, opm-simulators `ed3f9a631`). Two blockers, both comparing an active
count against a Cartesian one, both unreachable from the all-active test decks:
`classifyBox()` could never call a box with an inactive cell rank-interior, and
the I/O reference grid skipped MINPV/PINCH because it was processed without an
EclipseState. Norne's graded CARFIN now runs at np=2 with an EGRID identical to
serial's. See `STATUS.md`.

**B8 restart with an LGR — IMPLEMENTED (serial) 2026-08-20** (opm-common
`420ae50f6`, opm-gridrefined `c98d7851`, opm-simulators `de4e2fed3`). A restart
step holds one solution section per level, which ERst already addresses by
occurrence; only the first was ever read. Now every section is read and the leaf
assembled from them (`assembleSolutionFromLevelGrids`, the inverse of the split
the writer applies). Norne restarts from report step 101: 257 timesteps, 1478
Newton, tracking the uninterrupted run to 0.2 % on field rates and 0.002 % on
field pressure, the refined level agreeing cell by cell as closely as the global
grid.

**Parallel restart of a refined run is refused**, with a message saying so. The
reference grid holding the leaf ordering lives only on the I/O rank; broadcasting
the assembled solution from there is not solved yet.

Found on the way: the deck writer dropped a data keyword's trailing defaults, so
`rst_deck` shortened Norne's `HXFIN` from 33 widths to 22 (opm-common
`e9e007ba0`). The CARFIN validation caught it rather than the deck being silently
refined into a different geometry.

*Superseded description of the original gap:* A restart deck built
from Norne's graded CARFIN run stops with "Refined grids are not yet supported
for restart" (`FlowProblemBlackoil::readEclRestartSolution_`, a blanket guard on
`grid().maxLevel() > 0`). A clean refusal, not a wrong answer. Restart *without*
an LGR is unaffected: the same deck without CARFIN restarts from step 101 and
runs to the end.

What it would take: the writer already splits the solution across levels
(`extractRestartValueLevelGrids` + `mapLevelIndicesToCartesianOutputOrder` in
`LgrOutputHelpers.hpp`); reading needs the inverse — load every per-level
solution section and reassemble it in leaf order, after which the existing
`setRestart(..., globalIdx)` indexing works unchanged. opm-common has a
`test_RestartLGR`, so some of the file-format side may already be there.

**Aside, not LGR — FIXED 2026-08-20** (opm-common `5c5ce317b`, `b4b8e62d0`).
`rst_deck` aborted with `std::out_of_range` on Norne, with or without the LGR:
`FileDeck::rst_solution` cleared the SOLUTION section by walking towards SUMMARY
while decrementing SUMMARY's index per erase, which only holds if the section
sits in one file — Norne's SOLUTION includes its equilibration data. It now
collects the positions and erases back to front. Separately, an option given
after the positional arguments (as its own usage example shows) was silently
dropped on macOS, where getopt does not permute argv.

Norne restart decks no longer need writing by hand: `rst_deck -s CASE.DATA
BASE:101 OUT` produces one that runs, 233 timesteps / 1211 Newton, identical to
the hand-written equivalent.

**B9 transmissibility multipliers on refined faces — FIXED 2026-08-20**
(opm-simulators `1a47c840e`). A refined leaf cell reports its *coarse* cell's
Cartesian index, so two cells refining one coarse cell share it. `MULT[XYZ]`
describes a coarse cell's own faces, which the refinement inherits on its outer
boundary; the code applied them to faces *interior* to the coarse cell as well.

- PINCH's MULTZ option `ALL` walks the pillar by coarse index, which for an
  interior face has nothing to walk. That case threw `"MULTZ not support with
  LGRS, yet"`, refusing any refined grid.
- The ordinary path threw nothing and had been quietly damping interior faces
  since LGRs arrived.

Interior faces now take no multiplier. `SPE1CASE1_CARFIN1_MULTZ` covers it: the
refined layer closing the coarse cell that carries `MULTZ 0.05` has exactly
0.0500 times its no-MULTZ transmissibility, every other refined layer exactly
1.0000. Changes results where an LGR box meets a multiplier: SPE1CASE1_CARFIN_FAULTS
49 -> 53 Newton, Norne 1284 -> 1306, with Norne's field vectors moving 0.005 % at
most (its LGR is 1:1 in k, so it has no interior Z faces).

**B10 TRANX/TRANY/TRANZ modifiers on a refined box — FIXED (serial) 2026-08-20**
(opm-common `bbd813330`, opm-simulators `a375ecf48`). Same shape as B9: a TRAN*
modifier is written per cell of the deck's grid, while the simulator holds one
transmissibility per face, so a refined cell has more faces than the deck has
entries. Applying the two in lockstep reads the wrong modifier for every face
past the first refined cell, and refinement was refused outright.

The modifier now reaches the refined faces that close its coarse cell, through a
map built from the same `LookUpData` this class reads porosity and NTG through;
faces interior to a coarse cell take none. Only `MULTIPLY`, `MINVALUE` and
`MAXVALUE` carry over -- an assigned or added transmissibility is absolute and
does not divide over the faces a refinement puts in a coarse face's place, so it
is refused with a message rather than multiplied by their number.

`SPE1CASE1_CARFIN1_TRANZ` covers it: halving TRANZ on the coarse layer the LGR
spans halves exactly the refined layer closing that coarse cell (0.5000) and
leaves every other refined layer at 1.0000.

**Parallel is refused**: the map uses a rank's own field-prop indices, which do
not line up with the global arrays the modifiers come from.

## C. Parallel correctness / infrastructure

| # | Gap | Notes |
|---|-----|-------|
| C1 | **Distributed wells across an LGR boundary** | rank-interior model keeps each box on one rank; a well perforating cells on both sides of a rank cut, or `--enable-distributed-wells` with LGR, is untested. |
| C1b | **Well completed inside an LGR (`COMPDATL`) at high rank counts** | works at np≤4, **hangs at np≥6** (`SIMPLE_2PH_W_FAULT_LGR`, injector I1 in the WELLI1 box). The well's assigned rank and the box's refining rank diverge, so `compressedIndexForInteriorLGR` finds the connection cells on *no* rank → `ParallelWellInfo.cpp:812` "cells not found" → `checkAllConnectionsFound` throws asymmetrically and deadlocks. Coarse-well LGR decks (e.g. `CARFIN1`) scale to np=8 fine. Partial fix landed (compressedIndexForInteriorLGR returns -1 instead of throwing out_of_range); the remaining fix is to anchor the LGR well to its box's parent coarse cell so its rank matches the box's, and/or make the connection-check collective-safe. **Reproducer:** `mpirun -np 8 flow SIMPLE_2PH_W_FAULT_LGR.DATA ...`. A run should finish in <10 s; a longer one is this hang. |
| C2 | **Timestep-path stability serial vs parallel** | small numbering/geometry differences can move the adaptive controller to a different ministep count → different-length SMSPEC (values agree). Stabilising the controller is a separate task; the regression harness reports these as `Lnz` not FAIL. |
| C3 | **Acceptance harness** | port upstream `tests/cpgrid/lgr/LgrChecks.hpp` invariants (equal cell/intersection geometry, father/siblings, id-consistency) and revive `global_refine` / `lgr_cartesian_idx` / `lgrIJK` tests once nested/parallel features catch up. |
| C4 | **Refine-before-distribute (refine then load-balance) — kept as opt-in `--refine-before-redistribute`, default off (2026-06-16).** The fork uses the *rank-interior* model: load-balance the coarse grid, then refine each box on its owning rank. The alternative (refine globally on rank 0, then distribute the already-refined grid — what upstream master does) is wired in as a selectable option: `Parameters::RefineBeforeRedistribute` (commit `e988172dc`); when on, `CpGridVanguard::loadBalance()` refines `grid_` before `doLoadBalance_` and skips the cell-group partitioning, and `addLgrs()` no-ops if already refined. The corner-point broadcast guard in `CpGrid.cpp` (commit `7c503cf2`) now enters on `comm size > 1` unconditionally (equivalent for the default path, fixes the refine-before asymmetry). **Default stays false / not viable in parallel:** `CpGrid`'s scatter only distributes **level 0** and discards the refinement (the distributed-refinement / refined-grid-scatter machinery was *stripped* from this fork on `strip-lgr`); with the option on in parallel, `addLgrs()` re-refines after scatter and the run hangs in a second `assembleLeafGrid`. Serial / single-rank is correct (verified identical to default). The option is preserved so it becomes the on-switch once refined-grid distribution is reinstated — a substantial feature, separate track. |

| C5 | **`WellConnections::init` reads LGR-local positions as level-zero Cartesian positions** (opm-grid, `opm/grid/common/WellConnections.cpp`). The load-balance well graph maps each connection with `cart_grid_idx = i + nx*(j + ny*k)` into `cartesian_to_compressed`, which is sized by level zero. A `COMPDATL` connection's `getI/getJ/getK` are local to the *refined* grid, so the index is meaningless there. **Two distinct failure modes, and the second is the dangerous one:** (a) if the position falls *outside* the coarse grid it is an out-of-bounds read — undefined, but at least reachable by a sanitizer; (b) if it happens to fall *inside* the coarse grid it is a perfectly valid index for an **unrelated cell**, which is then silently anchored to the well in the partitioning graph. Nothing rejects (b) — the existing `compressed_idx >= 0` test passes — so it is invisible. This is why an out-of-range-only guard is insufficient, and why a test built on (a) alone is not deterministic: the garbage read is usually negative and gets filtered by the `>= 0` test, so the test passes without the fix. A deterministic test must use case (b) — e.g. on a 2×2×2 grid, a `COMPDATL` connection at LGR-local (1,1,1) reads as coarse index 7. The fork already carries the full fix (skip `get_lgr_level() != 0` plus a bounds check) in `opm/grid/common/WellConnections.cpp:120-155`. Upstream (OPM/opm-grid#1053) was narrowed on review to the bounds check only — the refinement-level skip is a modelling decision about what belongs in the level-zero graph and is deferred, so **upstream still has (b)**. Anchoring `COMPDATL` wells to their box's parent coarse cell (see C1b, opm-simulators `2a1de22b4`) is the same problem from the other end and is the real fix. The same class of bug was found and fixed in opm-common's `RegionCache::buildCache` (OPM/opm-common#5251), where an in-range LGR-local index silently files a connection under the wrong FIP region. |

---

## How to run the new decks

```sh
FLOW=builds/refined/opm-simulators/bin/flow
CMP=builds/refined/opm-common/bin/compareECL
cd opm-tests/lgr

# B1 MINPV: serial ok, parallel cell output wrong (gap)
$FLOW SPE1CASE1_CARFIN1_MINPV.DATA --parsing-strictness=low --output-dir=/tmp/mp_s
mpirun -np 2 $FLOW SPE1CASE1_CARFIN1_MINPV.DATA --parsing-strictness=low --output-dir=/tmp/mp_p
$CMP -t UNRST -k PRESSURE -n /tmp/mp_s/SPE1CASE1_CARFIN1_MINPV /tmp/mp_p/SPE1CASE1_CARFIN1_MINPV 0.01 1e-3   # expect errors -> gap

# B2 RFT: completes, no .RFT produced
$FLOW SPE1CASE1_CARFIN1_RFT.DATA --parsing-strictness=low --output-dir=/tmp/rft
ls /tmp/rft/*.RFT 2>/dev/null || echo "no RFT (gap)"

# B3 restart: base run then restart -> expected throw
$FLOW SPE1CASE1_CARFIN1.DATA --parsing-strictness=low --output-dir=/tmp/rb
( cd /tmp/rb && $FLOW <repo>/opm-tests/lgr/SPE1CASE1_CARFIN1_RESTART.DATA --parsing-strictness=low --output-dir=. )
# -> "Refined grids are not yet supported for restart"
```

When a gap is fixed, the corresponding deck becomes a positive regression
(compareECL serial==parallel for B1; `.RFT` present + correct for B2; restart
continues for B3).

## D. Index-space and output audit (2026-08-20)

Everything in this section came out of one recurring defect, worth stating plainly
because it will keep recurring:

> **An array is built in one index space and read in another.** Field properties
> and FIP region arrays are sized by the *input grid's* active cells; the solver
> and the output loops index by *leaf element*. Without refinement the two
> coincide, so the code looks correct and every non-LGR test passes. With a
> CARFIN the leaf is longer, and the read runs off the end of the array.

The second family is structural rather than an index slip: **a feature attached to
a coarse cell that no longer exists on the leaf** — an NNC, an aquifer connection,
a block summary vector. There the data is not misread, it is silently dropped.

Neither family announces itself. The observed symptoms were "solver failed to
converge", "region indices must be non-negative", `unordered_map::at: key not
found`, and — worst — a plausible-looking answer with an aquifer contributing
nothing.

**Method.** Two things found all of it, and both are cheap to repeat:

1. `grep` the simulator for `fieldProps().get_*` and check, at each site, whether
   the result is indexed by leaf element. `LookUpData::assignFieldProps*OnLeaf` is
   the fix and is the identity without LGRs (`getFieldPropIdx(i) == i`), so it can
   be applied without perturbing non-LGR runs.
2. Build a small deck on `SPE1CASE1_CARFIN1.DATA` exercising one feature, and run
   it **twice** — with the CARFIN and with it stripped. Any difference in a
   quantity the refinement should barely move is a finding. Running is not the
   test; comparing the numbers is.

For the output files, `scripts/compare_lgr_output.py` walks an EGRID/INIT array by
array against a reference. Its `--lgr-gap` mode — which arrays exist for the
global grid but for no LGR grid — needs no reference at all and is what found D4b.
The cell-by-cell ACTNUM/HOSTNUM checks that got Norne and Drogon matching say
nothing about which arrays are *present*, which is why these went unnoticed.

### D1 — fixed: arrays now mapped onto the leaf

| # | Gap | Where | Test deck | Fix |
|---|-----|-------|-----------|-----|
| D1a | **Deck NNC and numerical-aquifer transmissibility looked up in the wrong space.** The input-NNC branch resolved its two Cartesian cells through the *level-zero compressed* map, then indexed `globalTrans()`, which is built on the **leaf**. Any deck NNC in a refined model threw `unordered_map::at: key not found` before the first timestep. Numerical aquifers hit it every time — their connections are routed through this branch unconditionally, even when both cells lie far outside the box. | `EclGenericWriter_impl.hpp` `exportNncStructure_` | `SPE1CASE1_CARFIN1_AQUNUM.DATA` | opm-simulators `17deafe26` |
| D1b | **Inter-region flow region arrays.** `InterRegFlowMap` is built from the input-grid FIP arrays and sized by them, but `processFluxes` accumulates per leaf element. Refined runs read past the end and used the garbage as a region id: *"Region indices must be non-negative. Got (r1,r2) = (99, -478425464)"*. Only decks asking for `ROFT`/`RGFT`-style vectors build these arrays, which is why no existing LGR deck caught it. | `GenericOutputBlackoilModule` / `OutputBlackoilModule::createLeafInterRegionFlows_` | `SPE1CASE1_CARFIN1_ROFT.DATA` | opm-simulators `1124dcee0` |
| D1c | **Explicit initialisation.** `PRESSURE`, `SWAT`, `SGAS`, `RS`, `RSW`, `RV`, `RVW`, `TEMPI`, `SALT`, `SALTP` were read straight from field properties and indexed by leaf cell over `numGridDof()`. Every refined cell was initialised from whatever followed the array in memory; the run then failed to converge on step one, which reads as a solver problem rather than an initialisation one. Same read on the CO2STORE/H2STORE restart path. | `FlowProblemBlackoil.hpp` `readExplicitInitialCondition_` | `SPE1CASE1_CARFIN1_EXPLICIT.DATA` | opm-simulators `6003b5c1b` |
| D1d | **GPMAINT pressure maintenance.** The regional-pressure calculator builds its `RegionMapping` from an input-grid FIP array, then indexes it by simulation cell (`RegionAverageCalculator.hpp:127`). On SPE1CASE1 the deck **aborts** (SIGABRT); whether it aborts or quietly returns a garbage region id is down to what follows the array in memory. `setRegionAveragePressureCalculator` now takes a callable supplying the leaf-mapped array instead of the `FieldPropsManager`. | `GroupStateHelper.hpp`, `BlackoilWellModel_impl.hpp` | `SPE1CASE1_CARFIN1_GPMAINT.DATA` | opm-simulators `1775bc53b` |

Earlier members of the same family, for context: EQLNUM/PVTNUM/SWATINIT in
equilibration (`a7bb9cb3e`), the FIP region arrays behind FPR (`ae1809ba1`), and
the datum-region arrays (`37c209c6d`).

### D2 — fixed: output files

| # | Gap | Where | Fix |
|---|-----|-------|-----|
| D2a | **`LOGIHEAD` and `DOUBHEAD` were skipped for `NORST != 0`** on the grounds that a graphics-only restart does not need them. It does: `DOUBHEAD` carries the simulated time and `LOGIHEAD` the dual-porosity flag, so libecl builds its restart header from **uninitialised memory** (it null-checks and leaves `sim_days`/`dualp` unset) and ResInsight shows a case with no dynamic data at all; OPM's own `LoadRestart` refuses the file outright. ECLIPSE writes both for a graphics-only restart — checked against a `NORST=1` reference. **Not LGR-specific**: any deck with `NORST=1` was affected. | opm-common `RestartIO.cpp` | `3228891c9` |
| D2b | **`NNCHEAD` announced the wrong count** for the LGR-to-global NNC section: it was handed the LGR's *internal* count. On a two-box Norne case LGR2 announced 374 while writing 744, and LGR1 — whose interior has no NNC at all — announced **zero** while writing 684 boundary connections. libecl reads the arrays by their own length and takes only the LGR number from the header, so ResInsight was unaffected; a reader trusting the count sees a fraction of the connections or none. | opm-common `EclipseGrid.cpp` `save_nnc_local_global` | `9cc2e3dbf` |

### D3 — made visible, not fixed

These are cases where refinement silently swallows something. Each now reports
itself; none is repaired.

| # | Gap | Test deck | Message |
|---|-----|-----------|---------|
| D3a | **An NNC, EDITNNC or numerical-aquifer connection naming a cell inside a box is dropped from the simulation.** `applyNncToGridTrans_` only *adds* to a face the grid already holds; the coarse cell is not on the leaf, so neither is its NNC face, and `trans_.find()` simply misses. A numerical aquifer in that position stops feeding the reservoir: `ANQR`/`ANQT` read zero for the whole run where the same deck without the CARFIN reaches ~9 sm3. | `SPE1CASE1_CARFIN1_AQUNUM_IN_LGR.DATA` | *"N explicit connection(s) … name a cell pair the grid does not join"*, with the cell pairs listed (opm-simulators `a3102b2ec`) |
| D3b | **An analytical aquifer (`AQUFETP`/`AQUANCON`) connecting into a box loses every connection.** `AquiferAnalytical::initializeConnections` resolves each `AQUANCON` cell through `compressedIndex()` on its Cartesian index and skips what it cannot find. `AAQT` goes from **-2.15e6 to exactly zero** and pressure holds up 200 psi too well. A **separate path** from D3a — the NNC warning does not cover it. | `SPE1CASE1_CARFIN1_AQUFETP.DATA` | *"Analytical aquifer N: M of M AQUANCON connection(s) name a cell that is not in the simulation grid"* (opm-simulators `1eab62f19`) |
| D3c | **`B*` summary vectors on a refined cell read zero for the whole run** (see B5). | `SPE1CASE1_CARFIN_GR.DATA` | *"N block summary vector(s) name a cell inside a refined (CARFIN) box"*, listing them (opm-simulators `1eab62f19`) |

### D4 — open gaps

| # | Gap | Evidence | Repair |
|---|-----|----------|--------|
| D4a | **The global NNC list is truncated wherever an LGR covers it.** OPM drops every NNC whose cells lie inside a box, because `exportNncStructure_` walks the leaf and those coarse cells are not on it. ECLIPSE keeps the coarse grid's connectivity complete — reasonably, since the global section of the EGRID still contains those cells in COORD/ZCORN/ACTNUM. | Norne: reference 11287 global NNCs, of which **549 have both ends in the box and 148 one end**; OPM writes 10589 and none of either. Drogon: 6247 vs 1170. | Needs the coarse grid's connectivity computed at output time; no current code path produces it. **Output only.** |
| D4b | **The INIT's LGR section has no saturation-endpoint arrays.** 17 of them — `SGCR SGL SGU SOGCR SOWCR SWCR SWL SWU SWATINIT` and their `I*` index variants — are written for the global grid and for no LGR. Already flagged in the source: *"Not yet supported: LGR-specific aquifer and satfunc scaling"*. | `compare_lgr_output.py --lgr-gap`: OPM writes 42 per-cell arrays for the global grid and 25 for the LGR; the reference writes 67 for both, its own global-vs-LGR gap being empty. | The tractable one. A refined cell inherits its father's endpoints, so it is the same father lookup `writeLGRLocalProperties` already does for SATNUM, plus a second LGR pass after the global satfunc block. A reference now exists to verify against. **Output only.** |
| D4c | **The refined boundary resolves sliver fault juxtapositions less well than the coarse grid.** OPM's LGR NNC lists are a strict *subset* of the reference's — 7 missing, 0 spurious — and all 7 are marginal overlaps across large fault throws. | Two are the minimum entry of their array (~2e-6 against a median of 0.48); the largest is 1.6e-3 against a median of 1.11. Five of them sit in **one** refined row; the rows either side of it match the reference connection for connection. **Control:** OPM's *unrefined* Norne differs from the reference's coarse connectivity by **1 of 11287 (0.009 %)**, against 7 of 3303 (0.2 %) refined — same class of difference, ~25× the rate. | Tried and reverted: aligning `FaultedBoundaryFaces`'s hardcoded `process_grdecl` tolerance (1e-6) with the main path's `tolerance_unique_points` (0) changes nothing. The faces are absent from the leaf itself, so the cause is in the refined boundary/leaf assembly. Not repaired. |
| D4d | **A plain `COMPDAT` naming a cell inside a box aborts the run** — *"Cells with these i,j,k indices were not found in grid"*. Wells completed in a refined region must use `WELSPECL`/`COMPDATL` with LGR-local indices (or a trajectory). This is correct behaviour rather than a defect, but it is the first thing a field deck hits when a box is placed over a well. | `NORNE_LGR_WELLS.DATA` demonstrates the conversion. | Check for it before choosing a box: scan every well's completions against the candidate box (see the showcase note below). |
| D4e | **A multisegment well cannot be completed in an LGR.** `COMPSEGL` — the LGR form of `COMPSEGS` — is parsed but implemented nowhere (zero references outside its keyword definition). Fails loudly either way, which is the right outcome: strict parsing refuses it (*"COMPSEGL: keyword not supported"*), and under `--parsing-strictness=low` the keyword is ignored and opm-common then catches the well with *"Missing COMPSEGS or COMPTRAJ keyword for the following multisegment well"*. **Not** a silent wrong answer. | An MSW `WELSEGS` + `COMPSEGL` well on `SPE1CASE1_CARFIN_GR` | Implementing `COMPSEGL` — segment-to-connection mapping in LGR-local indices. Note that until CARFIN came off the unsupported-keyword list, every LGR deck ran with `--parsing-strictness=low`, which is the confusing path of the two. |

### D5 — keyword handling

`CARFIN`, `LGR`, `NXFIN`/`NYFIN`/`NZFIN`, `HXFIN`/`HYFIN`/`HZFIN`, `WELSPECL` and
`COMPDATL` were all honoured but still on flow's unsupported-keyword list as
*critical*, so every LGR deck needed `--parsing-strictness=low` — which also
silences whatever else the deck gets wrong. Dropped (opm-simulators `676cb7158`,
`5db773b44`). `LGRCOPY` and `LGRLOCK` remain listed as **non-critical** with a note
on what flow does instead; `AMALGAM`, `LGRFREE` and `RADFIN*` stay **critical**
because they change the grid and are not implemented.

**The recipes below still pass `--parsing-strictness=low`; it is no longer needed
for the LGR keywords themselves.**

### D6 — checked and clean

Analytical aquifer *outside* a box (2 % difference = the refinement's real
effect), `BCCON`/`BCPROP`, `MULTZ`, `TRAN*` modifiers, numerical aquifer outside a
box, inter-region flows after D1b, and the LGR-internal fault connections
(verified cell by cell and by transmissibility — see the showcase note). Solvent,
polymer, biofilm and MICP throw a clear refusal with LGR rather than running.

Restart files carry no NNC arrays at all, so the D2b/D4a class cannot affect them.

### Full-field showcase

`opm-tests/norne/NORNE_LGR_WELLS.DATA` — base `NORNE_ATW2013` with a 3×3×22 box
around the injector **F-1H** and another around the producer **E-3H**, each
refined **3×3×1** (lateral only, so the layering is the base case's). Both wells
are rewritten to `WELSPECL`/`COMPDATL` by
`opm-tests/norne/INCLUDE_LGRWELLS/make_lgr_wells.py`, **carrying the deck's own
connection factors over unchanged** so each well keeps the well index it was
history-matched with.

Against the unrefined base: same 353 timesteps, 1296 → 1308 Newton, global active
cells still exactly 44431. FGPT 0.06 %, FOPT 0.19 %, FPR 0.03 %; an untouched well
(B-1H) moves 0.09 %. The two refined wells move — F-1H's BHP by 1.5 % at identical
injected volume, E-3H's cumulative oil by 3.6 % — which is the refinement doing
its job. Each box comes out at 1539 and 1683 active cells, both exact multiples of
nine, so every child of an active parent survives and the refinement is a pure
subdivision; that needs block `MINPV 0.1`, because a refined cell holds a ninth of
its parent's pore volume and the field's `MINPV 500` would delete exactly the
cells the refinement creates.

Two things to do before choosing a box, both learned the hard way:

- **Scan every well's completions against the candidate box.** Only the wells you
  intend to convert may have a connection inside it (D4d). LGR2 above is offset
  one cell in j from centred on E-3H so that it does not clip E-3AH's cell.
- **Lower `MINPV` inside the box** by at least the refinement factor's product.

Verified connection-wise on that case: a faulted juxtaposition (12,74,1)→(13,74,2)
and (13,74,3) becomes **6** refined NNCs (3 j-subcolumns × 2), with ΣT = 0.4256
against the coarse 0.1457 — a ratio of **2.92 ≈ 3**, which is the correct
signature of lateral refinement (a sub-face has ⅓ the area *and* ⅓ the
centre-to-centre distance, so each carries about the whole coarse T and there are
three). Global bookkeeping closes exactly: 129 base NNCs had both ends inside the
box, all 129 are absent from the refined run's global list, and 374 refined ones
replace them.

### Test deck index

All in `opm-tests/lgr/` unless noted; all derived from `SPE1CASE1_CARFIN1.DATA`
so they run in seconds. Each is meant to be run **twice** — as written, and with
the `CARFIN … ENDFIN` block stripped — and the numbers compared.

| Deck | Exercises | Status |
|---|---|---|
| `SPE1CASE1_CARFIN1_AQUNUM.DATA` | numerical aquifer, cells outside the box | passes (D1a) |
| `SPE1CASE1_CARFIN1_AQUNUM_IN_LGR.DATA` | numerical aquifer connecting **into** the box | warns; ANQR zero (D3a) |
| `SPE1CASE1_CARFIN1_AQUFETP.DATA` | analytical aquifer connecting **into** the box | warns; AAQT zero (D3b) |
| `SPE1CASE1_CARFIN1_ROFT.DATA` | inter-region flow vectors across a box | passes (D1b) |
| `SPE1CASE1_CARFIN1_EXPLICIT.DATA` | explicit initialisation instead of EQUIL | passes (D1c) |
| `SPE1CASE1_CARFIN1_GPMAINT.DATA` | GPMAINT pressure maintenance on a FIP region | passes (D1d) |
| `SPE1CASE1_CARFIN1_MULTZ.DATA` | `MULTZ` and PINCH's `ALL` option over a box | passes |
| `SPE1CASE1_CARFIN1_TRANZ.DATA` | a `TRANZ` modifier over a box | passes |
| `SPE1CASE1_CARFIN_GR.DATA` | whole grid refined; wells via `WELSPECL`/`COMPDATL` | passes; 11 `B*` vectors read zero (D3c) |
| `SPE1CASE1_CARFIN_FAULTS.DATA` | fault crossing a box boundary | passes (needs `--parsing-strictness=low` for `AMALGAM`) |
| `SPE1CASE1_CARFIN1_NESTED.DATA` | nested box touching its parent's boundary | expected refusal |
| `SPE1CASE1_CARFIN1_NESTED_CONTAINED.DATA` | nested box strictly inside its parent | passes |
| `norne/NORNE_LGR_WELLS.DATA` | full field, one box per well, `COMPDATL` | passes; the showcase |
| `lgrtests/NORNE_LGR.DATA` | full field, graded box + block `MINPV` | passes; ships an ECLIPSE reference |
| `drogon/DROGON_HIST_LGR1.DATA` | full field, uniform box, MSW-era deck, `NORST=1` | passes; ships an ECLIPSE reference that **aborts** at 224 d |

```sh
# the two-run comparison, for any of the decks above
F=builds/refined/opm-simulators/bin/flow_blackoil
S=builds/refined/opm-common/bin/summary
D=opm-tests/lgr/SPE1CASE1_CARFIN1_AQUFETP.DATA
python3 - "$D" <<'EOF'
import re,sys
s=open(sys.argv[1]).read()
open('/tmp/nolgr.DATA','w').write(re.sub(r"(?m)^CARFIN\n(?:.*\n)*?^ENDFIN\n","",s))
EOF
$F "$D"            --output-dir=/tmp/lgr
$F /tmp/nolgr.DATA --output-dir=/tmp/nolgr
$S /tmp/lgr/*.SMSPEC   AAQT:1 FPR
$S /tmp/nolgr/*.SMSPEC AAQT:1 FPR      # differences here are the finding

# array-by-array against a reference, or against nothing at all
export CONVERTECL=builds/refined/opm-common/bin/convertECL
python3 opm-gridrefined/scripts/compare_lgr_output.py REF.EGRID RUN.EGRID
python3 opm-gridrefined/scripts/compare_lgr_output.py --lgr-gap RUN.INIT
```
