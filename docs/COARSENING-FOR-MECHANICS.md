# Corner-point coarsening, and a coarse mechanics grid

2026-09-22, status updated 2026-09-23. Companion to `COARSENING-BELOW-INPUT.md`
(coarsening for flow, route C) — this note is the geomechanics driver for the same
machinery, and it fixes the rules the coarsening has to obey. The geomech side of the
work lives in `~/Documents/OPM/opm_geomech`.

## Why

Flow and mechanics share one CpGrid. Every mechanics array is indexed by flow cell, and
`VemElasticitySolver` is built from `vanguard().grid()`
(`opm-flowgeomechanics/opm/geomech/GeoMechModel.hpp:58`). Two consequences:

- The mechanics runs on the flow model's thin, high-aspect cells. That is where VEM has
  been unstable, and it is the reason for the stabilization variants in
  `vem/MECHANICS_STABILITY_NOTES.md`.
- The mechanics runs on the fine grid in the side-, over- and underburden, where only
  the stiffness of the rock matters.

The aim is one general **corner-point coarsening**, used in two ways:

1. the whole model is coarsened in the padding, for flow and mechanics alike;
2. mechanics alone is coarsened further, e.g. merging thin caprock cells that flow must
   keep.

## Rules

- **Nesting.** Every coarse cell is a union of input cells. Between any two grids in the
  chain, two cells either coincide or one lies inside the other. There is never partial
  overlap. The mechanics grid is always a coarsening of the flow grid.
- **The coarse grid is a corner-point grid**, or is coarsened in a way consistent with
  corner-point: block boundaries lie on input pillars and layer surfaces, and there is no
  coarsening across faults.
- **Edge-conformal geometry**, both in the MINPV/PINCH processing that precedes
  coarsening and in the coarse grid itself.
- **Two grid objects** (flow, mechanics) for now. A view is a later refactor, behind the
  map interface.
- **Parallel:** the grids are partitioned so they correspond exactly. Every mechanics
  cell and all of its flow cells live on the same rank.
- **Output stays on the input/flow grid** for now.
- **Existing results must not change.** Everything is opt-in.

## Input: COARSEN

The GRID keyword (`opm-common/.../keywords/000_Eclipse100/C/COARSEN`; parsed, refused at
`UnsupportedFlowKeywords.cpp:81`) is one record per box:

```
COARSEN
-- I1 I2  J1 J2  K1 K2   NX NY NZ
    1  5   1 21   1 35    1  5  7 /   -- west sideburden: 5 cols -> 1, 21 rows -> 5, 35 layers -> 7
   17 21   1 21   1 35    1  5  7 /   -- east sideburden
    6 16   1 21   1  5   11 21  1 /   -- overburden above the core: 5 layers -> 1
/
```

The box I1–I2 × J1–J2 × K1–K2 (1-based, inclusive) becomes NX×NY×NZ coarse cells, split
as evenly as possible along each axis; an omitted NX/NY/NZ means 1. Boxes must not
overlap each other or a CARFIN box. (The exact rule the other simulators use for an
uneven split still needs checking.)

opm-common needs two changes: the definition has `"size": 1` and must become a
slash-terminated list, and NX/NY/NZ need defaults.

**Staging.** v1 puts the same records in a `"mech_grid"` block of the mechanics/fracture
parameter JSON (`"coarsen": [[1,5,1,21,1,35,1,5,7], …]`, with a per-axis shorthand
`"i_groups"`/`"k_groups"` for padding), so no parser change is needed. The final version
is deck keywords: `COARSEN` for flow and a sibling keyword with the same record syntax
for mechanics, applied on top of the flow coarsening so nesting holds by construction.

## Design

### One description, two builders

A `CoarseningSpec` (list of records) becomes a cell→block assignment. The validator
checks:

1. every block is a box;
2. no block contains a fault face — an interior face of the block where the two sides'
   ZCORN disagree, or where the face is split (the test in
   `LeafGridAssembler.cpp:359-420` is the model);
3. no deck NNC or pinch pair lies inside a block (`getInputNNC()`, `getPinchNNC()`);
4. no block crosses a boundary of an optional integer region array;
5. mechanics blocks are unions of flow blocks;
6. the sub-faces behind one coarse face are at most `max_subfaces`.

**B1, the grdecl route (v1).** Applies when the assignment can be written as a grdecl:

- a dropped pillar line is dropped along its whole length (every layer);
- layers may be grouped differently in each column. Columns with fewer groups are padded
  with zero-thickness cells, which the preprocessor skips (`preprocess.c:380-385`), and
  mismatched lateral faces become partial faces, exactly as at a throw;
- output: coarse COORD/ZCORN/ACTNUM plus `fineToCoarseCart`;
- built with `CpGrid::processEclipseFormat(const grdecl&, …, edge_conformal=true)`;
- covers full-column sideburden padding and vertical merging anywhere, including thin
  caprock.

**B2, the CpGridData merge (route C, v2).** Needed for **lateral coarsening of the
overburden above a laterally fine reservoir**: pillars run through all layers, so a
grdecl cannot express it. Merge each block's cells into one, drop interior faces, keep
one face per fine neighbour on the coarse–fine interface. For flow, this is also the core
of a future `COARSEN` in the vanguard.

### One consistent geometry: edge-conformal MINPV/PINCH, then coarsen

With flow and mechanics together, the preferred processing is `--edge-conformal=true`:
removed and thin cells are merged geometrically into their neighbours
(`processEclipseFormat.cpp:210-215`, `mergeMinPVCells`, `thin_cells_as_minpv`) instead of
bridged, and a leftover pinch NNC throws (`:231`). The result is one geometric model in
which removed cells have zero thickness.

**Coarsening applies to that processed geometry, never to the raw input.**

- The processed COORD/ZCORN/ACTNUM must be retained when coarsening is requested. Today
  `this->zcorn` is kept only when NNCs exist (`:216`) in upstream-style opm-grid, and
  `retained_cp_input_` only for LGR decks (`:358`) here. Both need a "retain when
  coarsening" flag.
- The coarse grid is built from it with `edge_conformal=true`, and MINPV is not applied
  twice.
- A collapsed cell is a zero-volume member of its block: it contributes nothing and needs
  no special rule.
- Mechanics coarsening requires `--edge-conformal=true` and refuses to start without it.
  The flow default is unchanged.

This also removes the MINPV "Owner is not a partition of unity" failures on the mechanics
side: mechanics never sees a grid with bridged gaps.

### Edge-conformal coarse geometry

Every coarse face lists every node on its edges, including nodes from a finer neighbour's
subdivision, so neighbouring faces share their edges exactly. B1 gets this from
`processEclipseFormat(…, edge_conformal=true)`. B2 must rebuild each coarse face polygon
from all sub-face nodes on its boundary, in order; the unit test checks that every edge is
shared consistently by the adjacent cells.

### Faces and nodes per cell

Too many nodes on a cell has caused instability, so the spec is constrained:

- neighbouring groupings must nest, with a size ratio of at most `r_max` (default 2)
  across any face;
- `max_subfaces` caps the fine faces behind one coarse face; violations are refused with
  the offending block named;
- where two coarse blocks meet with equal grouping the face is a single 4-node face —
  automatic in B1, merged in B2;
- VEM's `identify_star_point` (`vem/vem.cpp:1486-1520`) assumes planar faces, so the
  report gives the worst face non-planarity of the coarse cells, and blocks beyond a
  tolerance are refused or split.

### Map between the grids

```
mechCell(flowCell); children(mechCell) + bulk-volume weights;
restrict(flowVec) -> mechVec; prolong(mechVec) -> flowVec
```

Built from `globalCell()` on both grids plus `fineToCoarseCart`, the pattern of
`CpGrid::leafPartitionFromLevelZero` (`CpGrid.cpp:773-800`). It operates on interior
cells, followed by one cell communication on the receiving grid. Everything in geomech
goes through this interface, so a later view implementation can replace the second grid
without touching the consumers.

### Exact parallel correspondence

`GenericCpGridVanguard::setExternalLoadBalancer` is installed in the geomech mains. On
rank 0 it builds the serial mechanics grid, partitions it weighted by child count, and
returns `flowParts[c] = mechParts[parent(c)]`. The mechanics grid is then distributed
with `loadBalance(mechParts, ownersFirst, addCorners=true)`; CpGrid always adds one
overlap layer (`CpGrid.cpp:229,466-475`). Two fatal startup checks: every flow interior
cell has its parent interior on the same rank, and the mechanics grid passes the node
partition-of-unity check. Note that the external-balancer path skips the Zoltan well
handling, so well columns have to be kept together explicitly.

## Status (2026-09-23)

**P0 and P1 are done.**

- Test decks: `opm_geomech/bcmech/opm-flowgeomechanics/data/coarsen_tests/`
  (`make_coarsen_tests.py`, its README, T1_PAD_FINE / T1_PAD_COARSE / T2_CAPROCK and the
  two specs). All three run with `flow_energy_geomech`; at 90 days the fracture grows
  from its 74.7 m² seed to 3880 m². Coarsening the padding for flow and mechanics
  together moves the stress at the well by 0.6 % and the fracture volume by 1.0 %, and
  halves the run time.
- Library: `opm/grid/cpgrid/coarsening/CornerPointCoarsening.{hpp,cpp}`, the CLI
  `examples/coarsen_grdecl.cpp`, and `tests/cpgrid/coarsening_test.cpp` (12 cases,
  passing). All four are registered in `CMakeLists_files.cmake`. The library is
  array-in / array-out (`Grdecl` mirrors `Refinement::RefinedBlockGrdecl`) and depends
  only on `RefinementRequest.hpp`, so it also copies into upstream-style opm-grid.
- Acceptance: coarsening T1_PAD_FINE with the T1 records reproduces T1_PAD_COARSE's
  COORD, ZCORN and ACTNUM exactly (max difference 0). Coarsening T2_CAPROCK with the
  mechanics-only records gives that same grid, i.e. the thin layers are merged away
  exactly.
- `refinementBackToFine()` returns the CARFIN-style requests that refine the coarse grid
  back to the fine one — 26 boxes for T1, with the 1:1 core correctly left out. Index-wise
  the fine grid is an LGR of the coarse grid. Geometrically, a CARFIN would subdivide
  evenly, so an exact rebuild needs a builder that takes child geometry from the input
  (the same gap `COARSENING-BELOW-INPUT.md` notes for its route B).
- Confirmed limitation, now a test: a request that coarsens laterally over part of the
  k-range is refused, because pillars run through every layer. Lateral coarsening of the
  overburden above a laterally fine reservoir therefore needs B2, for mechanics as much
  as for flow.

Not yet done: wiring into a CpGrid build (`processEclipseFormat` on the coarse grdecl),
the retain flag for the processed geometry, property upscaling in the CLI, and P3 onward.

## Phases

**P0 — test decks** (`opm-flowgeomechanics/data/coarsen_tests/`, generator script).
T1: padded SIMPLE from `SIMPLE_MECH_NX_11_NY_11_NZ_25_FRAC_SEQ.DATA`, starting from
`examples/padmodel.cpp` (top/bottom exist; side padding to add): geometrically growing
lateral padding, over- and underburden, BCCON moved to the new outer faces, IJK of
WELSPECS/COMPDAT/WSEED shifted. The generator also writes **T1-coarse** directly — the
exact geometric reference for the tool. T2: T1 with the top reservoir layer split into
thin low-perm layers (3 × 0.5 m gives aspect ≈ 360 at 181 m). Later T1f: a ZCORN-tilted
variant with one fault.

**P1 — coarsening library and CLI (B1).**
`opm/grid/cpgrid/coarsening/CornerPointCoarsening.{hpp,cpp}`, depending only on the
grdecl type and `EclipseGrid` so the files copy into upstream-style opm-grid unchanged.
`CoarseningSpec`, the validator, B1, a report. CLI `coarsen_grdecl` runs edge-conformal
MINPV/PINCH first where the deck has it, coarsens the processed geometry, and writes a
coarse deck (COORD/ZCORN/ACTNUM), upscaled properties (PORO pore-volume weighted, PERM
arithmetic along / harmonic across layers, mechanics moduli Voigt–Reuss on the Lamé
parameters, regions required uniform), IJK-remapped COMPDAT/WSEED/BCCON, and
`fineToCoarseCart`.

**P2 — test 1 run**, single grid, no simulator change: T1 fine vs T1-coarse with
`flow_energy_geomech`, serial and np=4. Compare core stress, BHP and fracture growth.
This sets the tolerance band for the two-grid path.

**P3 — two-grid mechanics path** in opm-flowgeomechanics: a `MechGridContext`, a
`mechGrid()` accessor used by the solver construction and the mechanics loops in
`GeoMechModel.hpp`, load restriction, material upscaling, STRESSEQUIL and
`nodesAtBoundary` on the mechanics grid, and prolongation for every accessor taking a
flow index. Output stays on the flow grid; VTK vertex displacement is copied where the
nodes coincide and interpolated trilinearly otherwise. Without coarsening, no second grid
is built and nothing changes.

**P4 — test 2 run:** T2 with flow fine and mechanics coarsened. Compare the single fine
grid (expected to struggle in VEM), the two-grid run and the fully coarse run; serial,
then np = 2/4/8.

**P5 — B2 merge pass:** lateral overburden coarsening, first for mechanics, then the flow
`COARSEN` keyword reusing the same builder (simulator-side items in
`COARSENING-BELOW-INPUT.md`). Move the mechanics input to the deck keyword.

**P6 — LGR near injection** once geomech is on gridrefined: the same CARFIN in both
grids, inside the 1:1 region, each box on one rank and off the overlap
(`ConformingBlockBuilder.cpp:69-108`).

Later: cut the padding out of flow; flow consistency for MINPV/PINCH NNCs in thermal
decks; replace the two grids with a view.

## Verification

0. Current results unchanged: `ctest -R REGTEST_geomech` 9/9, and bit-identical
   VTK/UNRST for SIMPLE FRAC_SEQ and CASE_REFINE, serial and np=2. The opm-grid changes
   are opt-in, so the grid build without coarsening stays bit-identical, LGR decks
   included.
1. P1 unit tests: identity round trip; exact reproduction of T1-coarse's geometry; volume
   sums; edge-conformity; a fault inside a block refused; `max_subfaces` enforced;
   coarsening an edge-conformal MINPV-processed deck absorbs collapsed cells and produces
   no NNC; `examples/test_partition_of_unity.cpp` passes on the output.
2. Identity map in P3: regtests 9/9, solution bit for bit.
3. T1 fine vs coarse, and T1 through the two-grid path with padding-only coarsening: core
   stress within the P2 band.
4. T2: the two-grid run converges with fewer mechanics iterations than the fine run;
   caprock and reservoir stress within band against the fully coarse run.
5. Prime directive: `frac_area.py` and `WWIRFRAC/WWIR` on T1/T2 must not show fracturing
   suppressed by the coarsening.
6. Parallel np = 2/4/8: both correspondence checks and the partition-of-unity check pass
   on the mechanics grid.
