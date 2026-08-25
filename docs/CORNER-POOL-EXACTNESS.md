# Corner-pool exactness: why cross-box corner dedup by exact coordinate is sound

The leaf assembler identifies refined corners shared between two face-sharing
refinement boxes by **exact coordinate**
(`std::map<std::array<double,3>, int>` — LeafGridAssembler.cpp, the
`refinedCornerPool`). This note records why that is a sound design rather than
a floating-point accident, what its invariants are, how a violation would have
failed before it was guarded, and which guards now exist. Companion to
REFINEMENT-ALGORITHM.md §2.2.

## Scope of the claim

Exact-coordinate matching only carries corners in the **interior of a shared
parent face or edge** between two boxes. Corners on the parent lattice are
identified *through the parent cell* by integer arithmetic (a per-cell test,
LeafGridAssembler.cpp ~:244), with no floating point involved. Within one box,
the corner-point preprocessor uniquifies corners itself.

## Why shared corners are bitwise identical

For an interior shared corner, box A evaluates the resampling formulas with
lateral fraction `a = 1` in its last parent column and box B with `a = 0` in
its first — different inputs, so this is *not* "same function, same inputs".
The equality is a term-by-term exact collapse:

1. **Boundary fractions are exactly 0.0 and 1.0.** Fraction tables are built
   as `double(sub)/factor` (RefinementBuilder.cpp, `axisSubdivision`), so
   `0/n = 0.0` and `n/n = 1.0` exactly. Interior fractions agree between boxes
   because IEEE division is correctly rounded: `j/n` depends only on the
   rational value — `2/4` and `1/2` are the same double, which is what the
   compatible-multiple case needs.
2. **Multiplying by exact 0 or 1 and adding ±0 are exact.** In the bilinear
   sub-pillar sum and the trilinear zcorn accumulation
   (GrdeclRefinement.cpp), the non-shared side's terms carry weight exactly 0
   and vanish without perturbing the accumulator; surviving weights pass
   through `*1.0` unchanged. Both boxes therefore reduce to the identical
   sequence of operations on identical operands: the shared parent pillars and
   the shared-face zcorn entries, read from the same retained level-zero
   arrays. Signed zeros cannot upset the pool: `operator<` on doubles treats
   −0.0 and +0.0 as equal.
3. **The preprocessor step preserves it.** Each box's `processEclipseFormat`
   computes corner x/y from (pillar, z). Both boxes hand it bitwise-identical
   inputs on the shared face, and it is the same compiled code.
4. **"Conforming" is defined consistently across the pipeline.** The collapse
   needs the two sides of the shared parent face to carry bitwise-equal zcorn
   in the input (they are distinct ZCORN entries). If they differ at all,
   level zero has a split face there — level-zero processing runs with
   `tolerance_unique_points = 0`, hardcoded (processEclipseFormat.cpp:176) —
   and the side is routed to the faulted-boundary rebuild instead of the
   conforming path. The dedup's notion of "same corner" is exactly the
   preprocessor's notion of "not a fault"; no near-miss can fall between the
   two definitions.

There is no accumulated arithmetic anywhere: every corner is computed in one
shot from level-zero data by one fixed expression. The invariant is discrete,
not a tolerance.

## The two genuine fragilities, and their guards

**1. The failure mode used to be silent.** Had a shared corner failed to
merge, the partner box's corner-set lookup would miss, the partner would
register itself as a second "owner", and the interface would become two
coincident one-sided faces — `mosaicOutside` never patched, the face left as a
boundary face: a **sealed box↔box interface, no error, wrong physics**.

*Guard:* the leaf assembler now verifies, after the face loop, that every
face-sharing owner face was claimed by its partner, and throws
`std::logic_error` naming the box otherwise (LeafGridAssembler.cpp, directly
after the box/face loop). The check was validated by deliberately corrupting
one box's corner-set key and observing the throw.

**2. The build flags are part of the invariant.** The collapse survives FMA
contraction (`-ffp-contract=fast`, GCC's default): `fma(0, y, acc) = acc`
exactly, and the same binary evaluates both boxes. It would **not** survive
value-changing transforms (`-ffast-math`, `-funsafe-math-optimizations`):
reassociating `(1-a)*p00 + a*p10` into `p00 + a*(p10-p00)` breaks exactness at
`a = 1` while leaving `a = 0` exact, and the boxes then disagree. No OPM build
uses fast-math; if that ever changes, the tests below fail loudly.

*Guard:* three skew-pillar tests in `tests/cpgrid/conforming_builder_test.cpp`
(`skewPillarFaceSharingBoxes`, `skewPillarCompatibleSubdivisionMosaic`,
`skewPillarStackedBoxesShareKFace`). They use inclined pillars with per-pillar
tilts and layer depths with binary-inexact increments (0.1, 0.07), so the
resampled corners are full-precision doubles — the collapse is doing real
work. Each test checks the cross-box connection count exactly (a merge miss
seals the interface for equal factors) and that the **minimum pairwise vertex
distance** is macroscopic — a near-miss leaves two vertices an ulp apart,
which no exact-duplicate check can see.

Related guard already in the design: touching **graded** (N\*FIN/H\*FIN) boxes
are rejected outright, because their column tables need not align — the
exactness claim is not stretched to cases where it would not hold.

## What the checks cannot promise

- The compatible-subdivision mosaic pairs faces by *integer* lattice
  arithmetic, so a corner near-miss there would not seal the interface — it
  would only leave duplicate near-coincident vertices (caught by the
  pair-distance test, and relevant to VEM/edge-conformal use).
- Cell closure (`Σ area·n̂ = 0`) on inclined pillars holds only to the shared
  face's *non-planarity* for the coarser cell of a mixed-resolution interface:
  the finer side's sub-face triangulations follow the curved bilinear face more
  closely than the coarse quad's own centroid fan would. That is a geometric
  approximation property of the mosaic, not a stitching defect (see the
  tolerance note in `skewPillarCompatibleSubdivisionMosaic`).

## History and fallback

The previous implementation identified corners with an explicit cross-box
lattice-bookkeeping layer — the largest and most fragile part of that code
(LESSONS.md). The exact-arithmetic pool replaced code-complexity fragility
with a small, provable, and now machine-checked invariant. If it ever had to
go, the robust fallback for conforming interfaces is to key the pool by
integer box-global lattice coordinates on the shared parent face (matching
factors imply a common lattice), removing floating point from identification
entirely at the cost of reintroducing part of the old bookkeeping.
