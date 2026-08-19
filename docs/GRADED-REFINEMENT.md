# Graded local refinement (NXFIN/HXFIN and friends) — what it would take

Investigation, 2026-08-19. Nothing implemented; this is the survey that should
precede it. Companion to `LGR_GAPS.md` (B5) and `STATUS.md`.

`NORNE_LGR.DATA` is the motivating deck: it asks for graded refinement, OPM
parses the keywords and ignores them, and the block comes out uniformly
subdivided 3×3×1. Since 2026-08-19 that is warned about rather than silent, but
the geometry is still not the one the deck describes.

## What the keywords mean

Six data keywords, all GRID section, all inside a `CARFIN...ENDFIN` block:

| Keyword | Type | Length | Meaning |
|---|---|---|---|
| `NXFIN` / `NYFIN` / `NZFIN` | INT | one per **parent** cell in that direction | how many refined columns that parent cell is split into |
| `HXFIN` / `HYFIN` / `HZFIN` | DOUBLE | one per **refined** column | relative width of that refined column; defaulted entries mean "equal split of the parent cell" |

`sum(NXFIN)` must equal the `NX` given on the `CARFIN` record. The `H*FIN`
widths are normalised **within each parent cell**, not across the box.

Norne's block confirms both readings exactly:

```
CARFIN
  'LGR1' 27 37 54 64 1 22 33 33 22 /
NXFIN
 1 1 1 3 5 11 5 3 1 1 1 /            -- 11 parent columns, sum = 33 = NX
HXFIN
 11* 11 9 7 5 3 1 3 5 7 9 11 11* /   -- 11 + 11 + 11 = 33 refined columns
```

The prefix sums put parent column `i=32` at refined columns 12..22 — exactly 11
of them — and the 11 explicitly-given `HXFIN` values are exactly the middle
block, flanked by 11 defaulted values on each side covering the parent columns
whose `NXFIN` counts sum to 11 either way. So the deck grades one parent cell
(the well cell) into 11 columns with relative widths 11 9 7 5 3 1 3 5 7 9 11,
i.e. the centre sub-column is 1/71 of the parent's width against 11/71 for the
outermost: an **11:1 size ratio inside one parent cell**, and 1/71 × 1/71 ≈
1/5000 of its footprint at the centre.

That also explains the block's `MINPV 0.1`, against the field's `MINPV 500`:
without it the field threshold would delete the fine cells the refinement exists
to create. **Graded refinement and block-local `MINPV` are one feature**, not
two — which is why the reference run has 19206 active LGR cells where plain
ACTNUM inheritance gives 20145: 939 of the finest cells fall below 0.1 rm3.

## The structural good news

A graded refined block is still a **logically Cartesian `NX × NY × NZ` block** —
only the cell sizes vary. So everything that treats a refinement level as its own
Cartesian grid is already correct and needs no change:

- `LevelCartesianIndexMapper` / `CartesianIndexMapper` — read the level's own
  `globalCell()` and dims.
- `LookUpData` — already scales father properties by
  `elemVolume / fatherVolume` (`LookUpData.hh:308`), so non-uniform children
  distribute correctly with no change at all.
- The parent/child relation — stored explicitly in `child_to_parent_cells_` and
  `cell_to_idxInParentCell_`, not derived from a factor.
- The whole leaf-assembly, output, well and solver path.

What breaks is confined to the places that assume **one integer factor per
direction**, i.e. that refined index `/ factor` gives the parent column and
`% factor` the position inside it.

## Work list

Replace the scalar `cellsPerDim[d]` with, per direction, two tables derived once
from `NXFIN`/`HXFIN`:

- `parentOfRefined[ir]` — which parent column refined column `ir` belongs to
  (prefix sums of `NXFIN`);
- `fracLow[ir]`, `fracHigh[ir]` — its normalised extent within that parent cell
  (cumulative normalised `HXFIN`, defaulting to `j/n`).

Every site below is then a table lookup instead of a division.

### opm-gridrefined

| Site | What it assumes |
|---|---|
| `refinement/RefinementRequest.hpp` — `BlockRefinement::cellsPerDim` | the request carries one factor per direction; needs the tables (and `dims` from `sum(NXFIN)` rather than `factor × boxDims`) |
| `refinement/GrdeclRefinement.cpp:40` `lateralPos()` | `refinedIdx / factor`, `refinedIdx % factor / factor` — the COORD sub-pillar positions |
| `refinement/GrdeclRefinement.cpp` ZCORN loop | `(ii + di) / factors[d]` as the trilinear fraction |
| `refinement/GrdeclRefinement.cpp` ACTNUM loop | `ir / factors[0]` for the parent lookup |
| `refinement/LevelGridAssembler.cpp:89,151` | level dims as `(end - start) × cellsPerDim` |
| `refinement/FaultedBoundaryFaces.cpp:105,117,166` | `L[d] / cellsPerDim[d]`, `oL[d] % cellsPerDim[d]` on the faulted boundary |
| `refinement/LeafGridAssembler.cpp:203` | `pos % rx`, `(pos / rx) % ry` for corner identification with level zero |
| `refinement/LeafGridAssembler.cpp:516,743` | touching-box conformity compares scalar factors; becomes a comparison of the two boxes' sub-column boundaries along the shared face — arguably *more* natural with the tables |
| `cpgrid/Entity.hpp:575` `geometryInFather()` | `getReferenceRefinedCorners(idx, cells_per_dim)` and volume `1/(cx·cy·cz)`; the child's box in the father's unit cube is no longer uniform |
| `cpgrid/CpGridData.cpp:1785` `getReferenceRefinedCorners` | same |
| `cpgrid/CpGrid.cpp:1808` `addLgrsUpdateLeafView` | public API takes `cells_per_dim_vec`; needs an overload carrying the tables |

### opm-common

| Site | What it assumes |
|---|---|
| `Carfin.cpp:39` `assert_dims` | rejects `NX % (I2-I1+1) != 0`; under grading the constraint is `sum(NXFIN) == NX` instead |
| `Carfin` / `LgrCollection` | must carry the per-direction tables; the keywords arrive via `Deck::lgrBlock(lgrName)`, which is what the CARFIN block scoping added |
| `EclipseGrid.cpp:2316` `getCellSubdivisionRatioLGR` | returns one ratio per direction |
| `WriteInit.cpp:906` | divides the father's PORV by `subdiv[0]·subdiv[1]·subdiv[2]` — must become volume-weighted, the same `elemVolume/fatherVolume` rule `LookUpData` already uses |
| `EclipseGrid.cpp` `init_children_host_cells_logical` | `nx / host_nx` for HOSTNUM |
| `EclipseGrid.cpp` `EclipseGridLGR::refinementFactors()` | `dims[d] / nparent[d]`, used by `inheritActiveCellsFromFather()` |

### opm-simulators

| Site | What it assumes |
|---|---|
| `flow/AdaptiveLgr.hpp:97` | derives `cellsPerDim` as `nd[d] / nparents[d]` |

## Ordering

1. **Block-local `MINPV` first.** It is a prerequisite, not a follow-up: without
   it the field's `MINPV` deletes the fine cells (Norne would lose ~939 of them,
   and a deck grading harder would lose more). It needs refined pore volumes,
   which are father PORV × (child volume / father volume) — available from the
   refined geometry, and the same rule as the PORV output fix above. Note this
   introduces a seam: the CpGrid level and opm-common's `EclipseGridLGR` must
   agree on which refined cells survive, or the output arrays mismatch.
2. **The tables through the builder** — `RefinementRequest`, `GrdeclRefinement`,
   `LevelGridAssembler`. Self-contained, and `grdecl_refinement_test` /
   `level_grid_assembler_test` cover it.
3. **Leaf assembly and `geometryInFather`** — the corner identification and the
   faulted-boundary index arithmetic.
4. **Output and the ratio API** — the volume-weighted PORV split.
5. **Parsing and validation** — relax the divisibility check, attach the tables.

Steps 2–4 are mechanical once the tables exist; the design risk is concentrated
in step 1 and in the touching-box conformity rule, which becomes a question about
matching sub-column boundaries rather than matching integers.

## Not investigated

`RADFIN` (radial LGR) and `CARFIN`'s `NWMAX` well argument. `AMALGAM`,
`COARSEN`. Whether ECLIPSE normalises `H*FIN` per parent cell or per box was
inferred from Norne's deck alone — it fits exactly, but only one deck was
checked.
