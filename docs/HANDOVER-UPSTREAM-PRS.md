# Handover: upstreaming the opm-common / opm-simulators enablers

Audience: whoever prepares and argues the pull requests.
Post-audit revision, **2026-07-29** (supersedes the 2026-07-21 draft).

Source of truth: branch `dynamic-refinement` in each repo — linear on an
upstream master tip, no merges. Companions:
[`PR-PLAN.md`](PR-PLAN.md) (per-PR content, ordering, current status),
[`PR-SUBMISSION-GUIDE.md`](PR-SUBMISSION-GUIDE.md) (mechanics),
[`LGR_GAPS.md`](LGR_GAPS.md) (gaps, incl. C5),
[`DYNAMIC-REFINEMENT-FLOW-{REVIEW,PLAN}.md`](DYNAMIC-REFINEMENT-FLOW-PLAN.md),
[`REFINEMENT-ALGORITHM.md`](REFINEMENT-ALGORITHM.md),
[`lgr_review.md`](lgr_review.md) Part VI.

## Strategy in one paragraph

The goal is that opm-common and opm-simulators mainline *allow* the
opm-gridrefined backend without carrying it. The 2026-07-21 draft split the
work into three lanes and listed the audit of which commits need fork-only grid
API as "task one". **That audit is now done, and it changed the answer: there is
almost no Lane B.** 38 of the 44 opm-simulators commits work against current
upstream opm-grid master, the 13 opm-common commits have zero grid dependency,
and the adaptive work needs no fork API either. What remains is a series of
ordinary opm-common/opm-simulators PRs, plus an RFC for the builder itself.

## The audit, and why the three "enablers" mostly evaporated

The draft proposed three minimal opm-grid PRs (G1 seam, G2 stable ids, G3
partition cell groups), each unlocking specific simulator PRs. Re-checked
against the true opm-grid master (`8cb1da37`):

| ID | Draft claim | Audit finding |
|---|---|---|
| **G1** — `Refinement::Builder` + `GridStateWriter` + a dispatch hook | "unlocks the entire external-backend model" | **Not needed for anything we want to ship.** The adaptive demonstrator can drive upstream's own public adaptivity API — `mark()`, `preAdapt()`, `adapt()`, `refineAndUpdateGrid()`, `postAdapt()` (`CpGrid.hpp:565-606`), `addLgrsUpdateLeafView` (`:501`), `autoRefine` (`:513`). Deleting the ~25-line `setBuilder`/`ConformingBlockBuilder` block from `AdaptiveCpGridVanguard.hpp:96-124` makes the vanguard *shorter*. G1 is only required to plug the fork in as a backend, which is the RFC conversation, not a precondition. Also note the draft's "a dispatch hook at the top of `addLgrsUpdateLeafView`" **does not exist in the fork** — the fork *replaces* that function wholesale, so the hook would have to be newly written and tested. That was the hidden cost. |
| **G2** — `stableCellId`, `poisonRefinedGlobalCell`, the `cell_to_idxInParentCell_` scatter | "unlocks parallel LGR output collection and the dynamic state transfer" | **Emulatable in ~15 lines.** Upstream sets a refined leaf cell's `global_cell_` to its level-zero ancestor's Cartesian index (`CpGrid.cpp:716-724`) and `Entity<0>::getIdxInParentCell()` is public (`Entity.hpp:326`), so the packed id can be built in opm-simulators. Caveat to assert on: for `maxLevel() > 1` that pair is **not injective**, because `getIdxInParentCell()` is the index in the *immediate* parent — the fork's own `stableCellId` has the same limitation. Parallel LGR output does **not** need G2; it already uses the public `getIdxInParentCell()`. The only irreplaceable piece is the `distributeGlobalGrid` scatter, needed solely by refine-before-redistribute (held). |
| **G3** — `CpGrid::setPartitionCellGroups` | "unlocks rank-interior LGR partitioning" | **The only one with no simulator-side workaround** — `GraphOfGrid` is constructed and consumed entirely inside `zoltanPartitioningWithGraphOfGrid` / `applySerialZoltan`, so contracted vertices cannot be injected from outside. But upstream it is *dead API*: upstream's model is distribute-then-refine, so the three simulator commits that use it are SFINAE-guarded to a no-op there. Submitting inert code is what reviewers push back on. **Deferred**, to be re-proposed with a concrete parallel-LGR deck that needs it. |

### What we submitted to opm-grid instead

A single unrelated finding the audit turned up: `WellConnections::init`
(`opm/grid/common/WellConnections.cpp`) indexes `cartesian_to_compressed`
without a bounds check, using a position that a COMPDATL connection does not
supply in level-zero coordinates. Two failure modes — an out-of-bounds read
when the position is outside the coarse grid, and a *silent wrong answer* when
it happens to be inside it (a valid index for an unrelated cell, which nothing
rejects).

Submitted as [opm-grid#1053](https://github.com/OPM/opm-grid/pull/1053), then
narrowed on review to the bounds check alone — see `PR-PLAN.md` §2. The
refinement-level half is deferred and recorded as gap **C5** in `LGR_GAPS.md`,
including why a test built on the out-of-range case is not deterministic.

**Net position: no opm-grid change is required for anything currently in
flight.** #1053 can be parked at no cost. That is worth stating plainly to
maintainers, because it removes the sequencing objection from everything else.

## opm-common — no grid dependency at all

Verified: the 13 commits touch only Schedule/WellConnections/output, with zero
`opm/grid`, `CpGrid` or `Dune::` references. The trajectory-replay API is
type-erased through `std::function` + POD structs rather than templated on a
grid — the right shape for a module that cannot depend on Dune, and worth
saying so in review, since "why is this not templated?" is the obvious question.

Four disjoint file clusters, so PR boundaries fall cleanly: the INIT/UNRST
output pair; the `Carfin`/`LgrCollection` input pair; the one-file `RegionCache`
guard; and the trajectory-replay stack. See `PR-PLAN.md` for what shipped and
what remains.

Two things the audit flagged that must not be forgotten:

- **Licensing.** `RigEclipseWellLogExtractorGrid.{cpp,hpp}` is a near-verbatim
  derivative of the vendored ResInsight-derived `RigEclipseWellLogExtractor`
  (~30 semantic lines differ out of 250) carrying only "Copyright 2026 Equinor" —
  the `Statoil ASA` / `Ceetron Solutions AS` lines and the "based on ResInsight"
  derivation note were dropped. The fix is to fold the geometry-fed path into
  the existing class rather than restore the header: that deletes 339
  duplicated GPL lines and the attribution question together.
- **Test gaps.** `Carfin` had no serialization coverage at all, which is exactly
  how the missing `parent_name_grid` survived; and `Carfin::operator==` compared
  only dims/offsets, so a round-trip test would have passed anyway. Both fixed
  in #5250. The same trap is still open for `WellConnections::m_traj_perfs`:
  `serializationTestObject()` does not populate it and `operator==` does not
  compare it, so the field is untestable as written. Fix that in C3.

## opm-simulators — the remaining sequencing

Per-PR detail is in `PR-PLAN.md`. The strategic points:

- Lead with the **wrong-answer bugfixes on decks upstream already supports** —
  EQLNUM/FIPNUM region arrays read on the input grid but indexed by leaf
  (#7244), and the Cartesian→compressed map not being rebuilt after refinement
  so wells attach to the wrong leaf cell (#7245). These are not feature
  enablers; they buy the most goodwill per line and need no rewriting.
- **Say up front when a PR changes simulation output.** #7244 does, #5252
  changes INIT/UNRST section ordering. Do not let a reviewer discover it.
- **Keep known gaps visible.** #7245 states that the rank-asymmetric throw fix
  does not fully resolve well-in-LGR at high rank counts, because the well's
  rank and the box's refining rank can still diverge and
  `checkAllConnectionsFound` is not collective-safe. Better from the PR than
  found later.
- **Never mention the fork** in a commit message or PR body. Each PR is an
  independent improvement to upstream, not a visible step toward something the
  reviewer cannot see.

## Lane C — the builder

Unchanged from the draft, and the audit strengthens the case for doing it as an
RFC rather than a PR series: the 92 commits *replace* upstream's
actively-developed LGR implementation, so piecewise PRs are meaningless and a
mega-PR reads as "delete the maintainer's code".

Route: open an **issue/RFC** presenting the builder as an *alternative backend* —
the measured motivations (fault-boundary generality, preprocessor reuse,
construction-stable ids removing id-sync, dynamic re-adapt, the bit-identical
oracle equivalence and benchmarks), explicitly crediting the existing
implementation. The strongest possible backing is a **working demonstrator on
upstream's own grid**: dynamic refinement driven by `LGRON`/`LGROFF`, running
unmodified upstream opm-grid (`PR-PLAN.md` Wave 4). That turns the argument from
"replace your code" into "here is dynamic refinement working on your grid; here
is why a better refinement kernel would help".

Independently extractable and low controversy, if the RFC stalls: an id-backed
`PersistentContainer<CpGrid>` (today's is leaf-index-backed and not truly
persistent), and the reserved-name-`GLOBAL` guard.

## Verification recipe

```sh
# fetch upstream in ALL FOUR repos and check the dates first -- a stale
# sibling remote cost a full baseline build to diagnose
git checkout -b pr/<name> upstream/master && git cherry-pick <commits>
# build the FULL upstream stack (upstream opm-grid!), never builds/refined*
#  - opm-common PRs: opm-common ctest + a CARFIN deck run
#  - simulators: serial + mpirun -np 2 on opm-tests/lgr decks
#                (CARFIN1 baseline: 52 Newton; compareECL vs builds/upstream)
#  - anything with a new test: prove it FAILS without the fix, not just that
#    it passes with it
```

That last line is not boilerplate. The first version of #1053's test passed
*without* the fix — the out-of-bounds read returned garbage that the existing
`compressed_idx >= 0` guard then filtered — and had to be rebuilt around the
in-range case to be decisive. A test that cannot fail is worth nothing on a
memory-safety PR.
