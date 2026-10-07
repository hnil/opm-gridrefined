# REFCELLS: refining part of a CARFIN box (design note, 2026-10-07)

## Proposal

Inside a `CARFIN ... ENDFIN` block, an optional integer array `REFCELLS` over the block's
parent cells says which of them are refined (1) and which stay unrefined (0). Default: all 1,
which is today's behaviour.

```
CARFIN
 'LGR1'  10 19  20 29  1 5   30 30 10 /
REFCELLS
 -- 10 x 10 x 5 parent cells, I fastest
 ...
/
ENDFIN
```

`REFCELLS` is an OPM extension; the reference has no such keyword. A deck using it does not
run elsewhere, so it is accepted only where everything it touches supports it, and is refused
with a clear message otherwise.

## Rules for a first version

1. **No overlapping CARFIN boxes** (already enforced) and **no touching boxes** that carry
   `REFCELLS`: a mask next to another box's boundary gives a three-way interface.
2. **No nested LGR** whose parent is a box with `REFCELLS`.
3. **No fault on an interface between a refined and an unrefined parent inside the box.**
   The box boundary already handles faults (`FaultedBoundaryFaces`); the interior case is
   phase 2.
4. A `REFCELLS` that refines no cell is an error (the CARFIN would be empty); one that
   refines every cell is the plain CARFIN.

Not required: a connected refined region, or a convex one. Checkerboard masks are legal; they
are the worst case for the interface code and make a good test, not a target.

## Two ways to build it

### A. Split into sub-boxes at parse time (not recommended)

Decompose the mask into maximal boxes, as `AdaptiveCpGrid::mergeMarksIntoBoxes_` already does
for cell-by-cell marks, and refine each as its own LGR. The grid side works today: adjacent
boxes with the same subdivision are supported by the builder.

What it costs: one CARFIN becomes several LGRs, and everything keyed by LGR name or level sees
them separately. That includes `COMPDATL` addressing (a local IJK has to be mapped to the right
sub-box), the EGRID/INIT LGR sections, LGR summary vectors, the restart's LGR sections,
`HOSTNUM`, and `Carfin::refinedColumns`. Making them look like one LGR again is much of the work
of B, done in more places. It is useful only as a quick prototype.

### B. One LGR per CARFIN, unrefined parents' children inactive (recommended)

Build the box's level grid exactly as today, over every parent in the box. Give the children of
a `REFCELLS = 0` parent `ACTNUM = 0` in the refined description, as block `ACTNUM` and block
`MINPV` already do (`BlockRefinement::minpvRemoved`, applied in `refineBlock`). On the leaf,
**keep that parent as an unrefined cell** instead of replacing it.

What stays the same: the LGR's name, its lattice and dimensions, `COMPDATL` indexing, the
output layout (the masked parents' children are simply inactive in the LGR section), `HOSTNUM`,
graded refinement (`NXFIN`/`HXFIN`: a masked parent still owns its lattice columns), and the
rank-interior rule for parallel runs (the box, masked parents included, stays on one rank).

The rest of this note is about B.

## What has to change

### 1. Leaf assembly (opm-gridrefined; the hardest part)

Today every face between an unrefined and a refined cell is on the box boundary, and the leaf
assembler assumes so:

- `LeafGridAssembler.cpp`: `boxOfCell` marks every parent in a box as replaced by its children.
  It has to become "refined parent" (box and mask). The masked parent is then a source cell from
  level zero, like any cell outside a box.
- `outsideNeighborOf` (same file) finds the unrefined neighbour of a box-side child face from the
  parent lattice. With a mask, a level-grid face whose neighbour is an inactive child of a masked
  parent is such a face too, on any side, at concave corners, around holes, and in K: a masked
  parent between refined parents above and below.
- The box-boundary face mosaic (one unrefined face matched to several child faces) is built per
  box side. It has to be built per (masked parent, side) pair instead. The corner pool already
  maps refined corners that sit on a parent corner to the level-zero corner (`cornerEquiv`),
  so the shared nodes match.
- `FaultedBoundaryFaces` (`faultedBoundaryConnections(..., axis, side)`) processes one box side
  against its unrefined shell. Rule 3 keeps faults out of the interior interfaces in phase 1;
  phase 2 generalises it to a single parent face.
- Pinch-outs: `boxPinchPairs` (`LevelGridAssembler.cpp`) keeps level-zero pinch pairs inside the
  box, and the leaf's pinch-neighbour rule (an open face plus a pinch face in the same column)
  handles the box top and bottom. Pairs where one end is a masked parent become pairs between an
  unrefined cell and refined cells: the same situation as a pinch-out across the box boundary,
  which the `CARFIN_PINCH_*_ACROSS` decks cover. To be tested, not rewritten.

Test oracle: `refined_structure_comparison_test` builds the same grid directly from the
refined corner-point description. A masked box must give the same cells and connections as the
refined description with the masked region replaced by the parent cells. That oracle grid is not
a corner-point grid, so the comparison is against the refined description with those children
merged (the coarsening code's `processEclipseFormatCoarsened` can build it).

### 2. opm-common

- Parse `REFCELLS` in the CARFIN block, next to block `ACTNUM` (block keywords are already
  scanned for `FieldProps::lgrBlockValues`).
- `EclipseGridLGR`: the children of a masked parent are inactive (as `removeBlockCells` does),
  but the parent stays active in the global grid. Today a block `ACTNUM` that empties a parent
  is refused (`throwIfHostEmptied`); with `REFCELLS = 0` that is the intended result.
  `inheritActiveCellsFromFather` and the LGR's active-index maps follow.
- The LGR's PORV and the INIT arrays only cover active children, so masked parents drop out
  of the LGR section automatically.
- `COMPDATL` into a masked parent's child: a clear error (the cell is not active).
- A predicate `EclipseGrid::isRefined(globalIndex)` (box membership and mask) for the next
  point.

### 3. "Inside a box" becomes "refined" (all modules)

Several checks ask whether a cell is inside a box when they mean refined. With a mask, a
masked parent is inside a box but not refined, and has to behave as an ordinary cell:

| Where | What it does today |
|---|---|
| `Schedule::refineConnectionsIntoLgrs` (opm-common) | moves a `COMPDAT` connection inside a box into the LGR |
| `LgrDeckConnectionCheck.hpp` (opm-simulators) | refuses NNC, `AQUCON`, numerical aquifer cells "covered by a refinement box" |
| LGR well head (opm-common, `AggregateConnectionData`) | takes K from the first refined connection |
| `ScheduleGrid::populate_props_lgr` | LGR properties for connections |
| Summary block vectors for host cells (gap row 50) | host cells read zero |

Already by refined status, so a masked parent behaves as an ordinary cell without change:
`Transmissibility` (`refined(c)` = more than one child: EDITNNC, EDITNNCR, MULTREGT on NNCs,
pinch distribution), `aquiferConnectionsOnLeaf` (resolves via `compressedIndex`), the
transmissibility host-level output (`isHost` from level-zero origins of refined elements).

### 4. Output

- **EGRID LGR section:** full lattice; masked parents' children `ACTNUM = 0`; `HOSTNUM` as
  today.
- **Global section:** masked parents are ordinary cells, with their own TRAN and NNCs.
- **LGR to global NNCs:** the faces between a masked parent and its refined neighbours have to
  be in the list. Today they come only from the box boundary. Check that the writer builds the
  list from leaf faces between level-zero and refined cells, not from box sides.
- **ResInsight** shows an LGR with inactive cells without change.

Since the reference has no `REFCELLS`, there is no reference output. The convention above is
"the box as refined, with the masked parents' children inactive and the parents themselves
active in the global grid".

### 5. Smaller points

- Block property arrays (`PERMX` etc. inside the CARFIN) stay sized over the whole refined box.
  Values for masked children are unused.
- Block `MINPV` applies to refined children only. A masked parent takes the global `MINPV`.
- `LGRON`/`LGROFF` (dynamic refinement) carries the mask with the request. `AdaptiveCpGrid`'s
  cell marks can produce masked requests instead of split boxes, which also removes the
  "different factor, touching boxes" limits of the marks.
- Parallel: no change to the rank-interior rule. The refusal script gets a deck with a mask that
  is invalid under rule 3, to check every rank stops.

## Phases

1. **Interior mask, unfaulted** (about 2 weeks): opm-common parsing and active cells; leaf
   assembly for interior interfaces; the "refined" predicate in the table above; output.
   Decks, starting from `SPE1CASE1_CARFIN`:
   - `REFCELLS_HOLE`: one unrefined parent in the middle of a box
   - `REFCELLS_L`: an L-shaped refined region
   - `REFCELLS_K`: an unrefined layer between refined layers
   - `REFCELLS_CHECKER`: a checkerboard mask
   - `REFCELLS_WELL`: a well through refined and unrefined parents

   Each runs serial and at np=2 and np=3, and is compared with the same model refined only where
   the mask is 1, written as separate CARFINs where possible.
2. **Faults on interior interfaces**: generalise `faultedBoundaryConnections` to one parent
   face; Drogon with a masked box over the faulted region.
3. **Touching boxes with masks; nested LGRs inside the refined part of a masked box.**

## Open questions

- Should a mask also be allowed to *grade* (refine some parents more than others)? That is a
  different keyword (per-parent subdivision) and conflicts with the one-lattice-per-box
  layout. Out of scope here; nesting is the grading mechanism.
- Should `REFCELLS` accept the box/region operators (`EQUALS`, `BOX` inside the CARFIN block)?
  Cheap once block keywords go through the same FieldProps path, but needs a decision on
  whether `REFCELLS` is a field property or a block-only array.
