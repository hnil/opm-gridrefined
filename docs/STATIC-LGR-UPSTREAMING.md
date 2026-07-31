# Static LGR upstream: what is needed, and where the line should go

Scope: deck-declared CARFIN, refined at simulation start — correct
initialization, correct wells, correct output, serial and parallel. Nothing
here concerns dynamic refinement, trajectory wells, or alternative refinement
backends; those are separate discussions. Status as of 2026-07-30.

The grid build and solve already work on opm-grid master. Every remaining gap
is in opm-common output or opm-simulators glue — **no opm-grid change is
required for any of this.**

## Merged

- **opm-common#5250** — `Carfin::parent_name_grid` was missing from
  serialization, so non-root ranks deserialized an empty parent name and took a
  different code path than rank 0: asymmetric collectives, deadlock in the
  parallel grid build. This affected every parallel CARFIN run, not just nested
  ones. Now includes a round-trip test.
- **opm-simulators#7243** — a rank left with an empty partition (easy to hit
  when a small LGR deck is over-decomposed) segfaulted in ILU0; now a clear
  error.

## Open

- **opm-simulators#7244** — region arrays (EQLNUM, PVTNUM, SWATINIT, FIPNUM)
  are read on the input grid but indexed by leaf cell. With an LGR the leaf is
  larger, so refined cells equilibrate in the wrong region (wrong WOC) and are
  zero-padded out of the FIP sums (wrong FPR). Uses only existing
  `LookUpData`; identity on unrefined grids. Without this, static-LGR results
  are silently wrong even in serial.

- **opm-simulators#7245** — three bugs: wells resolve their cells through a
  Cartesian→compressed map that is stale after refinement, so the source term
  lands on the wrong leaf cell; summary/FIP evaluation is skipped for any
  refined grid, so serial CARFIN runs write all-zero summaries; and an
  out-of-range throw fires asymmetrically across ranks and deadlocks COMPDATL
  decks at np≥6. **Reworked per the review comments:** the map now contains
  unrefined cells only — Markus's inline proposal, adopted as stated — so a
  refined-away level-zero index resolves to "not present" instead of an
  arbitrary child; the LGR lookup treats a missing name or out-of-range
  position as fatal (programming errors — the level structure is identical on
  all ranks) and returns −1 only for a cell genuinely absent on this rank,
  matching the coarse-path contract; and the duplicated update/condition
  blocks are factored into single helpers as suggested.

- **opm-common#5252** — INIT/UNRST write their per-LGR sections in deck order
  while the EGRID writes grids in host-cell order. Post-processors pair them
  positionally, so whenever the two orders differ the output is unloadable
  (wrong PORV array against a grid). Complementary to the summary fix in
  #7245: one makes LGR output exist, the other makes it load.

- **opm-common#5251** — the summary region cache indexes the global grid with
  a COMPDATL connection's LGR-local cell index: out-of-range throw at setup,
  or — worse — an in-range hit files the connection under the wrong FIP
  region silently. Needed for FIP summaries on decks with wells inside an LGR.

- **opm-grid#1053** — narrowed after review to a pure bounds check on the
  `cartesian_to_compressed` lookup, routed into the existing inactive-cell
  handling. Nothing above depends on it; it can wait or be closed if this path
  is being reworked anyway.

## Remaining, in order — not yet submitted

1. **Parallel LGR ECL output.** The summary fix above is serial-only;
   parallel output needs the I/O rank to hold a refined reference grid and
   collision-free cell ids in `CollectDataOnIORank`. Verifiable in existing
   CI by flipping `spe1case1_carfin_parallel` to `--enable-ecl-output=true`.
   Same files as #7245, so it waits for that discussion to settle.
2. **Wells inside an LGR at higher rank counts.** A COMPDATL well's
   connections carry LGR-local indices, so the well gets no say in load
   balancing and its rank can diverge from the rank that refines its box —
   the np≥6 failure that #7245 turns from a hang into an error. The candidate
   fix anchors the well to its box's coarse host cells in the partitioning
   graph. This touches how wells are represented during load balancing, so it
   is exactly the kind of change that should follow, not precede, agreement on
   the simple cases.
3. **Nested CARFIN ordering** (if nested is wanted in this round): pass the
   parent grid name through to `addLgrsUpdateLeafView` — the API already
   accepts it — and order parents before children. Non-nested decks take a
   byte-identical path.

## Suggested sequencing

The serial-correctness pair (#7244, and the summary/ordering halves of
#7245/#5252) makes the simple case — one CARFIN box, serial — give right
answers with loadable output. That seems like the natural first milestone, and
matches "make the simple cases work first". Parallel output and well
anchoring build on it in that order. Where exactly the line goes — in
particular whether the #7245 rework should split serial summary enablement
from the well-cell fix — is open for discussion.
