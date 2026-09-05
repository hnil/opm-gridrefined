# Refinement around wells: the `--well-refine` prototype and the keyword to follow

2026-09-05. First application: resolve the near-well thermal front and keep
cell aspect ratios acceptable for the mechanical solve, refining at least the
layers the well is completed in. Prototype on `flow_blackoil_adaptive`
(opm-simulators `b68c1bf1f`), command-line driven; the keyword form is
sketched at the end.

## What it does

```
--well-refine="PATTERN:FX,FY,FZ:rings=W1[,W2,...][:layers=all][:klayers=N]"
```

Zones are `;`-separated. For each zone the perforated cells of every well
matching `PATTERN` (all report steps) seed one box per well. The outermost
ring is the seed dilated laterally by the sum of the ring widths, each inner
ring by one width less, and each ring is nested in the one outside it with the
same factor, so the well column is refined `FX^n` times laterally for `n`
rings. In K each ring reaches one layer beyond the ring inside it; the
innermost covers the perforated layers (plus `klayers` above and below), or
every ring covers every layer with `layers=all`. Boxes of one zone that
overlap or touch are merged. The requests join any `--adaptive-lgr` boxes and
go through the ordinary nested-CARFIN builder path, then every well is
replayed onto the refined leaf.

Implementation: `opm/simulators/flow/WellZoneLgr.hpp` (spec, ring construction,
request generation) and the hook in `AdaptiveCpGridVanguard::addLgrs()`.

## What it did on model2

`TEST_NOLGR_INJ1_NOTHPRES.DATA`, `--well-refine="PROD1:3,3,1:rings=1,1"`,
ECL output off, VTK on:

| | coarse | refined |
|---|---|---|
| leaf cells | 8866 | 12658 |
| PROD1 connections | 4 coarse | 4, all in the innermost 9x9 column |
| timesteps / Newton | 55 / 285 | 59 / 327 |
| VTK | | 40 `.vtu` files of the leaf, 12658 cells each |

The two rings: `WZ1R1B1` on GLOBAL, cells `[4,8]x[1,5]x[16,21]` by 3x3x1, and
`WZ1R2B1` nested in it, `[4,12]x[4,12]x[2,5]` of the parent's refined cells
by 3x3x1. Sizes 100 % → 33 % → 11 % laterally, K unrefined, which is what the
aspect-ratio argument asks for.

## What stopped it, in order of importance

1. **A well must lie in one LGR.** The trajectory replay tags a well with a
   single grid; connections in two LGRs are refused. A ring layout satisfies
   this only if every perforation falls in the innermost ring, which the K
   margin guarantees for a vertical well. A deviated well crossing rings
   needs the single-LGR lift (plan S6a-2).
2. **A synthesized trajectory can hit the layer above a perforation on
   sheared cells.** `INJ2` (completed in layers 19-21) replayed with a fourth
   connection in layer 18, a coarse cell outside its zone, and the LGR
   bookkeeping then failed on that connection's global index. The synthesis
   extends each in-cell segment by a sliver beyond the cell faces using the
   input grid's DZ; on a tilted corner-point cell the true face at the nudged
   lateral position is closer than DZ/2, so the sliver becomes a real crossing
   longer than the replay's 0.1 m filter. Fix belongs in
   `WellConnections::synthesizeTrajectory`: clip each segment to the cell's
   own vertical extent at the nudged position (needs a corner callback, not
   just centre and dims), or filter replayed hits by the deck connection's
   MD window. Until then a vertical well on regular cells works; on sheared
   cells it may not.
3. **A nested child must be strictly interior to its parent in every
   direction.** The builder rule (`LeafGridAssembler`, one refined parent cell
   on each side) is why each ring adds a K layer, and why a well completed in
   the top or bottom layer loses that layer from the inner rings at the grid
   boundary (the ring is shrunk with a warning). Lifting it for faces on the
   domain boundary is small; lifting it in general is the multi-level mosaic.
4. **No ECL output** on this route: the deck declares no LGR, so the writer
   has nowhere to put the refined cells (`--enable-ecl-output=false`, VTK for
   ParaView). ResInsight needs the keyword form below.
5. Grading is uniform per ring; `H*FIN`-style columns inside a ring are not
   generated (they would be wrong for the mechanics anyway).

## The keyword form

The GRID section is parsed before the SCHEDULE, so a keyword naming wells
cannot be resolved inside `EclipseState`; it has to be resolved where the
deck's wells are known and then written back as ordinary CARFIN blocks, so
that the grid builder, the EGRID/INIT writer and ResInsight see nothing new.
Proposed:

```
WELLREF
-- well    ring widths   factor     layers   klayers
  'PROD*'  2 1           3 3 1      PERF     0 /
  'INJ1'   1             5 5 1      ALL      /
/
```

- Parsed into a small `WellRefinement` record set (opm-common, GRID section,
  keyword JSON + `EclipseState` accessor), no geometry work.
- Resolved in the vanguard after the Schedule exists, with exactly the ring
  construction the prototype has, into `Carfin` objects added to the
  `LgrCollection`, followed by the `EclipseGrid` LGR tree update
  (`create_lgr_cells_tree` / `updateLgrActiveCells`) so output and restart
  are the deck-CARFIN route. Wells inside the boxes then need either
  `COMPDATL` conversion or the replay; the replay is what the prototype uses.
- Alternative that avoids touching `EclipseState` after construction: expand
  `WELLREF` into CARFIN blocks at deck level in a pre-pass that reads `COMPDAT`
  from the raw deck. Cheaper, and it makes the expansion visible in the PRT.
