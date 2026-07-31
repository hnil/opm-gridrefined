# How to submit the upstream PRs — a working guide

Companion to `PR-PLAN.md` (what each PR contains) and `HANDOVER-UPSTREAM-PRS.md`
(why). This file is the *mechanics*: the exact commands, the PR body template,
how to make OPM's CI build against a sibling PR, and the order to go in.

Date: 2026-07-29.

---

## Coordination — more than one session works on these branches

Two sessions have edited the same PR branches on the same day (both reworked
#7245 independently on 2026-07-31; `--force-with-lease` caught it and the
result was merged by hand). Before touching a shared branch:

```bash
git fetch hnil && git log --oneline hnil/<branch> -3
```

and prefer `--force-with-lease` (never plain `--force`) so a concurrent push
is refused rather than silently overwritten.

**Restructured 2026-07-31.** `dynamic-refinement` in **opm-common** and
**opm-simulators** was rebased onto current upstream with history rewrite;
the pre-restructure states are preserved as
`backup/dynamic-refinement-pre-restructure-20260731` on the hnil forks.
**Any older checkout must re-sync before committing.** What changed:

- merged work dropped (opm-common #5249/#5250; opm-simulators #7243);
- dead commits dropped: the AVX2 guard (upstream has its own) and the
  `HAVE_HYPRE` define (#7242 closed — the macro already reaches the
  executables, the premise was wrong);
- superseded commits replaced by their reviewed shapes: the level-zero-only
  Cartesian→compressed map, the fatal/−1 `compressedIndexForInteriorLGR`, and
  the `eclOutputEvalSupported_` helper (from the #7245 rework);
- the nested-CARFIN commit replaced by the improved #5256 pair (which reports
  the undefined-parent error with its deck location);
- **the whole branch now builds and runs against upstream opm-grid.** Every
  backend-specific grid query is behind a compile-time guard
  (`__has_include` for `refinement/GridStateWriter.hpp`, `requires` for
  `leafHasParentCellIndices()` and `poisonRefinedGlobalCell()`), and the
  state transfer computes stable cell ids from the public grid interface
  instead of `CpGridData::stableCellId()`.

  Measured 2026-07-31 with `--adaptive-lgr='5 6 5 6 1 3 6 6 9'` on
  `spe1/SPE1CASE1.DATA`: **upstream opm-grid** 328 Newton / 451
  linearizations / 449 linear; **opm-gridrefined** 331 / 454 / 453, which
  is unchanged from before the decoupling. The small difference between
  the two is the refinement kernel (trilinear vs corner-point-native
  resampling), not a regression.

  Note the builder registration in `AdaptiveCpGridVanguard` is **not**
  redundant and must stay: opm-gridrefined retains the corner-point
  description only when the deck declares LGRs, and `--adaptive-lgr`
  refines a deck with no CARFIN, so removing it makes that backend throw.

## Ground rules

1. **Every PR branch is cut fresh off `upstream/master`** and *cherry-picks*
   from the prototype. Work is never moved out of the prototype, only copied.
2. **The prototype branches are restructured deliberately, not incidentally.**
   `dynamic-refinement` was rebased on 2026-07-31 (see above) to drop merged
   and dead commits and adopt the reviewed shapes; `new_lgr` and
   `adaptive-cpgrid-class` are untouched. Do not rebase or force-push a
   prototype as a side effect of other work — announce it, back it up, and
   check the remote first, because more than one session uses them.
3. **Never mention the fork** in a commit message or a PR body. Each PR is an
   independent improvement to upstream opm-common / opm-grid / opm-simulators,
   not a visible step toward something the reviewer cannot see. Strip any
   reference to `opm-gridrefined`, "the builder", "the conforming builder",
   "refine-before-redistribute" from messages you carry over.
4. **One idea per PR.** If a reviewer has to ask "why is this hunk here?", the PR
   is too big — split it.
5. **Never test against `builds/refined*` or `vscode_build/*`.** Those are
   configured against the fork's opm-grid and will silently make a broken PR look
   fine. Build every PR against a clean upstream sibling stack.

---

## One-time setup

Remotes are already correct in every repo (`upstream` = OPM/…, `hnil` / `origin`
= your fork). Refresh **all** of them before starting a session, and check the
dates:

```bash
for r in opm-common opm-grid opm-simulators opm-tests; do
  git -C ~/Documents/OPM/opm_vscode_clean/$r fetch upstream --prune
  echo "$r: $(git -C ~/Documents/OPM/opm_vscode_clean/$r log -1 --format='%h %cd' --date=short upstream/master)"
done
```

This is not a formality. On 2026-07-29 the `opm-grid` checkout's
`upstream/master` was a month stale (`0ff52dd4`, 2026-06-09) while the real tip
was `8cb1da37`; a branch cut from it looked fine and then failed to build
against opm-simulators master with a `loadBalance` arity error that had nothing
to do with the change. Refresh every repo, not just the ones you are editing —
the sibling you are *not* touching is the one that breaks the build.

opm-simulators master in particular can move several times a day; rebase and
re-check before pushing:

```bash
git rebase upstream/master
```

Create a clean reference build once, and keep it — every "did I change output?"
question is answered by diffing against it:

```bash
# all four modules checked out at upstream/master; see
# ~/Documents/OPM/opm_docs/00-build-and-run/build_opm.md for the toolchain
builds/upstream
```

Match CI's flags when you build a PR locally
(`opm-common/jenkins/build-opm-module.sh:12`):

```
-DBUILD_FLOW_VARIANTS=ON -DOPM_ENABLE_PYTHON=ON -DBUILD_FLOW_POLY_GRID=ON -DBUILD_FLOW_ALU_GRID=ON
```

`BUILD_FLOW_ALU_GRID=ON` matters: several changes in this series are guarded with
`if constexpr (requires { … })` precisely so the non-CpGrid instantiations still
compile, and CI *will* exercise them.

---

## Per-PR recipe

### 1. Cut the branch off upstream — never off the prototype

```bash
git checkout -b pr/<name> upstream/master
```

### 2. Cherry-pick the named commits, oldest first

```bash
git cherry-pick <sha1> <sha2> <sha3>
```

A conflict is information, not an obstacle. Check `PR-PLAN.md` for that PR's
"manual edit" note before resolving — several commits in the prototype sit on top
of commits that are deliberately excluded, and the fix is to reposition the hunk,
not to drag the excluded commit in.

### 3. Apply the manual edits and reshape the history

```bash
git rebase -i upstream/master     # squash what the plan says to squash
```

Rewrite every commit message so it stands on its own against upstream master.

### 4. Build and run the PR's verification row

Against a clean upstream sibling stack. The verification table in `PR-PLAN.md`
gives the deck and the pass criterion for each PR.

### 5. Push and open the PR

```bash
git push -u hnil pr/<name>
gh pr create --repo OPM/<module> --base master --head hnil:pr/<name> \
  --title "<one line>" --body-file /tmp/body.md
```

### 6. PR body template

```markdown
## What
One paragraph: the defect, or the capability, stated in upstream's own terms.

## Why it matters
The failing case. For a bugfix: the deck, and the number that comes out wrong.

## How to reproduce
    flow opm-tests/lgr/SPE1CASE1_CARFIN.DATA
    # before: FPR = ...    after: FPR = ...

## Testing
Serial and parallel runs; `ctest -L regression` status; exactly what output
changed and why.

## Depends on
OPM/opm-grid#NNN   (must merge first)
```

If the PR legitimately changes simulation output, say so **in the first
paragraph**, with before/after numbers. Do not let a reviewer discover it.

### 7. Cross-repo CI

OPM's Jenkins takes sibling revisions from a **trigger comment** on the PR, not
from the body (`opm-common/jenkins/build-opm-module.sh:20-46`,
`jenkins/setup-opm-tests.sh:5-14`). Comment on the PR:

```
jenkins build this please opm-grid=1234 opm-tests=567
```

- form is `<module-name>=<PR number>`, lowercase module name, space-separated
- `opm-tests=<PR number>` is honoured the same way
- add `with downstreams` to also build downstream modules

Do this for **every** PR in this series that has a "Depends on" line. Without it
CI builds against upstream master and fails for the wrong reason, and reviewers
read a red X as "this doesn't work".

---

## Order

### Day one — all independent, submit in parallel

| repo | PR |
|---|---|
| opm-grid | **G0** `pr/wellconnections-lgr-safety` |
| opm-common | **C0** stray `std::cout` · **C1a** INIT/UNRST EGRID order · **C1b** CARFIN parent name · **C2** RegionCache guard · **C3** welltraj replay core |
| opm-simulators | **S1** Hypre link · **S2** ILU0 empty partition · **S3** LGR region arrays on leaf · **S4** LGR serial output/robustness |
| opm-tests | nested decks · weltraj-LGR decks · the LGRON demonstrator deck |
| opm-simulators | the one-line `maxWaterSaturation_` fix (`FlowProblem.hpp:1338`) |

**Start with S3 and S4.** Both are pure bugfixes against upstream's own CARFIN
behaviour — wrong WOC from EQLNUM, wells attached to the wrong leaf cell — so
they need no rewriting and buy the most goodwill per line. **C3** is the one to
take time over: it needs the extractor refactor before it is submittable.

### Then, as parents merge

```
C3 ──► C4 ──► C5
S4 ──► S5
G0 ──► S6
C1b ─► S7
C4 + S4 ──► S8
A1 ──► A2
```

### Held back — do not submit yet

- **G3** `setPartitionCellGroups` and the three simulator commits that use it —
  inert against upstream, re-propose after Wave 1–3 land.
- **Refine-before-redistribute** — challenges upstream's parallel model; opt-in.
- **The debug canary** (`poisonRefinedGlobalCell`).
- **`--adaptive-lgr`** — superseded by the deck-driven `LGRON`/`LGROFF` trigger.
- **opm-gridrefined itself** — an RFC issue, not a PR series.

---

## If a PR stalls

Do not stack more work on it. Reorder around it: every "Depends on" edge in the
graph above is real, but the rest of the series is genuinely independent. A PR
sitting in review for three weeks should not block eight others.

If review asks for something that would pull fork-only API back in, say no and
offer the guarded alternative — the whole point of this series is that upstream
gets a working feature without carrying the fork.
