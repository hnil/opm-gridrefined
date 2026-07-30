# Dynamic refinement inside flow — implementation plan

Re-refine the grid **during** a flow run (not only at init), with solution and
wells carried across, at the smallest possible code cost. The supporting
evidence — prior art, the machinery map of what flow already re-derives, the
state-carrier and driver seams, the well-connection derivation — lives in
[DYNAMIC-REFINEMENT-FLOW-REVIEW.md](DYNAMIC-REFINEMENT-FLOW-REVIEW.md); this
file is the plan only.

Ground rules (2026-07-20/21 discussion):

- **Simplest first** — full recomputation of everything grid-derived is
  acceptable and preferred: it reuses existing init code instead of new
  incremental code.
- **Simple remapping** — intensive quantities prolong as constants (child :=
  parent) and restrict as pore-volume-weighted averages.
- **Transmissibility** — full recompute through the existing LGR-aware
  `Transmissibility::update`; no incremental trans code.
- **Coarsening** wanted from early on; nearly free under full rebuild.
- **No dune-fem** — explicit transfer code replaces
  `AdaptationManager`/`RestrictProlong`.
- **Wells by trajectory replay** — never map old connections cell-by-cell (the
  abandoned flowdynamics approach); represent every well as a trajectory and
  re-derive connections on the new grid (review §5.3).

## Phase overview

| Phase | What | State |
|---|---|---|
| 0 | `flow_blackoil_adaptive`: refine at init, static-equivalent | **exists** |
| 1 | **Restart-in-memory**: full world rebuild at report-step boundaries, explicit state remap, trajectory-replay wells, refine **and** coarsen, well-zone (graded) refinement | this plan, steps S0–S9 |
| 2 | In-place rebuild (no object re-construction) | milestone, §Phase 2 |
| 3 | Incremental grid adapt, parallel, remaining state transfer | milestone, §Phase 3 |

Phase-1 target: a serial `flow_blackoil_adaptive_dynamic` demonstrator.
Adaptation happens at report-step boundaries: wells re-derive there anyway,
output flushes there, schedule events process there — and there the minimal
implementation is "restart-in-memory": tear down the simulator, rebuild the
world through the *existing* init path with a new mark set, remap state, and
continue. Every bound-at-construction object (`lookUpData_`, `EclWriter`,
mappers, sparsity — review §2) is simply constructed correctly, so no re-init
orchestration code exists at all in phase 1.

---

## Phase 1 — detailed steps

### S0 Grid-side prerequisites (opm-gridrefined; small)

1. Fix the `globalRefine`/`autoRefine` reserved-name clobber (they submit their
   whole-grid box as `"GLOBAL"`, overwriting `lgr_names_["GLOBAL"] = 0`;
   `lgr_review.md` Part VI.2-1) and reject `"GLOBAL"` as a request name in
   `validateBlockRefinements`.
2. Replace the `--adaptive-lgr` string at the seam with a **mark-set object**
   the driver can mutate between events (`AdaptiveLgr.hpp` boxes → marks):
   per-cell or per-box marks with factors, un-marking (= coarsening), and the
   `WellZone` spec of S7b, expanding to an ordered parent-before-child
   `BlockRefinement` request list.
3. Optional, later: A2 edge/corner-contact mosaic; multi-level nesting
   (NESTED_LGR_PLAN Phase C).

### S1 Step-driver skeleton (opm-simulators fork)

New main (working name `flow_blackoil_adaptive_dynamic`) built on the existing
decomposition: `FlowMain::executeInitStep()` / `executeStep()` /
`executeStepsCleanup()` + `getSimulatorPtr()` / `getSimTimer()`
(`FlowMain.hpp:182-208`) — the same API the Python step-driver uses. First
milestone: drive a run to completion with **no** adaptation.

*Verify:* summary byte-identical to `flow_blackoil_adaptive` on the same deck.

### S2 World rebuild mid-run

At adaptation event (report step N):

1. Tear down simulator #1 (after extracting state, S3).
2. Re-populate the static `FlowGenericVanguard::modelParams_` from the driver's
   own `shared_ptr<EclipseState>/<Schedule>/<SummaryConfig>` copies (the
   vanguard ctor moves-from the static — review §4). **No re-parse.**
3. Construct simulator #2; the adaptive vanguard refines to the **new** mark
   set during construction, exactly as at init (including the S6 trajectory
   replay and S7b well zones).
4. Position the timer directly: `simtimer_->setCurrentStepNum(N)` (avoids
   touching the deck's `InitConfig`). Equil init runs and is then overwritten
   by S5 — wasted work, accepted for phase-1 simplicity.

*Verify:* rebuild at N with an **unchanged** mark set, inject state, continue —
run completes.

### S3 State extraction (new file, e.g. `AdaptiveStateTransfer.hpp`)

Walk the old leaf once; per cell store, keyed by **`stableCellId()`** (plain
Cartesian index for coarse cells; packed `(parentCart, idxInParent)` for
refined cells — build/partition-invariant), each field tagged with its
**reduction op** (see S4/S5b):

- PRESSURE, SWAT, SGAS, TEMP, RS, RV, RSW, RVW (the restart field set) —
  op `avg`;
- the transferable explicit-state scalars (S5b): somax, swmax — op `max`;
  minRefPressure — op `min`; polymer maxAdsorption — op `max` (when active);
- pore volume (the restriction weight).

**No hysteresis buffers** — hysteresis is guarded off in phase 1 (S5b).
Values read from the problem's fluid state / output-module accessors. Plus the
`WellState`, keyed by well name (S6d).

### S4 Remap — the explicit `RestrictProlong` replacement (~100 lines)

For each new-leaf cell, compute its stable id and resolve against the old map:

- **exact id match** → copy;
- **new refined child, old had the (coarse) parent** → copy the parent's values
  (constant prolongation; exact for constant fields);
- **new coarse parent, old had refined children** → **per-field reduction**
  over the children: pv-weighted `avg` for thermodynamic fields, `max` for
  monotone envelopes (somax/swmax/maxAdsorption), `min` for minRefPressure.
  The op tag makes the envelope restriction *correct* (the max of the children
  is the parent's max), where averaging would silently violate monotonicity;
- **factor change** (both sides refined, different subdivision) → restrict to
  the common parent, then prolong.

Pure function of two keyed maps + an op per field — unit-testable against
hand-built cases with no simulator involved.

### S5 State injection

Build an in-memory `data::Solution` in leaf order; per cell call
`outputModule_->setRestart(sol, elemIdx, elemIdx)` (serial: local == global
index), then call `problem().readSolutionFromOutputModule(N, false)` directly —
this **bypasses** `readEclRestartSolution_` and its "refined grids not
supported for restart" throw, and reuses the existing arrays→fluid-state→
primary-variables conversion including the switching-variable logic (review
§3-A). Set `setTime(schedule.seconds(N))` + `setEpisodeIndex(N)` (mirroring
`FlowProblemBlackoil.hpp:1323-1327`).

Known tolerance: `processRestartSaturations_` clamping — documented and
measured in S8(a).

### S5b Explicit (non-primary) state

The conceptual problem: beyond primary variables, flow keeps per-cell state
that is updated **explicitly** at `beginTimeStep` — the
`updateExplicitQuantities_` funnel (`FlowProblem.hpp:366,383` →
`FlowProblemBlackoil.hpp:1659-1681`) — outside the Newton solve. These fields
have *different transfer semantics* than the solution, and one class of them
(hysteresis) cannot be transferred naively at all. Full inventory with
storage/update-site/consumer/restart-key per quantity: review §6. Summary and
phase-1 policy:

| Explicit state | Nature | Phase-1 policy |
|---|---|---|
| `maxOilSaturation_` (somax → VAPPARS), `maxWaterSaturation_` (swmax → rock compaction), polymer `maxAdsorption` | monotone envelope (per-cell running max) | **transfer, op `max`** (S3/S4) |
| `minRefPressure_` (irreversible rock compaction) | monotone envelope (running min) | **transfer, op `min`** |
| `overburdenPressure_` | static, deck-derived | re-derived at construction (nothing to do) |
| DRSDT/DRVDT state (`MixingRateControls`: lastRs/lastRv/maxDRs/…) | rate-limiter history | **reset** at the adaptation event (documented; conservative limiter restart) |
| tracer concentrations (`GenericTracerModel` own BlockVectors) | solution-like | **reset** in phase 1; transfer with the same avg primitive in phase 3 |
| **hysteresis** memory (`pcSwMdc_/krnSwMdc_/krwSwMdc_` per cell, inside each cell's `EclHysteresisTwoPhaseLawParams`, owned by the MaterialLawManager) + PPCW/SWATINIT scaling (`maxPcow`) | curve-state; only reachable through the MLM; prolong/restrict semantics for scanning curves are genuinely unclear | **unsupported in phase 1** — hard guard |

**The hysteresis guard.** Throw "hysteresis is not supported with dynamic grid
adaptation" where both facts are visible: on the problem side, at the end of
`readMaterialLawParams_()` / in `finishInit` — the MLM exists there and
`materialLawManager_->enableHysteresis()` (`EclMaterialLawManager.hpp:185`,
set from EHYSTR via `EclHysteresisConfig::initFromState`) can be checked
against the adaptive mode. (The vanguard runs before the MLM exists, so the
guard cannot live in `addLgrs()`.) PPCW/SWATINIT max-pc scaling rides on the
same guard initially. Lifting the guard later means porting the restart
carry-through — the SOMAX/SWMAX/SWHY1/SGMAX/SHMAX/SOMIN/PPCW keys applied back
via `OutputBlackoilModule::initHysteresisParams`
(`OutputBlackoilModule.hpp:586-649`) — through the S4 remap with per-key ops
(maxima → `max`, minima → `min`), plus a defensible prolongation rule for
scanning-curve state; that is phase-3 work, and pv-averaging is *never*
correct for these.

Also flagged (pre-existing, independent of adaptation, report upstream):
`FlowProblem.hpp:1338` executes
`maxWaterSaturation_[/*timeIdx=*/1] = maxWaterSaturation_[/*timeIdx=*/0]` —
the comments claim time indices but the container is a flat per-cell vector,
so this touches **cells** 0 and 1.

### S6 Wells — the trajectory-replay strategy

Every well is represented by a trajectory; connections are **re-derived** on
the new grid by replaying it, never mapped cell-by-cell. The replay pipeline
exists (review §5.3): retained+serialized survey and `TrajPerf` parameters,
`WellConnections::recomputeTrajectoryConnections`,
`Schedule::recomputeTrajectoryConnections`, driven by
`CpGridVanguard::recomputeWellTrajectoriesInLgr_()` feeding leaf corners +
per-cell props (parent perm/ntg, true refined dimensions).

- **S6a Wells with trajectories (WELTRAJ/COMPTRAJ).** Two gaps to close:
  1. Wire the recompute into the adaptive path —
     `AdaptiveCpGridVanguard::addLgrs` must call
     `recomputeWellTrajectoriesInLgr_()` after its `addLgrsUpdateLeafView`
     (today only the deck-CARFIN branch of `Base::addLgrs()` runs it,
     `CpGridVanguard.hpp:584-633`).
  2. Lift the **single-LGR restriction** (`Schedule.cpp:1369-1390` warns and
     bails when a trajectory crosses more than one refined box) — required for
     moving refinement windows and load-bearing for graded well zones (S7b).
- **S6b COMPDAT wells (no trajectory).** Synthesize an **equivalent
  trajectory**: a polyline through each perforated cell's centre,
  entering/leaving along the connection's direction (X/Y/Z) across the cell,
  MD accumulated from segment lengths; store it as the same retained trajectory
  state and replay through S6a's pipeline. Anchor property: on the *unrefined*
  grid the synthetic trajectory must reproduce the original connection set
  (cells, order, CF within tolerance) — this is a unit test before it is ever
  used on a refined grid.
- **S6c CF conservation policy**, by `ctf_kind` (review §5.2):
  - `Defaulted` (Peaceman-computed): recompute per refined cell — parent
    perm/ntg + true refined-cell dimensions (already what the replay does).
    Totals legitimately change (r0 scales with cell size); that is the
    better-resolved physics and the *point* of near-well refinement.
  - `DeckValue` (explicit CF/Kh): **preserve the deck total** — apportion the
    parent connection's CF and Kh over its child connections by in-cell length
    fraction, `CF_child = CF_parent · L_child / Σ L_children`, using the
    per-child `intersectionLengthsInCellCS` the extractor already produces
    (`connection_length`, `WellConnections.cpp:886`). Small extension to
    `addOrUpdateTrajectoryConnection` (`WellConnections.cpp:959-1051`): when
    the replayed `TrajPerf` carries user CF/Kh, apportion instead of copying.
    Coarsening is the inverse: children of one parent merge and their CFs sum.
    (No CF-splitting code exists anywhere in-tree today — review §5.2 — so this
    is new but tiny and localized.)
- **S6d Well state.** `wellModel().prepareDeserialize(N-1)` resizes the well
  state and re-derives perforation cell indices against the new grid
  (`BlackoilWellModelGeneric.cpp:265-285`). Carry per-well scalars (BHP, THP,
  rates) by well name; connection-level values re-derived. Documented phase-1
  approximation.

### S6-alt Minimal-update routes (small refine/coarsen deltas)

For when only a small part of the grid changes:

- **Per-well replay only:** replay only wells whose trajectory bounding box
  intersects the changed region (mark-set diff); all other wells keep their
  connection sets untouched. The recompute is already a per-well routine
  (`WELLTRAJ_LGR_STATUS.md`: "reusable per-well routine so a later report-step
  (re)build can call it too").
- **Localized intersection:** `RigEclipseWellLogExtractorGrid` accepts an
  arbitrary corner set + index map — feed it only cells near the affected
  trajectory (changed boxes + a coarse halo), not the whole leaf.
- **Cheap COMPDAT special case:** an axis-aligned COMPDAT connection in a
  refined cell can skip intersection entirely — split it onto the child-cell
  column along the connection direction through the perforation point, CF
  divided equally by length (children have equal extent). Exact for
  axis-aligned wells; S6b remains the general fallback.
- These compose with phase-2/3 incremental grid adapt: mark-diff → affected
  boxes → affected wells → localized replay.

### S7 Mark policy / indicator

1. First: scripted, driver-supplied schedule of boxes (a moving refinement
   window) — enough for the S8 harness.
2. Then: saturation-threshold indicator on level-0 parents (restricted values),
   with a **hysteresis band** (refine at `|ΔS| > a`, un-mark only when
   `|ΔS| < b < a`) so the window follows a front without flip-flopping.
3. Single factor initially — same-factor regions merge into maximal boxes and
   touch conformally by construction. Different factors only where the A2
   compatible-mosaic rules allow.

### S7b Custom refinement around wells, with optional grading

- **Automatic well-zone marks.** At an adaptation event, collect each well's
  perforated level-0 columns (from the connection set / trajectory replayed on
  level 0), dilate laterally by R rings (vertical extent = perforated interval,
  optionally dilated), and mark the box with a per-well factor — driven by a
  parameter such as `--well-refine "PROD*:3,3,1:rings=1"`. Wells opening later
  in the Schedule (WELSPECS/COMPDAT at step M) are natural adaptation-event
  triggers: refine their zone at step M; a permanently shut well's zone can be
  un-marked (coarsened).
- **Graded refinement — recommended route: nesting.** Grading = an outer
  buffer box with factor f1 (e.g. 2,2,1) plus the inner well-column box
  **nested inside it** with factor f2 → total f1·f2 at the well, stepping down
  to coarse. The builder already supports exactly this: fully-contained
  one-level-deep nested LGR (`assembleNestedLeafGrid`; the child must be ≥1
  refined cell interior to its parent, `LeafGridAssembler.cpp:1122-1172`), and
  every graded interface is a conformal parent-child interface *by
  construction*. Missing is only mark plumbing: `AdaptiveCpGrid` marks are
  GLOBAL-parent-only today — the S0 `WellZone` spec expands into the ordered
  parent-before-child nested request list.
- **Why not grading via touching different-factor boxes:** a fine box
  surrounded by coarser ring boxes meets them on faces (A2-compatible, fine)
  but also on **edges/corners — which A2 rejects** (the un-implemented "1-D
  mosaic", `LGR_GAPS.md` A2). Either extend A2 to edge/corner contact
  (contained, medium effort) or use the nesting route. This plan recommends
  nesting; the A2 edge extension stays optional later work.
- **Depth of grading.** One nesting level (supported today) already gives three
  grid sizes — coarse → f1 → f1·f2, e.g. 1→2→4 laterally — usually enough for
  near-well resolution. Deeper grading needs multi-level nesting (currently
  throws "Nested LGR deeper than one level is not implemented"; Phase C) —
  later work, not phase 1.
- **Interaction with wells.** A well inside a graded zone crosses BOTH the
  nested LGR and its parent → the single-LGR restriction lift (S6a-2) is
  load-bearing here. The payoff is the physics: `Defaulted` CF recomputed on
  the innermost cells gives a genuinely better-resolved well index (r0 scales
  with cell size); `DeckValue` CF is still apportioned by length (S6c) so deck
  totals are honoured.
- **Out of scope:** ECLIPSE-style radial near-well LGR (a different geometry
  class); Cartesian graded nesting is the substitute.

### S8 Verification harness (the acceptance tests)

- (a) **Identity:** continuous run vs. run with rebuild-at-N and an
  **unchanged** grid — near-identical; measure and document the
  `processRestartSaturations_` clamping tolerance.
- (b) **Refine:** refined-from-start vs. refined-at-N on an SPE1-style deck —
  converging behaviour after N.
- (c) **Coarsen:** refine → un-mark → rebuild; report the mass-balance error of
  the pv-weighted restriction.
- (d) **Well zone:** SPE1-style deck with a graded well zone (1→2→4) — well
  connections land in the innermost cells; deck-CF totals preserved
  (`DeckValue` apportioning); synthetic-COMPDAT trajectory reproduces the
  original connections on the unrefined grid (S6b anchor); BHP/rates compared
  against a globally-fine reference run.
- (e) **Guard:** a deck with EHYSTR + adaptive mode → clean, early throw with
  the documented message (S5b); envelope transfer sanity: after a
  refine-then-coarsen round trip, somax/swmax on the parent equal the max over
  what the children reached (op-`max` restriction), never less.

### S9 Output

Phase 1: each rebuild starts a new writer on the current refined leaf (accepted
limitation; ECL restart-file semantics across a topology change are unresolved
upstream anyway — LGR restart is gap B3). The clean long-term option — **report
on level 0 only**, restricting cell fields to parents with the same pv-weighted
primitive and driving `CollectDataOnIORank` from the level-0/equil view — is
listed as phase-2 work; no such mode exists today.

### DUNE machinery — what to use, what not (decision)

DUNE has three concepts relevant to state transfer; they apply differently to
the two phases:

- **Index sets vs. id sets.** Leaf *indices* (what `std::vector`/`BlockVector`
  storage uses) are consecutive but renumber on any grid change — fine within
  one grid shape, useless as transfer keys. DUNE's answer is the **IdSet**:
  ids are persistent across *modification of the same grid object*. But phase 1
  destroys the grid object and builds a new one — and the generic DUNE contract
  says nothing about ids agreeing between two separately constructed grids.
  That cross-instance guarantee is exactly what `stableCellId()` (D3: packed
  parent-Cartesian + child lattice index) adds. So phase 1's
  `unordered_map<stableCellId, CellState>` is not a workaround around DUNE —
  it **is** the id-set concept, strengthened to survive reconstruction. Keep it.
- **`Dune::PersistentContainer`.** The in-tree specialization
  (`cpgrid/PersistentContainer.hpp:16-33`) is a `PersistentContainerVector`
  over the **LeafIndexSet** — i.e. leaf-index-backed and *not* actually
  persistent across adaptation (the shortcut valid only for non-adaptive
  grids; also noted in `lgr_review.md` §7). Phase 1 cannot use it (the
  container's grid dies with the rebuild). **Phase 2 should fix and use it**:
  once `clearRefinement()` + re-refine mutate the *same* grid object, an
  id-backed `PersistentContainer` (a `PersistentContainerMap` over the local
  IdSet, or one keyed by `stableCellId`) plus honest
  `preAdapt()/adapt()/postAdapt()` semantics (`mightVanish`, `isNew`,
  `father()`) makes the **standard non-fem DUNE transfer idiom** work: fill
  container on the old leaf → adapt → new entities prolong from `father()`,
  vanishing children restrict onto the father in preAdapt. That gives generic
  DUNE user code (and textbook restrict/prolong loops) for free and is the
  natural companion to wiring the `mark/adapt` facade. `geometryInFather()`
  already works on this fork; phase-1 constant/pv-weighted transfer doesn't
  need it, higher-order transfer later can use it.
- **What NOT to take:** dune-fem's `DofManager`/`AdaptationManager`/
  `AdaptiveDiscreteFunction`/`RestrictProlongDefault` — the implicit
  auto-resize/callback machinery is precisely what the explicit
  `finishInit`/`resetLinearizer`/resize sequence replaces, and it drags in the
  fem discrete-function stack.
- **Parallel ("consistent containers"):** in plain dune-grid this is the
  `DataHandle` + `communicate()` mechanism — already used by the fork (e.g.
  the `cell_to_idxInParentCell_` scatter via `DefaultContainerHandle`). Stable
  ids are partition-invariant, so transfer maps are consistent across ranks by
  construction; phase 3 communicates them with the existing handles.
- **Property containers in phase 2 — derived vs. evolving.** Should the
  per-cell property containers be migrated to persistent containers when the
  grid mutates in place? Only by class:
  * *Deck-derived properties* (poro, perm, ntg, satnum/pvtnum/region arrays —
    everything `fieldProps()`-backed) — **no**. Re-derive on the new leaf via
    the existing `assignFieldProps{Double,Int}OnLeaf` / `LookUpData` path
    (review §2); this supersedes the old flowdynamics `update*num_(map)`
    remapping. Likewise the per-cell `MaterialLawParams` vector
    (`EclMaterialLawManager::materialLawParams`,
    `EclMaterialLawManager.hpp:103,123,222-231`): phase 2 re-runs
    `readMaterialLawParams_()` (`FlowProblem.hpp:1451-1455`) rather than
    remapping params objects — which is also *why* hysteresis memory (stored
    inside those params) needs its own policy (see "Explicit state" below).
  * *Evolving per-cell state* (the solution + the explicit-state inventory
    below) — these are the only candidates for the id-backed
    `PersistentContainer`; phase 1 carries them in the stable-id maps.

### Decision points recorded

- `setRestart` global-index semantics on a refined leaf: serial leaf-order
  injection sidesteps it; parallel needs the composite-id scheme (phase 3).
- Explicit state per S5b: hysteresis (+PPCW) hard-guarded off; envelope
  scalars transferred with `max`/`min` ops; DRSDT state and tracer reset;
  aquifer state reset in phase 1.
- Adaptive-timestep controller history: reset at each adaptation event.

### Phase-1 effort

S0 + S1 + S2 are days each; S3–S5 about a week including the unit tests; S6a-1
days, S6a-2 (multi-LGR lift) and S6c a few days each, S6b about a week with its
anchor test; S7/S7b days on top of S0's mark plumbing. A working serial
demonstrator with well zones: **3–4 weeks**; without S6b/S7b (trajectory wells
only, scripted marks): **1–2 weeks**.

---

## Phase 2 — in-place rebuild (same semantics, no re-construction)

Only when phase 1's rebuild cost or output-restart bothers us. Keep the
`Simulator` alive and do explicitly what the fem `adaptGrid()` does (review
§1.3):

1. Grid: `CpGrid::clearRefinement()` (new, small: pop `data_` back to level 0,
   reset `lgr_names_`/id-set registrations) + refine to the new mark set —
   grid object identity preserved, the vanguard's reference stays valid.
2. Vanguard refreshers (exist): `updateGridView_`,
   `updateCartesianToCompressedMapping_`, `updateCellDepths_`,
   `updateCellThickness_`.
3. Rebind the two `lookUpData_` members (drop `const`, recreate from the new
   gridView) and call `transmissibilities_.update(true, All, …)` — the
   GEO_MODIFIER path, verbatim.
4. Model: `elementMapper_.update()`, resize `solution_[t]`, `finishInit()`,
   `resetLinearizer()`, `resizeAndResetIntensiveQuantitiesCache_()` — the
   femadapt sequence, written out.
5. Wells: nothing — `beginReportStep` re-derives (plus the S6 replay).
6. Writer: reconstruct `EclWriter`/`CollectDataOnIORank`, or the
   level-0-reporting mode (S9).
7. State transfer: identical to phase 1 — same extract/remap functions. In
   addition, adopt the DUNE adaptation protocol properly (see the DUNE-machinery
   decision above): honest `preAdapt()/adapt()/postAdapt()` with
   `mightVanish`/`isNew`, and an **id-backed `PersistentContainer<CpGrid>`**
   (today it is leaf-index-backed, `cpgrid/PersistentContainer.hpp:16-33`, and
   not actually persistent) — so the standard non-fem DUNE restrict/prolong
   idiom works on this grid and the transfer can migrate from external maps to
   the protocol when convenient.

## Phase 3 — performance and generality (as needed)

- **Grid-side incremental adapt**: cache unchanged level grids across re-adapts
  (marks monotone per event), only build new boxes + re-stitch the leaf — cuts
  the measured 0.7–0.9 M cells/s full-rebuild cost for small deltas.
- **Parallel**: rank-interior refinement per adapt event (exists for the static
  path); adaptation events collective (same marks on all ranks, boxes
  constrained to rank interiors); occasional redistribute-from-Layer-A as the
  load-balance escape valve (`REDISTRIBUTION-requirements.md`). The stable-id
  keying is already partition-invariant, so the S3–S5 transfer generalizes.
- Tracer/aquifer/hysteresis transfer with the same two primitives; multi-level
  nesting for deeper grading; A2 edge/corner mosaic if ring-based grading is
  ever preferred over nesting.

---

*Working document; not committed. Evidence and file:line anchors:
[DYNAMIC-REFINEMENT-FLOW-REVIEW.md](DYNAMIC-REFINEMENT-FLOW-REVIEW.md).
Companions: [REFINEMENT-ALGORITHM.md](REFINEMENT-ALGORITHM.md),
[lgr_review.md](lgr_review.md) Part VI, [WELLTRAJ_LGR_STATUS.md](WELLTRAJ_LGR_STATUS.md),
[NESTED_LGR_PLAN.md](NESTED_LGR_PLAN.md), [LGR_GAPS.md](LGR_GAPS.md).*
