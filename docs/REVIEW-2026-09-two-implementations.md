# LGR review, September 2026: where the rebuild stands, how it compares to the original, and one grid for both

Scope: the `dynamic-refinement` branch of opm-gridrefined / opm-simulators /
opm-common against upstream opm-grid master (`8cb1da37`, the original LGR by
Antonella Ritorto and Equinor). Three questions: where the code stands and what
to improve; whether the two implementations can be reformulated so both sit on
a CpGrid that itself cannot refine, so they can live in one branch; and what
refinement of arbitrary regions, graded around wells (lines), would take.

Companions: `STATUS.md` (capability table), `LGR_GAPS.md` (gap list),
`LGR_OUTPUT_STATUS.md` (against the reference), `REFINEMENT-ALGORITHM.md`
(file:line walk-through), `DESIGN-parallel-octree.md` (dynamic design),
`DYNAMIC-REFINEMENT-FLOW-PLAN.md` (S0 to S9), `lgr_review.md` (the June review).

## 1. Where it stands

### Static (deck CARFIN at start)

Mature. Verified on three field cases with reference runs (model2, Norne
graded 3x3x1, Drogon 3x2x1): ACTNUM, HOSTNUM, ZCORN, DZ, DEPTH, PORO, NTG, PERM
identical; refined pillars within millimetres. Serial and rank-interior
parallel run to completion; serial restart works.

What the rebuild handles that the original cannot: faults inside a box and at
its boundary (the preprocessor runs per box), inactive parents, graded
`N*FIN`/`H*FIN` columns with block-local `MINPV`, touching boxes with equal or
compatible-multiple subdivision, `MULT*`/`TRAN*` on refined faces, `ENDFIN`
scoping, nested boxes one level deep.

Open items that change the flow field, in priority order:

1. **Decided 2026-09-04:** `--lgr-trans-from-host` is now on by default. The
   reference distributes the host transmissibility by the refinement factor
   where OPM recomputed per child, which left refined `TRANX` on Drogon at 0.76
   of the reference; from the host it is 0.9993 and Drogon's cumulative water
   gap closes from 8927 to 202. `--lgr-trans-from-host=false` restores the
   geometric recompute.
2. Deck connections inside a box: fixed on 2026-08-27/28. `EDITNNC` reaches
   every child face, `PINCH` is divided among the child pairs, and the `NNC`
   keyword, numerical aquifers and a sealing `MULTREGT` are refused with the
   cells named rather than misapplied. Drogon's 5245 fault seals are back.
3. Parallel INIT transmissibilities: fixed 2026-09-05 (the writer walked the
   coarse equilGrid; it now walks the refined reference grid).
4. Parallel restart from an LGR run refused.

Structural limits: a box must sit on one rank; touching boxes may meet only on
faces, not edges or corners, when factors differ; nesting is one level deep and
the child must be strictly interior; `geometryInFather` refuses graded levels.

### Dynamic

Phase 1 of the plan is done as a serial demonstrator: `LGRON`/`LGROFF` in the
Schedule fire a restart-in-memory rebuild, state moves through a stable-id map,
wells are re-derived by replaying synthesized trajectories, refine and coarsen
both work, ECL output is valid on the deck-CARFIN route.

`AdaptiveCpGrid` is a wrapper around a `Dune::CpGrid`, not a subclass. Every
`adapt()` is a full rebuild through the static builder. Marks are per level-0
cell and are merged into maximal boxes, so the request that reaches the builder
is always a box list.

Not done: pore-volume-weighted restriction (plain child average today), the
explicit-state inventory (somax, swmax, hysteresis guard), a `mark`/`adapt`
facade on CpGrid (stubs), any distance- or well-based mark policy, parallel
adaptation, in-place rebuild.

### Coupling to CpGrid (the fact that matters for section 3)

The rebuild writes the grid through one friend seam, `GridStateWriter`, which
holds 24 named operations, and reads CpGrid through public methods only.
Outside `refinement/` the fork's diff against upstream is 95 percent deletion
of the old algorithm; the reading side of the multilevel model (`Entity`,
`Indexsets`, `Iterators`, `PartitionTypeIndicator`) is untouched. The
opm-simulators branch builds and runs against upstream opm-grid unchanged,
because every fork-only grid call sits behind `requires` or `__has_include`.

## 2. Against the original

| | Original (upstream master) | Rebuild (this fork) |
|---|---|---|
| Geometry of a refined cell | trilinear map of the parent's 8 corners, per cell | resample COORD/ZCORN onto sub-pillars, run the corner-point preprocessor per box |
| Parents it can refine | 8 distinct corners, 6 faces; no NNC, no aquifer cell | any parent the preprocessor accepts, including fault-split and inactive |
| Faults | inside a box: throws; at a boundary: throws | inside: by construction; at boundary: windowed reprocess, harvested faces |
| Graded (`N*FIN`/`H*FIN`) | none; uniform factor per level | per-parent column tables; Norne identical to reference |
| Marking | per leaf cell (`mark`/`adapt`), also boxes | boxes; per-cell marks merged into boxes |
| Touching regions | equal subdivision on shared faces | equal or compatible multiple on faces; edge/corner contact refused when factors differ |
| Nesting | via parent names | one level, fully interior |
| Parallel | distribute then refine; a box may cross ranks; ids predicted and synchronised over level 0 with two bespoke handles | box on one rank (`setPartitionCellGroups`); ids stable by construction; optional refine-before-redistribute |
| Coarsening | none | by rebuild from a smaller mark set |
| Code inside core CpGrid files | about 2700 lines in `CpGrid.cpp`, `CpGridData.cpp`, `Geometry.hpp`, `Entity.hpp`, plus 4900 in LGR-only files | one friend seam and a registry hook; 4100 lines under `refinement/` |
| Tests | 32 files, 11 200 lines, largely re-deriving the same index arithmetic | 15 files, 7 800 lines; structural-equivalence oracle against a directly built refined grid |
| Where geometry differs | none on non-faulted, vertical-pillar grids: bit-identical | on inclined pillars the rebuild follows the reference's sub-pillar semantics |

Both share the same multilevel data model in `CpGridData` and the same
simulator-facing API, which is why the simulator branch runs on either. The
original's real advantages are that it is upstream, that a box may span ranks,
and that marking is per cell. Its structural limit is index-arithmetic
identification of refined entities, which assumes six logical faces per parent
and is what rules out faults and degenerate cells; `BACKPORT.md` section D
explains why no small patch lifts that.

## 3. Both on a non-refinable CpGrid

Yes, and most of the work exists. Define "non-refinable" as: CpGrid holds no
refinement algorithm. Two depths are possible.

### 3a. Container stays, algorithms leave (recommended)

CpGrid keeps the multilevel container but gathers it into one struct,
`LevelHierarchy` (the review's section 6 state component): the vector of level
`CpGridData`, `child_to_parent_cells_`, `cell_to_idxInParentCell_`,
`parent_to_children_cells_`, `leaf_to_level_cells_`, `level_to_leaf_cells_`,
`corner_history_`, `cells_per_dim_`/`subdivision_`, `lgr_names_`,
`refinement_max_level_`. `Entity::father()`, `level()`, `geometryInFather()`,
the hierarchic iterator, id delegation and partition-type delegation keep
reading it, so the Dune interface and the simulator are unchanged.

Both algorithms become backends of the existing `Refinement::Builder`
interface and write only through `GridStateWriter`:

- `ConformingBlockBuilder` (the rebuild), as today.
- `TrilinearCellBuilder` (the original): `LgrHelpers`, `refineSingleCell`,
  `refineCellifiedPatch`, `NestedRefinementUtilities`, the two id handles and
  `CpGridUtilities`, moved under `refinement/legacy/`. `refineAndUpdateGrid`
  is already one function over the `CpGridData` vector; what it needs beyond
  the current seam is population of `cell_index_set_`, remote indices, `mark_`
  and the global id sets, which is a handful of extra `GridStateWriter`
  operations.

`addLgrsUpdateLeafView`, `globalRefine`, `autoRefine` and the `mark`/`adapt`
facade dispatch to the registered builder. The request type becomes the union
of what the two accept: a named block on a parent grid, or an explicit cell
set on a parent grid, with a factor or graded subdivision.

Why this is the right depth: it is what the fork already is plus a revert of
the strip commit into a subdirectory; the 33 original tests and the 15 new
ones run in one tree; the structural-equivalence oracle can require the two
backends to agree on every non-faulted deck; and the diff against upstream
turns from a 6000-line deletion into a move plus a seam, which is the shape a
reviewer can accept as "no behaviour change" before the second backend is
argued on Norne and Drogon evidence. The earlier `CpGridLGR` subclass PR was
rejected because it moved declarations and no coupling; this moves the
coupling behind one seam and adds a demonstrable capability, which is a
different argument. Antonella's August mail sketches the per-box
`processEclipseFormat` approach herself, so the seam is also the vehicle by
which upstream could adopt the algorithm.

### 3b. Container leaves too

CpGrid carries no multilevel members at all; a plain `CpGrid` is the leaf
(cells with more than six faces are already representable), a separate
`RefinementHierarchy` object owns the level grids and maps, and the components
that need levels (output, transmissibility, property lookup) take that object
the way they already take `LookUpData` and `LevelCartesianIndexMapper`.

What it costs: `Entity::father()` and friends stop working on CpGrid, so the
roughly twenty simulator call sites listed in the survey move to the
hierarchy object (about eight of them are upstream code: `getLevelElem` in
output, `getOrigin` in the writer and `PropsDataHandle`, `father` in the
host-transmissibility path, `getParentIntersectionFromLgrBoundaryFace`).
Leaf ids must be the stable packed ids, which the fork already computes.
Parallel index sets for the leaf must be built by the hierarchy layer, which
the leaf assembler already does.

What it buys: CpGrid returns to the pre-2022 core, and the hierarchy is one
object with one owner. It is the cleaner end state and the right shape for
the octree design, but it removes an API upstream built and uses, so it is a
fork-only design unless it arrives as a strictly additive alternative. Do 3a
first; 3b is a later move of the same struct out of the class.

### Work list for 3a

1. Gather the members into `LevelHierarchy` inside `CpGridData`/`CpGrid`;
   `GridStateWriter` and the readers point at it. Pure move.
2. Restore the stripped files under `refinement/legacy/` as
   `TrilinearCellBuilder`; extend `GridStateWriter` with the index-set,
   remote-index, mark and id-set writes it needs.
3. Generalise the request: `{name, parentGridName, cells (box | list),
   cellsPerDim | subdivision, minpvRemoved}`. Original backend marks the cells;
   rebuild backend merges a list into boxes (as `AdaptiveCpGrid` does).
4. Wire `mark`/`preAdapt`/`adapt`/`postAdapt` to the registered builder.
5. Restore the 33 original tests against the legacy backend; run
   `refined_structure_comparison_test` across both backends.
6. Runtime selection: a CpGrid parameter or a flow option, default the original
   until the deck needs what only the rebuild gives (faults in a box, graded
   columns, inactive parents), then switch the default with the evidence.

About two weeks to a green tree with both backends; the builds cost more than
the code.

## 4. Refining parts of a region, graded around wells

Two different things are wanted and both are worth having.

**Grading inside a box** exists: `N*FIN`/`H*FIN` give per-parent column widths
(Norne's 11 9 7 5 3 1 3 5 7 9 11 across the well cell, an 11:1 ratio inside one
parent). This is the other simulator's own near-well grading and is the right tool for a
vertical or near-vertical well in a box.

**Grading by distance to a line** (a deviated or horizontal well path, or a
fault trace) is not implemented in either backend. It means: level-0 cells
within distance d1 of the polyline get level 2, within d2 level 1, so the
refined region is an irregular tube, not a box. What it takes, in the
rebuild's terms and in order:

1. **A region, not a box, as the unit of refinement.** A level grid today is
   one box. Let a request carry the box's bounding extent plus a parent mask
   (which parents inside the extent are refined). The window resampler already
   masks refined cells (`GrdeclRefinement.cpp:188`, used for block MINPV), and
   the leaf assembler decides per parent whether it is refined
   (`LeafGridAssembler.cpp:144-150`, `boxOfCell`) and treats any unrefined
   neighbour as a coarse neighbour (`:530`). So an unmarked parent inside the
   extent becomes an ordinary coarse neighbour of the refined tube. The one
   piece that assumes a box side is the faulted-boundary window
   (`FaultedBoundaryFaces.cpp`, keyed by `(box, axis, side)`); it needs a
   per-boundary-face window instead. Everything else (corner pool, mosaic,
   ids, output, wells) is per cell already.
2. **A mark policy**: distance from cell centre to the polyline segments,
   thresholds per level, and a dilation of at least one coarse cell per ring
   so that each finer region is strictly interior to the next coarser one.
   The well path is available: deck trajectories, or the synthesized polyline
   through `COMPDAT` cells that the dynamic driver already builds. About a
   hundred lines in `AdaptiveCpGrid`, plus a flow option such as
   `--well-refine=PROD*:2,2,1:rings=1,2`.
3. **Nesting as the grading mechanism.** Ring k+1 is a child region nested in
   ring k. One nesting level exists (coarse, f1, f1·f2, e.g. 1, 2, 4). Deeper
   grading needs the recursive nested leaf (Phase C in `NESTED_LGR_PLAN.md`);
   the tree-walk cell emission is written, the constraint is the one-level
   guard. Nesting keeps every interface a conformal parent-child interface by
   construction, which is why it is preferred over touching boxes of
   different factor (those meet on edges and corners, which is refused).
4. **Later, the per-cell factor-2 octree with 2:1 balance** from
   `DESIGN-parallel-octree.md` sections 3 and 13. That is the general answer
   for dynamic front tracking and makes rings unnecessary, but it is a larger
   build than steps 1 to 3 and is not needed for well grading.

On the original backend, distance grading is reachable through successive
`adapt()` passes with per-cell marks, but only where no fault, pinch-out or
NNC is near the well, which in practice excludes most wells.

## 5. What to improve, in order

Static:

1. Done: host transmissibility is the default and deck connections inside a
   box are handled or refused. No known defect changes results on a field
   case any more.
2. Parallel restart (INIT done).
3. Region-mask requests (section 4 step 1) and the multi-level nested leaf.
   Both serve static grading and dynamic refinement.
4. Continue the upstream chain in `PR-PLAN.md`; the simulator and opm-common
   PRs need no grid change, and the section 3a restructure is the grid PR.

Dynamic:

1. Pore-volume-weighted restriction and the envelope scalars (`max`/`min`
   ops), with the hysteresis guard.
2. The `mark`/`adapt` facade on CpGrid backed by `AdaptiveCpGrid`, so
   `EnableGridAdaptation` in the model works without the restart-in-memory
   driver; keep the driver as the oracle.
3. Well-zone marks (section 4 steps 2 and 3).
4. Parallel: rank-interior adapt plus occasional redistribution from the
   retained corner-point description; migrate no refined state.

Housekeeping before any PR: `MPIPacker_backup.cpp`, `HypreSetup.hpp.orig`,
`flow/Testing/Temporary/`, `tests/test_blackoilprimaryvariables_tmp.cpp` and
the `.bak` test are stray and must not ship; the new `refinement/` headers
should acknowledge the Equinor/Ritorto lineage they depend on
(`lgr_rewrite_provenance.md` section 5).
