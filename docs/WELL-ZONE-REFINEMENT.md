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

## The keyword: `WELLREF` (opm-common, implemented 2026-09-05)

```
GRID
WELLREF
-- well    NX NY NZ  RING1 RING2 RING3  LAYERS  KLAYERS
  'PROD*'   3  3  1    1     1     0     PERF     0 /
  'INJ1'    5  5  1    2                 ALL        /
/
```

One record per well pattern: the refinement factor of every ring relative to
the ring outside it, up to three ring widths in coarse cells (outermost first,
zero means absent), whether the K range is the completed layers (`PERF`,
default) or the whole column (`ALL`), and extra layers above and below.

The keyword is expanded **at parse time** (`Parser.cpp`,
`expandWellRefinement`) into ordinary `CARFIN ... ENDFIN` blocks inserted right
after it in the GRID section, named `WR<record>R<ring>B<box>`, an inner ring
carrying its outer ring as `PARENT`. Seeds are the wells' `WELSPECS` heads and
`COMPDAT` cells read from the raw deck (defaulted I/J take the head; wells
completed only by `COMPTRAJ` are skipped with a warning). The ring geometry is
the prototype's, in `EclipseState/Grid/WellRefinement.{hpp,cpp}`, so
`--well-refine` and `WELLREF` build the same boxes. Everything downstream is the
deck-CARFIN route: `LgrCollection`, the `EclipseGrid` LGR tree, the grid
builder, EGRID/INIT/UNRST sections per LGR, ResInsight. `EclipseState::
hasWellRefinement()` tells the vanguard to synthesize trajectories for the
COMPDAT wells before the replay places them in the refined cells (serial only
for now: the synthesis reads the input grid, which only the I/O rank holds).

Answering the question whether the refined grid "is an LGR": with `WELLREF` it
is a combination of ordinary LGRs, nested where the rings nest; with
`--well-refine` it is the same grid but the deck does not know, so no ECL
output. A single LGR around the whole grid is `RING1` large enough and
`LAYERS ALL` (clamped to the grid), but note the parallel model refuses a box
that spans the whole grid.

Unit test: `tests/parser/WellRefinementTests.cpp` (two nested rings on model2's
PROD1 give `CARFIN 'WR1R1B1' 4 8 1 5 16 21 15 15 6` and
`CARFIN 'WR1R2B1' 4 12 4 12 2 5 27 27 4 'WR1R1B1'`).

### Lifting "one LGR per well"

The connections already carry their own grid number (`Connection::
get_lgr_level()`); the restriction is that `Well` is tagged with one LGR
(`Well.cpp` throws when connections span two) and the vanguard resolves every
connection against that tag (`compressedIndexForInteriorLGR(lgr_tag, conn)`).
Resolving per connection and dropping the two throws is a day's work on the
simulation side. What does not follow is the ECL output: `WELSPECL`/`COMPDATL`
and the per-LGR well arrays name one LGR per well, and the reference format
has no representation for a well in two LGRs short of `AMALGAM`. The rings
avoid the need: every perforation lies in the innermost ring by construction.
