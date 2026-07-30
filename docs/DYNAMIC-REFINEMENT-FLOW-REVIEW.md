# Dynamic refinement in flow — review of prior art and existing machinery

Companion to [DYNAMIC-REFINEMENT-FLOW-PLAN.md](DYNAMIC-REFINEMENT-FLOW-PLAN.md)
(the implementation plan). This file holds the *evidence*: what was tried before,
what flow already re-derives mid-run, which objects are bound at construction, and
where the reusable seams are — all with `file:line` anchors into the actual
branches so the plan can stay short.

State reviewed (2026-07-21): opm-simulators branch `adaptive-cpgrid-class`
(local), opm-gridrefined `adaptive-cpgrid-class`; prior art in
`hnil/flowdynamics`, `hnil/non_dunefem_default`,
github.com/hnil/opm-flowdynamicgrid, and the ElyesAhmed fork branches
`adaptivity`, `adaptivity2`, `adaptiveflowdynamics`, `flowdynamics_main`.

---

## 1. Prior art

### 1.1 `hnil/flowdynamics` (opm-simulators, ebos-era, dune-fem path)

Touches 16 files (~400 lines): `eclalugridvanguard.hh`, `eclproblem`/
`eclgenericproblem_impl.hh`, `eclgenerictracermodel`, `initstateequil`,
`BlackoilWellModel*`, `ISTLSolverEbos`, the simulator loop. Two ideas survive
into the plan:

- **Per-subsystem `gridChanged()` re-derivation.** It added
  `BlackoilWellModel::gridChanged()` (re-derive `local_num_cells_`, PVT region
  index, depths) and `EclGenericProblem::updatePvtnum_/updateSatnum_/
  updateMiscnum_(map)` — field-prop re-mapping through a cell map. The pattern
  "each grid-dependent component re-derives from the current grid on demand" is
  exactly right; today's flow already does this per report step for most
  components (§2), so much of that branch is now unnecessary.
- **What to avoid.** The transfer itself rode on ALUGrid + dune-fem
  (`PersistentContainer` with pre/post-adapt indices, `RestrictProlong`), which
  drags in the fem discrete-function stack and bypasses CpGrid's ECL/parallel
  machinery. `hnil/non_dunefem_default` (make the non-fem discretization the
  default even with dune-fem installed) points the same direction the plan goes.

### 1.2 The ElyesAhmed branches (the furthest this line got)

`elyes/flowdynamics_main` is the continuation of the same work (shares its tip
commits with `hnil/flowdynamics`), and its history is a candid record of where
the difficulty concentrated:

- *Wells were the pain point.* The commit sequence "added mapping for cells of
  wells to active grid indexes — **work if well cell do not get refined**" →
  "cleaner mapping implementation" → "removing wellmapping functions" shows
  hand-maintained old→new well-cell maps that could not survive refining a well
  cell, eventually abandoned. The plan dissolves this problem by adapting at
  report-step boundaries, where `initializeWellPerfData` re-derives all
  perforation indices from the Schedule against the current grid — and by
  replaying well *trajectories* instead of mapping old connections (§5).
- *Property/output mapping fought bound-at-construction objects.* The earlier
  `elyes/adaptivity`/`adaptivity2` (2021–2023, ALUGrid + dune-fem, "WIP hack to
  make adaptivity work") carried properties across adapt in a fem
  `PersistentContainer` (`container_`) and had to patch
  `alucartesianindexmapper`, `collecttoiorank`, the vanguard — the same
  construction-time-bound objects identified in §2. Re-deriving properties from
  `EclipseState` via `LookUpData` (which static LGR now does anyway) replaces the
  container approach; full reconstruction (plan phase 1) sidesteps the
  mapper/output patching entirely.
- `elyes/adaptiveflowdynamics` additionally fought dune-fem/ALUGrid template
  instantiation issues (TransFluxModule) — cost that simply disappears without
  fem.
- "few fixes towards **parallel** ALUGRID" is where the line stopped — parallel
  adaptivity on ALUGrid loses CpGrid's ECL output/wells machinery, which is the
  structural reason the plan stays on CpGrid.

### 1.3 The in-tree dune-fem `adaptGrid()` — the best specification of the job

`fvbasediscretizationfemadapt.hh:122-155` is the only working `adaptGrid()`
implementation, and even though the plan won't use it, its sequence *is* the
contract a non-fem replacement must satisfy:

mark → `adaptationManager().adapt()` (solution transfer via the
`RestrictProlong` tuple, `:88-89`) → `elementMapper_.update()` `:134` →
`vertexMapper_.update()` `:135` → `resetLinearizer()` `:136` → `finishInit()`
`:141` (comment: "supposes Problem::finishInit() works fine multiple times") →
`problem().gridChanged()` `:147` → output `allocBuffers()` `:150-152`.

Hook plumbing: `enableGridAdaptation_` from `Parameters::EnableGridAdaptation`
(`fvbasediscretization.hh:401,440`); base `adaptGrid()` is a throwing stub
`:1443`; fired from `advanceTimeLevel()` `:1481-1497`; note the guard
`:1841-1844` restricting adaptation with auxiliary modules (the well model is
one) — a reason the plan adapts at report-step boundaries instead of inside the
models-layer hook.

### 1.4 `opm-flowdynamicgrid` (github)

An empty module skeleton (3 commits, empty `MAIN_SOURCE_FILES`, commented-out
`flow_test.cpp` examples) — the "thin app repo" pattern, never populated. Usable
as a host later; contains no algorithmic content to port.

### 1.5 This branch's `flow_blackoil_adaptive` (init-only refinement)

`flow/flow_blackoil_adaptive.cpp` defines TypeTag `FlowProblemAdaptive`
(TpfaLinearizer, `Vanguard = AdaptiveCpGridVanguard`).
`AdaptiveCpGridVanguard::addLgrs()` (`AdaptiveCpGridVanguard.hpp:78-128`)
refines a CARFIN-less deck **at init** from `--adaptive-lgr` boxes through the
same `addLgrsUpdateLeafView` machinery as a deck CARFIN, then refreshes the
vanguard bookkeeping: `updateGridView_()`, `updateCartesianToCompressedMapping_()`,
`updateCellDepths_()`, `updateCellThickness_()` (`:124-127`). No per-timestep
re-refinement — but it is the template for "refine + refresh" the dynamic driver
re-invokes mid-run.

---

## 2. What flow already re-derives vs. what is bound at construction

Flow's design already assumes grid-derived state can be recomputed mid-run —
because schedule events force it to:

| Component | Re-derived when | Where |
|---|---|---|
| Well perforation cell indices | **every report step** | `BlackoilWellModel::beginReportStep` → `initializeWellPerfData()` → `compressedIndexForInterior(LGR)` (`BlackoilWellModel_impl.hpp:199-266`, `BlackoilWellModelGeneric.cpp:337-400`) — already LGR-aware (COMPDATL) |
| Transmissibility | on GEO_MODIFIER / ACTIONX | `FlowProblem::beginEpisode` `:317-342`, `FlowProblemBlackoil.hpp:562-576` → `transmissibilities_.update(true, All, …)`; builds a **fresh ElementMapper each call** (`Transmissibility_impl.hpp:177-187`) and is LGR-leaf-aware (`getParentIntersectionFromLgrBoundaryFace`, `:1033`) |
| Field props on the leaf | on demand | `assignFieldProps{Double,Int}OnLeaf` via `LookUpData` (`FlowProblem.hpp:1397-1415`) — reads live from `eclState.fieldProps()` |
| Reference porosity, PFF data, linearizer params | after trans update | `FlowProblem.hpp:338-342` |
| Solution-side re-init entries | exist, re-callable | `finishInit()` (femadapt calls it twice), `resetLinearizer()` (`fvbasediscretization.hh:1621`), `resizeAndResetIntensiveQuantitiesCache_()` `:1918` |

**Bound at construction** (no refresh entry):

- `lookUpData_` — a `const` member bound to the construction-time gridView, in
  both `FlowGenericProblem` (`:377`) and `Transmissibility` (`:302`).
- `EclWriter` / `CollectDataOnIORank` — all output index machinery computed once
  in the ctor (`CollectDataOnIORank_impl.hpp:841-970`).
- `FvBaseDiscretization` mappers/caches/solution sizes (recipe exists but is only
  orchestrated in the fem path, §1.3).
- The aux-module guard (`fvbasediscretization.hh:1841-1844`).

**Conclusion carried into the plan:** the models-layer `adaptGrid()` hook is the
wrong place for the minimal version; the **report-step boundary** is the natural
adaptation point, and there the truly minimal implementation is full
reconstruction ("restart-in-memory") — every bound-at-construction object is
simply constructed correctly.

---

## 3. State carriers: restart-solution path vs. OPMRST serializer

### Option A — the ECL restart-solution path (chosen)

Chain: `FlowProblemBlackoil::readEclRestartSolution_` (`FlowProblemBlackoil.hpp:1309`)
- `:1312-1314` — the "Refined grids are not yet supported for restart" throw is a
  pure grid check at the top of the *file-reading* wrapper; the array→state
  machinery below it is grid-agnostic.
- `:1323-1327` — sets clock/episode (`setTime(schedule.seconds(step))`,
  `setEpisodeIndex(step)`).
- `EclWriter::beginRestart` `:559` reads the `.UNRST` and lands the arrays in the
  OutputModule's per-cell buffers via
  `setRestart(sol, elemIdx, globalIdx)` (`GenericOutputBlackoilModule.cpp:483`);
  fields consumed: PRESSURE, SWAT, SGAS, TEMP, RS, RV, RSW, RVW + hysteresis
  (SOMAX/SGMAX/SHMAX/SWHY1/…) + PPCW.
- `readSolutionFromOutputModule(step, false)` (`FlowProblemBlackoil.hpp:1079`) is
  the **array→state converter**: per element `assignToFluidState`
  (`OutputBlackoilModule.hpp:534` — reads only the buffers), then
  `processRestartSaturations_` (clamping, `:1569`), then writes
  `model().solution(0)` via `initial(...)` (`:1160-1167`).

**Injection seam:** build an in-memory `data::Solution`, call `setRestart` per
cell, then call `readSolutionFromOutputModule` directly — bypassing
`beginRestart()` and the LGR throw entirely. Alternative mirror:
`readExplicitInitialCondition_` (`:1354-1566`) shows the same arrays→fluid-state
assembly without the writer.

### Option B — the OPMRST HDF5 save/load

`SimulatorSerializer.{hpp,cpp}` + `HDF5Serializer`; parameters
`SaveStep/SaveFile/LoadFile/LoadStep` (`SimulatorFullyImplicit.cpp:46-64`).
Serializes the ebos `Simulator` (solution vectors + problem + writer/output
module), the report, and the adaptive-timestep controller
(`SimulatorFullyImplicit_impl.hpp:554`); load seam at `:328-332`
(`prepareDeserialize` → `loadState` → invalidate intensive quantities).

**Format is positional** — raw dense per-cell vectors in current compressed-cell
order; the only shape guard is a grid-hash check *in parallel only*
(`SimulatorSerializer.cpp:118-167`); a serial load of a changed grid would be
silently misinterpreted. No remap hook exists.

**Verdict:** B is higher-fidelity on an *unchanged* grid (bit-exact solver
state), but A already speaks per-cell field arrays that map naturally onto a
re-refined grid — A is the remap-friendly carrier. (Documented tolerance: A
round-trips through `processRestartSaturations_` clamping.)

---

## 4. Driver lifecycle

- **Separable phases exist** (the Python step API):
  `FlowMain::executeInitStep()` (`FlowMain.hpp:182-185`), `executeStep()`
  (`:189-192`), `executeStepsCleanup()` (`:196-201`), `getSimulatorPtr()`
  (`:203`), `getSimTimer()` (`:208`). `Simulator::run` itself is
  `init + while(!done) runStep + finalize` (`SimulatorFullyImplicit_impl.hpp:102-140`).
- **Deck reuse without re-parse:** `Main` holds `eclipseState_`, `schedule_`,
  `summaryConfig_` as `shared_ptr` members (`Main.hpp:585-587`);
  `Main::setupVanguard()` copies them into the static
  `FlowGenericVanguard::modelParams_` (`Main.cpp:372-381`), which the vanguard
  ctor **moves from** (`FlowGenericVanguard.cpp:108-109, 202-203`). A second
  simulator instance therefore just re-populates `modelParams_` from the
  driver's own `shared_ptr` copies.
- **Positioning at report step N:** `simtimer_->init(schedule, N)` /
  `setCurrentStepNum(N)` (`SimulatorTimer.cpp:70-86`; normally driven by
  `InitConfig::getRestartStep()`, `FlowMain.hpp:439-443` — the driver can set the
  timer directly and avoid touching the deck's `InitConfig`). Episode/clock are
  set as in §3-A (`:1323-1327`); `runStep` re-asserts
  `setEpisodeIndex(timer.currentStepNum())` (`SimulatorFullyImplicit_impl.hpp:115`).

---

## 5. Well machinery

### 5.1 Well-state restore / perforation re-derivation

`BlackoilWellModel::prepareDeserialize(report_step)`
(`BlackoilWellModel.hpp:200-205` → `BlackoilWellModelGeneric.cpp:265-285`):
rebuilds `wells_ecl_` from `schedule()[step]`, re-runs
**`initializeWellPerfData()`** `:273` — which recomputes every connection's
active cell against the *current* grid via
`compressedIndexForInterior(connection.global_index())` `:375` (LGR variant
`compressedIndexForInteriorLGR` `:374`) — and resizes `wellState()` `:277-279`.
It does not restore well solution values; those come from the serialized well
state (B) or `initFromRestartFile(restartValues)` (A path).

### 5.2 How connections are derived (COMPTRAJ pipeline, Peaceman, `ctf_kind`)

- **WELTRAJ** stores the survey (X, Y, TVD, MD) on `WellConnections`
  (`GridIndependentWellKeywordHandlers.cpp:195`, `WellConnections.cpp:1133-1152`);
  no grid involved.
- **COMPTRAJ** → `WellConnections::loadCOMPTRAJ` (`WellConnections.cpp:710-948`):
  interpolate perforation top/bot from MD (`:753-757`), intersect the polyline
  with the grid via the ResInsight-derived
  `RigEclipseWellLogExtractor{path, EclipseGrid, tree}` (`:781-791`); per
  intersected cell get entry/exit, `startMD/endMD`, and
  `intersectionLengthsInCellCS` (the in-cell length vector,
  `RigWellLogExtractor.h:37-51`); cell props come from the `CompletedCells`
  cache via `ScheduleGrid::get_cell` (`:823`; LGR population
  `ScheduleGrid.cpp:266-291`). Produces per connection: ijk, global index,
  depth, direction (hard-coded Z for trajectories, `:900`), and
  `Connection::CTFProperties` {CF, Kh, Ke, rw, r0, re, `connection_length`
  (`:886`), skin, d-factor, peaceman_denom} (`Connection.hpp:95-165`).
- **Peaceman helpers** (anonymous namespace, `WellConnections.cpp`):
  `effectiveRadius` (r0 with the 0.28 constant; perpendicular perms + cell
  extents, `:181-198`), `peacemanDenominator` (`log(r0/rw)+skin`, `:200-210`),
  `effectiveExtent` (NTG scales vertical, `:120-135`), `permThickness`
  (`:234-259`), `connectionFactor` (`2π·Kh/denominator`, `:261-292`). COMPTRAJ's
  CF/Kh are the 3-directional magnitudes weighted by the in-cell length vector
  (`:880-895`). **Cell quantities entering: permx/permy/permz, dx/dy/dz, ntg**,
  plus per-connection rw and skin.
- **Deck-given vs computed** — `ctf_kind`: COMPDAT decision `:539-590` (both
  CF>0 and Kh>0 → `DeckValue`, `peaceman_denom = 2π·Kh/CF`; else Peaceman →
  `Defaulted`); COMPTRAJ decision `:863-903` (both-or-neither, else throws).
- **The simulator uses the parsed CF; it does not re-run Peaceman.**
  `Connection::CF()` → `PerforationData::connection_transmissibility_factor`
  (`BlackoilWellModelGeneric.cpp:396`) → `well_index_`
  (`WellInterfaceGeneric.cpp:106-113`), scaled only by the rock-compaction
  multiplier (`WellInterface_impl.hpp:2047-2073`). Only the runtime-fracturing
  path synthesises CFs (`RuntimePerforation.hpp`).
- **No CF-splitting code exists anywhere** — nothing divides a CF across
  sub-cells or by length fraction; same-cell duplicate connections are
  *replaced*, not summed (`WellConnections.cpp:919-946`). Re-derivation, not
  scaling, is the in-tree idiom — which is exactly what the replay machinery
  below provides.

### 5.3 The welltraj-LGR replay machinery (the reusable core) and its gaps

Built on `new_lgr` (originally branch `welltraj-lgr-postproc`; see
`WELLTRAJ_LGR_STATUS.md`):

- `external::RigEclipseWellLogExtractorGrid`
  (`opm-common/opm/input/eclipse/Schedule/WellTraj/…`) — geometry-fed sibling of
  the extractor: takes a flat `vector<array<Vec3d,8>>` of per-cell corners
  instead of an `EclipseGrid` (same AABB tree + hex intersection; OPM→ResInsight
  permutation `{0,1,3,2,4,5,7,6}`).
- `WellConnections::TrajPerf` — parse-time-retained per-COMPTRAJ-record
  parameters (perf top/bot, rw, skin, d-factor, user Kh/CF, sat table, state;
  `WellConnections.hpp:255-279`) — together with the retained, serialized
  survey (`coord`/`md`) this makes the derivation **replayable at any report
  step against any grid geometry**.
- `WellConnections::recomputeTrajectoryConnections(cellCorners, cellInfo)`
  (`WellConnections.cpp:1054-1131`) — clears and rebuilds the connection set;
  per intersection calls the caller-supplied `cellInfo(idx)` →
  `TrajectoryCell` {ijk, global index, depth, perm[3], dimensions[3], ntg,
  satnum, lgr name/grid} (`WellConnections.hpp:141-152`) and
  `addOrUpdateTrajectoryConnection` (`:959-1051`, same Peaceman calls as §5.2).
- `Schedule::recomputeTrajectoryConnections` (`Schedule.cpp:1333-1396`) — per
  snapshot, per trajectory well; single-LGR tagging at `:1369-1382`;
  **crossing >1 LGR currently warns and bails** (`:1384-1390`).
- Simulator driver `CpGridVanguard::recomputeWellTrajectoriesInLgr_()`
  (`CpGridVanguard.hpp:660-796`), called from `addLgrs()` `:633` after the
  Cartesian↔compressed map refresh: feeds leaf corners (`:708-717`) and cell
  info with **perm/ntg/satnum inherited from the parent coarse cell but true
  refined-cell dimensions** (`:727-742`) — so the Peaceman CTF is computed for
  the refined cell; encodes LGR-local ijk/grid number (COMPDATL convention,
  `:744-767`). Downstream resolution via `compressedIndexForInteriorLGR`
  (`CpGridVanguard.hpp:140-165`).

**Gaps for dynamic use** (closed by the plan): (1) the adaptive vanguard never
calls the recompute — `Base::addLgrs()` only runs it inside the deck-CARFIN
branch (`CpGridVanguard.hpp:584-633`), which a CARFIN-less adaptive deck skips;
(2) the single-LGR restriction (`Schedule.cpp:1369-1390`) — load-bearing for
graded well zones, where a well crosses a nested LGR *and* its parent.

---

## 6. Explicit-state inventory (non-primary per-cell state)

Beyond primary variables, flow keeps per-cell "explicit" state updated outside
the Newton solve. **Architectural fact:** all of it is refreshed at
**beginTimeStep**, through one funnel — `FlowProblem::beginTimeStep()` →
`updateExplicitQuantities_(...)` (`FlowProblem.hpp:366,383`; pure-virtual
`:1636`; blackoil override `FlowProblemBlackoil.hpp:1210` → body `:1659-1681`,
which runs `updateMaxWaterSaturation_`, `updateMinPressure_`,
`updateHysteresis_`, `updateMaxOilSaturation_`, DRSDT/DRVDT, rock-comp trans
mult, and — in the extended override — `updateMaxPolymerAdsorption_` and
`mixControls_.updateExplicitQuantities`). Initial seeding from the initial
fluid state: `FlowProblem::readInitialCondition_()` `:1547-1557`.

### 6.1 The per-cell quantities

Storage is plain `std::vector<Scalar>` per grid dof in the CRTP base
`FlowGenericProblem` (`FlowGenericProblem.hpp:353-359`, serialized `:278-281`)
unless noted:

| Quantity | Container | Updated in | Consumer |
|---|---|---|---|
| maxOilSaturation (somax) | `maxOilSaturation_` `:354` | `updateMaxOilSaturation_` `FlowProblem.hpp:1299-1329` (per-cell max `:1322-1326`) | **VAPPARS**; SOMAX restart target; accessors `:978,:995` |
| maxWaterSaturation (swmax) | `maxWaterSaturation_` `:355` | `updateMaxWaterSaturation_` `:1331-1360` | water-induced **rock compaction** (poro mult `:1155-1158`, trans mult `:1803`) |
| minRefPressure | `minRefPressure_` `:356` | `updateMinPressure_` `:1362-1390` (init 1e99, `FlowGenericProblem_impl.hpp:241`) | irreversible rock compaction (`:1136-1140`, `:1785-1789`) |
| overburdenPressure | `overburdenPressure_` `:357` | static (OVERBURD at init) | rock-comp effective pressure `:1142-1143` |
| DRSDT/DRVDT limiter state | `lastRs_/maxDRs_/lastRv_/maxDRv_/…` in `MixingRateControls` (`MixingRateControls.hpp:202-208`) | `updateExplicitQuantities()` `MixingRateControls.hpp:92` via `FlowProblemBlackoil.hpp:1217` | dissolution-rate limiting in intensive quantities |
| polymer maxAdsorption | `polymer_.maxAdsorption` (`SolutionContainers.hpp:37-40`) | `updateMaxPolymerAdsorption_` `FlowProblemBlackoil.hpp:1220-1236` | irreversible adsorption → perm reduction |
| tracer concentrations | `GenericTracerModel::tracerConcentration_` — **own** `Dune::BlockVector`s (`GenericTracerModel.hpp:158-161`, serialized `:110`) | tracer begin/endTimeStep (`FlowProblem.hpp:392,448`) | tracer output; per-tracer restart keys (`EclWriter.hpp:598-605`) |
| filter cake | per **well connection** in `WellState` (`WellFilterCake.{hpp,cpp}`) — not grid state | well model | well restart path |

### 6.2 Hysteresis (the hard one)

- **Where it lives:** per cell inside the MaterialLawManager — the params
  vector `materialLawParams` (`EclMaterialLawManager.hpp:103,123`, accessor
  `:222-231`); each cell's params hold `oilWaterParams()`/`gasOilParams()`,
  each an `EclHysteresisTwoPhaseLawParams` whose per-cell memory is
  `pcSwMdc_`, `krnSwMdc_`, `krwSwMdc_`
  (`EclHysteresisTwoPhaseLawParams.hpp:279,304,320`; serialized `:682-683`),
  advanced by `EclHysteresisTwoPhaseLaw::updateHysteresis`
  (`EclHysteresisTwoPhaseLaw.hpp:591-619`). SWATINIT max-pc scaling is
  separate: `oilWaterScaledEpsInfoDrainage[elemIdx].maxPcow`
  (`EclMaterialLawManager.hpp:316`).
- **Enablement:** EHYSTR → `EclHysteresisConfig::initFromState`
  (`EclHysteresisConfig.cpp:31-44`) → `enableHysteresis()` etc.
  (`EclMaterialLawManager.hpp:185-195`); early-outs at
  `EclMaterialLawManager.hpp:274-279` and `FlowProblem.hpp:1566`.
- **Restart carry-through:** keys declared in `EclWriter::beginRestart`
  (`EclWriter.hpp:569-593`, enablement `:561-567`) → per-cell `setRestart`
  buffers (`GenericOutputBlackoilModule.hpp:426-432`) → applied back by
  `OutputBlackoilModule::initHysteresisParams` (`:586-649`):

| Key | Buffer | Applied to |
|---|---|---|
| SOMAX | `soMax_` | `setMaxOilSaturation` (always) + oil-water `somax` (nonwetting hyst) `:588-589,601-602` |
| SWMAX | `swMax_` | oil-water `swmax` (wetting) `:606-607,615` |
| SWHY1 | `swmin_` | oil-water `swmin` (PC hyst) `:611-612,615` |
| SGMAX | `sgmax_` | gas-oil `sgmax` `:625-626,639` |
| SHMAX | `shmax_` | gas-oil `shmax` `:630-631,639` |
| SOMIN | `somin_` | gas-oil `somin` `:635-636,639` |
| PPCW | `ppcw_` | `applyRestartSwatInit` (`EclMaterialLawManager.cpp:213-221`) `:645-647` |

  MLM sinks: `setOilWaterHysteresisParams`/`setGasOilHysteresisParams`
  (`EclMaterialLawManager.hpp:298-308`).
- **Guard site for "unsupported with adaptation":** the problem side — end of
  `readMaterialLawParams_()` (`FlowProblem.hpp:1451-1456`) or `finishInit` —
  where `materialLawManager_->enableHysteresis()` is queryable. The vanguard
  runs before the MLM exists, so the guard cannot live in `addLgrs()`.

### 6.3 Transfer-semantics consequence

These fields split into classes with **different restriction ops** under
coarsening: monotone envelopes (somax/swmax/maxAdsorption → `max`;
minRefPressure → `min`) where pv-averaging would silently violate
monotonicity; rate-limiter history (DRSDT state) with no meaningful spatial
reduction (reset); and hysteresis scanning-curve state, whose
prolongation/restriction semantics are genuinely unclear (phase-1: hard
guard). See the plan, section S5b.

**Pre-existing bug found in passing** (independent of adaptation, worth
reporting upstream): `FlowProblem.hpp:1338` executes
`maxWaterSaturation_[/*timeIdx=*/1] = maxWaterSaturation_[/*timeIdx=*/0]` —
the comments claim time indices, but the container is a flat per-cell vector,
so this reads/writes **cells** 0 and 1.

---

*Companions: [DYNAMIC-REFINEMENT-FLOW-PLAN.md](DYNAMIC-REFINEMENT-FLOW-PLAN.md)
(the plan built on this evidence), [REFINEMENT-ALGORITHM.md](REFINEMENT-ALGORITHM.md)
(builder pipeline), [lgr_review.md](lgr_review.md) Part VI (current grid-side
review), [WELLTRAJ_LGR_STATUS.md](WELLTRAJ_LGR_STATUS.md) (welltraj replay
status). Working document; not committed.*
