# Pull-request plan: status, content, and controversy assessment

Post-audit revision, **2026-07-29**. Supersedes the 2026-07-21 draft, which was
written *before* the "does this need fork-only opm-grid API?" audit and was
wrong in five places (§0). Companions: [`PR-SUBMISSION-GUIDE.md`](PR-SUBMISSION-GUIDE.md)
(mechanics — commands, PR body template, Jenkins triggers),
[`HANDOVER-UPSTREAM-PRS.md`](HANDOVER-UPSTREAM-PRS.md) (strategy and the
G1/G2/G3 reassessment), [`LGR_GAPS.md`](LGR_GAPS.md) (gap C5).

Every PR is a fresh branch off `upstream/master` with named commits
cherry-picked onto it. **The prototype branches (`dynamic-refinement`,
`new_lgr`, `adaptive-cpgrid-class`) are never touched.**

Controversy scale: **low** = mechanical fix, hard to object to; **medium** =
touches behaviour or design someone owns; **high** = challenges an upstream
design decision or replaces maintained code, needs an issue/RFC first.

---

## 0. Corrections to the 2026-07-21 draft

Recorded because the old text is still quoted in places:

1. **`26899fe9c` (AVX2 guard) is obsolete.** Upstream `793f988a1` (merged
   2026-07-20) is the same fix in the same two files —
   `StandardPreconditioners_mpi.hpp:36,170` already has `#if HAVE_AVX2_EXTENSION`.
   Dropped.
2. **`3ea533889` (HAVE_HYPRE) was 100% redundant, not 90%.** opm-common's
   `FindHYPRE.cmake:68,116` already puts `HAVE_HYPRE=1` on the imported
   target's INTERFACE, and — checked on a fresh configure — the definition
   reaches `flow_blackoil.cpp.o` even with the `PRIVATE` link, via the
   `simulators_add_target_options` property copy. The trimmed one-line PR
   (#7242) was therefore **closed unmerged**: the premise that `PRIVATE` hides
   the macro from the executables does not hold in this build system. Drop the
   commit entirely at the next prototype rebase.
3. **`af33a0e7a` cannot be cherry-picked.** Two of its four hunks patch code
   introduced by commits that are deliberately excluded (`fe4dc7f96`,
   `133cb128c`), so they have no pre-image on upstream. Its surviving
   `if constexpr (requires …)` guards must be folded into the rewritten
   `dbd57f3d5` instead.
4. **Nested LGR is Lane A, not Lane C.** Upstream `addLgrsUpdateLeafView`
   already takes `lgr_parent_grid_name_vec`
   (`opm-grid/opm/grid/CpGrid.hpp:501-505`), so the nested-LGR simulator trio
   needs no grid change.
5. **`81b36e513` must be held.** It is refine-before-redistribute only, and its
   `CpGridVanguard.hpp` hunk edits a block introduced by the excluded
   `6e15f740a`.

A sixth, process-level lesson: **fetch `upstream` in all four repos and check
the dates before cutting anything.** The `opm-grid` checkout's `upstream/master`
was a month stale (`0ff52dd4`, 2026-06-09 vs the real `8cb1da37`), and the first
baseline build failed on a `loadBalance` arity mismatch belonging to neither
upstream nor the branch. Re-verified against the true tip afterwards:
`setPartitionCellGroups`, `stableCellId`, `poisonRefinedGlobalCell`,
`leafHasParentCellIndices`, `GridStateWriter`, `Refinement::Builder` are all
still absent upstream, so the audit conclusions below stand.

---

## 1. The audit result

Of the 44 opm-simulators commits on `dynamic-refinement`, **38 work against
current upstream opm-grid master.** The one that looked like a hard blocker —
`dbd57f3d5`, parallel LGR output — used the fork's `GridStateWriter` *only* to
hand its builder retained COORD/ZCORN. Deleting ~10 lines leaves
`processEclipseFormat` + `addLgrsUpdateLeafView`, all upstream API
(`opm-grid/opm/grid/CpGrid.hpp:227,313,501`), running on upstream's own LGR
implementation.

The 13 opm-common commits have **zero** opm-grid dependency: no `opm/grid`,
`CpGrid` or `Dune::` reference anywhere in them. The trajectory-replay API is
type-erased through `std::function` + POD structs, which is the right shape for
a module that cannot depend on Dune.

The adaptive work needs no fork either — upstream exposes
`mark()/preAdapt()/adapt()/refineAndUpdateGrid()/postAdapt()`
(`CpGrid.hpp:565-606`).

---

## 2. Submitted 2026-07-29 — status as of 2026-07-31

All nine were built against a clean upstream sibling stack before submission,
and all passed CI. A milestone view of the same material, written for sharing
with the maintainers, is [`STATIC-LGR-UPSTREAMING.md`](STATIC-LGR-UPSTREAMING.md).

| PR | Content | Status |
|---|---|---|
| [opm-common#5249](https://github.com/OPM/opm-common/pull/5249) | remove 4 stray `std::cout` from the vendored `RigWellLogExtractor` | **merged** |
| [opm-common#5250](https://github.com/OPM/opm-common/pull/5250) | nested CARFIN: serialize `parent_name_grid`, validate against the parent LGR, + round-trip test | **merged** |
| [opm-simulators#7243](https://github.com/OPM/opm-simulators/pull/7243) | `ParallelOverlappingILU0` empty parallel partition | **merged** |
| [opm-simulators#7242](https://github.com/OPM/opm-simulators/pull/7242) | link Hypre `PUBLIC` | **closed unmerged** — premise wrong, see §0.2 |
| [opm-common#5251](https://github.com/OPM/opm-common/pull/5251) | `RegionCache`: skip LGR-completed connections | open, awaiting review |
| [opm-common#5252](https://github.com/OPM/opm-common/pull/5252) | INIT/UNRST LGR sections in EGRID order + per-LGR integer maps | open, awaiting review |
| [opm-simulators#7244](https://github.com/OPM/opm-simulators/pull/7244) | map EQLNUM/PVTNUM/SWATINIT/FIP region arrays onto the leaf | open, awaiting review |
| [opm-simulators#7245](https://github.com/OPM/opm-simulators/pull/7245) | LGR well cells + serial summary + rank-asymmetric throw | open — akva2 approved, **blattms changes-requested**, needs rework (below) |
| [opm-grid#1053](https://github.com/OPM/opm-grid/pull/1053) | bound the Cartesian→compressed lookup | open — narrowed after changes-requested; parked at no cost |

The `manual:*` label is mandatory — a required CI job
(`verify-pr-label-action`) fails without one of `manual:bugfix` /
`manual:enhancement` / `manual:new-feature` / `manual:irrelevant`.

### Review outcomes

**opm-simulators#7245 — reworked 2026-07-30 per review.** akva2 approved with
small suggestions; blattms requested changes. The inline comments were more
specific than the top-level review and fixed the design for us:

- **The map** (blattms's own proposal, adopted verbatim): "only add entries
  for unrefined cells. Then it would be a mapping for existing cells on
  level 0 only." `updateCartesianToCompressedMapping_` now skips
  `element.hasFather()` cells and clears the map on rebuild. A refined-away
  level-zero index resolves to "not present" (→ the existing cells-not-found
  handling) instead of to an arbitrary child — on a refined grid a level-zero
  Cartesian index is not a unique key, since every child reports its
  ancestor's index and the last insert used to win. The rebuild after
  refinement stays (leaf renumbering makes the old entries stale).
- **`compressedIndexForInteriorLGR`** (blattms: "should be fatal … we are
  just hiding it"): misses are now separated. Name unknown → fatal — every
  rank registers every requested LGR with an empty level grid where it holds
  no box cells (verified: the `lgr_names_` fill at opm-grid `CpGrid.cpp:2283`
  runs for all requested levels), so the level structure is rank-identical
  and a name miss is a programming error. (i,j,k) outside the LGR dims →
  fatal. Cell absent from this rank's level mapper → −1, the one legitimate
  miss, mirroring `compressedIndexForInterior`'s contract. The
  "rank-interior / owning rank" comment language (a fork-model leak blattms
  flagged) is gone: upstream refines every rank's copy, interior and overlap.
- **akva2's dedupe**: the post-grid-change block is now
  `updateDerivedGridState_()` shared by `loadBalance()` and `addLgrs()`; the
  output-support condition is one private helper
  `eclOutputEvalSupported_()` used at both `FlowProblemBlackoil` sites.

Consequence to remember: a coarse COMPDAT connection *inside* a refined box
now resolves to "not present" (clear error) rather than an arbitrary child.
Same for aquifer cells inside refined boxes (AquiferNumerical/ConstantFlux
treat −1 as not-on-rank). Both were silently wrong before; if such decks need
to work, that is COMPDATL's job.

**opm-grid#1053 — narrowed after changes-requested.** blattms: "10 steps ahead
of our schedule … some of this code is more dangerous than before." Both
points were valid — the original patch also silently dropped out-of-range
*level-zero* connections, converting a sanitizer-detectable read into silent
graph corruption. Now only the bounds check, routed into the existing
inactive-cell test; the refinement-level half is deferred and recorded as gap
**C5** in [`LGR_GAPS.md`](LGR_GAPS.md). Unlocks nothing in flight; can be
parked or closed.

**Status 2026-07-31.** #7245 was reworked per every inline comment (map
restricted to unrefined cells — Markus's own proposal; fatal/−1 split in the
LGR lookup; both duplicated blocks factored into helpers) and force-pushed
with a point-by-point reply; his CHANGES_REQUESTED stands until he re-reviews.
The nested-CARFIN half of #5250 was split out on review request as **#5256**;
its reviewer (arturcastiel) is out of office until ~mid-August, which also
stalls #5251/#5252 — he owns that output code. #5251, #5252 and #7244 have no
reviews yet. `dynamic-refinement` was restructured (see PR-SUBMISSION-GUIDE)
and now builds and runs against upstream opm-grid end to end, so S5 can be
cut and verified at any time; it stays unsubmitted until #7245 settles
because it edits the same files.

**Standing maintainer signal (blattms): make the simple cases work first.**
Sequencing below follows that: serial correctness → serial output → parallel
output → wells-in-LGR at scale.

---

## 3. Next waves

### Wave 2 — after their parents merge

| ID | PR | Commits | Depends on |
|---|---|---|---|
| C3 | `pr/welltraj-replay-core` | `85b21ed6a`, `f59228a3f` + **`e14fbff58` squashed in**, `25e01aed3` | — (but needs the extractor refactor below) |
| C4 | `pr/welltraj-lgr-encoding` | `5b704263f` + `218ceaf37` + `636ba6cd5`, **squashed** | C3 |
| S5 | `pr/parallel-lgr-output-collection` | `3dfc9c0e2`, `a695c91f7`, `dbd57f3d5`\*, `f2afeb6e3`, `02937cd90` | the **reworked** #7245 — same files, and the rework (leaf-direct lookup instead of map rebuild) changes S5's baseline; do not cut S5 until #7245's shape settles |
| S6 | `pr/lgr-well-partitioning-diagnostics` | `608dc5fb3`, `2a1de22b4` | #1053 (safety, not compile). Touches well representation during load balancing — per blattms's simple-cases-first signal, this goes **after** serial+parallel output land, not in parallel with them |
| S7 | `pr/nested-lgr-parent-name` | `f1b026e7b` + `aeee14882` + `8cd6342bf`, **squashed** | ~~#5250~~ merged ✓; opm-tests nested decks still needed |

**C3 blocking work.** `RigEclipseWellLogExtractorGrid.{cpp,hpp}` is a 339-line
near-verbatim derivative of the vendored ResInsight-derived
`RigEclipseWellLogExtractor`, with the `Copyright (C) Statoil ASA` /
`Copyright (C) Ceetron Solutions AS` lines and the "based on ResInsight" note
dropped. *Attribution restored 2026-07-31* (opm-common `dynamic-refinement`,
`d035bdd48`): both files now carry the Statoil/Ceetron lines and an explicit
derivation note. The duplication itself remains; folding into the existing
class is still the better end state. Fold the geometry-fed path into the existing
class as a second constructor taking a flat cell-corner list — the classes
differ by ~30 semantic lines out of 250 — which removes the duplication and the
attribution problem together. Also extend
`WellConnections::serializationTestObject()` with `coord`/`md`/`m_traj_perfs`
and add `m_traj_perfs` to `operator==`; today the new serialized field
round-trips empty and is not compared, so the test passes with
`serializer(m_traj_perfs)` deleted. Consider replacing the dense
`std::vector<std::array<std::array<double,3>,8>>` corner argument (192 B/cell →
~1.9 GB at 10M cells, copied again internally once per well per snapshot) with a
lazy accessor while the signature is being touched.

**S5 rewrite work.** Delete `GenericCpGridVanguard.cpp:37` and the
`retained`/`setRetainedCornerPointInput` lines; fold in the surviving
`af33a0e7a` guards (§0.3) rather than cherry-picking it; rewrite `02937cd90`'s
message — it is *not* refine-before-only, `haveLgrCellOutput` gates on
`grid_.maxLevel() > 0`, which is false on the I/O rank whenever rank 0 owns no
LGR box, so it fixes a real partition-dependent output loss; flip
`spe1case1_carfin_parallel` in `compareECLFiles.cmake:659` to
`--enable-ecl-output=true`, which is the proof in upstream's own CI.

### Wave 3

| ID | PR | Commits | Depends on |
|---|---|---|---|
| C5 | `pr/synthesize-trajectories` | `7d9388cdc` minus the `external/resinsight` hunk (already in #5249) | C3, C4 |
| S8 | `pr/welltraj-lgr-vanguard` | `56b542102`, `5cf626fae`, `ca956e831`, `c150e4191`, `e8f5f1135` | C3, C4, #7245 |

**S8 manual edit:** `56b542102` inserts `recomputeWellTrajectoriesInLgr_()`
immediately before the poison-canary block from the excluded `7a116a931`, so its
trailing context will not match. Reposition the call to the end of `addLgrs()`
(upstream `CpGridVanguard.hpp:281-291`).

**Check before submitting:** `e8f5f1135` (CPR sparsity reserve) may be a
genuine upstream bug independent of LGR — `getMaxWellConnections()` can
disagree with the actual perforation cells for wells filtered by ACTNUM/MINPV
too. If confirmed, promote it to a standalone bugfix.

### Wave 4 — adaptive, deck-driven

The `--adaptive-lgr` command-line spec string is **superseded**. `LGRON` and
`LGROFF` are already SCHEDULE-section keywords in opm-common's parser
(`opm/input/eclipse/share/keywords/000_Eclipse100/L/{LGRON,LGROFF}`, with a
`LOCAL_GRID_REFINMENT` name argument) and are **parsed then silently ignored** —
nothing outside the generated parser references them. So a fully standard deck
can declare the geometry with `CARFIN` in GRID, switch it off before the first
`TSTEP` with `LGROFF 'LGR1' /`, and switch it on at a later report step with
`LGRON 'LGR1' /`.

| ID | PR | Content |
|---|---|---|
| A1 | opm-common `pr/lgron-lgroff-schedule` | **SUBMITTED as [#5263](https://github.com/OPM/opm-common/pull/5263)** (2026-07-31, reviewers bska+akva2, `manual:new-feature`): `ScheduleState` name→active map with `lgr_active()` defaulting to active, persistent across steps, serialized+compared (round trip verified to fail with the field dropped); name validated against the grids' LGR label table via new `ScheduleGrid::has_lgr`, unknown name → `OpmInputError` at the keyword location; defaulted name rejected, well-activation item warned+ignored. Consumers diff `lgr_activation()` between steps. |
| A2 | opm-simulators `pr/schedule-driven-lgr` | rebuild the grid with upstream `addLgrsUpdateLeafView` when the active set changes; built from `859075bf9` plus the world-rebuild/state-transfer machinery of `585235396` / `05f7d1823`, rewritten to be driven by `Schedule`. Remove the `setBuilder`/`ConformingBlockBuilder` block (`AdaptiveCpGridVanguard.hpp:33-34, 96-124`) — the vanguard gets ~25 lines shorter. Reproduce `stableCellId` locally from public API (`CpGrid.cpp:716-724` + `Entity.hpp:326`) and **assert `maxLevel() <= 1`**, since `getIdxInParentCell()` is the index in the *immediate* parent and the pair is not injective deeper. Gate behind `option(BUILD_FLOW_SCHEDULE_LGR ... OFF)` with its own `opm_add_library`/`opm_add_executable` pair — **not** `FLOW_MODELS`, which would link an extra blackoil TypeTag into `flow` and `flow_distribute_z` for code nothing dispatches to. State the known limits honestly: group/well cumulative accumulators diverge across the rebuild and `WellTestState` restarts empty. |
| A3 | `--adaptive-lgr` option | **held, needs rethinking.** Superseded by the deck-driven trigger; revisit only as a convenience for non-deck experiments, after A1/A2. |

Demonstrator deck (new opm-tests PR): SPE1-style, `CARFIN` in GRID, `LGROFF`
before the first `TSTEP`, `LGRON` at a later step. Two claims to prove: with
`LGRON` at step 0 the run is **bit-identical** to static `SPE1CASE1_CARFIN1`
(15 steps / 52 Newton / 64 linear); with `LGRON` at step N it is stable, mass
balance holds across the rebuild, and it converges to the static answer.

---

## 4. Held back

| What | Commits | Why |
|---|---|---|
| **G3 `setPartitionCellGroups`** + the LGR-aware partitioning trio | `1c1112c93`, `b2df887de`, `b6842e0e0` | inert against upstream (upstream refines *after* distribution; rank-interior is a fork choice). A textual bundle — the latter two edit inside `applyLgrPartitionCellGroups_` added by the first. Re-propose once Waves 1–3 land and a concrete parallel-LGR deck needs it. |
| **Refine-before-redistribute** | `6e15f740a`, `0e4934663`, `81b36e513`, `fe4dc7f96`, `7f5fe33cc`, `a7626b09c` | challenges upstream's parallel model; opt-in. Note `a7626b09c`'s `if constexpr (std::is_same_v<Grid, Dune::CpGrid>)` guard at `FlowBaseVanguard.hpp:321` is **useless** — that branch *is* taken for CpGrid and `leafHasParentCellIndices()` does not exist upstream. Needs a `requires` guard before it can ever be submitted. |
| **Debug canary** | `7a116a931`, `133cb128c` | fork-only `poisonRefinedGlobalCell` |
| **Dynamic report-step driver** | `8824a0543` + the standalone `flow_blackoil_adaptive_dynamic` exe | superseded by A2's schedule-driven trigger |
| **opm-gridrefined itself** | 92 commits | RFC issue, backed by A2's numbers. Not a PR series — piecewise PRs are meaningless and a mega-PR reads as "delete the maintainer's code". |

**Unrelated, submit anyway (free goodwill):** the `maxWaterSaturation_`
cell-indexing bug at `FlowProblem.hpp:1338` — indexes cells 0/1 while the
comments claim time indices; affects ROCKCOMP runs. Still uncommitted, one line.

---

## 5. What is controversial, ranked

1. **The opm-gridrefined strip/rebuild** — replaces maintained code. RFC only.
2. **Refine-before-redistribute** — parallel-model philosophy vs upstream default.
3. **`Schedule` trajectory replay** (C3) — post-parse `Schedule` mutation plus
   retained per-record `TrajPerf` state. Lead with the design note: replay is a
   *post-process*, grid-agnostic, no solve-loop coupling — pre-empt the
   comparison with the rejected in-loop recompute of PR #5914.
4. **Vanguard partitioning API** (G3/S6) — a rank-interior modelling choice.
5. **Everything already submitted** — low; #5252 is the most arguable, since it
   changes INIT/UNRST section ordering.

## 6. Bookkeeping

- `dynamic-refinement` stays the integration branch; PR branches are
  cherry-picked views of it. Drop merged commits at the next rebase — **not
  before**.
- Cross-repo CI takes sibling revisions from a **comment** on the PR, not the
  body: `jenkins build this please opm-common=5252 opm-tests=567`
  (`opm-common/jenkins/build-opm-module.sh:20-46`).
- CI builds opm-simulators with `-DBUILD_FLOW_ALU_GRID=ON`
  (`build-opm-module.sh:12`), so the `if constexpr` guards in S5 *will* be
  exercised. Build with it locally.
