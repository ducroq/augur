# Hypothesis Log

Provisional design decisions under observation. Each entry is a position we took where the evidence to confirm or revise it lives in the future. Different from:

- **`docs/TODO`** / GitHub issues — tasks with an owner, ready to execute
- **`docs/experiment-backlog.md`** — experiments *designed but not started*, each already pre-committed under ADR-007. Promoted into this file verbatim (adding only the run date) when work begins; if the Method needs changing first, that is a new entry with a new date, never an edit.
- **ADRs** — decisions accepted, with rationale frozen
- **`memory/gotcha-log.md`** — problems encountered & solved

Lifecycle: **open** → dormant → revisit (with evidence) → resolved (close or promote to ADR).

**How to use this file:**

- Add an entry when you take a provisional position you want to revisit later.
- Each entry has a `Review by:` date and a `Revisit trigger:` so Claude can surface due items at session start and in `/curate`.
- The **Method** field pins the falsification criterion *before* the data lands — that's the whole point. Don't loosen Method when the answer arrives; if you want to redefine the bet, open a new entry.
- When an entry is resolved (ratified, revised, or no longer relevant), move it to the `## Resolved` section at the bottom with a one-line outcome.
- Keep entries tight. If an entry grows a plan, it becomes a TODO; if it grows a rationale, it becomes an ADR.

---

## Open

### [2026-08-30] EXP-023a: the 112-day window's 3.0% gain is real and survives on vintages the sweep never scored

**Position (provisional):** EXP-023 found a 112-day training window beats production's 56 by 3.0% quantile score (DM p<0.0001), with better coverage on both sides and better Winkler — all four pre-committed gates passing. Position: this is a real generalisation gain, and it reproduces both on historical vintages the discovery sweep never touched and on vintages that did not exist when it was measured.

**Why this needs its own pre-commit:** EXP-023's 112d rung is the **best of five** compared on one window, so its effect size is upward-biased by selection — the same objection that produced EXP-018a. Worse, the confound control (fix the vintage set so the 168d rung is available throughout) left only **95 vintages, all 2026-03-15..2026-08-21** — the high-price half of the year. A 3.0% effect measured on a best-of-five over one regime is exactly the kind of result that evaporates. Per ADR-007 the confirming test is fixed here, before the confirming data is looked at, and before `WINDOW_DAYS` changes anywhere.

**The power problem, stated up front because it drives the design.** EXP-018a could demand 14 fresh vintages because its in-sample effect was 8.1%. Here it is 3.0%. Power scales roughly with the square of the effect, so matching EXP-018a's power at this effect size needs on the order of **7× the vintages** — ~98, i.e. late November. Demanding "≥3% on 14 fresh vintages" would be demanding *zero shrinkage* on an underpowered sample, which is not a test, it is a coin flip dressed as one. The design below therefore splits into a cheap quasi-holdout available now and a properly-powered fresh-vintage stage later, with the bar lowered honestly rather than the sample pretended larger.

**Alternatives (failure-mode signals):**

1. **Regime artifact.** 112d wins only because Mar–Aug 2026 was a rising, high-price regime where a longer window damps over-reaction. **Signal:** Stage A (Dec 2025–Mar 2026, a calmer stretch) shows no gain or a loss. Then the finding is regime-conditional, not a window-length law, and the right answer is an adaptive window rather than a new constant.
2. **Selection mirage.** **Signal:** Stage A or B lands under 1.0% against 3.0% in-sample. Do not ship on a shrunken effect; the curve's *shape* (inverted U peaking interior) may still be worth keeping as evidence while the point estimate is not.
3. **The optimum moves with the feature set.** EXP-023 ran on `lean`, but production is `full` and EXP-018a has not concluded. **Signal:** re-running the two rungs on `full` gives a different winner. Then window and feature set are not separable and both must be settled together.
4. **Longer is simply better and 168 was a fluke of the confound control.** **Signal:** Stage B shows 168d ≥ 112d. Then re-open the sweep at 140/168/196 on the then-available history rather than shipping 112.

**Method (pre-committed 2026-08-30, before either stage is run):**

*Stage A — quasi-holdout on unscored history, runnable immediately.* EXP-023's sweep scored only `t0 ∈ [2026-03-15, 2026-08-21]`, because the 168d rung needed 168 days of pre-history. A **56-vs-112 comparison needs only 112 days**, so vintages from `2026-01-20` to `2026-03-14` are available *and were never scored by the discovery run*. Run exactly two rungs — **56 and 112, treatment fixed here so it cannot be chosen on the holdout** — on `t0 ∈ [2026-01-20, 2026-03-14]`, feature set `lean`, everything else identical to EXP-023:

```
PYTHONPATH=.:scripts .venv/bin/python scripts/exp023_window_sweep.py \
    --start 2026-01-20 --end 2026-03-15 --windows 56,112 \
    --jobs 14 --out ml/shadow/exp023a_stage_a
```

This is a **quasi**-holdout, not a true one: the data existed when 112 was chosen, even though these rows were not scored. It is therefore evidence about Alternative 1 (regime) and Alternative 2 (shrinkage), and **cannot on its own justify shipping**.

*Stage B — fresh-vintage confirmation.* When **≥45 vintages with `t0 ≥ 2026-08-26`** exist (≈2026-10-09; 45 rather than 14 for the power reason above, and ≥ the EXP-023 discovery end so there is no overlap), run the same two rungs on that range. Incumbent = 56d. Treatment = 112d.

*Gates.* IMPLEMENT iff **all four** hold **on Stage B** (Stage A informs but does not gate):

1. **Skill:** paired DM on per-observation quantile score, H1 112d better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size:** 112d QS at least **1.5%** better than 56d. Deliberately below the in-sample 3.0% — half the discovery effect is the most that can be honestly demanded of a properly-powered replication of a small effect, and pretending otherwise would make the gate unpassable by design.
3. **Calibration:** 112d lower- and upper-side coverage each **not more than 0.02 worse** than 56d (raw quantiles, no CQR).
4. **Sharpness:** 112d mean Winkler (α=0.20) **≤ 1.05 ×** 56d.

*If it passes.* The change is one constant (`WINDOW_DAYS` in `ml/shadow/update_shadow.py` and its siblings), and the revert is the same one constant. Deploy behind the same live-shadow discipline ADR-006 was earned with: 14 evaluable post-deploy vintages in `shadow_state.json:calibration_history`, `lightgbm_mae` not worse than the pre-deploy trailing-14 mean, no new alarm classes. **Note the interaction with EXP-018a**: if that ships the lean feature set, re-derive the optimum before changing the window, per Alternative 3.

**Addendum 2026-08-30 (feasibility defect found before Stage A was run; gates unchanged).** The Stage A range above is **wrong and unrunnable**, and finding out why also corrects a factual error in EXP-023's own record. `load_frame_ext` drops rows on the EXP-020 fundamentals columns, which begin 2025-12-01, so the *feature frame* starts **2025-12-02** — not the parquet's 2025-09-28. Consequences:

- The earliest usable `t0` for a 112-day window is **2026-03-24**, not 2026-01-18, so the pre-committed Stage A range (2026-01-20..2026-03-14) yields **zero** vintages.
- **EXP-023's discovery window was `2026-05-19..2026-08-21`, not "2026-03-15..2026-08-21" / "Mar–Aug 2026"** as recorded in `experiments/registry.jsonl` EXP-023 notes, `docs/model-progress-log.md`, CLAUDE.md and `memory/MEMORY.md`. The real window is **three months, May–August**, narrower and later than recorded — which makes Alternative 1 (regime artifact) *more* live, not less, since May–Aug 2026 is squarely the rising-price stretch.

**Corrected Stage A range: `t0 ∈ [2026-03-24, 2026-05-18]`** — the vintages that a 112d window can reach and that the discovery sweep never scored, ~56 of them. Everything else about Stage A is unchanged: two rungs only (56 and 112, treatment still fixed in advance), `lean`, quasi-holdout status, informs but does not gate. **Stage B and all four gates are untouched.** Recorded here rather than edited into the text above, per ADR-007: this is a defect in the data the Method reads, found *before* any Stage A number was seen, not a Method loosened after a peek.

**Revisit trigger:** Stage A immediately (corrected range). Stage B at ≥45 vintages with `t0 ≥ 2026-08-26`, ≈2026-10-09, and **after** EXP-018a Stage 1 has claimed the fresh window. Surface in `/curate`.

**Review by:** 2026-11-15.

**Domain:** EXP-023a, window length, ADR-006, augur#19, `scripts/exp023_window_sweep.py`.

**Status:** open — pre-committed 2026-08-30, before either stage was run.

### [2026-08-30] EXP-028a: Chronos-2's covariate gain survives on uncontaminated fresh vintages, and the coverage cost is a real trade rather than a fixable artifact

**Position (provisional):** EXP-028 found `amazon/chronos-2` gains **8.3% quantile score** (DM p=0.0051) from exogenous covariates supplied at inference time with no retraining — Augur's first positive exogenous result, and a genuine qualification of EXP-020's "exogenous is inert" conclusion, which held for LightGBM and for a LightGBM-specific mechanism. Position: the gain reproduces on fresh vintages, and the coverage cost that failed gate 3 (lower 0.923→0.886, upper 0.880→0.856) persists rather than vanishing — i.e. it is a real skill-for-calibration trade that a conformal layer must be asked to absorb, not a small-sample wobble.

**Why this needs its own pre-commit, and why it is more urgent than EXP-023a's:** EXP-028 carries a contamination exposure that none of the Bolt experiments do. `chronos-bolt-base`'s weights were frozen **2025-11-21**, before the evaluation window, so EXP-021 could call contamination *impossible*. **`amazon/chronos-2` was last modified 2026-06-05 — inside the window.** Restricting to `t0 > 2026-06-05` removes overlap with the freeze date but does **not** prove the pretraining corpus excludes NL day-ahead prices. Fresh vintages from September onward are the only thing that resolves this by construction, and they are the reason this entry exists. Additionally the discovery ran on only **77 vintages**, and its covariates carry the harness's vintage-overwrite optimism (ratio 1.84), which biases *toward* the result.

**Alternatives (failure-mode signals):**

1. **It was contamination.** **Signal:** the gain collapses to under 2% on vintages strictly after the weight-modification date by a wide margin. Then the exogenous question is *not* re-opened, EXP-020's conclusion stands unqualified across model classes, and this is the most important negative available — it would also cast doubt on the c2-vs-bolt comparison generally.
2. **It was the model, not the covariates.** chronos-2 univariate already beat bolt-base by 5.5% on the discovery subset. **Signal:** the covariate-vs-univariate delta shrinks while chronos-2 univariate keeps beating bolt. Then the headline belongs to the newer checkpoint and the covariate story is separate and smaller. *(The covariate-vs-univariate comparison is the internally valid one precisely because both arms share weights; this alternative is why the two must never be conflated.)*
3. **The coverage cost is fixable, not intrinsic.** **Signal:** applying CQR to the covariate arm restores coverage to ≥0.80 without giving back the skill. Then gate 3's failure was an artifact of comparing raw bands, and the arm becomes shippable on a conformal layer we already run.
4. **Exogenous freshness is doing the work.** The harness feeds vintage-overwritten covariates, fresher than the live cron sees. **Signal:** re-running with covariates lagged to what was genuinely known at t0 erases the gain. Then the result is a backtest artifact and cannot survive deployment — **this arm is mandatory, not optional**, because it is the failure mode most likely to produce a real-looking gain that dies in production.

**Method (pre-committed 2026-08-30, before any fresh vintage is scored):**

*Stage 1 — fresh, uncontaminated confirmation.* When **≥28 vintages with `t0 ≥ 2026-08-26`** exist (≈2026-09-23; 28 rather than 14 because the discovery subset was small and the effect must clear a raised bar), re-run four arms on that range with `scripts/exp028_chronos2_covariates.py`:

```
c2_univariate            base
c2_known_future          treatment  — PRIMARY
c2_known_future_lagged   Alternative 4: covariates as known at t0, not overwritten
bolt_base                reference  (frozen weights, contamination-free anchor)
```

*Gates.* IMPLEMENT-as-candidate iff **all four** hold for `c2_known_future` vs `c2_univariate`:

1. **Skill:** paired DM on per-observation quantile score, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size:** QS at least **5%** better — the same bar the discovery cleared (8.3%), not lowered, because unlike EXP-023a this effect is large enough that a properly-powered replication can be held to it.
3. **Calibration:** lower- and upper-side coverage each not more than **0.02** worse than the univariate base. **This gate FAILED in discovery and is expected to fail again**; the Position predicts it. Failing it again is *not* a reason to loosen it — it routes to Stage 2 rather than to shipping.
4. **Sharpness:** mean Winkler (α=0.20) ≤ 1.05 × base.

*Mandatory regardless of gate outcome:* report `c2_known_future_lagged`. If the lagged arm loses more than half the gain, record Alternative 4 as confirmed and **stop** — no Stage 2, whatever the primary arm did.

*Stage 2 — only if skill passes and calibration fails, which is what the Position predicts.* Apply the production CQR layer to both arms and re-score. Ship-worthy iff the covariate arm's CQR-corrected band coverage is within 0.02 of the univariate arm's **and** it keeps ≥5% QS advantage. That tests Alternative 3 directly. If CQR cannot absorb the cost, the honest conclusion is that covariates buy point skill at a calibration price Augur should not pay while augur#19 is open, and the entry parks.

**What does not happen in this entry, whatever the numbers.** No production path is touched. Chronos-2 is not in the nightly job, and EXP-021a — the confirmation ladder for the foundation model as *forecaster* — is a separate and earlier question than whether that forecaster gets covariates. If EXP-021a fails, this entry is moot regardless of its own result.

**Revisit trigger:** ≥28 vintages with `t0 ≥ 2026-08-26`, ≈2026-09-23, after EXP-018a Stage 1. Surface in `/curate`.

**Review by:** 2026-10-31.

**Domain:** EXP-028a, foundation models (augur#15), exogenous features (augur#3, augur#22), augur#19, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-30, before any fresh vintage was scored.

### [2026-08-29] EXP-021a: Chronos-Bolt's 20% zero-shot win survives on fresh vintages, and survives contact with production constraints

**Position (provisional):** EXP-021 (resolved same day) measured `chronos-bolt-base` zero-shot at **-20.3% quantile score and -16% MAE against the lean LightGBM incumbent**, with raw band coverage 0.811 against a 0.80 target where the incumbent sits at 0.611, on 260 paired vintages. Position: this reproduces on vintages that did not exist when it was measured, and the operational objections to running it in production (latency, dependency weight, the loss of a nightly-refit story, no CPU path on sadalsuud) are surmountable rather than disqualifying.

**Why this needs its own pre-commit:** EXP-021's window is the same one EXP-018/019/020 already explored. The usual selection-bias objection is *weaker* here than it was for EXP-018a — a zero-shot arm tunes nothing, so there was no search to overfit with, and the model's weights were frozen 2025-11-21, before the window opens. But "weaker" is not "absent": the window was chosen because it is the one already instrumented, the FM was chosen after a literature scan, and a 20% claim against a production system should clear a fresh-vintage bar at least as high as the 8% one did. Per ADR-007 the confirming test is fixed here, before the confirming data exists and before any production path is touched.

**Alternatives (failure-mode signals):**

1. **The gap is a backtest artifact of exogenous freshness.** The EXP-018 harness reads a parquet whose exogenous rows are overwritten by later vintages (refuted-hypothesis 2026-05-29, ratio 1.84), so the *incumbent* is scored with fresher inputs than the live cron sees — but the incumbent is also the arm that gets hurt if that advantage is removed, and the FM uses no exogenous at all. **Signal:** the gap *widens* on live vintages rather than narrowing. That is a confirmation, not a failure — recorded here so the direction is fixed in advance and cannot be read either way after the fact.
2. **Latency or footprint makes it undeployable.** 205M params, a torch install, and a GPU-less production host. **Signal:** CPU inference for 1 vintage x 72h exceeds ~60s on sadalsuud's hardware, or the dependency set cannot be installed alongside the existing venv. Then the arm is offline-only — an ensemble member or a band source scored on the GPU box, not the nightly production path.
3. **Zero-shot skill is unstable vintage-to-vintage.** Pooled means can hide a model that is excellent on 8 days and catastrophic on the 9th, which matters far more for a live dashboard than for a pooled score. **Signal:** the FM's per-vintage MAE distribution has a materially heavier right tail than the incumbent's (95th percentile more than 1.5x the incumbent's 95th). Then the pooled win is not the operationally relevant statistic and a hybrid/guarded design is needed.
4. **The calibration win does not survive CQR.** EXP-021 compared *raw* bands, where the incumbent is at 0.611 and badly under-covering. Production wraps CQR around it. **Signal:** the incumbent's CQR-widened live coverage (`shadow_state.json:calibration_history`) is comparable to the FM's raw coverage. Then the calibration half of EXP-021 is an artifact of comparing a pre-conformal band to a post-conformal one, and only the skill half stands.

**Method (pre-committed 2026-08-29, before any fresh vintage is scored and before any production path is touched):**

*Stage 1 — fresh-vintage confirmation, offline, zero production risk.* When ≥14 vintages with `t0 ≥ 2026-08-25` exist in the parquet (≈2026-09-09 — the same trigger as EXP-018a Stage 1, which has priority on that window and must run first), re-run all three arms on `t0 ≥ 2026-08-25` only:

```
PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py contexts \
    --start 2026-08-25 --end <first-unrealised-day> --context-end-offset-h 1 \
    --out ml/shadow/exp021_stage1
# predict on b650-gpu, then:
PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py score \
    --out ml/shadow/exp021_stage1 --incumbents <fresh full/lean predictions>
```

Incumbent = whichever base EXP-018a Stage 1 leaves standing (`lean` if it passes, `full` if it fails); if EXP-018a has not concluded, the primary gate stays against `lean`, the harder bar, exactly as in EXP-021. **The matched-information arm (`--context-end-offset-h 1`) is the one that counts**; the unmatched arm is not run again. IMPLEMENT-as-candidate iff all four hold:

1. **Skill:** paired DM on per-observation quantile score, H1 FM better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size survives:** FM QS at least **10% better** than the incumbent. Deliberately higher than EXP-018a's 3%: the in-sample effect is 20%, and a bar of 3% would let a 90%-shrunken result pass as confirmation.
3. **Calibration:** FM lower- and upper-side coverage each **not more than 0.02 worse** than the incumbent (raw quantiles, no CQR, both arms).
4. **Sharpness:** FM mean Winkler (α=0.20) **≤ 1.05 ×** incumbent.

*Stage 2 — operational feasibility, gated on Stage 1 and decided on measurement, not preference.* Only if Stage 1 passes. Measure, on sadalsuud's actual hardware: (a) CPU-only wall-clock for one 1344-point context x 72h forecast, 10 runs, report median and max; (b) venv size delta and whether `torch` installs cleanly alongside the existing pins; (c) a 14-day replay of per-vintage MAE distributions for Alternative 3's tail check. Feasible iff median CPU latency ≤60s **and** the p95 per-vintage MAE ratio (FM ÷ incumbent) ≤1.5. Infeasible on latency alone → the FM becomes an offline band source for augur#19 rather than the production forecaster, which is a smaller but still real win.

*Stage 3 — shadow, then swap.* Only if Stages 1 and 2 pass. The FM runs as a **shadow** alongside production LightGBM for **14 evaluable vintages**, written to a separate output file, dashboard untouched — the same shape as the original LightGBM shadow that produced ADR-006, and for the same reason: EXP-014's promotion was earned by a live shadow, not a backtest, and this one will be too. Promotion criterion at that point is ADR-007's, re-derived against whatever the incumbent then is; ADR-006 is amended only after a live swap, never before.

**What is explicitly not decided by this entry:** whether Augur's production forecaster *should* be a 205M-parameter pretrained model rather than a 1344-row nightly refit is a question about operational surface, reproducibility and the project's ability to debug its own forecasts — not only about quantile score. Stage 3 is where that judgement gets made, with a live shadow in hand. Recording it here so a strong Stage 1 does not read as having settled it.

**Revisit trigger:** ≥14 vintages with `t0 ≥ 2026-08-25` in the parquet — ≈2026-09-09, **after** EXP-018a Stage 1 has run on the same window. Surface in `/curate`.

**Review by:** 2026-10-15.

**Domain:** EXP-021a, augur#15 (foundation models), augur#19 (calibration), model class, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-29 immediately after EXP-021 resolved, before any production path was touched.

### [2026-08-28] The t0 guard plus the publish-hour gate end silent vintage loss; EDH's skipped publishes are the residual, and they are not ours to fix

**Position (provisional):** Two changes shipped today (`4a2afc4`, `05b4d43`) close the failure that cost the 2026-08-25 vintage: `wait_for_edh.sh` now requires the EDH report to be stamped ≥12:00 UTC as well as dated today, so an overnight catch-up publish can no longer release the run early; and `classify_t0_advance` alarms in the commit subject whenever t0 fails to advance exactly one calendar day. Position: from here on, **every vintage is either produced or loudly announced as missing** — no further day is lost without a same-day marker naming the cause. The residual failure rate is then EDH's, not ours: over 2026-07-25..08-28 EDH published on 31 of 35 days (missing 08-03, 08-06, 08-23, 08-27; catch-up double-publishes on 08-09 and 08-24), so expect roughly one `[ALARM: t0 stale …]` per fortnight with no Augur-side defect behind it.

**Alternatives (failure-mode signals):**

1. **The 12:00 UTC floor is mis-set.** If EDH ever moves its schedule earlier, or a legitimate publish lands before noon UTC, the gate waits the full 4h and the run goes out late on stale data every day. **Signal:** `[ALARM: t0 stale …]` on days where EDH *did* publish, with a pre-noon timestamp in `logs/daily_update.log`. Then the floor is the bug, not the publish — move it, or switch to the semantically exact test (report timestamp strictly newer than the one the last successful run consumed, persisted across runs).
2. **The race is narrower than the fix.** The 08-24 miss was 90 seconds. If EDH's publish drifts to straddle 16:30 routinely, the gate releases on the *previous* day's ≥12:00 publish before today's lands — the same failure with a different clock offset. **Signal:** a `t0 stale` alarm on a day EDH published after 16:30. Then the fix is augur#25 (repository_dispatch, event-driven) rather than any polling threshold.
3. **Skipped publishes are not random.** Four misses in five weeks may be a systematic EDH failure (a workflow that silently exits 0) rather than transient runner flakiness. **Signal:** the EDH issue filed today identifies a repeating cause. Then Augur's absorption is a band-aid over something fixable upstream, and the residual rate should drop rather than persist.

**Method:** After **14 consecutive daily runs** on the deployed code (2026-08-28 → ≈2026-09-11), from the daily commit subjects and `ml/models/shadow/shadow_state.json`:

```
# (1) No silent loss: every eval_day gap in calibration_history has a
#     matching [ALARM: t0 ...] marker on the commit for that date.
# (2) No false alarms: every [ALARM: t0 stale] day is one where EDH
#     genuinely published nothing >= 12:00 UTC (check EDH commit history).
# (3) Alarm rate <= 3 in 14 days, consistent with EDH's observed ~11% miss rate.
```

Position confirmed if all three hold. (1) failing means the guard has a blind spot — investigate before trusting any trailing-window metric. (2) failing confirms Alternative 1 or 2. (3) failing means EDH reliability degraded and Alternative 3 becomes the priority.

**Revisit trigger:** 14 daily runs on deployed code, ≈2026-09-11 — before EXP-018a Stage 1 (≈2026-09-09) consumes the vintages this guard protects. Surface in `/curate`.

**Review by:** 2026-09-18.

**Domain:** daily pipeline reliability, `wait_for_edh.sh`, `update_shadow.py`, augur#14, augur#25, EDH publish reliability.

**Addendum [2026-08-31] — the Position is falsified on both halves, 11 days before its own review date.**

The 2026-08-30 run lost a vintage. What the Position claimed cannot happen, happened:

1. **"Every vintage is either produced or loudly announced as missing" — half true, and the half that failed is the diagnostic half.** The day *was* announced, as `shadow rc=1/eval rc=skip` in the commit subject. But **no `[ALARM: t0 ...]` marker appeared at all**, because `T0_MARKER` in `daily_update.sh` is computed inside `if [ "${SHADOW_UPDATE_RC:-1}" -eq 0 ]`. That gate is deliberate and its comment is right — on a failed run `shadow_state.json` still holds the previous run's values, so an ungated marker would re-fire a stale alarm. The consequence was not anticipated: **a crash both loses the vintage and suppresses the alarm that would name why.** Criterion (1) of the Method fails as written — the gap in `calibration_history` has no matching t0 marker.
2. **"The residual failure rate is then EDH's, not ours" — refuted.** The loss was not an EDH skip. EDH published normally at 19:02 UTC. The vintage died on an **Augur-side structural defect**: `t0 = parquet["price_eur_mwh"].dropna().index.max()` followed the longest column while `predict_72h` requires all five feature columns, so when ENTSO-E returned A44 day-ahead prices for 08-31 but not A65 day-ahead load, the feature row was part-NaN and the run raised. The residual was ours, in a component this Position had just declared closed.

**What none of the three Alternatives predicted.** All three are about *publish timing* — a mis-set floor, a narrower race, a systematic skip. The actual mechanism was **feed-horizon divergence inside a publish that arrived exactly on time**. The Position's blind spot was treating "did the data arrive" as the whole question and never asking "does the data that arrived span what the model needs".

**Shipped in response** (2026-08-31): `latest_feasible_t0` (`87ed30c`) anchors t0 on the last *complete* feature row and names the short feeds; `1bfd728` persists `t0_held_back_hours`/`t0_short_feeds` and emits `[ALARM: t0 held back Nh — <feeds> short]`, because the first version of that fix only *logged* the hold-back — repeating this entry's own lesson inside its own remedy. Alerting gained a commit-subject marker reader (`da57139`) after `shadow rc=1` sat unread for ~11 hours.

**Not changed — decided 2026-08-31, deliberately, and this is the record so it is not re-litigated as an oversight.** The `SHADOW_UPDATE_RC -eq 0` gate on `T0_MARKER` stays. Three options were weighed:

- *Ungate it* — rejected as **strictly worse**. On a failed run `shadow_state.json` still holds the previous run's values, so `t0_advance_days` would report yesterday's number as today's: a stale `advance=1` reads as **healthy**, which is worse than silence.
- *Emit `[t0 unknown — shadow failed]` on non-zero rc* — rejected as redundant. It fires only on days whose subject already carries `shadow rc=N`, so it adds a marker without adding information.
- *Leave it* — **chosen.** The gate is correct in itself; the heartbeat's commit-subject reader now catches `rc=1` independently, so detection does not route through `T0_MARKER` at all. The residual gap is **forensic, not operational**: a reader of `git log` alone cannot tell from a crashed day's subject whether a vintage was skipped, though `calibration_history` still shows it.

**This review is the point at which to revisit it, on data rather than judgement** — criterion (1) below was rewritten precisely to measure it over 14 runs. If any gap in `calibration_history` turns out to have been diagnosable *only* from the run log, the forensic gap is real and worth closing; if the `rc=N` signal proved sufficient every time, close this as settled.

**Revised Method for the 2026-09-11 review.** Criteria (2) and (3) stand. Criterion (1) is replaced by: *every gap in `calibration_history` has a same-day commit subject carrying **either** a `[ALARM: t0 ...]` marker **or** a non-zero step rc* — the honest version of "loudly announced", which the original conflated with "correctly diagnosed". Add (4): *no `[ALARM: t0 held back Nh]` appears on a day when both feeds were full-length*, which would mean the new anchor is over-triggering.

**Status:** open — Position falsified 2026-08-31 and rewritten above; the 14-run window restarts from the 2026-08-31 run on `87ed30c`/`1bfd728`. Original deployment 2026-08-28.

### [2026-08-31] The load/price horizon divergence is transient ENTSO-E outage residue, not a new steady state

**Position (provisional):** The 2026-08-30 publish in which EDH's `load_forecast` spanned 24h while `energy_price_forecast` spanned 48h is **one-off outage residue and will not recur**. Basis: the energyDataHub session decrypted the committed publish (`8e5cc52`) and found EDH's request window unchanged at 48h with the envelope still declaring `end_time 2026-08-31T23:59:59+02:00` — so the collector asked for two days and ENTSO-E returned A44 day-ahead prices for 08-31 but not A65 day-ahead load. 2026-08-29 was a total ENTSO-E 503 at EDH (run `33269881393` published nothing), and the 08-30 18:58 run was the first success after it. Every normal-hour publish sampled before that — 08-20, 08-21, 08-24 16:32, 08-25, 08-26 — carried both feeds at 192 points. Filed as energydatahub#51.

**Alternatives (failure-mode signals):**

1. **It is a new steady state.** ENTSO-E's A65 day-ahead load publication may have moved to a 24h horizon permanently, or EDH's window may drift. **Signal:** three or more consecutive normal-hour publishes with price 192 / load 96. Then the `[ALARM: t0 held back Nh]` marker fires nightly forever, the forecast permanently loses ~24h of reach, and the response is a real decision rather than a wait — either accept the shorter horizon, or reconsider whether `load_forecast` earns its place at all (which is **EXP-018a's** question, so it must not be pre-empted by this).
2. **It is intermittent rather than transient.** Recurs every few weeks tied to ENTSO-E incidents. **Signal:** the marker fires, clears, and fires again within a month with a full-length publish in between. Then the hold-back mechanism is doing exactly its job and nothing more is needed — but the nightly heartbeat email becomes noise on those days, and the marker should probably alarm only after N consecutive days rather than on the first.
3. **A different feed truncates next.** The mechanism is not specific to load — any feed whose delivered span can differ from its requested span has it. **Signal:** `t0_short_feeds` names a column other than `load_forecast`/`wind_gen_forecast_mw`/`solar_gen_forecast_mw`. Then the fix generalised correctly and the finding is upstream-wide, worth telling EDH for their horizon-coverage check.

**Method:** over the **next 7 daily runs** (2026-08-31 → ≈2026-09-07), from the daily commit subjects and `ml/models/shadow/shadow_state.json`:

```
# (1) Count days with t0_held_back_hours > 0.
# (2) For each, record t0_short_feeds and whether EDH published at a normal hour.
# (3) Cross-check against energydatahub#51's status and EDH's own publish record.
```

Position confirmed if the hold-back appears on ≤1 of the 7 days and `#51` is closed as non-reproducing. ≥3 consecutive days confirms Alternative 1. A clear-then-recur pattern confirms Alternative 2.

**Cost of being wrong is asymmetric and worth stating:** if the Position holds, doing nothing is correct and the marker self-clears. If Alternative 1 holds and we assume the Position, we run a permanently degraded forecast while a nightly alarm trains us to ignore it — the classic alert-fatigue path. So the failure mode to watch for is *not noticing the marker stopped being informative*.

**Revisit trigger (corrected 2026-09-04 — was "7 daily runs, ≈2026-09-07", which is the wrong instrument):** **two further NORMAL-HOUR EDH publishes**, regardless of calendar date. Alternative 1's signal is three consecutive normal-hour publishes at price 192 / load 96, and exactly one exists (`260830_190255`, 19:02). Daily *Augur* runs do not advance this test — during 08-31..09-04 there were five of them and zero usable publishes. Early-hour publishes do not count either: they are short in the benign, long-standing way (see the evidence table). Still resolve this **before** EXP-018a Stage 1, for the original reason — its verdict on `load_forecast` is cleaner if we know whether the column is reliably present — and Stage 1 has itself slipped ~5 days from the same outage. Surface in `/curate`.

**Review by:** 2026-09-30.

**Domain:** upstream data reliability, `update_shadow.py:latest_feasible_t0`, `ml/data/consolidate.py`, energydatahub#51, energydatahub#33, EXP-018a.

**Evidence added 2026-09-04 — the Position's basis is confirmed and the Position itself is now the losing side, but the pre-committed signal is formally short.** Every `load_forecast` vintage on EDH `origin/main` was decrypted and counted by **distinct calendar days** as well as points, so a resolution change cannot be confused with a horizon change:

| vintage | publish hour | load NL | days | price entsoe | days |
|---|---|---|---|---|---|
| 260815_161800 | 16:18 | 192 | 2 | 192 | 2 |
| 260820_162737 | 16:27 | 192 | 2 | 192 | 2 |
| 260822_161734 | 16:17 | 192 | 2 | — | — |
| 260824_062847 | 06:28 | 96 | 1 | — | — |
| 260824_163211 | 16:32 | 192 | 2 | 192 | 2 |
| 260826_164411 | 16:44 | 192 | 2 | 96 | 1 |
| 260828_004401 | 00:44 | 96 | 1 | — | — |
| 260829_002024 | 00:20 | 96 | 1 | 96 | 1 |
| **260830_190255** | **19:02** | **96** | **1** | **192** | **2** |
| 260904_065333 | 06:53 | 96 | 1 | 96 | 1 |

**The Position's basis holds** — normal is 192/2 days, for months, so this is not a same-day feed and the 18h hold-back is a real loss of reach rather than a structural cost to design around. **The Position's conclusion does not** — "one-off, will not recur" is now four consecutive short publishes with no return to 192 since 08-26.

**The discriminator neither side had until now is publish hour.** Every 96/1 vintage *before* 08-28 is an early-hour run that recovered to 192 on the same day's normal-hour run (08-09 05:56→96 then 16:27→192; 08-24 06:28→96 then 16:32→192). So short-at-early-hour is the benign, long-standing pattern, and only a **normal-hour** short vintage is evidence. There is exactly one: `260830_190255` at 19:02. `260904_065333` is an early-hour manual dispatch and **does not count**.

**So Alternative 1 is strongly indicated and formally short of its signal** (three or more consecutive normal-hour publishes at price 192 / load 96): the 08-31..09-04 EDH publish outage denied us the normal-hour publishes the test requires. Recorded as indicative, **not** confirmed — resolve on the next two scheduled EDH runs rather than on the calendar trigger. Corroboration from the EDH session's own archive read: `metadata.end_time` declares +2 days on every short vintage, so EDH's request window is unchanged and the envelope over-declares its coverage; DE_LU tracks NL exactly, so it is not zone-specific. Locates the cause in **upstream ENTSO-E A65 availability**. **energydatahub#51 must not be closed as transient on this evidence.**

**Alternative 3 gains a concrete instance, in the other direction.** The mechanism generalises further than "another feed truncates": `load_forecast` is in EDH's `CRITICAL_FEEDS` and delivered half its horizon for four publishes **without their drift tripwire objecting**, because a shape signature captures structure and not span — 96 and 192 records have identical shape. No `CRITICAL_FEEDS` membership fixes that; a horizon/span check is a different instrument and neither repo has one. Augur's `t0` hold-back alarm was the only detector that fired. Told to EDH 2026-09-04; unowned on both sides.

**Narrowed 2026-09-04, and the scope was wider than it needed to be: this is an NL-only question.** `ml/data/consolidate.py:320 parse_load_file` reads `load_data.get("NL", {})` — hard-coded, no fallback, no merge — and `grep -rn "DE_LU" ml/ static/js/ scripts/` returns **zero hits** repo-wide. So `load_forecast` in `FEATURE_COLUMNS` is NL-only, `latest_feasible_t0` holds back on NL coverage alone, and DE_LU's state is structurally invisible to Augur. The evidence table above records both zones because that is what the publishes contain, but only the NL column bears on this entry.

**Pre-registered prediction (from the EDH session, stated 2026-09-04 09:59 CEST before the fact).** A direct ENTSO-E A65 probe found **NL recovered to 192/2 days while DE_LU is still 96/1**, with widening the request to +3d changing nothing and `DE_LU`-tomorrow-alone raising `NoMatchingDataError` — so tomorrow's NL data exists and tomorrow's DE_LU data does not. Their parser check (`_parse_response` in `collectors/entsoe_load.py` builds each zone's index from its own series, no cross-zone intersection) rules out a short DE_LU truncating NL, so the 08-28..08-30 96/96 was both zones genuinely short at once. Revised timeline: **through 08-26 both 192 · 08-28..08-30 both 96 · 09-04 NL 192, DE_LU 96.** Prediction for tonight's ~19:00 UTC scheduled publish: load NL **192/2**, DE_LU **96/1**, price entsoe **192/2**. Augur-side check: `t0_held_back_hours` → 0 and `t0_short_feeds` drops `load_forecast`.

**⚠️ How to score tonight, because the two outcomes are easy to conflate.** If NL returns 192, **Alternative 1 is falsified before its signal could accumulate** — that is *not* "signal met, alternative confirmed", and it is not "nothing happened either": the 08-28..08-30 gap was real, cost reach, and will be invisible once NL is back at 192. Record it as falsified-with-the-gap-on-record. If NL returns 96, the probe caught a transient and the accumulation toward Alternative 1 continues. The DE_LU timing confound the EDH session flagged (German TSOs possibly publishing day-ahead load later) cannot affect this scoring either way, given the NL-only finding above.

**Status:** open — Augur-side fix deployed 2026-08-31; this hypothesis is about the upstream behaviour, not the fix. **Evidence added 2026-09-04 (above): Position's basis confirmed, its "one-off" conclusion superseded, Alternative 1 indicated but formally short. Narrowed the same day to NL-only, and a pre-registered probe predicts NL recovery — so the likely resolution is Alternative 1 FALSIFIED on the zone we use, decided by tonight's normal-hour publish rather than by the ≈2026-09-07 calendar trigger.**

### [2026-08-25] EXP-018a: removing the six rolling-stat features (and the three exogenous) beats the 24-feature production set out of sample

**Position (provisional):** The EXP-018 Stage-0 sweep (entry below) found the production feature set carries features that actively hurt: dropping the six rolling stats buys −6.0% MAE / −7.8% quantile score, and the 15-feature **lean** set (rolling + exogenous removed) buys −6.5% / −8.1% with better lower-side coverage. Position: this is a real generalisation gain, not a selection artifact, and it will reproduce on vintages that did not exist when the finding was made. Mechanism claim: absolute-level features (`price_rolling_mean_168h` above all) make tree splits that are calibrated to the training window's price level, which is exactly what breaks when the level drifts — the same failure that produced August's upper-side coverage breach.

**Why this needs its own pre-commit:** Stage 0 was pre-committed as *descriptive*. The lean variant is the best of eight compared on one 263-vintage window, so its effect size is upward-biased by selection. Per ADR-007 ("don't loosen Method when the answer arrives; open a new entry"), the confirming test is fixed here, before the confirming data is looked at — and before any change to `FEATURE_COLUMNS`.

**Alternatives (failure-mode signals):**

1. **Regime-dependent, not universally harmful.** Rolling stats cost us in the volatile 2026 regime but earned their place in calm months — Stage 0 shows a +5.8% *loss* from dropping them in Dec 2025 and a wash in Jan. **Signal:** the fresh-vintage window is calm and shows no gain. Then the answer is regime-conditional features (or a longer training window), not deletion, and this entry is refuted rather than the feature set vindicated.
2. ~~**The real lever is stationarity, not removal.** Lean wins because absolute-level features drift, not because the information is worthless. **Signal:** a stationary reformulation (`price_lag_1h − price_rolling_mean_168h` spreads, price/rolling-mean ratios) beats *both* lean and incumbent in the same harness. Then park the deletion and open EXP-019 for the reformulation.~~ **Refuted same day (EXP-019, `scripts/exp019_stationary_ablation.py`, same 263 vintages):** anchor-relative spreads *tie* plain deletion (lean vs stat_lean_noanchor: QS p=0.405, |error| p=0.160), and re-adding `price_rolling_mean_168h` as the single explicit level column costs significantly (MAE −5.7% → −2.5% vs incumbent, QS p=0.0001). Since raw price lags are also absolute levels and are harmless, drift is at most half the mechanism — redundant smoothed-level columns diluting the split search fits better. Treatment for Stage 1 stays the plain 15-feature lean set.
3. **Selection-bias mirage.** **Signal:** fresh-vintage QS gain is under 2% (against −8.1% in-sample). Do not ship on a shrunken effect; extend the holdout instead.
4. **Exogenous removal is the wrong half.** Lean drops rolling *and* exogenous; the offline harness is if anything biased *toward* keeping exogenous (`consolidate.py` overwrites parquet rows with later vintages, so backtest exogenous is fresher than live). **Signal:** `drop_rolling` alone ≥ lean on fresh vintages. Then ship the rolling deletion only and keep wind/solar/load.

**Method (pre-committed 2026-08-25):**

*Stage 1 — fresh-vintage confirmation, offline, zero production risk.* When ≥14 vintages with `t0 ≥ 2026-08-25` exist in `ml/data/training_history.parquet` (≈2026-09-09, allowing for the 72h realisation lag), run:

```
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python scripts/exp018_stage0_ablation.py \
    --start 2026-08-25 --end <first-unrealised-day> --jobs 14 \
    --variants full,drop_rolling,drop_rolling_and_exog \
    --out ml/shadow/exp018_stage1
```

Incumbent = `full`. Treatment = whichever of `drop_rolling` / `drop_rolling_and_exog` has the lower in-sample QS (i.e. `drop_rolling_and_exog`, fixed here so the choice is not made on the holdout). IMPLEMENT iff **all four** hold on the fresh vintages:

1. **Skill:** paired DM on per-observation quantile score, H1 treatment better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size survives:** treatment QS at least **3% better** than incumbent (guards Alternative 3; in-sample was 8.1%).
3. **Calibration:** treatment lower-side and upper-side coverage each **not more than 0.02 worse** than incumbent (raw quantiles, no CQR — same "not worse than incumbent" framing as EXP-014).
4. **Sharpness:** treatment mean Winkler (α=0.20) **≤ 1.05 ×** incumbent.

*Stage 2 — live confirmation after deploy.* Swap `FEATURE_COLUMNS` in `ml/shadow/features_pandas.py`, deploy, then after **14 evaluable post-deploy vintages** in `shadow_state.json:calibration_history` (NOT `eval_log.jsonl` — it mixes 24/48/72h vintages): (1) mean `lightgbm_mae` from `eval_log.jsonl` ≤ the pre-deploy trailing-14-vintage mean; (2) band coverage not worse than the pre-deploy trailing-14 baseline (0.660 for Aug 2026 — a low bar, deliberately: this entry is about skill, augur#19 is the calibration arc); (3) no new alarm classes in the daily commit subjects. PASS → registry `kept`, update ADR-006's feature list + CLAUDE.md. FAIL → revert (one-line: restore the six/nine columns), registry `rolled_back`.

**Addendum 2026-08-28 (data defect, gates unchanged):** the vintage stream broke 2026-08-23..27 — EDH skipped its publish entirely on 08-23 and 08-27, and its overnight catch-up released Augur's gate early on 08-24, so `t0` repeated on 08-23/08-27 and jumped over 08-25, so **`eval_log.jsonl` has a permanent hole at 2026-08-25** (third, after 06-08/06-10). This does not touch Stage 1, which replays its own t0 grid off `training_history.parquet` rather than off shadow vintages. It does touch **Stage 2 check (1)**, whose trailing-14 mean comes from `eval_log.jsonl`: read 14 *present* rows, do not treat the hole as a zero or let it silently shorten the window, and apply the same rule to the pre-deploy baseline so both sides are measured the same way. Per ADR-007 this records a defect in the data the Method reads; the four Stage-1 gates and the three Stage-2 checks are unchanged. A `t0`-advance guard now alarms on the same failure same-day — see `docs/model-progress-log.md` 2026-08-28.

**Revisit trigger:** ≥14 vintages with `t0 ≥ 2026-08-25` in the parquet — ≈2026-09-09. Surface in `/curate`.

**Review by:** 2026-09-16.

**Domain:** EXP-018a, feature engineering, LightGBM production architecture (ADR-006), augur#19.

**Status:** open — pre-committed 2026-08-25, awaiting fresh vintages. Branch `exp018-feature-reduction`.

### [2026-05-29] The Augur method + the M4 arc are publishable if we invest ~2-3 weeks of empirical follow-up

**Position (provisional):** Augur's production stack (ADR-006: LightGBM-Quantile multi-horizon + CQR + horizon-as-feature stacking + 56-day rolling window on NL day-ahead) is *not* novel as a method — every component is in Lago, Marcjasz, De Schutter & Weron (2021) or Nowotarski & Weron (2018). On its own it's a competent application, not a paper. But combined with the five-iteration M4 → EXP-014 narrative arc (`docs/articles/m4-metric-redesign-story.md`) and the promotion method (ADR-007), plus ~2-3 weeks of standard EPF empirical follow-up, the package becomes publishable as an applied methodology paper at *International Journal of Forecasting* practitioner section, IEEE PES workshops, or similar applied-ML venues.

**Alternatives (failure modes):**

1. **Novelty bar still not met** even after the empirical follow-up. LGBM+CQR on NL is well-trod ground; the arc's contribution might be too case-study-y for a methodology venue. **Signal:** a peer skim says "interesting but not a methodology contribution." Fallback: publish the arc as a long-form blog post (Towards Data Science, Medium) instead. ~4-6 hours of light polish, no empirical follow-up needed.
2. **Interest drift before the work is done.** 2-3 weeks of empirical work is non-trivial; we may not have the bandwidth or motivation when the time comes. **Signal:** the review-by date passes without the work being prioritised. Fallback: same as (1) — blog only.
3. **A better venue exists we haven't surveyed.** EPF has its own conference culture (EEM, ENERGYCON), and an applied-ML practitioner audience might find the arc more useful than a methodology audience. **Signal:** finding a better-fit venue during the polish pass. Adjust target accordingly.

**Method (what gets the package to paper-ready, in order):**

When motivated to publish:

1. **Naive baseline + persistence** (rMAE per Lago 2021 — table-stakes for EPF). Add to `scripts/exp012_evaluate.py` or a sibling script.
2. **PIT histograms + reliability diagram** for LightGBM's 80% interval (table-stakes per Nowotarski & Weron 2018).
3. **Multi-window robustness** — re-run the EXP-014 criterion at 7/14/21/30-day windows from the same eval_log; confirm conclusions stable.
4. **Per-feature ablation** — drop each feature group (lags, calendar, wind, solar, load) and measure MAE/CRPS regression; cheap because LGBM trains fast.
5. **Hyperparameter sensitivity** — small grid around `n_estimators × num_leaves × learning_rate`; cheap.
6. **Optional: epftoolbox comparison** — if an NL dataset exists in `epftoolbox`, run LEAR/DNN as the benchmark. If not, skip.
7. **Canonical CRPS** — retrain at 9-19 quantiles, compute proper CRPS, re-run paired DM. Resolves the "3-point mean quantile score" caveat.
8. **Canonical threshold-weighted CRPS** — implement the Gneiting-Ranjan integral form, re-run on the same data. Resolves the "abstention-rewards" issue in the per-quantile-decomposition variant we have.
9. **Rewrite ADR-006 + arc article + ADR-007 into a single methodology paper** with these as the empirical contribution.

Items 1-5 are ~1 week. Items 6-8 are ~1 week. Item 9 is the polishing pass, ~3-5 days. Total ~2-3 weeks of focused work.

**Cheap shortcut (only the blog post):** items 1-3 sharpen the arc article enough for a TDS / Medium long-form, with no method-paper claims. ~3-4 days total. The current draft is already 80% there.

**Revisit trigger:** when we have a 2-3 week window we want to spend on publishing AND we still find the topic interesting. Surfaced by `/curate` at session-end. Independent of the production system — Augur runs whether or not we publish.

**Review by:** 2026-12-31 (loose — there's no external deadline; this becomes stale, not blocking).

**Domain:** Augur publication strategy, methodology dissemination
**Status:** open — backlog entry, no immediate action

---

## Resolved

### [2026-08-29 → resolved 2026-08-30] The 2026-08-29 experiment backlog: seven pre-committed arms, all executed

**Why this entry exists, and what it is making good.** `docs/experiment-backlog.md` (committed `4024420`, 2026-08-29) carries seven full ADR-007 pre-commits — Position, Alternatives with falsification signals, Method with gates. Its own promotion rule says that when one is picked up it must be copied into this file's `## Open` section verbatim with the run date added. **That rule was not followed**: all seven were run on 2026-08-29/30 and resolved straight into `experiments/registry.jsonl` and `docs/model-progress-log.md`, leaving this log with no trace of them. This entry restores the trace. They are filed under Resolved rather than Open because none is awaiting evidence any more.

**How pre-commitment is evidenced, given the rule was skipped.** Not by a copy in this file but by git, which is stronger: every Method body in the backlog is **sha256-identical between `4024420` and HEAD**, and the backlog commit (2026-08-29 20:44:27) precedes every result commit (`911be75` 21:01:57, `5260c2f` and `6e51032` the next morning). `scripts/audit_registry.py` check 5 re-verifies this on demand and exits non-zero if any Method was edited after its result landed.

**Outcomes** (full numbers in the registry; narrative in `docs/model-progress-log.md` 2026-08-29 and 2026-08-30):

| Entry | Decision | One-line outcome |
|---|---|---|
| EXP-023 window sweep | `parked` | 112d beats production's 56d by 3.0% QS, all four gates pass; parked because best-of-five on the discovery window, and only 95 vintages survive the confound control |
| EXP-024 lag richness | `rejected` | Widening the feature row fails (+2.5% QS worse); the matched control shows count *and* kind both matter (raw +2.5% vs derived +12.2% at identical width) |
| EXP-025 band transplant | `rejected` | Transplant fails (0.733 < 0.76 gate) — but its control arm showed lean+CQR reaches 0.788, correcting the calibration claim in EXP-021/022 |
| EXP-026 size ladder | `kept` | bolt-tiny retains 93.5% of base's advantage; coverage flat across the ladder |
| EXP-027 fine-tuning | `rejected` | Both halves degrade (MAE +19.0%, coverage 0.825→0.394); zero-shot is the deployment mode |
| EXP-028 chronos-2 covariates | `parked` | +8.3% QS from exogenous — Augur's first positive exogenous result — but fails the coverage gate |
| EXP-029 residual screen | `rejected` | Null as predicted, but invalid as a gate: it would have vetoed EXP-028's true positive |

**What this changes about the standing position.** Features, feature-row width and fine-tuning are all closed. Zero-shot foundation modelling is the deployment mode, latency is a non-issue (EXP-030), and two live threads remain: the 112-day window (cheap, needs fresh-vintage confirmation) and covariates in a covariate-capable model class.

**Domain:** EXP-023..EXP-030, `docs/experiment-backlog.md`, ADR-006, ADR-007, augur#15, augur#19.

**Status:** resolved 2026-08-30. Nothing shipped from any of the seven; no production path touched.

### [2026-08-29 -> resolved 2026-08-29] EXP-021: a pretrained time-series foundation model, zero-shot and feature-free, is competitive with the tuned LightGBM incumbent — model class is the lever EXP-020 pointed at

**Position (provisional):** EXP-020 closed the feature lever with a test that could have refuted it: at a 56-day window this model gains nothing from added exogenous columns and *loses* from added level columns, whatever their provenance. Two levers remain — window length and model class. This entry takes the model-class one. Position: `amazon/chronos-bolt-base`, run **zero-shot** on nothing but the 56-day price history that the incumbent trains on, lands within **5%** of the lean LightGBM's quantile score, and is **materially better on upper-side coverage** in the level-shift months (Jul/Aug 2026) — because its quantile heads were pretrained across many series and regimes and are therefore not recalibrated nightly to one 56-day price level, which is precisely the mechanism EXP-018/019/020 blamed **(the first half of this clause survived contact with the evidence; the level-drift half did not — see the Mechanism correction in the Resolution below, and EXP-022)** for both the dead weight in the feature set and the August upper-side breach (Aug 2026 upper 0.774, band 0.660, against a 128 EUR/MWh monthly mean).

Note this is a *competitiveness* position, not a superiority one, and it is deliberately weaker than EXP-018a's and EXP-020's. The honest prior against it is stated as Alternative 1: foundation models earn their keep across many series, and Augur is one series. A zero-shot model with no features, no NL-specific training and no exogenous inputs merely *drawing level* with a tuned gradient-boosting stack would already be the informative result, because it would mean the incumbent's entire feature and retraining apparatus buys nothing that pretraining does not already supply — and that reframes the roadmap far more than another 3% would.

**Why this is a new bet and not a re-run:** nothing in EXP-018/019/020 varied the model class; all three held `MultiHorizonLightGBMQuantileForecaster` fixed and moved columns. This entry holds the data, the window, the t0 grid, the horizon and the scoring fixed, and moves only the estimator. It is the first arm of augur#15.

**Alternatives (failure-mode signals):**

1. **Single-series underuse — the FM is the wrong tool for one asset.** Foundation models amortise pretraining across many series; Augur forecasts exactly one. **Signal:** the FM loses on skill but its per-observation errors decorrelate from the incumbent's (Pearson r < 0.8 on paired absolute errors). Then the value is *ensemble*, not replacement — open an ensemble arm rather than closing model class.
2. **Model size, not model class.** `bolt-base` (205M) is small. **Signal:** the FM loses, but skill improves monotonically across `bolt-tiny` → `bolt-small` → `bolt-base`. Then size is the live axis and a larger or longer-context FM (TimesFM-2.0, Granite TTM-R2) must be tested before model class is closed.
3. **The 64→72 rollout is the defect, not the model.** Chronos-Bolt's native `prediction_length` is 64; h+65..h+72 requires autoregressive extension and is off-distribution. **Signal:** the FM is competitive on the `h1_6`/`h7_24` groups and collapses only in `h25_72`, with the damage concentrated above h=64. Then the comparison is contaminated by an implementation limit — re-run at 64h, or switch to a model whose native horizon covers 72.
4. **Zero-shot is the wrong test; fine-tuning is the real bet.** **Signal:** zero-shot lands within ~10% of the incumbent. Then fine-tuning on the NL series plausibly closes the gap and a fine-tune arm is warranted. Conversely, if zero-shot is **>25% worse**, fine-tuning is very unlikely to bridge that and this alternative is foreclosed rather than opened.
5. **Calibration is the prize even when skill is not.** **Signal:** the FM loses on quantile score but its upper-side coverage in Jul/Aug 2026 is ≥0.05 better than the incumbent's. Then augur#19 gets a candidate band source (FM bands, incumbent median) even though the point forecast does not move.

**Method (pre-committed 2026-08-29, before any model is downloaded or any number is looked at):**

*Estimator.* `amazon/chronos-bolt-base`, Apache-2.0, zero-shot, no fine-tuning, `float32`, on `b650-gpu` (RTX 3090 Ti). Chronos-**Bolt** specifically, not Chronos-T5: Bolt has a direct multi-quantile head and is deterministic, so there is no sampling seed to tune and no sample-size confound in the comparison. Its native quantile levels include 0.1/0.5/0.9 exactly, so p10/p50/p90 are read off, never interpolated.

*Information set — matched, not merely similar.* The FM receives the price series at **exactly the row index the lean incumbent trains on** for the same t0: the 56-day window ending at t0, restricted to the rows with a complete `full` feature vector (the same `dropna` row set EXP-018/019/020 use, so all four arms see identical timestamps). It receives **no exogenous inputs and no calendar features** — justified by EXP-020, which found both inert or harmful at this window length. Context length is therefore ~1344 hourly points, inside `bolt-base`'s 2048 context. The realised max intra-context gap is recorded in the summary; if any vintage's context has a gap >3h the run is reported as compromised rather than scored, since Bolt treats the context as regularly spaced.

*Shape.* Identical to EXP-018/019/020: one t0 per vintage day (last clean feature row of the day), predict h+1..h+72, no CQR, score against realised prices, paired Diebold-Mariano on per-observation quantile score with HAC bandwidth 71. Window: **2025-12-01..2026-08-22, 263 vintages** — the same window as `ml/shadow/exp020_fundamentals_ctl`, chosen so the incumbent arms need not be refitted and the pairing is exact.

*Baselines — both, deliberately.* EXP-018a Stage 1 has not fired (≈2026-09-09), so the identity of "the incumbent" is genuinely open. Rather than guess, the FM is scored against **both `full` (today's production 24-feature set) and `lean` (the 15-feature candidate)**, and the **primary gate is against `lean`** — the stronger of the two on this window (−7.1% QS). A pass against `lean` is a pass whichever way EXP-018a resolves; a result that beats `full` but not `lean` is reported as such and shipped nowhere. This is fixed here so the baseline is not chosen after the numbers land.

*Gates.* Identical to EXP-018a and EXP-020 — the bar is the product requirement, not tuned to this method. The FM is the treatment, `lean` the base. Because the Position is competitiveness rather than superiority, gate 2 is stated in both directions:

1. **Skill:** paired DM on per-observation quantile score, H1 treatment better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size:** treatment QS at least **3% better** than base ⇒ *superiority*. Treatment QS within **±5%** of base with DM p > 0.10 ⇒ *parity*, which confirms the Position as stated. Treatment QS more than **5% worse** ⇒ Position refuted.
3. **Calibration:** treatment lower- and upper-side coverage each **not more than 0.02 worse** than base (raw quantiles, no CQR).
4. **Sharpness:** treatment mean Winkler (α=0.20) **≤ 1.05 ×** base.

*Decision rule, fixed now.* **Superiority (all four gates)** → model class is the lever; open EXP-021a for fresh-vintage confirmation on the EXP-018a grid before anything reaches production, and only then an ADR-006 amendment. **Parity** → the incumbent's feature-and-retrain apparatus is shown to be replaceable but not beatable; do not ship, and promote the ensemble arm (Alternative 1) and the fine-tune arm (Alternative 4) to the front of augur#15. **Refuted, >25% worse and no Alternative 1/3/5 signal** → single-series zero-shot foundation modelling is closed for Augur, augur#15 narrows to ensemble-only, and the remaining lever is **window length**, which is a cheap CPU sweep on the existing harness and becomes the next experiment.

*What does not happen in this entry, whatever the numbers.* No change to `FEATURE_COLUMNS`, `ml/shadow/`, `scripts/daily_update.sh` or any production path. This is an offline arm on a GPU box; the only repo artifacts are the runner script and a summary JSON. Production risk is zero by construction.

**Revisit trigger:** immediate — runnable on existing data, no waiting on vintages. Contrast with EXP-018a Stage 1 (≈2026-09-09) and the t0-guard review (≈2026-09-11), neither of which this touches or consumes.

**Addendum 2026-08-29 (context regularity — plumbing corrected, gates unchanged):** the Method's tripwire fired on the first `contexts` run: max intra-context gap **19h**, on **125 of 260 vintages**. Diagnosis: these are not parquet holes (the parquet's own holes are all in Oct/Nov 2025 plus one hour on 2026-06-30) but `load_frame_ext` `dropna` losses on exogenous NaNs — i.e. **exactly the rows the incumbent also drops**, so the information sets did match; what did not match was the *spacing*. The incumbent is a tabular model and is indifferent to row spacing; Bolt reads its context as regularly spaced, so handing it the compressed array silently shifts every hour-of-day across the hole. Fix: re-index each context onto the complete hourly grid over the same span and mark holes `NaN`. This adds no data (the missing hours stay missing), makes the spacing real, and gives the FM the calendar alignment the incumbent gets explicitly from its `hour`/`dow`/`month` features — it *tightens* the "matched, not merely similar" requirement rather than loosening it. After regridding: 1.77% of context points are NaN, longest run 18h. The tripwire is re-expressed for a regridded context (missing fraction ≤5%, longest run ≤48h) and passes.

Chronos-Bolt's NaN handling was **verified before being relied on**, not assumed: on a synthetic 1344-point series with an 18h block removed, the NaN-marked context tracks the clean-context forecast to 0.08 MAE while the compressed context deviates by 0.92 — 11x worse, and worse against ground truth (1.03 vs 0.86). NaN is Bolt's own documented missing-value marker (it is the mechanism used for left-padding batched series). The four gates are unchanged.

**Review-by:** 2026-10-15. **Status:** resolved 2026-08-29 — **Position confirmed, and exceeded**: the pre-commit predicted parity (within 5%) and the measured result is SUPERIORITY on all four gates against both bases.

**Resolution (2026-08-29, same day): SUPERIORITY on all four pre-committed gates, against both `lean` and `full`. Nothing shipped.**

`scripts/exp021_foundation_zeroshot.py`, `amazon/chronos-bolt-base` revision `5d9f166d69f47aef3401367a7b842e78fe97b121`, zero-shot on `b650-gpu` (RTX 3090 Ti), 260 paired vintages x 18 717 paired observations against the EXP-020 control's `full` and `lean` arms. Headline table is the **matched-information** arm (`ml/shadow/exp021_foundation_aligned/summary.json`), for the reason in Finding 3 below:

| variant | MAE | QS | dQS% vs lean | cov_lo | cov_hi | cov_band | Winkler | DM p |
|---|---|---|---|---|---|---|---|---|
| **chronos_bolt_base** | **23.23** | **7.86** | **-20.3** | 0.898 | 0.913 | **0.811** | **119.8** | **0.0000** |
| lean | 27.77 | 9.86 | 0.0 | 0.814 | 0.797 | 0.611 | 155.6 | — |
| full | 29.36 | 10.62 | +7.7 | 0.778 | 0.816 | 0.595 | 169.9 | — |

Primary gate vs `lean`: **g1 p<0.0001 / g2 QS -20.3% / g3 coverage better on both sides / g4 Winkler 0.77x — SUPERIORITY.** Secondary vs `full`: QS -26.0%, same verdict. A zero-shot model with **no features, no exogenous inputs, no NL-specific training and no nightly retraining** beats a tuned, nightly-refit gradient-boosting stack by 20% on quantile score and 16% on MAE.

**Code-review battery (ADR-007), six checks, all clean — the result is large enough that the battery is the load-bearing part of this entry:**

1. **Join integrity.** The `lean` and `full` arms re-scored inside EXP-021's harness reproduce the EXP-020 control **bit-identically** (QS 9.8637 / 10.6227, MAE 27.7737 / 29.3561, n=18 717 each). The pairing is exact, not approximate.
2. **No target leakage.** Context points strictly after t0: 0. Context max == t0 for every vintage. Minimum target offset: exactly +1h. Context/target overlap rows: 0. The scorer additionally asserts realised prices agree across all three arms on every shared cell (max delta 0.0) and exits rather than scoring if they do not.
3. **A real information asymmetry, found and corrected.** `build_features` uses `shift(1)`, so the incumbent's feature row at t0 stops at **t0-1h**, while the FM's context ran through **t0** — a one-hour edge the pre-commit did not anticipate. A second arm was run with the context held back to t0-1h (rolling out 73 steps and reading the same 72 target hours), matching the information sets exactly. Effect: QS -21.1% -> -20.3%, MAE 22.98 -> 23.23. The asymmetry is real, worth **0.8pp of 21**, and the matched arm is what is reported above. The unmatched arm is kept at `ml/shadow/exp021_foundation/` for the comparison.
4. **Batch invariance.** Contexts vary 72..1343 points and are left-padded with NaN when batched. The shortest three, run alone vs in a batch with the four longest, agree to 3e-5 — float noise.
5. **Pretraining contamination is impossible, not merely unlikely.** HF metadata for the pinned revision: created 2024-11-25, **last modified 2025-11-21**. The evaluation window opens 2025-12-05. Every hour scored postdates the frozen weights.
6. **Naive baselines confirm the incumbent is not simply weak.** rMAE against a seasonal-naive (price at target-168h, always known at t0): persistence 1.249, seasonal-naive 1.000, `full` 0.921, `lean` 0.871, **Chronos-Bolt 0.729**. The incumbent beats both naives, as it should; the FM beats the incumbent.

**Alternatives, as pre-committed:**

- **Alternative 3 (the 64->72 rollout is the defect) — refuted, and backwards.** Bolt's native `prediction_length` is 64, so h+65..h+72 is an off-distribution autoregressive rollout. It does not degrade: FM is **-19.9% QS vs lean on h1-64 and -22.8% on h65-72**, and its MAE barely moves across the boundary (23.15 -> 23.88) while lean's climbs (27.51 -> 29.87). The FM's advantage *grows* with horizon. Whatever the rollout costs, it costs less than the incumbent's own long-horizon decay.
- **Alternative 5 (calibration is the prize) — fires hard, and is arguably the more important half of this result.** The FM's **raw** band coverage is 0.811 against the 0.80 nominal target **with no conformal layer at all**, versus 0.611 for lean and 0.595 for full. Monthly upper-side coverage beats lean in 8 of 9 months, and the two biggest gaps are the two months that motivated augur#19: **Jul +0.232 and Aug +0.174** (Aug: FM upper 0.930 vs lean 0.756, at the highest monthly mean price in the parquet, 128 EUR/MWh). The band is only ~20% wider (median 72.96 vs 60.99) yet Winkler is 0.77x. This is the first thing tested against augur#19 that moves it, and it moves it by *not needing* the mechanism EXP-015/016 could not make work.
- **Alternative 1 (ensemble, not replacement) — signal fires but the remedy does not.** Paired absolute-error correlation with lean is r=0.753, below the pre-committed 0.8 threshold, so the errors genuinely decorrelate. But the cheapest ensemble that could exploit that — a 50/50 median blend — scores **MAE 23.69, worse than the FM alone at 23.24**. Decorrelation is present; blending with a weaker model still costs. Ensembling is not foreclosed, but it is not the free win the alternative anticipated, and any ensemble arm must be weighted rather than even.
- **Alternative 2 (model size, not model class)** was conditioned on the FM losing. It did not lose; the size ladder is not needed to reach a verdict, though it remains the obvious cheap follow-up now that the direction is established.

**Consequences, per the decision rule fixed before the run:** SUPERIORITY triggers *"open EXP-021a for fresh-vintage confirmation on the EXP-018a grid before anything reaches production, and only then an ADR-006 amendment."* Accordingly: **nothing ships from this entry.** `FEATURE_COLUMNS`, `ml/shadow/`, `dashboard.js` and `daily_update.sh` are untouched; the only repo artifacts are the runner and two summary JSONs. Every effect size above is measured on the **same 260-vintage window EXP-018/019/020 already explored**, and although this arm chose no hyperparameters on that data (it is zero-shot — there was nothing to tune, which weakens the usual selection-bias worry considerably), the window is still not fresh, and a 20% claim deserves the same discipline the 8% one got. EXP-021a is opened above.

**Mechanism correction (EXP-022, same day — the Position's stated *reason* was wrong even though its prediction was right).** This entry attributed the expected win to Chronos "not being recalibrated nightly to one 56-day price level" — the level-drift story carried since EXP-018/019/020. A context ladder plus a bias panel refute that reading. (a) **Bias is not where the gap lives:** mean signed error is +0.34 (FM) vs −0.52 (lean) EUR/MWh overall, and lean's worst month is June (−15.5), not the August level-shift month (−4.7). (b) **Starving the FM of context isolates the cause:** Chronos with a **7-day** context still beats LightGBM trained on 56 days by **12.5% QS** (DM p<0.0001), so ~12 of the 20.3 points are pretrained prior and only ~8 are context volume. (c) **The calibration half is entirely prior:** band coverage is 0.811 / 0.804 / 0.813 / 0.823 at 56d / 28d / 14d / 7d — flat. It does not depend on information at all, which also explains why the pinball gain is largest at p10 (26.3%) and smallest at the median (16.3%): tail quantiles are exactly what a 1344-row nightly refit can least afford to estimate. The bands are better *shaped*, not wider — lean needs 2.0x inflation to reach 0.811 coverage, ending 1.7x wider than the FM's, and at matched width reaches only 0.682. And the win is routine rather than extremal: the FM takes 75% of vintages with median per-vintage MAE 19.89 vs 26.62, but p95 is a tie (48.55 vs 48.39) — **better on ordinary days, no better on hard ones**. Registered as EXP-022 (`parked`, exploratory, no gates); the corrected mechanism is *pretrained distributional prior plus a feature-vector information bottleneck*, not level drift.

The standing conclusion from EXP-020 is now **half-resolved**: of the two levers left after features were closed, **model class is confirmed as live and large**. Window length is untested and, given that a 2048-context pretrained model beats a 1344-row nightly refit, is now a more interesting question than it was this morning rather than less.

---

### [2026-08-29 -> resolved 2026-08-29] EXP-020: residual load and gas price carry price signal the three current exogenous columns cannot, because those are point weather proxies rather than system quantities

**Position (provisional):** EXP-018 Stage 0 found the exogenous trio (`wind_speed_80m`, `solar_ghi`, `load_forecast`) worth ~nothing — wind −0.3%, solar −0.3%, load −0.4% individually. The obvious reading is "exogenous data doesn't help this model." Position: that reading is too strong, and the trio is inert for two reasons the sweep could not separate. (1) **It is not the merit-order quantity.** External EPF work puts residual load — load minus renewable generation, in MW — at ρ≈0.53 with day-ahead price, materially above load or renewables alone, because merit order is about the *residual* the dispatchable fleet must cover. LightGBM with axis-aligned splits on a ~1300-row window cannot reconstruct a three-way difference it is never given, and one of the three terms it *is* given (`wind_speed_80m`, a single offshore point's wind speed) is a nonlinear proxy for MW rather than MW. (2) **There is no fuel-cost level anchor at all.** Nothing in the 24-feature set carries the cost of the marginal generator; a trailing-56-day model can only infer level from its own price lags, which is exactly the mechanism EXP-018 blamed for the August upper-side coverage breach (Aug 2026 upper 0.774, band 0.660, against a 128 EUR/MWh monthly mean — the highest in the parquet). TTF gas is that anchor and is exogenous to the price history.

Prediction: adding `residual_load_mw` and `gas_ttf_eur_mwh` to the 15-feature lean set improves quantile score by ≥3%, and does so on the full-24 base as well.

**Why this is not simply re-opening a refuted bet:** the [2026-08-20] entry's "feature expansion is the highest-leverage lever" position was refuted, and per ADR-007 a refuted position is not re-run with a looser Method. This entry narrows rather than loosens: it names two specific derived columns, states the mechanism by which they differ from what Stage 0 actually tested (a *combination* and a *level anchor*, neither of which was in the ablation), and carries the same four gates. If these two also come back inert, the general claim "exogenous data does not help Augur at this window length" is then supported by a test that could have refuted it, which is worth more than the current evidence.

**Alternatives (failure-mode signals):**

1. **Everything exogenous really is inert at 56 days.** The trio was inert because 1300 rows cannot support any exogenous split, not because of proxy quality. **Signal:** residual load and gas both land inside ±1% QS, matching the trio. Then the lever is window length or model class, not features — open a window-length sweep, and stop proposing exogenous columns.
2. **Gas helps and residual load does not.** The breach is a level problem, not a merit-order problem. **Signal:** gas alone clears the gates, residual load alone does not. Then ship the level anchor only, and treat renewables as adequately covered by price lags.
3. **Residual load helps only because it re-encodes load.** The gain is the load column being made useful by rescaling, not the residual construction. **Signal:** `load_forecast` alone added to lean performs the same as `residual_load_mw`. Then keep the simpler column.
4. **Gain is confined to the August level shift.** **Signal:** the monthly panel shows the effect concentrated in Jul/Aug 2026 and absent Dec–Jun. That is not disqualifying — the shift is the failure we care about — but it makes the fresh-vintage window a weak test if that window is calm, and Stage 2 must then be extended rather than passed.

**Method (pre-committed 2026-08-29, before any column reaches `FEATURE_COLUMNS`):**

*Step 0 — data plumbing, additive only, no experiment.* Extend `ml/data/consolidate.py` with parsers for four new columns, all from feeds that already start 2025-12-01, so the ablation window does not shrink:

| Column | Source file | Path | Unit |
|---|---|---|---|
| `wind_gen_forecast_mw` | `*_wind_forecast.json` | `entsoe_wind_generation.data.NL[ts].wind_total` | MW |
| `solar_gen_forecast_mw` | `*_ned_production.json` | `solar.forecast[ts].capacity_kw / 1000` | MW |
| `gas_ttf_eur_mwh` | `*_market_proxies.json` | `gas_ttf.price` (one daily scalar per file) | EUR/MWh |
| `is_holiday_nl` | `*_calendar_features.json` | `[ts].is_holiday_nl` | 0/1 |

`residual_load_mw = load_forecast − wind_gen_forecast_mw − solar_gen_forecast_mw` is derived in the builder, not stored.

**Invariant, enforced by test:** the five existing columns and the row index must be bit-identical before and after this change. EXP-018a Stage 1 fires ≈2026-09-09 off this same parquet, and it must not be perturbed by this work. If the invariant cannot hold, the plumbing waits until EXP-018a Stage 1 has run.

*Step 1 — EXP-020 discovery sweep, offline, zero production risk.* `scripts/exp018_stage0_ablation.py` is drop-only (variants are subsets of `FEATURE_COLUMNS`); extend it to score added columns. Same production shape as EXP-018/019 — 56-day window, h+1..h+72, one t0 per vintage day, no CQR, 263 vintages 2025-12-01..2026-08-22, HAC bandwidth 71. Six arms:

```
full, lean,
lean+residual, lean+gas, lean+residual+gas+holiday,
full+residual+gas+holiday
```

Primary comparison: `lean+residual+gas+holiday` vs `lean`. Confirmatory: `full+residual+gas+holiday` vs `full` — the fundamentals must not degrade the full base either, or the result is base-dependent and does not travel. Gates (identical to EXP-018a, deliberately — the bar is the product requirement, not tuned to this method): (1) paired DM on per-observation quantile score, H1 treatment better, one-sided p < 0.10; (2) treatment QS ≥3% better than base; (3) lower- and upper-side coverage each not more than 0.02 worse than base; (4) mean Winkler (α=0.20) ≤ 1.05 × base.

*Step 2 — fresh-vintage confirmation, pre-committed now.* This runs on the **same 263-vintage window EXP-018 and EXP-019 already explored**, so every effect size it produces carries that selection bias, and **nothing ships from Step 1 directly** — same rule as EXP-018a. Confirmation runs on vintages with `t0 ≥` the Step-1 end date, ≥14 of them, gates unchanged. Sequencing: EXP-018a Stage 1 has priority on the fresh-vintage window; EXP-020 confirmation runs after it, on a base fixed by EXP-018a's outcome (lean if it passes, full if it fails).

**Addendum 2026-08-29 (data availability, gates unchanged):** Step 0 is done and the plumbing invariant holds (index and the five original columns bit-identical, verified by rebuilding the parquet from the same data directory with and without the new parsers). Measured NaN rates over 2025-12-01..2026-08-25 are `wind_gen_forecast_mw` 0.8%, `solar_gen_forecast_mw` 1.7%, `is_holiday_nl` 0.0% — but **`gas_ttf_eur_mwh` does not exist before 2026-02-05**: EDH's `market_proxies` collector only added TTF on that date (its own changelog), so the column is one contiguous leading hole, 100% complete afterwards. Consequence for Step 1: the six-arm sweep runs on **2026-02-05..2026-08-22** (~199 vintages) so all arms share one row set, and the no-gas arms (`lean`, `lean+residual`, `full`) are additionally run on the full 2025-12-01 window as a secondary check that the shorter window does not by itself change the residual-load conclusion. The four gates are unchanged. Backfilling TTF from yfinance would restore the full window but is **declined**: the daily EDH snapshot is vintage data (what was known that day) while a backfill is revised data, so the two halves would not be comparable, and Alternative 4 (effect confined to the recent level shift) is exactly the failure mode a mixed-provenance column would disguise.

**Revisit trigger:** Step 0 + Step 1 immediately (runnable on existing data). Step 2 after EXP-018a Stage 1 concludes. Surface in `/curate`.

**Review by:** 2026-09-30.

**Domain:** EXP-020, feature engineering, augur#19 (upper-side calibration), ADR-006.

**Status:** resolved 2026-08-29 — Position refuted, see Resolution below. Provenance: the mechanism claim comes from an external literature pass, not from Augur's own data — a HAN BDSD minor project on week-ahead NL price forecasting (`/home/jeroen/repos/FyE/core/sources/bdsd-minor-electricity-price-prediction-2026-01-19.pdf`, Jan 2026) and its cited sources (Aščerić 2021 for the ρ≈0.53 residual-load figure; Tschora 2022 for gas indices ranking top by SHAP). That report also independently discarded the energyDataHub feed as too gappy to train on and rebuilt from ENTSO-E + Open-Meteo — noted here as corroboration for ducroq/energyDataHub#50, not acted on in this entry.

**Resolution (2026-08-29, same day): Position refuted; Alternative 1 supported, with one correction to its mechanism.**

`scripts/exp020_fundamentals_ablation.py`, two runs. Main: 7 arms x 195 paired vintages (2026-02-05..2026-08-22), 14 037 paired observations, `ml/shadow/exp020_fundamentals/summary.json`. Control: 4 no-gas arms x 263 vintages (2025-12-01..2026-08-22), `ml/shadow/exp020_fundamentals_ctl/summary.json`.

| variant | nfeat | MAE | dQS% vs full | cov_lo | cov_hi | Winkler | base | DM p |
|---|---|---|---|---|---|---|---|---|
| full | 24 | 33.70 | 0.0 | 0.768 | 0.822 | 195.6 | — | — |
| lean | 15 | 31.60 | −7.8 | 0.792 | 0.800 | 177.6 | full | 0.0000 |
| lean_load | 16 | 31.69 | −7.5 | 0.789 | 0.802 | 178.4 | lean | 0.8505 |
| lean_residual | 16 | 31.52 | −7.7 | 0.795 | 0.796 | 177.9 | lean | 0.6484 |
| lean_gas | 16 | 32.29 | −4.9 | 0.769 | 0.833 | 184.2 | lean | 0.9908 |
| **lean_fund** | 18 | 32.56 | −4.7 | 0.772 | 0.830 | 183.4 | lean | **0.9929** |
| full_fund | 27 | 33.55 | +0.2 | 0.760 | 0.823 | 196.9 | full | 0.6150 |

**Primary gate `lean_fund` vs `lean`: FAIL** — gate 1 (DM p=0.993, decisively the wrong direction) and gate 2 (QS 3.4% *worse*, not 3% better) both fail; gates 3 and 4 pass. **Confirmatory `full_fund` vs `full`: FAIL** the same way (p=0.615, QS +0.2%). Both fail toward "no effect", not toward a bad trade-off.

- **Residual load is inert, and so is plain load.** `lean_residual` p=0.648 on the gas window and **p=0.899 on the full 263-vintage control** — a tie with `lean` on both. `lean_load` p=0.851. This makes Alternative 3 moot rather than decided: there is no gain to attribute to either construction. The rho≈0.53 residual-load correlation from the literature is real but already spanned by price lags plus calendar at a 56-day window.
- **Gas does not merely fail to help — it degrades.** `lean_gas` is +3.2% QS worse than `lean` (p=0.991). This corrects the Position's mechanism: the claim was that a trailing-56-day model lacks a fuel-cost *level anchor*. It has no use for one. This is the **second independent confirmation of EXP-019's mechanism** — EXP-019 found that re-adding `price_rolling_mean_168h` as a single explicit level column cost significantly, and read it as redundant smoothed-level columns diluting the split search. TTF gas is precisely such a column (slow-moving, level-carrying, correlated with price), and EXP-019's reading predicted this result before the sweep was run. The generalisation is now: **this model class at this window length rejects added level columns, whatever their provenance** — internal (rolling mean) or exogenous (gas).
- **Not a regime artifact (Alternative 4 does not apply).** Monthly panel for the primary comparison: `lean_fund` worse in 5 of 7 months (Jul +16.7%, May +8.0%, Feb +4.1%, Aug +1.2%, Apr +0.7%), better in 2 (Mar −1.7%, Jun −1.2%). There is no level-shift month where fundamentals rescue anything — including August, the month whose upper-side breach motivated the entry.
- **Free replication of EXP-018.** `lean` beats `full` at p<0.0001 on both windows: −7.8% QS on 2026-02-05.. and −7.1% on the full control window (against EXP-018's −8.1%). This is *not* the pre-committed fresh-vintage test — both windows overlap the discovery data, so EXP-018a Stage 1 is undischarged — but it makes EXP-018a's Alternative 3 (selection-bias mirage) less likely.

**Consequences:** (a) nothing ships; `FEATURE_COLUMNS` is untouched and no production path changed. (b) The Step-0 plumbing stays — the four columns cost nothing, are additive-only, and are now the cheap precondition for any future test that wants them. (c) The standing answer on exogenous features is now backed by a test that could have refuted it: **at a 56-day window, this model gets nothing from added exogenous columns, and actively loses from added level columns.** The next lever is therefore window length or model class, not features — which is where the foundation-model track (Chronos-Bolt / TinyTimeMixer, GPU-shaped) becomes the interesting bet rather than more feature engineering. (d) EXP-020 Step 2 (fresh-vintage confirmation) is **cancelled** — there is no effect to confirm.


---

### [2026-08-20 → resolved 2026-08-25] Feature expansion is the highest-leverage untried lever; calibration asymmetry has flipped to the upper side

**Position (provisional):** Production LightGBM-Quantile runs on 24 features built from only 4 columns (`price_eur_mwh`, `wind_speed_80m`, `solar_ghi`, `load_forecast`) while energyDataHub already collects ~7 more series (`ned_production`, `grid_imbalance`, `cross_border_flows`, `gas_storage`, `gas_flows`, `market_proxies`, `generation_forecast`) that never reach `consolidate.py`. Expanding features — residual load, generation mix, and volatility/uncertainty signals — is the highest-leverage untried lever for both point skill and the augur#19 quantile-spread gap. Re-computing `calibration_history` coverage through 2026-08-19 shows the per-side asymmetry has **flipped to the upper side**: August lower 0.916 / upper 0.755 (band ~0.67 vs 0.80 target), versus lower 0.834 / upper 0.886 through 2026-06-11 — so augur#19's "lower-side" framing is now stale.

**Alternative:** EXP-017 (9-quantile training) alone fixes the raw-quantile gap without new features — the path queued by the EXP-015/016 resolution.

**Method (pre-committed, deferred):** two-stage. *Stage 0* — per-feature-group ablation (drop lags / rolling / calendar / wind / solar / load; measure MAE + quantile score + coverage) on existing data. *Stage 1* — walk-forward backtest (temporal split, 56-day window, vintage-corrected) of incumbent (24 features, 3 quantiles) vs candidate (24 + fundamentals + volatility + calendar-gaps). Gates: calibration — lower AND upper coverage ∈ [0.85, 0.95] AND Winkler ≤ 1.05× incumbent; skill guardrail — paired DM on |y−p50| (α=0.10 one-sided, HAC bandwidth 71) not worse. Freshness skew (consolidate overwrites rows with later vintages) bounds backtest optimism — plan a short live confirmation before any production change.

**Revisit trigger:** next session — pick up EXP-018, run Stage-0 ablation first.

**Review by:** 2026-08-27.

**Domain:** EXP-018, feature engineering, calibration (augur#19).

**Status:** Stage 0 run 2026-08-25 — **Position refuted, Alternative not confirmed either.** Supersedes individual feature issues #2/#3/#4/#22 into one evaluated experiment. GPU hosts (jwasys-b650-eagle-ax, sadaltager, gpu-server) available but not needed for LightGBM feature work; hold for a possible neural-quantile track.

**Stage-0 resolution (2026-08-25):** `scripts/exp018_stage0_ablation.py`, 263 vintages 2025-12-01..2026-08-22, production-shaped (56-day window, h+1..h+72, no CQR), 2104 fits. Results in `ml/shadow/exp018_stage0/summary.json`.

The Position said feature *expansion* is the highest-leverage lever. Stage 0 says the opposite: the existing set contains features that actively hurt, and the exogenous series we already feed contribute almost nothing.

- **Rolling stats are harmful.** Dropping all six lifts MAE −6.0% (28.97 → 27.24), quantile score −7.8% (10.54 → 9.72) *and* lower-side coverage 0.778 → 0.805. Reverse-direction DM (HAC 71): stat −6.48, p<0.0001 on QS; −5.02, p<0.0001 on |error|. Holds in 7 of 9 months, biggest in the volatile recent regime (May −14%, Jul −11%, Aug −9%), costs only Dec 2025 (+5.8%); holds across all three horizon groups.
- **Calendar is the only group clearly earning its place** (+7.3% MAE, +9.2% QS when dropped, DM p=0.000).
- **The exogenous trio is worth ~nothing.** wind −0.3%, solar −0.3%, load −0.4% individually; all three together +0.8% QS (p=0.041). Not a data defect — over the last 120 days `load_forecast` correlates 0.59 with price and `solar_ghi` −0.53. LightGBM extracts nothing beyond what price lags plus calendar already encode.
- **Mechanism (second sweep, `ml/shadow/exp018_stage0_mech/`)**: damage is diffuse, not one broken column — rolling_mean −1.6%, rolling_std −1.8%, the 168h pair −2.2%, short windows −0.8%, all six −6.0%. Best variant is the 15-feature **lean** set (drop rolling + exog): MAE 27.08 (−6.5%), QS 9.69 (−8.1%), lower coverage 0.810. Reading: level-carrying, redundant features dilute the split search, and absolute-threshold splits learned in a 56-day window generalise badly when the price level moves.

Consequences: (a) the addition bet (#2/#3/#4/#22) is demoted behind a **reduction** bet — see the [2026-08-25] entry below; (b) augur#19's framing needs rewriting *again* — production through 2026-08-24 is lower 0.887 / upper 0.774 / band 0.660, so the breach is upper-side, while EXP-017's premise was a high-biased q10.

---

### [2026-06-12 → resolved 2026-06-12] EXP-016: per-side ACI closes the regime-shift coverage gap that static per-side CQR (EXP-015) could not

**Position (provisional):** EXP-015 showed per-side conformal scores fix the *side* asymmetry (+0.048 lower-side at +2.5% Winkler) but a static trailing-7-day calibration window cannot adapt to regime shifts — vintages 06-02/06-03 stayed at 0.375/0.708 lower-side and dragged the pool to 0.826, below the 0.86 bar. Adaptive Conformal Inference (Gibbs & Candès 2021) closes the loop: after a day of misses the target level rises, widening the next vintage's band. Since the bad days cluster in streaks (06-01 was also bad — incumbent 0.542), the day-after reaction should recover most of the deficit. Treatment = ACI layered on EXP-015's per-side scores.

**Method (pre-committed 2026-06-12, before running the treatment replay):**

*Treatment definition (every parameter fixed here):*
- Per-side adaptive state `α_lo`, `α_hi`, both initialised at 0.10 (the static case).
- One batched update per vintage day V, processing raw-bearing vintages chronologically (including warm-up vintages 05-30..06-01, which get bands but are excluded from evaluation): over the not-yet-consumed hours with `ts < V-day midnight UTC` (each hour consumed once, scored against the band assigned when its own vintage was predicted), per-side error rate `err = mean(missed)`; update `α ← clip(α + γ·(0.10 − err), 0.005, 0.5)`. No new hours → no update.
- Band for vintage V: `q_side` = finite-sample quantile of trailing-7-day (min 3 distinct days, cutoff V-day midnight — identical to production/EXP-015) per-side scores `E_lo = q10_sorted − y`, `E_hi = y − q90_sorted`, at level `1 − α_side`. Sparse calibration → q = 0 (raw bands), α still updates. No flooring of q at zero.
- Step size **γ = 0.10** (primary). γ ∈ {0.05, 0.20} reported descriptively, never gated. Rationale: a 0.5-error day moves α by 0.04 — a one-day reaction big enough to matter, small enough not to oscillate on noise.

*Stage 1 — offline replay* (`scripts/exp016_replay_aci.py`) on the **same evaluable rows as EXP-015** (8 vintages / 528 rows as of the 2026-06-12 state; precondition ≥4 evaluable vintages). Comparator: stored production bands on the same rows (lower 0.778, upper 0.903, Winkler 146.4). IMPLEMENT iff all four hold — **identical criteria to EXP-015**; the bar is the product requirement, not tuned to the method:
1. treatment lower-side ≥ incumbent lower-side + 0.03
2. treatment lower-side ≥ 0.86
3. treatment upper-side ∈ [0.85, 0.97]
4. treatment mean Winkler ≤ 1.05 × incumbent

*Stage 2 — live confirmation* (pre-committed now, evaluated after 14 evaluable post-deploy vintages in `calibration_history`, not `eval_log.jsonl`): (1) pooled lower ∈ [0.87, 0.95] and upper ∈ [0.85, 0.95]; (2) ≤2 of 14 vintages with per-vintage lower < 0.70; (3) mean Winkler ≤ 1.05 × pre-deploy trailing-14-vintage baseline. PASS → registry `kept`, update ADR-006 + CLAUDE.md, close the augur#19 calibration arc. FAIL with improvement → keep, escalate to EXP-017. FAIL with degradation → revert, EXP-017 primary.

**Alternatives (failure mode signals):**

1. **ACI rescues the day-after but not the first shift day; pooled lands in [0.84, 0.86).** The residual is irreducible single-day surprise that no calibration-layer fix reaches. Do NOT implement on a near-miss; escalate to EXP-017 (9-quantile training — better raw quantiles need less correction) and record the per-vintage tail to inform whether 0.90 is reachable by calibration alone.
2. **Oscillation at γ = 0.10**: α overshoots after good streaks, narrows, then misses. Signal: alternating per-vintage coverage with negative lag-1 autocorrelation of per-vintage err (reported descriptively). If γ = 0.05 (descriptive variant) is smooth where 0.10 oscillates, open a *new* entry with γ = 0.05 as primary — a new pre-commit, not a loosening.
3. **Winkler guardrail trips**: ACI buys coverage with chronically wide bands → the gap lives in the raw quantiles → EXP-017 moves up.
4. **Upper side degrades** (criterion 3 fails): per-side ACI narrowing the healthy side too aggressively — inspect the α_hi trace before any redesign.

**Revisit trigger:** Stage 1 — immediately (replay runnable today, same state file as EXP-015 → directly comparable). Stage 2 — 14 evaluable post-deploy vintages. Surface in `/curate`.

**Review by:** 2026-07-11.

**Domain:** EXP-016, augur#19 calibration follow-up, ACI
**Status:** resolved (refuted in part) — see Resolution below.

**Resolution (2026-06-12, same day):** Stage-1 replay run immediately after the pre-commit landed (commit `440b0b6`), same 8 evaluable vintages / 528 rows as EXP-015. Verdict **IMPLEMENT = False** — criteria 1/3 PASS, criterion 2 **FAIL** (lower 0.852 < 0.86, the pre-committed Alternative-1 near-miss zone [0.84, 0.86)), criterion 4 **FAIL** (Winkler 163.9 vs cap 153.7, +12% — Alternative 3).

What the replay showed: ACI does what ACI promises — every vintage from 06-04 onward is ≥ 0.903 lower-side — but it cannot rescue the *first* shift days (06-02 at 0.375, 06-03 at 0.667; α_lo was still ≈0.126 on 06-02 because the calm warm-up had drifted it *narrower*). The γ-sensitivity panel is the decisive evidence: γ ∈ {0.05, 0.10, 0.20} all converge to lower ≈ 0.85 — a γ-independent ceiling. The 69 hours missed on 06-02/06-03 alone cap any day-granularity calibration method at ≈0.87 on this window, and approaching that ceiling pegged α_lo at the 0.005 clip with q_lo ≈ 55-61 EUR/MWh (median width +30%, hence the Winkler trip). No oscillation (lag-1 err autocorr +0.96, persistent not alternating), so Alternative 2 (γ retune) does not apply.

Per the pre-committed Alternative-1 AND Alternative-3 paths, which agree: **the residual gap lives in the raw quantiles** (q10_raw biased high entering regime shifts), and **EXP-017 — 9-quantile training — is the next experiment**. The per-side score decomposition (EXP-015) and an adaptive layer (EXP-016) may both return on top of better raw quantiles. Logged as EXP-016 (`parked`) in `experiments/registry.jsonl`.

---

### [2026-06-12 → resolved 2026-06-12] EXP-015: two-sided (per-side) CQR fixes the lower-side coverage gap

**Position (provisional):** LightGBM's lower-side coverage deficit (augur#19) is caused by the *symmetric* CQR correction, not by horizon effects. Baseline from `calibration_history` (30 vintages, 2112 realised hours, 2026-05-10 → 2026-06-11, computed 2026-06-12 *before* any treatment was run):

- Lower-side coverage by horizon group: h1-6 = 0.828, h7-24 = 0.837, h25-72 = 0.833 — **flat across horizons**, refuting the horizon-conditioning hypothesis sketched in augur#19 as the primary mechanism.
- Per-side asymmetry under symmetric widening: lower 0.834 vs upper 0.886 (target 0.90 each side). The single `q = quantile(max(p10−y, y−p90))` splits the error budget wherever the score distribution happens to put it.
- Discovered while designing this experiment: production `compute_cqr_q` measures nonconformity against the **already-CQR-widened** stored bands (calibration_history's p10/p90), not the raw model quantiles — a feedback loop, not textbook split-conformal (Romano et al. 2019 calibrate the raw fitted quantiles). Raw quantiles (`p10_raw`/`p90_raw`) are stored since 2026-05-29 and make the clean version possible.

Treatment: **per-side CQR on raw sorted quantiles** — `q_lo` = finite-sample 0.90-quantile of `E_lo = q10_sorted − y`, `q_hi` = 0.90-quantile of `E_hi = y − q90_sorted`, each over the same trailing 7-day / min-3-distinct-days calibration window production uses; bands = `[q10_sorted − q_lo, q90_sorted + q_hi]`. No flooring at zero (negative q legitimately narrows an over-wide side; report how often it fires).

**Method (pre-committed 2026-06-12, before running the treatment replay):**

*Stage 1 — offline replay on existing data* (`scripts/exp015_replay_cqr.py`), per ADR-007 layer 2. Evaluable rows: calibration_history rows with raw quantiles (vintages 2026-05-30+) belonging to vintages with ≥3 distinct prior raw-bearing calibration days in the trailing 7; calibration cutoff = vintage-day midnight UTC (mirrors production `apply_cqr`). Precondition: ≥4 evaluable vintages (≥288 realised hours), else wait for more vintages — each day adds one.

Comparator: the stored production bands (p10/p90) on the **same** evaluated rows.

IMPLEMENT in production iff all four hold:
1. treatment lower-side ≥ incumbent lower-side + 0.03 (on same rows)
2. treatment lower-side ≥ 0.86
3. treatment upper-side ∈ [0.85, 0.97]
4. guardrail: treatment mean Winkler (α=0.20, `ml/shadow/metrics.py:winkler_interval_score`) ≤ 1.05 × incumbent mean Winkler — a coverage fix that only works by paying >5% interval-score cost means the problem is quantile-regression bias, not conformal correction, and EXP-017 (9-quantile training) moves up.

Descriptive companions, never gated: horizon-grouped per-side variant (3 groups × 2 sides), per-group coverage, median width change, share of negative q_lo/q_hi.

*Stage 2 — live confirmation* (pre-committed now, evaluated after 14 evaluable post-deploy vintages in `calibration_history` — **not** `eval_log.jsonl`, whose rows mix 24/48/72-hour vintages and have permanent holes at 2026-06-08/06-10 from the EDH v2.2 break):
1. pooled lower-side ∈ [0.87, 0.95] and upper-side ∈ [0.85, 0.95]
2. bimodality guard: ≤2 of the 14 vintages with per-vintage lower-side < 0.70 (baseline: 12 of 30 vintages < 0.80, worst 0.431)
3. mean Winkler ≤ 1.05 × the pre-deploy trailing-14-vintage baseline

PASS → registry entry `kept`, update ADR-006 calibration section + CLAUDE.md known-weakness note, close augur#19 stage. FAIL with coverage improved but short → keep the change, open EXP-016 (ACI) on top. FAIL with coverage degraded vs baseline → revert commit, EXP-016 becomes primary.

**Alternatives (failure mode signals):**

1. **Per-side fix passes offline but live bimodality persists** (guard 2 trips while pooled passes): the deficit is regime-shift-driven, exactly ACI's (Gibbs & Candès 2021) target — static trailing-window calibration can't adapt fast enough. Path: EXP-016, keeping per-side scores inside the ACI update.
2. **Offline result straddles a threshold** (e.g. lower lands in [0.84, 0.86)): do NOT loosen. Wait for more raw vintages (precondition scales at +1/day, +72 rows/day) and re-run the same pre-committed replay at ≥8 evaluable vintages.
3. **Winkler guardrail trips**: coverage gap is in the raw quantiles themselves (q10 biased high), not the correction. EXP-017 (9-quantile training) moves ahead of ACI.
4. **Upper side over-covers (>0.97)** after per-side split: per-side targets were already met on that side and splitting double-widens. Signal that negative-q narrowing must be allowed (it is) and is firing too rarely — inspect score distributions before any redesign.

**Revisit trigger:** Stage 1 — immediately (replay is runnable today). Stage 2 — 14 evaluable post-deploy vintages, ≈ 2026-06-27 if deployed 2026-06-13. Surface in `/curate`.

**Review by:** 2026-07-04.

**Domain:** EXP-015, augur#19 calibration follow-up, CQR
**Status:** resolved (refuted in part) — see Resolution below.

**Resolution (2026-06-12, same day):** Stage-1 replay run on 8 evaluable vintages (528 rows, 2026-06-02 → 2026-06-11) immediately after the pre-commit landed (commit `bcc3e78`). Verdict **IMPLEMENT = False**:
- Criterion 1 PASS: treatment lower-side 0.826 vs incumbent 0.778 on same rows (+0.048, > +0.03 required).
- Criterion 2 **FAIL**: 0.826 < 0.86.
- Criterion 3 PASS: upper-side 0.862. Criterion 4 PASS: Winkler 150.0 ≤ 153.7 (+2.5%).

The position is refuted *in part*: symmetric widening explains ~5 points of the gap (fixed by the per-side split), but the residual is concentrated in the regime-shift vintages 06-02/06-03 (treatment 0.375/0.708; every later vintage ≥ 0.847, mostly ≥ 0.90). That is **Alternative 1 firing in the offline data already** — static trailing-window calibration cannot adapt to regime shifts, which is ACI's (Gibbs & Candès 2021) design target. The result lands below the [0.84, 0.86) straddle band, so the wait-for-more-vintages path (Alternative 2) does not apply; per the pre-committed alternative-1 path, **EXP-016 = ACI with per-side scores** is the next experiment. Descriptive companion confirmed the design redirect: horizon-grouped calibration makes short horizons *worse* (h1-6 lower-side 0.646 vs pooled 0.625 — both bad, and small per-group calibration sets add variance), closing the door on the original horizon-conditioned sketch in augur#19. Logged as EXP-015 (`parked`) in `experiments/registry.jsonl`; per-side scores carry into EXP-016's design.

---

### [2026-05-29 → resolved 2026-05-29] LightGBM-Quantile passes the redesigned promotion criterion on the M4 window data

**Position (provisional):** the four-iteration metric-redesign arc (EXP-011 / EXP-012 / EXP-013, summarised in `docs/articles/m4-metric-redesign-story.md`) converged on a single-criterion-plus-guardrail promotion design. The candidate criterion below is now applied to the *already-collected* M4 window data (2026-05-14 → 2026-05-27, 14 contiguous days, 546 paired hourly observations after the vintage-corrected join). If LightGBM passes, ARF is demoted to backup and the dashboard loads `augur_forecast_shadow.json`. This is not a new shadow window — it is the application of the corrected method to the data we already have.

**Method (pre-committed, before checking the existing data passes it):**

1. **Skill gate**: paired Diebold-Mariano on absolute-error loss differentials.
   - Loss A: LightGBM's `|y − p50|` per paired observation.
   - Loss B: ARF's `|y − point|` per paired observation.
   - HAC bandwidth: `max_horizon − 1 = 71` (per DM 1995 §4 for h-step-ahead overlapping forecasts; default `n^(1/3)` is too short).
   - Threshold: mean of (Loss A − Loss B) negative (LightGBM lower) AND one-sided DM p < 0.10 (LightGBM significantly more accurate).

2. **Calibration guardrail (one-sided gate)**: 80% interval coverage.
   - Lower-side coverage (`fraction of realisations >= p10`): in [0.85, 0.95].
   - Upper-side coverage (`fraction of realisations <= p90`): in [0.85, 0.95].
   - Both sides must hold. If either fails, promotion is blocked and the calibration problem is the next experiment, not the model swap.

3. **No tail-metric gate.** Pinball-at-p10, twCRPS, per-horizon decomposition — report descriptively after the decision, never gate on them. The four-iteration arc showed that tail metrics are confounded by non-canonical implementations (per-quantile-decomposition twCRPS rewards abstention), data-structure timing (calibration_history starts at h=22), and quantile-sort artefacts (stored p10 is min(q0.10, q0.50, q0.90)).

4. **Pre-committed thresholds** in (1) and (2) are set *before* opening the corrected `paired` dataframe.

**Alternatives (failure mode signals):**

- **Skill gate passes, guardrail fails**: lower-side coverage outside [0.85, 0.95] for either model. This is the calibration problem we already know about (M4 §6 reported 0.81 for both). Argues for either (i) accepting LightGBM with a calibration caveat in the dashboard band display, or (ii) blocking promotion until CQR or ACI is retuned. The pre-committed decision: **block**. Calibration is a real product concern, not a footnote.
- **Skill gate fails**: would mean LightGBM's median forecast isn't actually more accurate than ARF's point on paired data. After the EXP-013 vintage-corrected numbers (LightGBM MAE 24.32 vs ARF MAE 38.42, ratio 0.62) this seems implausible; if it holds, the model swap is unsafe.

**Domain:** EXP-014, LightGBM promotion decision, dashboard cut-over
**Status:** resolved (refuted in form, but informative) — see Resolution below.

**Resolution (2026-05-29):** The skill gate passed (DM p=0.029, LGBM MAE 25% better than ARF), but the absolute-target calibration guardrail FAILED — both models have ~0.81 lower-side coverage, well below the [0.85, 0.95] band. Pre-committed decision: BLOCK. But the framework also surfaced that the gate as written was answering a question we weren't asking ("is the dashboard band acceptable?") rather than the swap-relevant question ("does swapping the model make calibration worse?"). Rather than loosen the criterion (forbidden by method discipline), opened the iteration-5 entry below with a redesigned gate.

---

### [2026-05-29 → resolved 2026-05-29] Iteration-5 redesign of the calibration guardrail: "not worse than incumbent"

**Position (provisional):** the iteration-4-finalised criterion (above) blocked promotion because both LightGBM and ARF have ~0.81 lower-side coverage (vs absolute target [0.85, 0.95]). The gate as written measures "is the dashboard band trustworthy in absolute terms?" — a real question, but a different question from "does swapping the model make calibration *worse*?" For a swap decision, the latter is what matters: both models share the calibration weakness, so swapping doesn't change that weakness. The absolute-target gate is the wrong tool for this decision.

This entry is the iteration-5 redesign. Per the method's "don't loosen Method when the answer arrives; if you want to redefine the bet, open a new entry" rule, we open a new entry rather than mutating the previous criterion.

**Method (pre-committed, before re-running the script):**

1. **Skill gate (unchanged from iteration-4 criterion):** paired Diebold-Mariano on absolute-error loss differentials, `|y − p50_LGBM|` vs `|y − point_ARF|`, with Newey-West HAC bandwidth = max_horizon − 1 = 71. Threshold: mean diff < 0 AND one-sided p < 0.10.

2. **Calibration guardrail (REDESIGNED):** LightGBM's coverage on each side of the 80% interval must be **not more than 0.02 worse than ARF's** on that side.
   - `lgbm_lower_coverage ≥ arf_lower_coverage − 0.02`
   - `lgbm_upper_coverage ≥ arf_upper_coverage − 0.02`
   - "Worse" is defined as further from the nominal 0.90 target (i.e. for lower-side, lower coverage is worse; for upper-side, lower coverage is also worse since target is 0.90 and we're measuring `y <= p90`).
   - The 0.02 tolerance is engineering noise (~1% margin on coverage estimates from ~500 paired observations).
   - This is a one-sided guardrail: the swap must not *degrade* calibration. It says nothing about whether calibration is acceptable in absolute terms; that's a separate problem with its own ticket.

3. **No tail-metric gate** (unchanged): tail metrics reported descriptively after the decision, never gated.

4. **Absolute calibration as separate concern:** if either model's lower-side coverage is < 0.85 (the original iteration-4 absolute threshold), it is logged as a known calibration weakness in the promotion entry and queued as a follow-up experiment (CQR retune, ACI, or wider quantile training). It is not a swap-blocker.

**Alternatives (failure mode signals):**

- **LGBM materially worse on one side, better on the other**: e.g. lower-side improves but upper-side degrades >0.02. The redesigned gate would block. The right interpretation is "this is a different model with a different calibration profile; the comparison is honest." Path forward: investigate where LGBM regresses and decide whether the trade-off is acceptable on its own merits.
- **Skill gate fails**: as in iteration-4 — implausible after EXP-013 corrections but blocking if it happens.

**Rationale for the redesign:**

The iteration-4 absolute-target gate was correct for a *fresh* model promotion (would I deploy a model with 0.81 lower-side coverage on first install?). It is incorrect for a *swap* from an incumbent that already has 0.81 lower-side coverage. The framework caught the gate as written, but the gate was answering a question we weren't asking. This is exactly the kind of "criterion fits a different question than the data answers" issue iterations 2, 3, and 4 surfaced; iteration 5 is the same pattern at a different level.

The redesign is not loosening — the new gate has *teeth* (it would block any LGBM whose coverage was significantly worse than ARF's). It just measures the right thing.

**Domain:** EXP-014 redesigned, LightGBM promotion decision, dashboard cut-over
**Status:** resolved (confirmed). See Resolution below.

**Resolution (2026-05-29):** Confirmed. Both pre-committed gates passed:
- **Skill gate**: LGBM MAE 28.94 vs ARF MAE 38.42 (25% better), DM stat = -1.90, one-sided p = 0.029. PASS (threshold p < 0.10).
- **Calibration guardrail** (redesigned): lower-side degradation +0.013 (ARF 0.824, LGBM 0.811 — within 0.02 tolerance); upper-side degradation -0.249 (ARF 0.621, LGBM 0.870 — LGBM significantly *better* on upper-side, as the ARF upper band was severely under-covering). PASS.
- Absolute-coverage floor warning logged but explicitly not a swap-blocker: LGBM lower-side 0.811 is below the 0.85 absolute floor, but ARF has the same problem, so the swap doesn't make it worse. Queued as a follow-up experiment (CQR retune at horizon-conditioned calibration, or ACI).

Swap executed: `static/js/dashboard.js:loadAugurForecast` now loads `augur_forecast_shadow.json`; `ml/shadow/update_shadow.py` extended to generate consumer-pricing fields via `read_arf_surcharge`; `scripts/daily_update.sh` shadow cron re-enabled with pre-flight stale check restored; ARF cron continues running as backup signal. Logged as EXP-014 in `experiments/registry.jsonl` (decision: kept). See `docs/articles/m4-metric-redesign-story.md` for the full five-iteration arc.

---

### [2026-04-30 → resolved 2026-05-29] LightGBM-Quantile shadow will pass plan §6 over a 14-day window

**Position (provisional):** EXP-009 milestone 3 landed the shadow pipeline (commits `2ec7a54..46c5ca5` on `feat/lightgbm-shadow`, including the round-1 + round-2 review fixups). Once sadalsuud starts producing daily eval-log rows, the LightGBM-Quantile multi-horizon model will pass all three of `docs/lightgbm-quantile-shadow-plan.md` §6 criteria over the first 14 contiguous days, justifying promotion to production. Concrete forecasts grounded in the EXP-009 backtest (LightGBM 14/14 vs ARF, +46% aggregate MAE, h+1 perfect-lag) and the M2.5 CQR result (aggregate coverage 77.5%):

- **(a) MAE on hours where realised < 30 EUR/MWh**: LightGBM beats ARF by ≥25% relative, with ≥50 low-price sample hours across the 14 days.
- **(b) P10/P90 empirical coverage**: 14-day mean in [0.75, 0.85] **AND** fewer than 3 of 14 days fall below 0.60 (additional guard added pre-commitment to address M2.5's bimodal-per-day finding — the regime-shift days 04-25/-26 sat at ~0.46/0.50 even with CQR).
- **(c) Weekday-evening-peak (16-19 UTC) MAE delta**: LightGBM no more than +10% relative worse than ARF at peak hours.

**Alternatives (failure mode signals):**

1. **Live exogenous freshness skew** (round-1 review caveat): `consolidate.py` overwrites parquet rows with later forecast vintages, so the backtest sees fresher exogenous data than live cron will get. **Signal**: 14-day mean `lightgbm_mae` is more than 20% worse than the backtest's h+1 MAE of 13.21 EUR/MWh — i.e. > 15.85 EUR/MWh. If this triggers without (a) failing, it argues for investigating the consolidation policy (separate hypothesis), not parking the model.
2. **Bimodal coverage breaks the aggregate** (M2.5 caveat): regime-shift days hold coverage in the 0.45–0.55 band, pulling 14-day mean below 0.75. **Signal**: criterion (b)'s second guard (≥3 days below 0.60) trips, even if the mean is fine. This argues the CQR window isn't reactive enough — investigate adaptive calibration.
3. **Power deficit on criterion (a)** (round-1 caveat, downgraded by round-2): NL April had ~100 negative-price hours, so 14 days should see ~50–100 low-price hours, ample for detecting a 25% relative delta. **Signal**: total n_low_price < 30 across 14 days. Implies the regime shifted away from spring extremes — extend window to 21 days.

**Method (pre-committed):**

When 14 contiguous rows are present in `ml/shadow/eval_log.jsonl` (most-recent 14 days only, ignore earlier rows from cron-shake-out):

```
import json, numpy as np
rows = [json.loads(l) for l in open("ml/shadow/eval_log.jsonl") if l.strip()][-14:]

# (a) Slice MAE win
lgbm_low = np.mean([r["lightgbm_mae_at_low_price"] for r in rows if r["lightgbm_mae_at_low_price"] is not None])
arf_low  = np.mean([r["arf_mae_at_low_price"]      for r in rows if r["arf_mae_at_low_price"]      is not None])
ratio_a = lgbm_low / arf_low
n_low = sum(r["n_low_price_hours"] for r in rows)

# (b) Coverage — both guards
mean_cov = np.mean([r["lightgbm_band_coverage_p80"] for r in rows])
n_low_days = sum(1 for r in rows if r["lightgbm_band_coverage_p80"] < 0.60)

# (c) Peak-hour delta — directly evaluable from the log
peak_ratios = [r["lightgbm_peak_hour_mae"] / r["arf_peak_hour_mae"]
               for r in rows
               if r["arf_peak_hour_mae"] and r["lightgbm_peak_hour_mae"]]
mean_peak_ratio = np.mean(peak_ratios) if peak_ratios else None

# Decision
PASS_A = ratio_a <= 0.75 and n_low >= 50
PASS_B = 0.75 <= mean_cov <= 0.85 and n_low_days < 3
PASS_C = mean_peak_ratio is not None and mean_peak_ratio <= 1.10
PROMOTE = PASS_A and PASS_B and PASS_C
```

Failure of any one criterion **does not** automatically refute the hypothesis — read the signals against the alternatives above. Refutation requires (a) failing AND none of the failure-mode signals firing, or any criterion failing for a reason not anticipated here.

**Prerequisites — schema gaps surfaced by round-2 review:**

- ✅ `n_low_price_hours`, `arf_peak_hour_mae`, `lightgbm_peak_hour_mae` added to `evaluate_one_day` output and eval_log schema (commit landing this hypothesis update).
- ⏳ Migrate sadalsuud's existing `static/ml/forecasts/` archives to `ml/forecasts/` (path-fix from M3 review fixup A) so historical ARF predictions are findable by `evaluate_shadow.py`. Server-side; not blocking the hypothesis log itself but blocking M4 cron from producing useful `arf_*` fields.

**Revisit trigger:** When `ml/shadow/eval_log.jsonl` contains 14 contiguous days of rows (date column), evaluating from the *first* row whose `arf_mae` is non-null. Original assumption was sadalsuud cron starting 2026-05-01 → earliest 2026-05-15; in practice the shadow CLI was broken on cron from 2026-05-01 to 2026-05-07 inclusive (`memory/gotcha-log.md` 2026-05-08 entry, fix in commit `d620b45`), so cron effectively starts 2026-05-08 → earliest 2026-05-22.

The first eval row (date=2026-04-30, n=72) was produced by a one-shot manual bootstrap on 2026-05-08 and had known structural issues: 72h forced into one `eval_day`, ARF-archive coverage matched only 40 of 72 LGBM hours so `lightgbm_mae_at_low_price` was computed over a different sample than `arf_mae_at_low_price`. **The bootstrap row was deleted from `eval_log.jsonl`** AND the 72 corresponding entries (all tagged `eval_day=2026-04-30`) were purged from `shadow_state.json:calibration_history`, with `last_cqr_q` and `last_cqr_n_calib_days` reset to 0. The purge prevents `evaluate_shadow.find_eligible_eval_days` from re-logging the same broken row on the next cron tick. CQR rebuilds within ~7 days from real nightly runs.

**Review by:** 2026-05-29 (one week buffer past 2026-05-22 to handle cron interruptions).

**Pre-read caveat (added 2026-05-18 mid-window preview, not a Method change):** `evaluate_one_day` aggregates **predictions made on day D, targeting D..D+3** (h+1..h+72). Criterion (a)'s low-price slice is therefore dominated by long-horizon hours where LGBM is structurally weakest (see `docs/model-progress-log.md` 2026-05-18 entry). The 2026-05-22 read should report criterion (a) decomposed by horizon (h≤24 vs h>24) as supplementary evidence, computed from `calibration_history` without touching the eval_log schema. If (a) fails with n_low ≥ 50 and the long-horizon decomposition shows the failure concentrated at h>24, the framework-correct triage is **Path B (park) with structural-failure-mode reason** — *not* Path C (extend window), since more days won't fix a model-design limit.

**Domain:** EXP-009, LightGBM shadow, promotion decision
**Status:** resolved (refuted) — see Resolution below.

**Resolution (2026-05-29):** Refuted. Method verdict PROMOTE = False. Trailing-14
window 2026-05-14 → 2026-05-27 of `ml/shadow/eval_log.jsonl`:
- (a) ratio_a = 1.610 (threshold ≤ 0.75) — **FAIL** in the wrong direction (LGBM
  61% worse than ARF on the low-price slice). n_low = 69 ≥ 50 rules out
  Alternative-3 (power deficit), so Path C is off the table.
- (b) mean cov = 0.696 (target [0.75, 0.85]) **FAIL**; 3 days < 0.60 — second
  guard tripped (Alternative-2 fired).
- (c) mean peak ratio = 0.450 (threshold ≤ 1.10) — **PASS** decisively.

Primary failure mode: **structural (a)** — exactly as the 2026-05-18 mid-window
preview anticipated. 72h aggregation forces the low-price slice into long-
horizon (h>24) midday hours where LGBM cannot extrapolate to negative/sub-30
EUR/MWh prices. Supplementary horizon decomposition from
`shadow_state.json:calibration_history`: 0 low-price entries at h ≤ 24, 200 at
h > 24 with mean |p50 − realized| = 71.2 EUR/MWh — structural error, not
spike-driven. Bimodal coverage Alternative also fired (3 days < 0.60). Path B
(park) executed per augur#13. Full diagnosis in `docs/lightgbm-shadow-postmortem.md`
including the meta-finding that criterion (a) as MAE is methodologically weak
for the question "can the model express negative prices?" — recorded as
postmortem §6 next-bet seed (metric redesign before model redesign).

---

### [2026-04-30 → resolved 2026-05-29] Live shadow MAE will be no more than 20% worse than backtest h+1 MAE

**Position (provisional):** EXP-009 backtest mean MAE was 13.21 EUR/MWh on 14 evaluable days of April 2026 (h+1 perfect-lag, single-horizon `LightGBMQuantileForecaster`). The new multi-horizon model with `horizon_h` as a feature should perform similarly at h+1 (it sees the same features at horizon=1) and somewhat worse at longer horizons. Live performance is *bounded above* by the backtest because `consolidate.py` overwrites parquet rows with later forecast vintages — backtest sees fresher exogenous than live cron will get (round-1 code-reviewer finding). Expect: 14-day mean `lightgbm_mae` from eval_log between 13.5 and 16.0 EUR/MWh.

**Alternative:** The freshness skew is small in practice because day-ahead exogenous (wind/solar/load) is dominated by the morning-of forecast which IS what consolidate.py captures. Signal: live MAE within 5% of backtest, which would mean the round-1 concern was theoretical not empirical. This would be welcome news but should still trigger a separate investigation of `consolidate.py`'s overwrite semantics.

**Method:** After 14 contiguous days of eval_log rows:
```
mean_live_mae = np.mean([r["lightgbm_mae"] for r in rows])
ratio = mean_live_mae / 13.21  # backtest h+1 MAE
# Position confirmed if 1.0 <= ratio <= 1.20
# Alternative confirmed if ratio < 1.05
# Position refuted (worse than expected) if ratio > 1.20 — investigate consolidate.py
```

The eval_log records full-day mean MAE, not h+1. The live mean is a mix of h+1..h+72 errors, so it will naturally be higher than backtest h+1 MAE even without freshness skew. The ratio threshold (1.0–1.20) bakes in roughly +5–10% from horizon-mix and +5–10% from freshness skew. If horizon-mix dominates and skew is small, expect closer to 1.10.

**Revisit trigger:** Same as the §6 hypothesis above (14-day eval_log window).

**Review by:** 2026-05-29 (bumped from 2026-05-22 to align with §6 hypothesis after the 05-22→05-23 verdict-session slip; resolution co-occurs with the Method run regardless).

**Domain:** EXP-009, exogenous data freshness, live-vs-backtest skew
**Status:** resolved (refuted) — see Resolution below.

**Resolution (2026-05-29):** Refuted. Observed `overall_lgbm_mae` = 24.32 EUR/MWh
over the trailing-14 window, ratio vs backtest h+1 of 13.21 = **1.84** (target
[1.0, 1.20]; refutation at > 1.20). Freshness skew is empirically material,
not theoretical. Some of the gap is horizon-mix (the live mean averages
h+1..h+72 while backtest measured h+1 only), but 1.84 exceeds even a
generous +5-10% horizon-mix + +5-10% freshness budget. Argues for prioritising
augur#12 (cron→systemd + run-after-EDH, so live exogenous matches backtest
freshness) **before** any next-bet shadow experiment — testing a new model
class through a layer of confounding data staleness wastes the shadow.
