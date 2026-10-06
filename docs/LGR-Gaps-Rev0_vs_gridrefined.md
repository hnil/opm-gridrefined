# LGR-Gaps-Rev0 (upstream master 2026-09-28) against our LGR branches

State of the code on `lgr-status` (2026-10-06, late): opm-common `276717b87`,
opm-gridrefined `522dcc8a`, opm-simulators `d7e39e32b`; decks on opm-tests `new_lgr`.
Each row of the sheet is judged against our code, not upstream's.

S = solved, P = partial, O = open, NA = does not apply to our design.
Tally of the 41 rows: **23 S, 12 P, 5 O, 1 NA** (morning of 2026-10-06: 13 S, 17 P, 10 O).

## Priority of what is open

Ordered for running field cases first, then output, then exotic features.

**Tier 1 — field cases run, and run right**

1. ~~Wells completed both inside and outside a box~~ — **supported**, both ways of declaring it:
   a global well (COMPDAT) whose connections partly fall in a box (common `22dba4680`), and an LGR
   well (WELSPECL/COMPDATL) with extra COMPDAT connections in the global grid (common `276717b87`;
   deck `CARFIN_LGRWELL_PLUS_GLOBAL`, same BHP as the other form, serial and np=2,3). Global
   connections stay global, the rest go into the LGR; deck `CARFIN_WELL_CROSSES_BOX` runs serial and
   np=2,3 and agrees with the same well inside a box over both layers.
2. ~~TRAN* edits refused in parallel, EQUALS/ADD everywhere~~ — **done** (sim `7f33842f8`): edits
   per refined face (this also fixed faces that shared one value in every serial run with a TRAN*
   edit), EQUALS/ADD scale a coarse face's refined faces, parallel supported. Drogon runs at np=2.
3. **Explicit NNC and AQUCON into a box stop the run; no keep-coarse fallback** (a sealing MULTREGT
   whose boundary crosses a box works, face by face — deck `CARFIN_MULTREGT_INTO_BOX`)
   (rows 16, 17, 20). Exported field models carry explicit NNCs.
4. ~~Numerical-aquifer cell list empty after refinement~~ — **fixed** (grid `522dcc8a`). Also fixed:
   a parallel run with a numerical aquifer and a box hung, rank 0's NNC output not finding the
   aquifer connection on the refined output grid (sim `5af4736eb`); `CARFIN1_AQUNUM` runs at np=2,3.
5. ~~Aquifer connections on a host face are dropped~~ — **fixed** (sim `d7e39e32b`): shared among
   the children with a boundary face on that side, by area, for analytic and constant-flux
   aquifers (tracers follow). `CARFIN1_AQUFETP`: AAQT within 0.07 % of the unrefined deck (was 0);
   `CARFIN1_AQUFLUX`: equal. Serial and np=2,3.
6. **Partitioning ignores refinement** (row 22): a box and its halo go to one rank, weighted as
   coarse cells. Field-size boxes make that rank the bottleneck.
7. **Drogon water −1.3 % against the reference at 212 d** (oil and gas within 0.03 %), all of it in
   well A2 (MSW, in the box). Not a grid issue: refined INIT and initial refined state equal the
   reference's. The end-point arrays (SOWCR, KRWR, PCW) and initial pressure differ in the unrefined
   grid too: check SWATINIT/PCW scaling, then A2's segments.
8. **Per-box properties only for GRID keywords** (row 44 rest): REFINE…ENDFIN in EDIT/PROPS/REGIONS
   (SATNUM, end-point scaling) is still refused; nested blocks inherit.
9. **Wells spanning several LGRs: connections de-duplicated by I/J/K alone** (row 46 rest).
10. ~~A setup error on one rank can hang~~ — **done** for the refinement steps: rank 0's output-grid
    refusal is broadcast (sim `ab343cc0f`) and a failure in any rank's own refinement now stops all
    ranks (sim `ecda69fff`, checked by injecting a failure on rank 1 at np=2,3). The one rank-local
    refusal left in the transmissibility setup (MULTREGT on an EDITNNCR record) is gone (sim
    `938cad6fe`). `scripts/lgr_parallel_refusal.sh`: 6 decks, all refused cleanly at np=2,3.

**Tier 2 — output and reporting**

11. WBP for LGR wells and RFT (row 34).
12. Host B* summary vectors read zero; no aggregation rule (row 50).
13. Restart read in parallel (row 52).
14. Regression tests run but compare nothing; no thermal LGR deck (row 53).
15. GDORIENT not written (OPM never writes it; not LGR-specific).

**Tier 3 — exotic or rare in field decks**

16. SOURCE in a host is injected once per child; BCCON on a host lands on one child (rows 29, 30).
    Silent but rare; a refusal is an hour's work.
17. Compositional runs: explicit initial arrays, inter-region flows, region reports (rows 26, 28, 31).
18. HybridNewton, NLDD and the GPU bridge are unguarded with a box (row 32).
19. CARFIN on AluGrid/PolyhedralGrid silently ignored (row 49).
20. AQANCONL not read (row 40).
21. Black-oil explicit PRESSURE without ρgΔz in a vertically split host (row 26 rest).

**For later — remaining INIT differences against the references** (detail under "INIT and EGRID
against the references"; none changes production measurably)

22. Norne: refined pinch-outs across thick inactive layers (`PINCH … GAP … TOPBOT TOP`), 4 % of
    refined TRANZ. The reference's value falls with the lateral offset of the two faces; rule not
    found. Unrefined OPM shows the same on 58 unrefined-grid pinch-outs.
23. Norne: ~320 of 1958 LGR↔global connections on faulted box sides (MULTFLT 0.1 and more) off by
    > 1 %. Not traced.
24. Drogon: 66 refined TRANZ (≈1e-3) where the reference bridges a pinch-out on the refined thickness;
    needs pinch processing per refined window.
25. Drogon: ~400 refined fault connections where the reference applies EDITNNC as refined
    MULTX/MULTY on 12 of ~160 host-column pairs. No rule found.
26. Not LGR: fault NNCs with EDITNNC differ by up to ±4 % (35 % of them) and initial pressure by up
    to 0.7 bar (3.8 % of cells) in Drogon's unrefined part — upstream against the reference.

## Row by row

### ① Can it run?
| Row | Gap | Ours | Evidence |
|---|---|---|---|
| 13 | Host < 8 corners | NA | Boxes are resampled as corner-point descriptions and processed normally; collapsed hosts give exactly collapsed children (grid `406c99ac`). |
| 14 | Host on a fault with throw | S | Mosaic faces at faulted box sides; unit tests `faultAtBoxBoundaryBuilds`, `faultInsideBoxEndToEnd`. |
| 15 | Host next to a pinch-out | **S** | Pinch connections carried into a box and across its top (grid `039589af`, `a1132f7a`); decks `CARFIN_PINCH_{GEOM,MINPV}_{ABOVE,BELOW,ACROSS}` all connect; Drogon's refined cells with TRANZ 0 against the reference 6456 → 66. |
| 16 | Host with an NNC / aquifer face | P | EDITNNC/EDITNNCR/PINCH handled; sealing MULTREGT across a box works per face; NNC keyword and AQUCON into a box refused with cell names on every rank (sim `d3267a242`). |
| 17 | Numerical-aquifer hosts | P | Refused at input naming cell and box (common `235f86ffb`). |
| 18 | Inactive host | S | ACTNUM inherited and rebuilt after MINPV; Norne box with inactive hosts runs np=1,2. |
| 19 | Switching off children | **S** | Block MINPV and block ACTNUM remove children (common `9ce78f152`); emptying an active host is refused, naming it. Decks `CARFIN_BLOCKACTNUM(_EMPTY)`. |
| 20 | One unrefinable host stops the box | P | Most reasons gone (rows 13–15); remaining refusals name the cell; no keep-coarse fallback. |
| 21 | A failure on one rank hangs | **S** | Rank 0's refusal broadcast (sim `ab343cc0f`); a refinement failure on any rank stops all (sim `ecda69fff`); the rank-local MULTREGT/EDITNNCR refusal removed (sim `938cad6fe`). `lgr_parallel_refusal.sh` refuses its 6 decks cleanly at np=2,3. The well model was not audited. |
| 22 | Partitioning ignores refinement | O | Box + halo pinned to one rank, weighted as coarse cells. |
| 23 | LGR wells partitioned by the wrong cells | S | Wells anchored to their box's host cells (sim `2a7cc52fd`), np up to 8. |

### ② Can we trust it? — cell mapping
| Row | Gap | Ours | Evidence |
|---|---|---|---|
| 24 | I/J/K lookup not rebuilt | S | Rebuilt after refinement; COMPDAT in a box moved into the LGR; a well partly outside a box keeps its global connections (common `22dba4680`). |
| 25 | COMPDATL lookup throws / double counts | S | Missing entry → −1; unknown LGR named. |
| 26 | Explicit initial arrays | P | Black-oil via LookUpData (no ρgΔz); compositional open. |
| 27 | GPMAINT region pressure | S | Region array mapped onto the leaf. |
| 28 | Inter-region flows | P | Black-oil mapped; compositional not. |
| 29 | SOURCE once per child | O | Host rate given to every child. |
| 30 | BCCON on a host | O | Last child wins. |
| 31 | Compositional region reports | O | No `mapRegionsOntoLeaf_`. |
| 32 | NLDD / GPU bridge / HybridNewton / well flags | P | Well flags fine; the rest unguarded. |
| 33 | Pinch value to one child | S | Pinch connections carried into boxes; PINCH ALL value shared over the joined child pairs. |
| 34 | WBP / RFT for LGR wells | P | Global wells right; LGR wells' WBP read as global, RFT skipped. |
| 35 | COMPDATL LGR ≠ WELSPECL LGR | S | Each connection resolved in its own LGR. |

### ② Aquifers, face and depth edits
| Row | Gap | Ours | Evidence |
|---|---|---|---|
| 36 | Aquifer influx to wrong cells | **S** | Host connections shared among the children's boundary faces by area (sim `d7e39e32b`). |
| 37 | AQUANCON on a host face | **S** | Spread over the children; analytic, constant-flux and tracers (sim `d7e39e32b`). |
| 38 | Numerical-aquifer list empty after refinement | **S** | Mapped onto the leaf (grid `522dcc8a`); parallel NNC output no longer hangs (sim `5af4736eb`). |
| 39 | NNC export abort with a numerical aquifer | S | Looked up on the leaf. |
| 40 | AQANCONL | O | Not read. |
| 41 | TRAN edits / PINCH ALL | **S** | Per refined face; EQUALS/ADD scale a coarse face's refined faces by its change; serial = np=2 (sim `7f33842f8`). Decks `CARFIN_TRAN_{MULTIPLY,EQUALS,MULTX}` give the same run. |
| 42 | Host face multipliers inside a host | **S** | No multiplier between children of one host; MULT*, MULTFLT, MULTREGT kept where host transmissibility rewrites a face (sim `3c0fa7ecf`). |
| 43 | DEPTH in EDIT | **S** | Host's edited depth + child's offset (sim `d659e0313`); deck `CARFIN_EDITDEPTH` equals the unedited run. |

### ③ Can we model it? / ④ Can we see it?
| Row | Gap | Ours | Evidence |
|---|---|---|---|
| 44 | Per-box property values | **S** GRID / P overall | PERMX/Y/Z, PORO, NTG, MULTPV in CARFIN blocks, local indices, full BOX/EQUALS/MULTIPLY/COPY (common `d85eb49a4`, grid `4bc1f7f4`, sim `e84ed84fd`); equals the same edit on the host, serial and np=2. REFINE sections, nested blocks and end-point scaling open. |
| 45 | MINPV in a box becomes global | S | Block MINPV kept on the box and applied to its children. |
| 46 | COMPDATL from host properties; I/J/K de-duplication | P | Connection factors use the block's own values; de-duplication still by I/J/K. |
| 47 | NXFIN/HXFIN read | S | Graded boxes read and validated. |
| 48 | One split per box | S | Per-axis subdivision tables. |
| 49 | PARENT / non-CpGrid / NXFIN ignored | P | PARENT and NXFIN honoured; AluGrid/Polyhedral silent. |
| 50 | Summary / FIP / host B* | P | Summary and FIP work serial and parallel; host B* reads zero. |
| 51 | INIT file | **S** | Global section written as the unrefined grid (host TRAN and host NNCs, sim `ba22a0039`); parallel INIT equals serial (sim `f6e849a79`). |
| 52 | Restart write / read | P | Write serial and parallel; read serial only. |
| 53 | Regression tests / thermal | P | 15 new decks with stated expectations on opm-tests `new_lgr`; not yet registered as compare tests; no thermal deck. |

## INIT and EGRID against the references (2026-10-06)

Compared with `scripts/compare_ecl_files.py` (whole arrays, section aware) and
`compare_ecl_nnc.py` (NNC by cell pair).

| | Drogon (3x2x1, faulted) | Norne (graded) | model2_lgr |
|---|---|---|---|
| global ZCORN, ACTNUM; refined ZCORN, ACTNUM, HOSTNUM | identical | identical | identical |
| global TRANX/Y/Z, within 1 % | 99.9 / 100 / 100 % | 99.98 / 99.9 / 99.8 % | identical |
| global NNC list | complete, median 1.0000 | 11288 against 11287 | identical |
| refined PORV, DX, DY, DZ, DEPTH | identical | identical | identical |
| refined TRANX / TRANY / TRANZ, > 1 % off | 0.00 / 0.00 / 0.04 % | 0.02 / 0.01 / 4.0 % | identical |
| refined NNCs median (p1, p99) | 1.0001 (0.991, 21.7) | 1.0000 (0.996, 1.004) | identical |
| LGR↔global NNCs median (p1) | 1.0000 (0.986) | 1.0001 (0.715) | identical |
| refined COORD | same lines; endpoints parameterised differently | same | identical |
| parallel INIT and EGRID (np=2) against serial | identical | identical | identical |

Rules the reference follows that we now follow too: refined transmissibility is plain two-point flux
on the child cells (corner-average centres, face centre = average of the face's corners, area from the
face diagonals); on a box boundary the coarse cell measures to the corner average of its whole face; a
refined pillar inside a host passes through the bilinear interpolation of the host's corners, and a
pillar on a shared host edge belongs to the lower column; EDITNNC not applied to any connection of a
refined cell; pinch-outs bridged inside boxes and reported in TRANZ; the global section describes the
grid as if unrefined.

What is left, each traced to a cause:

- **Drogon, 66 refined TRANZ (≈1e-3)**: the reference bridges a pinch-out because the *refined* gap
  (0.001 m) is at the PINCH threshold while the host's (0.005 m) is not; we take pinch-outs from level
  zero. Negligible flow; fixing it means running pinch processing on each refined window.
- **Drogon, ~400 refined fault connections**: the reference turns EDITNNC into a refined MULTX/MULTY
  on 12 host-column pairs and not on the other ~150. No rule found; not reproduced.
- **Norne, refined pinch-outs across thick inactive layers (4 % of refined TRANZ)**: deck uses
  `PINCH 0.001 GAP 1* TOPBOT TOP`; the gaps are 2–3.5 m of ACTNUM=0 on sloping pillars. The reference's
  value falls with the lateral offset between the two faces (to ≈0 on the narrowest graded child)
  without adding diagonal connections; ours is the two-point value along the pillar. The same effect
  shows at level zero in upstream OPM (58 host-grid pinch-outs off by 1–7 %). Not reproduced.
- **Norne, LGR↔global connections on faulted box sides** (~320 of 1958 off by > 1 %): all on faults
  with MULTFLT 0.1 and further multipliers; not traced further.
- **Not LGR**: Drogon's fault NNCs carrying EDITNNC differ by up to ±4 % (35 % of them) in the
  unrefined part of the grid too, and the initial pressure differs by up to 0.7 bar in 3.8 % of the
  unrefined cells. Both are upstream-vs-reference differences.

Drogon's water gap (−1.3 %, all in A2) is therefore not explained by the grid: the refined
INIT and the initial refined SWAT/SGAS/PRESSURE equal the reference's; at 181 days 41 refined cells
differ in SWAT by > 0.02, near A4, not A2.

## Fixed on 2026-10-06

| Fix | Commit |
|---|---|
| Host transmissibility kept MULT*/MULTFLT/MULTREGT | sim `3c0fa7ecf` |
| Per-box property values (GRID blocks) | common `d85eb49a4`, grid `4bc1f7f4`, sim `e84ed84fd` |
| Block ACTNUM | common `9ce78f152` |
| DEPTH in EDIT | sim `d659e0313` |
| Refinement refusals stop all ranks | sim `ab343cc0f`, grid `cec07e60` |
| Pinch-outs next to and inside boxes | grid `406c99ac`, `039589af`, `a1132f7a` |
| Well inside and outside a box: refused, then supported | common `9ab1b5d79`, `22dba4680` |
| (no effect) host-trans flag for globalTrans_ — its message is wrong: the serial INIT already carried the simulator's values | sim `d514d4f5f` |
| EDITNNC not applied to refined connections | sim `e0eb960b8` |
| Host transmissibility: box boundary, analytic ratio, host pairs | sim `314e3ca5b` (its last sentence on the INIT NNC list is wrong; see above) |
| Host transmissibility: corner-average centres | sim `2ea24f1d7` |
| Global section written as the unrefined grid | sim `ba22a0039` |
| Parallel output grid with pinch connections | grid `abf8e883`, sim `f6e849a79` |
| Wells completed inside and outside a box | common `22dba4680` |
| TRAN* edits per face, EQUALS/ADD, parallel | common `838ecac05`, sim `724ee93ff`, `7f33842f8` |
| Leaf grid gave children on a host's I sides a wrong corner on left-handed grids (Drogon) | grid `5439563f` |
| Refined pillars through the host's corners, lower column on shared edges | grid `4a23d02c`, common `1612152af` |
| Refined transmissibility from child geometry by default (`--lgr-trans-from-host=false`) | sim `89ed04654` |
| Box boundary: coarse side measures to its whole face | sim `328e7a100` |
| Global section's host-level values with the unrefined grid's face areas | grid `c4197188`, sim `7d633df23` |

Drogon at 212 days against the reference: FOPT −0.03 %, FGPT −0.02 %, FWPT −1.3 %, FWPR −2.7 %; np=2 within 0.04 % of serial
(morning: FOPT +0.23 %, FWPT −0.5 %, FWPR −0.1 %; the morning's water match hid compensating errors).
The evening's grid fixes changed none of these by more than 0.1 %.

## Why the earlier EGRID/INIT checks did not catch these (2026-10-06)

The August comparison (opm-gridrefined `docs/LGR_OUTPUT_STATUS.md`) was careful about geometry and
array inventories, and it did see most of these differences. It explained them away instead of
following them up:

| Error | Was it visible? | Why it was not followed up |
|---|---|---|
| EDITNNC on refined connections | yes: refined NNCs median 0.68 (Drogon) | filed with TRANX 0.76 as one "convention difference — decide which we want"; host-trans then fixed TRANX and the NNC half was never revisited |
| Pinch-outs lost inside boxes | yes: 6456 refined TRANZ = 0 where the reference has a value | explained by a count ("8415 LGR NNCs against 8408, so they are probably present as NNCs") instead of matching cell pairs |
| Host transmissibility dropped MULT*/MULTFLT/MULTREGT | Norne only: 139 refined NNCs the reference does not have, TRANY p99 1.14 | host-trans became default on 2026-09-04 after a check of **medians** on three cases; counts and tails were not rerun |
| Faces sharing one TRAN* value | only in the LGR↔global NNC tail (Drogon p1 0.81) | tails attributed to refined geometry |
| Host convention (corner centres, analytic ratio, host pairs) | as wide tails (TRANX p1 0.83) | same |
| Host cells' global TRAN = 0, host NNCs missing | yes | correctly judged output-only, but it also hid the host values that showed the convention |

What changed in method today: per-cell-pair and per-host-pair matching instead of medians and
counts; looking at p1/p99 and "only in reference/run" lists; and treating a difference as a defect
until the reference's own numbers (e.g. children summing to exactly 3.00 × the host) show it is a
convention.

One claim of mine today was itself wrong: that the serial INIT was written from an object without
the host-transmissibility flag (sim `d514d4f5f`). A full Drogon run from before that commit already
wrote refined TRANX at 0.9993 of the reference; the 0.7632 I compared against came from a run with
`--lgr-trans-from-host=false`. The commit is harmless. Likewise the message of sim `7f33842f8`
overstates the sibling case: faces are taken from the lower-index cell, so the collision that
mattered was a coarse cell beside a box with several child faces in one direction.

**Norne.** No EDITNNC or TRAN* edits, so those two fixes do not touch it. The multiplier fix did
(FOPT −0.7 % at the end of the run; the 139 spurious refined NNCs gone, 1339 against the reference's
1340), and the later transmissibility changes moved its INIT closer (refined NNC p1 0.40 → 0.97,
global NNC list 10589 → 11288 against 11287) without changing production noticeably. Against the
reference's first 616 days, mean error: FOPT 0.19 %, FGPT 0.17 %, FPR 0.02 %, FWPT 1.2 %.

## The host-transmissibility rule was a workaround for a grid bug (2026-10-06, evening)

The 0.76 refined TRANX on Drogon that `--lgr-trans-from-host` was built to fix (sim `742d79a36`,
default since 2026-09-04) was not a convention difference. Recomputing the reference's refined
TRANX from its own EGRID with plain two-point flux reproduces it exactly (100 % within 1 %), so the
reference does not distribute the host's value. Our own geometric value was wrong because
processEclipseFormat orders a cell's corners with J reversed on left-handed grids, and the leaf
assembler assumed the opposite: on Drogon each child on a host's I side lost a corner (two corners
coincided) and its centre moved by a quarter cell along J. Norne and model2 are right-handed, so the
host rule looked harmless there, and children summing to 3.000 × the host is also what two-point flux
gives on near-regular cells — which is why the convention story held up.

The remaining 1–5 % tails in refined PORV, DX and transmissibility came from pillar placement: we
interpolated pillar endpoints, the reference interpolates the host's corners.
