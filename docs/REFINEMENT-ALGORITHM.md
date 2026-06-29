# LGR refinement algorithm (opm-gridrefined)

How the corner-point refinement builder turns a coarse `Dune::CpGrid` plus a set
of CARFIN-style block requests into a refined level hierarchy and a single
conforming leaf view. Static path first (the production path), then a section on
the dynamic (`AdaptiveCpGrid`) path.

All references are `file:line` into `opm/grid/cpgrid/...` at the state of branch
`adaptive-cpgrid-class`. The entry point is
`CpGrid::addLgrsUpdateLeafView` → `Refinement::builder()->build()`
([CpGrid.cpp:1802-1823](../opm/grid/cpgrid/CpGrid.cpp)); the default backend is
`ConformingBlockBuilder`. Every write into the grid's multilevel state goes
through the single befriended accessor `GridStateWriter`.

---

## 0. The pipeline at a glance

For each block request `(name, parentGridName, cellsPerDim, startIJK, endIJK)`:

| Stage | What | Where |
|---|---|---|
| 1. Plan / validate | reject overlapping or incompatibly-touching boxes | `ConformingBlockBuilder.cpp:146-216` |
| 2. Sub-pillars | bilinear interpolation of new COORD pillars inside the block | `GrdeclRefinement.cpp:84-110` |
| 3. Refined ZCORN | per-parent-cell trilinear resampling of the 8 zcorn onto the sub-lattice + ACTNUM inheritance | `GrdeclRefinement.cpp:112-180` |
| 4. Window process | run the corner-point preprocessor on the refined grdecl window → a level `CpGridData` | `LevelGridAssembler.cpp:54-84` |
| 5. Parent relations | map each refined cell → (parent cell, child lattice index) | `LevelGridAssembler.cpp:86-131` |
| 6. Leaf stitch | merge level-0 + all level grids into one conforming leaf; cell/corner/face numbering; ids | `LeafGridAssembler.cpp` |
| 7. (opt) edge-conformal | insert hanging nodes into unrefined face edges for VEM | `EdgeConformal.cpp:44-157` |

The decisive design choice: **stage 4 reuses the existing corner-point
preprocessor** (`processEclipseFormat`/`process_grdecl`) on a *refined grdecl
window*, rather than refining each cell with a per-cell trilinear map. Faults and
pinch-outs inside the block are therefore matched by the same battle-tested
machinery that builds level zero — no special code.

---

## 1. Static refinement — geometry of one level grid

### 1.1 Sub-pillars (stage 2)

The block's refined corner geometry is built on **straight sub-pillars**
interpolated *bilinearly* from the four surrounding original COORD pillars. For
refined lateral position `(ir, jr)` with in-parent fractions `a, b ∈ [0,1]`
([GrdeclRefinement.cpp:99-108](../opm/grid/cpgrid/refinement/GrdeclRefinement.cpp)):

```cpp
const double* p00 = parentPillar(ci,   cj);    const double* p10 = parentPillar(ci+1, cj);
const double* p01 = parentPillar(ci,   cj+1);  const double* p11 = parentPillar(ci+1, cj+1);
for (int comp = 0; comp < 6; ++comp)           // 6 = (x,y,z) top + (x,y,z) base of a COORD line
    sub[comp] = (1-a)*(1-b)*p00[comp] + a*(1-b)*p10[comp]
              + (1-a)*b*p01[comp]     + a*b*p11[comp];
```

On a parent-pillar position the weights collapse and the parent pillar is
reproduced exactly. Output COORD has `(nx_ref+1)·(ny_ref+1)` pillars; `i` runs
fastest throughout.

### 1.2 Refined ZCORN and ACTNUM (stage 3)

Each refined cell corner gets a **trilinear** resample of its parent cell's 8
zcorn values, in the lateral fractions `(a,b)` and the vertical fraction `c`
([GrdeclRefinement.cpp:142-153](../opm/grid/cpgrid/refinement/GrdeclRefinement.cpp)):

```cpp
double z = 0.0;
for (int pk=0; pk<2; ++pk){ double wk=(pk==0)?(1-c):c;
 for (int pj=0; pj<2; ++pj){ double wj=(pj==0)?(1-b):b;
  for (int pi=0; pi<2; ++pi){ double wi=(pi==0)?(1-a):a;
   z += wi*wj*wk * parentZ(2*ci+pi, 2*cj+pj, 2*ck+pk); }}}
out.zcorn[refinedZIndex(2*ir+di, 2*jr+dj, 2*kr+dk)] = z;
```

This is the **corner-point-native** refinement: refined corners lie on the
straight sub-pillars. It coincides with the old per-hexahedron trilinear map
**only for vertical pillars**; on inclined pillars the two differ slightly (both
valid — this chooses ECLIPSE LGR semantics). zcorn *jumps* between columns
(faults) and *collapses* (pinch-outs) inside the block survive automatically,
because each child corner interpolates its 8 parent corners independently
([GrdeclRefinement.hpp:53-58](../opm/grid/cpgrid/refinement/GrdeclRefinement.hpp)).

ACTNUM is inherited per child from the covering parent cell
([GrdeclRefinement.cpp:161-180](../opm/grid/cpgrid/refinement/GrdeclRefinement.cpp));
a constraint check later rejects active children of inactive parents.

### 1.3 Window processing (stage 4)

The refined `(dims, coord, zcorn, actnum)` is wrapped in a `grdecl` and fed to the
preprocessor to produce the level `CpGridData`
([LevelGridAssembler.cpp:64-84](../opm/grid/cpgrid/refinement/LevelGridAssembler.cpp)):

```cpp
level->processEclipseFormat(raw, /*ecl*/nullptr, nnc,
    /*remove_ij_boundary=*/false, /*turn_normals=*/false,
    /*pinchActive=*/false, /*tol=*/0.0, /*edge_conformal=*/false);
```

This is where faults and pinch-outs **interior to the block** become real split /
collapsed faces — `findconnections` does it, exactly as on level zero. The level
grid is built on a **self (local) communicator** so the rank-local refinement does
no collectives (see §3).

### 1.4 Parent relations (stage 5)

Each refined compressed cell is mapped back to its parent and its **child lattice
index within the parent**
([LevelGridAssembler.cpp:107-125](../opm/grid/cpgrid/refinement/LevelGridAssembler.cpp)):

```cpp
const int refinedCart = level->globalCell()[cell];
const int ir =  refinedCart % rdx, jr = (refinedCart/rdx)%rdy, kr = refinedCart/(rdx*rdy);
childToParent[cell] = { parentLevel, parentCompressed[ ci + nx*cj + nx*ny*ck ] };
idxInParent[cell]   = (ir%rx) + (jr%ry)*rx + (kr%rz)*rx*ry;   // CARFIN-local position
```

`child_to_parent_cells_`, `cell_to_idxInParentCell_`, `cells_per_dim_`, `level_`
and the level's `logical_cartesian_size_` are set via `GridStateWriter`. These are
the same `CpGridData` members the simulator stack reads (`geometryInFather`,
`LevelCartesianIndexMapper`, output).

---

## 2. Static refinement — leaf stitching and numbering

The leaf (`data_.back()`) is a **single conforming grid** merging level zero with
every level grid. `assembleLeafGrid`
([LeafGridAssembler.cpp](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)) does
this in one pass. Three numbering problems: cells, corners, faces.

### 2.1 Cell numbering

Leaf order = **level-zero order, each refined parent replaced in place by its
children** (children ordered by `idxInParent`)
([LeafGridAssembler.cpp:289-317](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)):

```cpp
for (int c = 0; c < numCells0; ++c) {
    if (boxOfCell[c] < 0) { leafIdxOfCell0[c] = leafCells.size(); leafCells.push_back({0,c}); }
    else for (int child : box.childrenOfParent[c]) {        // sorted by idxInParent, lines 187-198
        leafIdxOfLevelCell[b][child] = leafCells.size(); leafCells.push_back({b+1, child}); }
}
```

`leaf_to_level_cells_` (`{level, indexInLevel}` per leaf cell) and
`child_to_parent_cells_` / `parentToChildren` are populated from this; ids route
through `leaf_to_level_cells_` (§2.5).

### 2.2 Corner numbering — the shared corner pool (design D1)

The leaf corner vector **starts as all level-zero corners, indices preserved**;
refined corners are appended. A refined corner that lands on a **parent-lattice
corner** is identified with the level-zero corner *through its parent cell* — a
**per-cell** test, so a fault inside the block (which gives geometrically
coincident points different lattice keys) still identifies correctly
([LeafGridAssembler.cpp:200-224](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)):

```cpp
const int ii=pos%rx, jj=(pos/rx)%ry, kk=pos/(rx*ry);          // child position in parent
for (int corner=0; corner<8; ++corner){
  int di=corner&1, dj=(corner>>1)&1, dk=(corner>>2)&1;
  if ((ii+di)%rx==0 && (jj+dj)%ry==0 && (kk+dk)%rz==0){        // lands on a parent corner
    int parentCorner = cellToPoint0[parent][(ii+di)/rx + 2*((jj+dj)/ry) + 4*((kk+dk)/rz)];
    box.cornerEquiv[cellToPointL[cell][corner]] = parentCorner;
}}
```

Non-lattice refined corners are appended, **deduplicated by exact coordinate**
([:249-285](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)) — corners shared
between two boxes with equal subdivision coincide bitwise because the resampling
arithmetic is identical, so the same pool index *is* the same corner. No
corner-identity layer is needed (this was the largest, most fragile part of the
old implementation).

### 2.3 Face / intersection numbering — mosaic replacement

A level-zero face is **dropped** if any adjacent cell is refined
([:319-334](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)); it is replaced
by the **mosaic of refined boundary faces**. Each refined boundary face is paired
with the coarse neighbour it abuts (`mosaicOutside`), so:

- the refined faces become **interior, two-sided** faces in `face_to_cell_`;
- the coarse neighbour accumulates many sub-faces → a **polyhedral cell with >6
  faces** in `cell_to_face_`, while its `cell_to_point_` stays 8 corners.

Before building the mosaic, `outsideNeighborOf`
([:336-403](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)) verifies the
parent boundary face is a single, full, non-faulted face (its corner set must
equal the parent's four lattice corners on that side); otherwise the side is
flagged `kFaultedSide` and rebuilt from the processor (§2.4, case 4). Finally
`face_to_cell_`, `face_to_point_` (remapped through the corner pool), `face_tag_`,
`face_normals_` are written and `cell_to_face_` is built as the inverse
([:831-928](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).

### 2.4 The particular boundary cases

The leaf assembler resolves a refined boundary face by *what it abuts* — there is
no separate "top vs side" code path; the axis (`0/1/2`) and side (`±1`) are
derived from the face tag, and the four cases are:

1. **Refined → coarse neighbour (the common top / bottom / side case).** Neighbour
   unrefined → `mosaicOutside = leafIdxOfCell0[neighbour]`; the coarse cell becomes
   a >6-face polyhedron tiled by the refined sub-faces
   ([:507-510](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)). This is the
   ordinary LGR boundary on every face (top, bottom, the four sides).

2. **LGR–LGR, equal subdivision (face-sharing).** Two boxes meet on a shared face
   with matching in-face factors → boundary faces have identical corner sets; the
   owner box emits the leaf face, the partner maps onto it and supplies its cell as
   the other side ([:511-535](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).

3. **LGR–LGR, compatible (multiple) subdivision.** The coarser side's interface
   face is tiled by the finer side's sub-faces (LGR_GAPS A2): finer box emits
   sub-faces referencing the coarser covering child; coarser interface cells become
   >6-face hexes ([:536-571](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).

4. **Fault at the LGR boundary (LGR–fault).** When a fault crosses a parent
   boundary face, **all refined faces on that side are suppressed and the whole
   side is rebuilt** from the corner-point processor (§2.6,
   [:583-807](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).

### 2.5 IDs (design D3) and `corner_history_`

Leaf entity ids delegate to the **birth-level** entity, via two maps the assembler
fills: `leaf_to_level_cells_` for cells
([:935-1045](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)) and
`corner_history_` (`{birthLevel, indexThere}`) for corners
([:235-285](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)). Level-zero
entities keep `{0, i}` (so unrefined runs are bit-identical); refined entities born
in box `b` get `{b+1, indexInBox}`; identified/deduped corners inherit the entry
they fold into.

The **cell id value** itself is construction-stable (no `insertIdSet` winner
selection): `CpGridData::stableCellId()` packs `(parentCartesian, childIndex)` into
a tagged 64-bit integer (§3.2).

### 2.6 Faults at the LGR box boundary (detail)

`faultedBoundaryConnections`
([FaultedBoundaryFaces.cpp:37-185](../opm/grid/cpgrid/refinement/FaultedBoundaryFaces.cpp))
builds the split faces for one faulted `(box, axis, side)`:

1. **Window**: the box + a one-cell coarse shell on `side` + a one-cell halo in the
   two perpendicular axes (so a throw that lands outside the box footprint is
   captured) ([:51-74](../opm/grid/cpgrid/refinement/FaultedBoundaryFaces.cpp)).
2. **Refine + process**: refine the window to `cellsPerDim`, run `process_grdecl`
   (`pinchActive=1`) — which **splits faces at the throw**
   ([:76-94](../opm/grid/cpgrid/refinement/FaultedBoundaryFaces.cpp)).
3. **Harvest**: keep processed faces of the right tag whose box-side cell lies on
   the boundary layer; classify the *other* side as coarse-neighbour-Cartesian +
   sub-position (which identifies the neighbour's child when the neighbour is itself
   refined → box↔box faulted interface), and record the real polygon nodes
   ([:99-181](../opm/grid/cpgrid/refinement/FaultedBoundaryFaces.cpp)).

So unlike the conforming case (one refined face ↔ one coarse neighbour), a faulted
boundary cell can connect to **several** coarse neighbours with real split-face
geometry. The leaf assembler emits these as synthetic faces, deduping nodes against
the corner pool.

### 2.7 Edge-conformal post-pass (optional, VEM)

The leaf is **face-conformal but not edge-conformal**: a coarse cell touching the
LGR only along an edge keeps its 4-node face while refined corners sit on that
edge. `edgeConformalizeLeaf`
([EdgeConformal.cpp:44-157](../opm/grid/cpgrid/refinement/EdgeConformal.cpp)) closes
this — analogous to `make_edge_conformal` — by, for every face edge `(a,b)`,
spatially hashing corners and inserting any corner that projects strictly onto the
segment (within `tol = 1e-9·diag`), sorted by edge parameter, into the face's node
list. Only `face_to_point_` changes; no new cells or corners. It is gated by the
`edgeConformal_` flag (default **off**;
[ConformingBlockBuilder.cpp:366-368](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp))
— TPFA does not need it.

---

## 3. Parallel indexing

### 3.1 Rank-interior model and the two paths

A box is classified per rank as **Owned** or **Absent**
([ConformingBlockBuilder.cpp:60-105](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp)):
all its cells local-and-interior → Owned; none present → Absent; anything in
between (box crosses a rank/overlap boundary) → throws. There are two regimes:

- **refine-after (`distributed`)**: grid already scattered. The **owning rank
  refines**; other ranks carry an **empty placeholder** level grid (correct
  Cartesian dims, zero cells —
  [LevelGridAssembler.cpp:142-161](../opm/grid/cpgrid/refinement/LevelGridAssembler.cpp)).
  Classification is by partition type (`classifyBox`).
- **refine-before-redistribute (`refineBefore`)**: full global grid on rank 0 only;
  classify by cell *presence* (`boxCellPresence`), rank 0 refines the whole grid
  serially, then the refined leaf is distributed.

Refinement runs on a **self communicator** so it does no collectives; the world
communicator is restored on the new grids afterwards
([ConformingBlockBuilder.cpp:230-244, 371-382](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp)).

**Broadcast of retained input.** In a distributed run only rank 0 holds the
undistributed COORD/ZCORN; it is broadcast so every rank can resample box geometry
([CpGrid.cpp:1771-1800](../opm/grid/cpgrid/CpGrid.cpp)). The broadcast is entered on
`size>1` unconditionally to keep the collective symmetric (a `!retained` guard would
deadlock the refine-before path).

**Collective-safe errors.** A per-rank failure (e.g. `classifyBox` rejecting a box)
is caught, agreed across ranks with a single `cc.max`, and re-thrown symmetrically
([ConformingBlockBuilder.cpp:332-355](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp))
— otherwise the throwing rank would abandon the survivors in the leaf-assembly
collectives and deadlock.

### 3.2 Construction-stable ids (no sync)

`stableCellId()` packs ids so they agree across ranks **by construction**
([CpGridData.cpp:92-118](../opm/grid/cpgrid/CpGridData.cpp)):

```cpp
constexpr int childBits = 20;  constexpr std::int64_t refinedTag = std::int64_t(1) << 62;
// unrefined cell: ids[c] = global_cell_[c];                       (tag bit clear)
// refined cell:   ids[c] = refinedTag | (parentCart << childBits) | childIndexInParent;
```

Because parent Cartesian indices (from the synchronized level-0 grid) and child
lattice indices are deterministic and partition-independent, **no
`syncDistributedGlobalCellIds` is required** — it is now a no-op
([CpGrid.cpp:1727-1730](../opm/grid/cpgrid/CpGrid.cpp)); new level/leaf grids are
just registered via `insertIdSet`
([CpGrid.cpp:1828-1833](../opm/grid/cpgrid/CpGrid.cpp)).

Supporting pieces: `poisonRefinedGlobalCell`
([CpGridData.cpp:120-131](../opm/grid/cpgrid/CpGridData.cpp)) stamps refined cells'
`global_cell_` with a sentinel so the parent Cartesian index can't be mistaken for
a real cell key; and `cell_to_idxInParentCell_` is scattered
([CpGridData.cpp:~1617](../opm/grid/cpgrid/CpGridData.cpp)) so refined siblings
(which share a parent Cartesian index) stay distinct for output collection in the
flat refine-before leaf.

---

## 4. Nested LGR (LGR-on-LGR)

A request with `parentGridName != "GLOBAL"` refines a *parent LGR* rather than
level zero. The builder detects nesting and routes to a separate
`assembleNestedLeafGrid` so GLOBAL-parent decks stay byte-identical
([ConformingBlockBuilder.cpp:252-257, 360-365](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp)).

Key points:

- **Geometry threading.** Each built level's resampled `(dims, coord, zcorn,
  actnum)` is carried forward as a `LevelGeom`
  ([LeafGridAssembler.hpp:83-89](../opm/grid/cpgrid/refinement/LeafGridAssembler.hpp));
  a child refines its **parent LGR's own Cartesian geometry**, reusing the exact
  single-level machinery (a parent LGR level grid is itself Cartesian in its local
  space).
- **Containment constraint** (one level deep, fully interior): the child's
  parent-local IJK must satisfy `1 ≤ start` and `end ≤ parentDim−1` in every
  direction; grandchildren and boundary-touching children throw
  ([LeafGridAssembler.cpp:1122-1172](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).
- **Parallel.** A contained child rides on whichever rank owns its parent box; it
  cannot be classified against level zero (its IJK is parent-local), so it
  **inherits the parent box's presence**
  ([ConformingBlockBuilder.cpp:301-313](../opm/grid/cpgrid/refinement/ConformingBlockBuilder.cpp)),
  and parent-before-child ordering guarantees the parent is already classified.
- **Leaf assembly** uses the same corner-pool identification (against the parent
  grid) and a recursive **tree-walk** cell emission (a refined cell is replaced by
  its children at any depth)
  ([LeafGridAssembler.cpp:1184-1294](../opm/grid/cpgrid/refinement/LeafGridAssembler.cpp)).

---

## 5. Dynamic refinement

The current dynamic entry, `AdaptiveCpGrid`
([AdaptiveCpGrid.cpp](../opm/grid/cpgrid/AdaptiveCpGrid.cpp)), is the
**correctness-oracle** form of dynamic refinement, not yet the fast in-place
adapter. It keeps **Layer A** (the persistent macro corner-point description) and a
**Layer B** `Dune::CpGrid`; `markBox`/`markCell` queue CARFIN-equivalent boxes, and
`adapt()` registers a `ConformingBlockBuilder` and drives the *same*
`addLgrsUpdateLeafView` static path described above. Hence each `adapt()` is a full
conforming rebuild and the refined leaf is bit-identical to the static-LGR grid —
the discretisation (and the simulation) are identical.

What this establishes and what is deliberately deferred
([AdaptiveCpGrid.hpp:32-62](../opm/grid/cpgrid/AdaptiveCpGrid.hpp),
[DESIGN-parallel-octree.md](DESIGN-parallel-octree.md) §10-14):

- **Established:** the `mark → adapt → equivalent-leaf` seam; static/adaptive
  equivalence; Layer A as the persistent source of truth.
- **Deferred — fast local adapt.** Instead of rebuilding the whole leaf, refine
  *in place*: append refined cells + free-list the replaced parent, touching only
  the marked region. The §2 corner pool and materialized leaf topology become a
  **per-rank derived cache** (owned+ghost only), rebuilt incrementally from Layer A.
- **Deferred — re-adapt / factor-2 levels.** Repeated adaptation of an
  already-refined grid (the current first cut refines level zero once and throws on
  re-adapt, [AdaptiveCpGrid.cpp:80-86](../opm/grid/cpgrid/AdaptiveCpGrid.cpp));
  dynamic levels with 2:1 balance and coarsening.
- **Deferred — forest-of-octrees representation.** Refined corners reconstructed on
  demand from sub-pillars (`root pillars + octant code`) and never persisted or
  communicated; the macro `RetainedCornerPointInput` + the forest are the only
  persistent/communicated state, which is what makes parallel migration cheap.
- **Deferred — parallel root-tree migration / repartitioning** of an already-refined
  grid.

The same numbering principles carry over unchanged in the dynamic design: cell
order = level-0 order with parents replaced by children; the shared corner pool
(D1); mosaic faces at refinement boundaries; and the **construction-stable ids
(D3)** — which are what make incremental and parallel adaptation tractable, since
ids need no synchronization after a local refine or a repartition.

---

## Appendix — file map

| File | Role |
|---|---|
| `refinement/RefinementBuilder.{hpp,cpp}` | the `Builder` seam + process-wide registry |
| `refinement/GrdeclRefinement.{hpp,cpp}` | stages 2-3: sub-pillars + trilinear zcorn/actnum |
| `refinement/LevelGridAssembler.{hpp,cpp}` | stages 4-5: window process + parent relations (and empty placeholder) |
| `refinement/LeafGridAssembler.{hpp,cpp}` | stage 6: leaf cell/corner/face numbering, mosaic, ids, nested |
| `refinement/FaultedBoundaryFaces.{hpp,cpp}` | split faces at a faulted LGR boundary |
| `refinement/EdgeConformal.{hpp,cpp}` | stage 7: VEM edge-conformal post-pass |
| `refinement/ConformingBlockBuilder.{hpp,cpp}` | orchestrator: validate, parallel classify, drive stages |
| `refinement/GridStateWriter.{hpp,cpp}` | single befriended writer of CpGridData multilevel state |
| `cpgrid/AdaptiveCpGrid.{hpp,cpp}` | dynamic mark→adapt controller (oracle path) |
| `cpgrid/CpGridData.cpp` | `stableCellId`, `poisonRefinedGlobalCell`, idx-in-parent scatter |

*Generated as a code-reading aid; not committed.*
