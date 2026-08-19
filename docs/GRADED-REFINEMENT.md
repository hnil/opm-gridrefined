# Graded local refinement (NXFIN/HXFIN and friends)

Survey and implementation, 2026-08-19. **Implemented** — `NORNE_LGR.DATA` runs as
written (434 timesteps, 2463 Newton). Companion to `LGR_GAPS.md` (B5) and
`STATUS.md`.

`NORNE_LGR.DATA` was the motivating deck: it asks for graded refinement, and OPM
used to parse the keywords and ignore them, subdividing the block uniformly
3×3×1 instead.

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

## What was done

The scalar `cellsPerDim[d]` gave way, per direction, to tables derived once from
`NXFIN`/`HXFIN`:

- `parentOfRefined[ir]` — which parent column refined column `ir` belongs to
  (prefix sums of `NXFIN`);
- `fracLow[ir]`, `fracHigh[ir]` — its normalised extent within that parent cell
  (cumulative normalised `HXFIN`, defaulting to `j/n`).

Every site below became a table lookup instead of a division. The tables are
computed in one place — `Carfin::refinedColumns()` in opm-common, mirrored by
`Opm::Refinement::axisSubdivision()` for the grid builder, which fills in the
uniform tables for a request that carries none so there is a single code path.
A uniform box therefore reaches the builder exactly as before; the
`explicitUniformTablesMatchTheFactorPath` test pins that equivalence.

### Validation

Against the reference EGRID for Norne's graded CARFIN, the sub-pillar spacing
across the graded parent cell reproduces the deck's 11 9 7 5 3 1 3 5 7 9 11
**exactly** (ratios 11.13, 9.09, 7.09, 5.04, 3.04, 1.00, … identical to the
reference to the printed precision).

The remaining few-percent differences elsewhere in the box are the reference's
own pillar handling, not this builder's: it clips the LGR's COORD pillars to the
LGR's depth range, and its corner sub-pillar then misses its own parent pillar by
0.78 m, where this builder reproduces the parent pillar exactly. That is the
corner-point-native resampling the geometry note in `STATUS.md` describes.

The per-parent normalisation of `H*FIN` — inferred from Norne's deck in the
survey below — is confirmed by that match, and by the defaulted `11*` groups
coming out as equal shares of their parent cells, which is what the reference
also produces.

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
| `flow/AdaptiveLgr.hpp:97` | derives `cellsPerDim` as `nd[d] / nparents[d]` — untouched: the adaptive path produces uniform boxes by construction |

## Refused rather than answered wrongly

Two places keep the scalar factor and now reject a graded box with a clear
message:

- **Box-to-box interfaces** (touching boxes, and the A5 faulted box↔box case).
  The conformity rule compares one subdivision factor per in-face direction; the
  graded question is whether the two sides' sub-column *boundaries* line up.
- **`Entity::geometryInFather()`**. Placing a child in its father's unit cube
  means knowing which of that father's columns it is, and reaching the tables
  from a possibly-leaf entity needs a leaf-to-level mapping the method does not
  have. Nothing in flow calls it (only `ecfvstencil.hh` re-exports it).

## Still open

**Block-local `MINPV` is not applied.** Norne's block sets `MINPV 0.1` against
the field's `MINPV 500` precisely so the graded fine cells survive — the centre
sub-cell is ~1/5000 of its parent's footprint. Without it the refined cells
simply inherit their father's activity, so no fine cell is dropped for being
small (nor kept where the reference drops it: the reference deactivates 939 of
them). Implementing it needs refined pore volumes, which are father PORV × (child
volume / father volume) — the same rule the PORV output now uses — and a seam to
watch: the CpGrid level and opm-common's `EclipseGridLGR` must agree on which
refined cells survive, or the output arrays mismatch.

## Not investigated

`RADFIN` (radial LGR) and `CARFIN`'s `NWMAX` well argument. `AMALGAM`,
`COARSEN`. Whether ECLIPSE normalises `H*FIN` per parent cell or per box was
inferred from Norne's deck alone — it fits exactly, but only one deck was
checked.
