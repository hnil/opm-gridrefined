# Coarsening below the input grid — what it takes

2026-09-22. Investigation only; nothing implemented.

## What exists today

"Coarsening" in the dynamic driver (`flow_blackoil_adaptive_dynamic`,
`--adaptive-rebuild-lgr=none`, `LGROFF`) only *un-refines*: it rebuilds the world
without an LGR, so the finest it can go back to is the input grid. The input grid
is the coarsest level everywhere in the stack:

- `CpGrid` level 0 = the deck corner-point grid; refinement only adds levels.
- Every consumer of per-cell input data goes through the level-0 Cartesian index:
  `LookUpData` (field props; refined cells inherit the ancestor's, `PORV` is split
  by volume, `LookUpData.hh:300`), `cartesianToCompressed_` (wells, summary,
  NNC/aquifer lookup), Schedule connections (`global_index`), output.
- `AdaptiveStateTransfer.hpp` keys state by `stableCellId` = Cartesian index or
  `tag|parent|child`; restriction is a plain child average.
- `COARSEN` (the deck keyword, `I1 I2 J1 J2 K1 K2 NX NY NZ`, GRID section) parses
  but is refused (`UnsupportedFlowKeywords.cpp:81`).

The rebuild seam itself (tear down, rebuild from the parsed `EclipseState`,
remap by stable id, inject through the restart path) does not care how the new
leaf was produced. So "the same processing method" works for coarsening as long as
the vanguard can build a leaf coarser than the input, and the consumers above can
handle a leaf cell that covers several input cells.

## Three routes

**A. Coarse deck (rebuild from a coarsened `EclipseState`).** Generate a coarse
COORD/ZCORN + upscaled PORV/TRAN*/regions and rebuild from it. No grid code, but it
changes the Cartesian index space mid-run: the Schedule, summary config, restart
output and every deck IJK are in input indices. Only tensor-product (global)
coarsening. Useful as a *reference* for testing, not as the feature.

**B. Inverted hierarchy.** Level 0 = coarse grid, input cells = an LGR of it;
coarsening = `LGROFF`. DUNE-correct and reuses LGRON/LGROFF, but the deck now
describes level 1: field props, wells, NNCs, output all index the "refined" level.
Also needs a builder that takes child geometry from the input instead of
interpolating. Too invasive.

**C. Agglomerated leaf on the input index space (recommended).** Keep the input
grid as the index space; build a single-level `CpGrid` in which each coarsened
block is one cell. That cell carries an *anchor* Cartesian index (e.g. the block's
lowest) and a side table of the input cells it covers. The covered non-anchor
indices look to the rest of the stack like inactive cells, except that the side
table tells the consumers where they went. Everything deck-indexed keeps working;
ECL output stays on the input grid (write the coarse value into every covered cell
— the mirror of how refined parents get the child mean today).

The rest of this note is route C.

## Grid side (opm-gridrefined)

A merge pass over a built level-0 `CpGridData`, producing a new single-level one:

1. Cells: uncovered input cells + one per block. `cell_to_point_` for a block =
   the 8 outer corners, taken from the block's extreme cells (corner pool reused,
   D1). `Geometry<3,3>` stores centre and volume separately from the corners, so
   the exact volume sum and volume-weighted centroid can be stored.
2. Faces: keep input faces whose two cells map to different new cells; drop the
   rest. Faces between the same new-cell pair must be **merged into one** (area
   sum, area-weighted centroid and normal): `Transmissibility_impl.hpp:659` does
   `insert_or_assign` per cell pair, so a second face overwrites the first.
   Coarse–fine interfaces keep one face per fine neighbour (the same shape as an
   LGR box next to its host today). Boundary faces merge per side.
3. `global_cell_` = anchor index; `logical_cartesian_size_` = input dims.
4. Block validity (first cut, refuse otherwise): all covered cells active; no
   fault or NNC *inside* the block; block does not overlap a CARFIN box.

About a week. Serial only; the partitioner sees an ordinary level-0 grid, so
parallel may work unchanged but is untested territory.

Mixing with refinement in the same world (coarse far away, LGR near a well) needs
the refinement builders to accept an agglomerated level 0. They read the input
corner-point description by Cartesian index (`RetainedCornerPointInput`), so boxes
disjoint from coarse blocks probably work — verify rather than assume.

## Simulator side (opm-simulators)

| Consumer | Change |
|---|---|
| `LookUpData` field props | reduce over the covered set: `PORV` sum; doubles (`SWATINIT`, end-points, `PORO`/`NTG` if still read) pv-weighted; integer regions (`SATNUM`, `PVTNUM`, `EQLNUM`, `FIPNUM`, `ROCKNUM`, …) must be uniform — refuse the block otherwise |
| `Transmissibility` | coarse faces: upscale from level-0 (input) transmissibilities, not from the anchor's perm. First cut: per-row series / per-face parallel ("arithmetic-harmonic") from the fine trans; flow-based local upscaling later. The `--lgr-trans-from-host` code already computes level-0 trans for the opposite purpose. Deck NNCs/EDITNNC/MULTREGT between cells mapping to the same pair must accumulate; an NNC inside a block is dropped (reported). Diffusivity/thermal half-trans: same or refuse |
| `cartesianToCompressed_` (`FlowBaseVanguard.hpp:351`) | many-to-one: every covered index → the coarse cell |
| Wells | trajectory replay onto the coarse hex works as-is; several input connections landing in one coarse cell must be **merged** in the replay (CF summed, one connection) rather than passed as duplicates to the well model |
| Summary | block vectors `B*:(i,j,k)` resolve through the many-to-one map; region vectors fine given uniform regions |
| ECL output | INIT/UNRST on input dims, coarse value replicated to covered cells; EGRID unchanged. Unlike the LGR case, dims never change across the event |
| Equilibration | runs on the rebuilt world before injection overwrites it — harmless |

## State transfer

- Stable id for a coarse cell: a second tag bit (`1<<61`) | anchor index.
- Restrict (fine → coarse): **pv-weighted** for P, S, Rs, Rv, T (today's plain
  average is not mass-consistent); `max` for the hysteresis envelopes
  (somax/swmax, the plan's S4 item).
- Prolong (coarse → fine, i.e. un-coarsen): constant copy. Sub-block saturation
  structure is lost; an upgrade is to keep the fine state from the coarsening
  event as a shape and rescale it to the coarse mass.
- Nested cases (a coarse cell being refined directly) are not needed: un-coarsen
  first, then refine, as two rebuilds.

## Deck and driver surface

- Static: support `COARSEN` in GRID (the keyword already has the right
  semantics: box + number of coarse cells per direction). This is the natural
  first milestone and removes a refused keyword.
- Dynamic: `--adaptive-rebuild-coarsen="I1 I2 J1 J2 K1 K2 NX NY NZ"` next to
  `--adaptive-rebuild-lgr`; later an indicator-driven mark set. There is no
  standard schedule keyword for switching `COARSEN` on/off.

## Acceptance tests

1. **Static equivalence.** SPE1 with `COARSEN` over a region with uniform
   properties vs. a hand-built coarse deck (route A) with the same explicit
   `PORV`/`TRANX/Y/Z` and `COMPDAT`: same Newton counts, rates to round-off.
2. **Mass balance.** Dynamic coarsen@N / un-coarsen@M on SPE1: report the
   in-place change at each event (should be ~0 with pv-weighted restriction).
3. Regression: no `COARSEN` → byte-identical to today.

## Order of work

1. Grid merge pass + `COARSEN` parsing into the vanguard, serial, validity checks.
2. `LookUpData` covered-set reductions, `cartesianToCompressed_` many-to-one.
3. Transmissibility upscaling + pair accumulation.
4. Well connection merge in the replay; summary block lookup.
5. Output replication.
6. Stable-id tag + pv-weighted restriction; dynamic driver option.

Steps 1–5 give static `COARSEN`; step 6 makes it dynamic through the existing
rebuild seam. Rough total 2–3 weeks.
