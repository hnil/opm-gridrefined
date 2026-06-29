# Porting the upstream LGR unit tests to the rewrite

The upstream CpGrid LGR unit-test suite lives in
`opm-grid/tests/cpgrid/lgr/` (the untouched reference checkout) — **32 tests +
`LgrChecks.hpp`**. The rewrite (`opm-gridrefined`, built *as* the `opm-grid`
module) did **not** port them; it wrote its own `grdecl`-based unit tests
(`conforming_builder_test`, `grdecl_refinement_test`, `adaptive_cpgrid_test`,
`faulted_boundary_test`, …) plus flow-level deck regression
(`opm-tests/lgr/*.DATA` via `lgr_regression.sh`).

This note records **what the originals tested**, **what carries over**, and
**why most do not transfer as-is**.

## Status: ported so far (build + pass against the rewrite, 2026-06-26)

Pulled into `tests/cpgrid/lgr/` (+ `LgrChecks.hpp`) and **verified green**:

| Test | Module | Result |
|---|---|---|
| `lgr_cartesian_idx_test` | LgrCartesianIndexTests | ✅ builds, passes |
| `consistent_vertex_order_in_face_test` | FaultFullyInLgrTest | ✅ builds, passes |
| `getParentIntersectionFromLgrBoundaryFace_test` | GetParentIntersectionFromLgrBoundaryFaceTests | ✅ builds, passes |

These transfer because they assert *geometric/topological invariants of a
single-rank refined leaf* — exactly the surface the rewrite kept compatible.

## Why a test is probably NOT transferable — four structural reasons

A non-transferable test fails for a structural reason, not an oversight. The
rewrite changed the parallel model, dropped some features, and replaced the
internal indexing/merge algorithm.

### R1 — it exercises the parallel architecture the rewrite replaced
Upstream distributes level 0 and then **scatters the refined grid** across ranks
(distribute-then-refine). The rewrite **stripped that machinery** and uses the
*rank-interior* model: each box is refined on its owning rank and refined cells
are never scattered (see `LGR_GAPS.md` C4). A test that distributes a
grid-with-LGRs, or checks refined cells on the overlap / another rank, asserts
behavior that cannot occur here.

### R2 — it tests a feature not implemented in the rewrite
The rewrite is block-CARFIN focused. Tests for NNC inside LGRs, aquifer-cell
exclusion, fully-recursive nested leaf, and (likely) auto/global refinement drive
code paths that throw "not implemented" or do not exist.

### R3 — it asserts on an internal representation/algorithm the rewrite swapped out
Upstream merges shared-LGR boundaries by **replacing lgr1's corner/face indices
with lgr2's** (`replaceLgr…`); the rewrite merges via a **coordinate-keyed corner
pool + sub-face mosaic** (`refinedCornerPool` / `coordKey` in
`LeafGridAssembler.cpp`). The same conformal *result* is reached, but the test
checks the old index-replacement step — nothing equivalent exists to assert
against. Likewise `lgrIJK` (API removed) and the level-Cartesian mappers probe an
internal indexing the rewrite does not expose identically.

### R4 — it pins exact entity numbers that the rewrite assigns differently
The rewrite numbers refined corners/cells in a different order and gives refined
cells **fresh per-rank global ids**. Equality assertions on specific
indices/ids fail even though the grid is geometrically identical. Transferable
only by **rewriting the assertions as invariants** (counts, uniqueness, geometry,
father/child) — which is what `LgrChecks.hpp` is for, and why it was pulled in
alongside the three ported tests.

## Per-test map (all 32)

Legend — ✅ ported+passing · ▣ covered by a different new-framework test ·
🔶 likely portable (feature exists; needs API edits) · ⚠️ portable only by
rewriting to invariants (R4) · ❌ not transferable (reason).

Legend for **Built+run** (empirical, against the rewrite): ✅ built & passes ·
✗ built but throws at runtime · — not attempted.

| Upstream test | What it tests | Transferability | Built+run |
|---|---|---|---|
| `lgr_cartesian_idx_test` | LGR Cartesian index | ✅ ported | ✅ passes |
| `consistent_vertex_order_in_face_test` | fault fully inside an LGR; face vertex order | ✅ ported | ✅ passes |
| `getParentIntersectionFromLgrBoundaryFace_test` | parent intersection from an LGR boundary face | ✅ ported | ✅ passes |
| `global_refine_test` | uniform global refinement | 🔶 builder-portable — `globalRefine` now wired to the builder (refCount==1); recursive levels still unsupported | ✗ as-is (R3/R4 + recursion); ✅ scenario demonstrated by `global_refine_via_builder_test` |
| `adapt_cpgrid_test` | `adapt()` mark→refine | ▣ `adaptive_cpgrid_test`; portable via builder | ✗ throws (`adaptGridWithParams` → "use createGridAndAddLgrs") |
| `autoRefine_test` | arbitrary per-direction (odd) global refinement | 🔶 builder-portable — `autoRefine` now wired to the builder (one full-grid LGR with factors nxnynz) | ✗ as-is (R3/R4 assertions); ✅ scenario demonstrated by `global_refine_via_builder_test` |
| `lgrs_sharing_faces_test` | two LGRs sharing a face | ▣ `conforming_builder_test::faceSharingBoxes` | — |
| `refine_hexahedron_with_non_rectangular_faces_test` | trilinear refinement of distorted hexes | ▣ `grdecl_refinement_test` / distorted-pillar grids | — |
| `addLgrs_in_allActiveCartesianGrid_test` | block LGR on a Cartesian grid | ▣ `conforming_builder_test` (Cartesian box) | — |
| `lookupdataCpGrid_test` | `LookUpData` field props on the leaf | 🔶 feature exists (flow-verified); needs API port | — |
| `lookUpCellCentroid_cpgrid_test` | leaf cell centroids via `LookUpData` | 🔶 feature exists; needs API port | — |
| `restrict_data_to_level_grids_test` | restrict cell data to level grids | 🔶 feature exists; needs API port | — |
| `lgr_coord_zcorn_test` | refined COORD/ZCORN | 🔶 `RetainedCornerPointInput` exists; partial via `refined_structure_comparison_test` | — |
| `save_lgr_coord_zcorn_test` | export refined COORD/ZCORN | 🔶 as above | — |
| `grid_global_id_set_test` | global id set over the leaf | ⚠️ R4 (ids differ) | — |
| `lgr_cell_id_sync_test` | cell-id sync across levels | ⚠️ R4 (ids differ) | — |
| `id_entity_entityrep_test` | entity/entityrep id comparison | ⚠️ R4 (ids differ) | — |
| `addLgrsOnDistributedGrid_test` | add LGRs on an already-distributed grid | ❌ R1 | — |
| `communicate_distributed_grid_with_lgrs_test` | comms over a distributed LGR grid | ❌ R1 | — |
| `distribute_level_zero_from_grid_with_lgrs_test` | distribute-then-refine | ❌ R1 | — |
| `distribute_level_zero_from_grid_with_lgrs_and_wells_test` | distribute-then-refine + wells | ❌ R1 | — |
| `addLgrs_if_non_nnc_in_lgrs_test` | NNC interaction with LGRs | ❌ R2 (NNC-in-LGR not done) | — |
| `aquifer_cells_and_conn_not_refined_test` | aquifer cells/connections not refined | ❌ R2 (aquifer+LGR not done) | — |
| `nested_refinement_test` | LGR inside an LGR (recursive leaf) | ❌ R2 (nested leaf only partial — A1) | — |
| `lgr_with_inactive_parent_cells_test` | LGR over inactive parents | ❌ R2 (partial; verify) | — |
| `lgrIJK_test` | `lgrIJK` mapping | ❌ R3 (API removed) | — |
| `replace_lgr1_corner_idx_by_lgr2_corner_idx_test` | shared-LGR corner-index replacement | ❌ R3 (merge-by-coordinate replaces it) | — |
| `replace_lgr1_face_idx_by_lgr2_face_idx_test` | shared-LGR face-index replacement | ❌ R3 (merge-by-coordinate replaces it) | — |
| `levelCartToLevelCompressed_test` | level Cartesian→compressed mapper | ❌ R3 (internal indexing differs) | — |
| `level_and_grid_cartesianIndexMappers_test` | level/grid Cartesian index mappers | ❌ R3 | — |
| `mapLevelIndicesToCartesianOutputOrder_test` | level→Cartesian output order | ❌ R3 | — |
| `logicalCartesianSize_and_refinement_test` | logical Cartesian size under refinement | ❌ R3 (verify; may be portable) | — |

The three `✗` rows were built & run during this analysis (then removed, since
they fail); the result is recorded here rather than kept as red tests.

## The adapt framework: more tests are reachable than "feature absent" implies

Empirical check (2026-06-26): the upstream adapt-interface tests `adapt_cpgrid_test`,
`global_refine_test`, `autoRefine_test` **compile** against the rewrite (the Dune
signatures `mark`/`preAdapt`/`adapt`/`postAdapt`/`globalRefine`/`autoRefine` are
still on `CpGrid`, CpGrid.hpp:521–628) but **throw at runtime**:

- `adapt_cpgrid_test` → *"the DUNE mark/adapt refinement path is not available in
  opm-gridrefined; use `createGridAndAddLgrs`"* (`LgrChecks.hpp:859`)
- `global_refine_test` / `autoRefine_test` → *"Local grid refinement has been
  removed in opm-gridrefined …"* (`CpGrid.cpp:1820/1838`)

So these are **not "feature absent" (R2)** — the refinement *capability* exists; it
was only **rerouted off the Dune mark/adapt interface onto the builder**
(`ConformingBlockBuilder` / `addLgrsUpdateLeafView`), which is exactly what
`AdaptiveCpGrid` (markBox/markCell→adapt) and `LgrChecks::createGridAndAddLgrs`
drive. Two ways to make these tests usable:

1. **Re-point the tests to the builder path.** `LgrChecks.hpp` already provides
   `createGridAndAddLgrs` (the working refine-after path) next to the throwing
   `adaptGridWithParams`. A test that calls `adaptGridWithParams` /
   `grid.adapt()` can be rewritten to drive `createGridAndAddLgrs` or
   `AdaptiveCpGrid::markBox/adapt` and then assert the **same** result invariants
   (the refined leaf is identical — `adaptive_cpgrid_test` already proves
   adapt() == static addLgrs). The 3 already-ported tests pass precisely because
   they take this path.
2. **Wire `CpGrid::globalRefine()`/`adapt()` to the builder.** `AdaptiveCpGrid`
   demonstrates the mechanism end-to-end (mark → merge → one `addLgrsUpdateLeafView`).
   Routing `globalRefine(n)` to a whole-grid box and the Dune `mark`/`adapt` calls
   to accumulated marks would un-stub the Dune interface, and `global_refine_test`
   / `adapt_cpgrid_test` would then run **unchanged**.

Net: the **adapt/globalRefine/autoRefine family moves from ❌ R2 to 🔶 portable**
once you accept the builder (or `AdaptiveCpGrid`) as the adapt engine. `autoRefine`
additionally needs the criterion→mark step, but the refine half is solved. Only
`nested_refinement_test` stays a genuine feature gap (recursive nested leaf, A1).

**Demonstrated (route 2, 2026-06-26):** both Dune-interface entry points are now
wired to the builder (`CpGrid.cpp`), reusing `addLgrsUpdateLeafView` — no removed
Dune mark/adapt machinery reintroduced:

- `globalRefine(refCount)` — `0` is a no-op; `1` refines every cell 2x2x2 as one
  whole-grid block; negative / recursive (`refCount > 1`) / already-refined throw.
- `autoRefine(nxnynz)` — **arbitrary anisotropic global refinement = one full-grid
  LGR** with `cells_per_dim = nxnynz`. Factors must be positive and odd (upstream
  convention: an odd split has a central cell/row for well placement); else
  `std::invalid_argument`.

Why `globalRefine` looks "limited" but the grid is not: `globalRefine(int)` is a
single integer — it can only express *isotropic 2x, recursively nested* levels, so
`refCount > 1` needs re-refining an already-refined grid (a feature the
single-level builder lacks). That is an **interface** limit, not a capability one:
refining the whole grid by *any* (odd) per-direction factor in one LGR is fully
supported through `autoRefine` / a direct whole-grid `addLgrsUpdateLeafView`.

Verified by `tests/cpgrid/lgr/global_refine_via_builder_test.cpp` (5 cases):
`globalRefine(1)` == whole-grid `addLgrsUpdateLeafView({2,2,2})`; the no-op; the
globalRefine throwing cases; `autoRefine({3,5,7})` == whole-grid
`addLgrsUpdateLeafView({3,5,7})` (same leaf, conformal); and autoRefine's
even/non-positive rejection. The upstream `global_refine_test` / `autoRefine_test`
still do not pass unchanged (multi-level recursion + level-index/id assertions,
R3/R4), so the **scenarios** are demonstrated with a rewrite-native test rather
than by reviving the old ones.

## How far is `AdaptiveCpGrid` from the Dune adaptive interface?

Two interfaces must be distinguished:

- **`Dune::Grid` interface** (leafGridView, entities, index/id sets, intersections,
  communication). `AdaptiveCpGrid` does **not** implement it — it *delegates* to the
  underlying `Dune::CpGrid` via `grid()`, which already is a full `Dune::Grid`. So
  the grid interface is "served by `grid()`"; promoting `AdaptiveCpGrid` itself to a
  `Dune::Grid` is neither done nor the intended design.
- **Dune adaptive/refinement interface** (`mark`/`getMark`/`preAdapt`/`adapt`/
  `postAdapt`/`globalRefine`/`autoRefine`). This is the relevant one. Current state
  on `CpGrid`: `globalRefine`/`autoRefine` now route to the builder (done here);
  `mark` throws, `getMark`→0, `preAdapt`/`adapt`→false, `postAdapt`→no-op (stubs).
  `AdaptiveCpGrid` implements the *semantics* (mark→adapt→refined leaf) but with a
  richer signature (`markBox`/`markCell(ijk, cellsPerDim)` + `void adapt()`).

Distance to fulfilling the **adaptive** interface:

| Piece | Status | Effort |
|---|---|---|
| Refine semantics (mark region → conformal refined leaf) | ✅ done (`AdaptiveCpGrid`; proven == static LGR) | — |
| `globalRefine` / `autoRefine` | ✅ wired to builder | done |
| `mark(int refCount, Entity)` signature | ✗ adapter: entity→ijk (Cartesian index) + refCount→factor (e.g. 2^refCount) | thin |
| `adapt()` returns `bool`, `preAdapt()`, `postAdapt()`, `getMark()` | ✗ lifecycle glue (preAdapt→false, postAdapt→clear marks) | thin |
| **Coarsening** (`mark(-1)` / de-refinement) | ❌ not implemented (design defers it) | real feature |
| **Data prolong/restrict across adapt** (`adaptDataHandle`) | ❌ full-rebuild loses the transfer hook; needs father/child wiring | real feature |
| **Parallel adapt** | ❌ rank-interior; refined-grid scatter stripped (R1) | large |

Net: the **refine half is ~90% there** — only adapter glue separates
`AdaptiveCpGrid`'s engine from the literal Dune `mark`/`adapt` signatures, and the
cleanest route is to implement `CpGrid::mark`/`adapt` by accumulating per-entity
marks and rebuilding through the builder (exactly the `globalRefine`/`autoRefine`
pattern, exactly what `AdaptiveCpGrid` already does). The **coarsening half and
cross-adapt data transfer are genuine unstarted features**, and parallel adapt is
the same architectural gap as R1.

## Full coverage summary (four quadrants)

### Tested in the original (upstream `opm-grid/tests/cpgrid/lgr/`, 32 tests)
- **Refinement build & geometry:** Cartesian/distorted-hex refinement, two LGRs
  sharing a face, refined COORD/ZCORN + export, fault fully inside an LGR, parent
  intersection from an LGR boundary face.
- **Adapt framework:** `adapt`/`mark`/`preAdapt`/`postAdapt`, `globalRefine`,
  `autoRefine`.
- **Nested:** an LGR inside an LGR.
- **Indexing / mappers:** `lgrIJK`, LGR Cartesian index, level↔compressed,
  level/grid Cartesian index mappers, level→Cartesian output order, logical
  Cartesian size under refinement.
- **Identity:** global id set, cross-level cell-id sync, entity/entityrep ids.
- **Field data:** `LookUpData` props, leaf cell centroids, restrict-to-level.
- **Shared-LGR internals:** corner/face index replacement, consistent vertex order.
- **Robustness:** LGR over inactive parent cells, aquifer cells/connections not
  refined, NNC interaction with LGRs.
- **Parallel:** add LGRs on a distributed grid, communicate over a distributed LGR
  grid, distribute-then-refine (± wells).

### Tested in the new (rewrite `opm-gridrefined/tests/cpgrid/`)
- **Builder unit tests:** `conforming_builder_test` (build, multi-box,
  edge/face-sharing, A2 compatible mosaic, A5 box↔box fault, id sets,
  nested-reaches-boundary), `grdecl_refinement_test`, `level_grid_assembler_test`,
  `refined_structure_comparison_test`, `refinement_seam_test`,
  `edge_conformal_refinement_test`, `faulted_boundary_test`.
- **Adaptive grid:** `adaptive_cpgrid_test` (mark→adapt, re-adapt, cell-by-cell;
  proves adapt() == static LGR), `adaptive_cpgrid_bench`.
- **Parallel (rank-interior model):** `distributed_builder_test`.
- **Ported upstream:** `lgr_cartesian_idx`, `consistent_vertex_order_in_face`,
  `getParentIntersectionFromLgrBoundaryFace`; **new** `global_refine_via_builder`.
- **Flow level:** `opm-tests/lgr/*.DATA` (13 decks) via `lgr_regression.sh` —
  end-to-end CARFIN/welltraj/field-props/fault decks.

### Tested in the original but NOT in the new (the porting gap)
Everything in the per-test table tagged ▣ / 🔶 / ⚠️ / ❌ (≈26 tests). The largest
clusters: parallel distribute/communicate (R1), the level-index/id-mapper family
and shared-LGR index-replacement (R3/R4), and the not-yet-implemented features
(NNC-in-LGR, aquifer-not-refined, recursive nested leaf). The adapt/global/auto
family is portable (engine demonstrated); the LookUpData and COORD/ZCORN groups
are near-direct ports.

### NOT tested anywhere (gaps in BOTH suites)
Scenarios neither suite covers today — candidates for new tests once the feature
lands (from `LGR_GAPS.md`):
- **Parallel LGR transmissibility / inter-level `TRANNNC` in INIT** (B4) —
  serial-vs-parallel not checked.
- **Block summary vectors at refined cells** (e.g. `BPR` inside an LGR, B5).
- **MINPV with parallel LGR cell output** (B1), **RFT for LGR** (B2), **restart of
  a refined grid** (B3) — flow-output paths.
- **Distributed wells across an LGR boundary** (C1) and **COMPDATL at high rank
  counts** (C1b, known to hang at np≥6).
- **Unequal/edge/corner touching beyond the A2/A5 cases**, and **incompatible
  touching** is only asserted to *throw*, not its diagnostics.

(Conversely, several rewrite capabilities are tested in the new suite but had no
upstream test: the A2 compatible sub-face mosaic, the A5 box↔box faulted
interface, and the post-construction `AdaptiveCpGrid` — i.e. new-not-original.)

## Recommended next ports (highest value, lowest friction)
1. **`LgrChecks.hpp` invariants** as a reusable harness (already pulled in) — then
   re-express R4 tests (`grid_global_id_set`, `lgr_cell_id_sync`) as invariant
   checks instead of exact-id assertions.
2. **LookUpData group** (`lookupdataCpGrid`, `lookUpCellCentroid`,
   `restrict_data_to_level_grids`) — the feature exists and is only flow-verified
   today; a unit port closes a real gap (`LGR_GAPS.md` C3).
3. **COORD/ZCORN pair** (`lgr_coord_zcorn`, `save_lgr_coord_zcorn`) — retained
   input exists; near-direct port.

Defer R1/R2/R3 tests until the corresponding architecture/feature lands (parallel
refined-grid distribution, NNC/aquifer/nested, or a decision to expose the old
index mappers).
