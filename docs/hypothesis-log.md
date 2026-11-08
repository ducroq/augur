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

> **Counts: run `.venv/bin/python scripts/vintage_counts.py`.** Don't hand-count, and don't trust an "≈date" in any entry below; those dates are all stale. It counts fully realised 72-hour vintages per each entry's Method, plus the room left before the oldest one leaves `calibration_history` (30 vintage days, `MAX_HISTORY_DAYS`). Eval-log days are h1–24 only and overcount: the 2026-11-06 hand count said 7 when 6 were fully realised.
>
> | Entry | Trigger | Status |
> |---|---|---|
> | [2026-08-29] EXP-021a Stage 1 | 14 clean vintages (`t0 ≥ 2026-10-30`, after EXP-038's window) | ≈2026-11-16; Review by 10-15 passed, gate vs `lean` per its own Method |
> | [2026-08-30] EXP-028a | ≥28 vintages | **Deferred 2026-11-06** past the EXP-021a Stage 1 read, since it is moot if that fails; Review by 11-30. Lagged-arm source: the EDH publish archive (see the entry's notes) |
> | [2026-11-06] CQR on unwidened scores | 28 post-deploy vintages (`t0 ≥ 2026-11-06 22:00`) | fix merged 2026-11-06; live check running. **No slack:** 28 plus two partial vintages fill the 30-day history, so read it the run the 28th is fully realised (the counter's room hits 0) |
> | [2026-10-28] product criterion | FM Stage 3 shadow reaches 14 vintages | pre-committed; the floor drives the dashboard since 2026-11-07 (ADR-009), so this is the bar to replace it |
> | [2026-11-07] Stage 3 promotion criterion | 14 fully realised FM vintages with live CQR | pre-committed and signed off 2026-11-07 |
> | [2026-05-29] publishable | engineer's call | not due (12-31) |
>
> EXP-018a Stage 1 and EXP-023a Stage B are parked and moved to `docs/archive/hypothesis-log-resolved.md`; the [2026-10-28] park entry below holds their revisit trigger.
>
> Vintage holes: count them at run time; do not trust a list here. Holes since 2026-09-14 have not been enumerated.

### [2026-11-07] Stage 3 promotion criterion: Chronos-Bolt beats production LightGBM on live vintages

**Status:** pre-committed 2026-11-07 with the engineer's sign-off, before the shadow deployed and before any FM vintage existed. Two choices were the engineer's: count only vintages whose CQR was live, and only fully realised ones.

**Position (provisional):** on live vintages, Chronos-Bolt's `p50` has lower absolute error than production LightGBM's without worsening band coverage. This is the ADR-007 criterion that EXP-021a's Stage 3 said would be re-derived against the incumbent of the day. It's relative to LightGBM only: the floor is judged by the [2026-10-28] product criterion, which stands beside it.

**Alternatives (failure-mode signals):**

1. **The offline win doesn't survive live data.** Signal: the skill gate fails.
2. **Raw Bolt bands look good only until production's CQR defect is gone.** The fix of 2026-11-06 raised production's coverage. Signal: the guardrail blocks.
3. **The criterion measures a state that never ships.** A swapped-in FM would always run with warm CQR, so its cold-start vintages (q = 0 against a warmed-up incumbent) are excluded from the population, not merely reported. Signal that this exclusion matters: FM coverage on the excluded vintages differs from the counted ones by more than 0.02 on either side. That is reported, never gated.

**Method (pre-committed 2026-11-07):**

- **Population.** The first 14 FM vintages in date order whose rows carry `cqr_n_calib_days ≥ 3` (the FM's own CQR was live) and where all 72 hours are realised in both arms, read from `fm_state.json` and `shadow_state.json:calibration_history`, paired on (`eval_day`, `timestamp_utc`). Production's history can hold duplicate keys after a repeated `t0`: in each arm, keep the last row per key, and a vintage counts only with exactly 72 unique paired timestamps. Observations enter the DM ordered by `t0`, then horizon. No vintage is excluded for its result. No interim read of either gate, and the window isn't extended.
- **Skill gate.** Paired DM on `|y − p50|`, FM against production `p50`, per observation, Newey-West HAC bandwidth 71, one-sided α = 0.10. Passes iff the mean difference is negative and p < 0.10.
- **Calibration guardrail.** Lower- and upper-side coverage of the shipped bands (`p10`, `p90` after CQR, both arms) on the same population. Blocks if FM is more than 0.02 worse than production on either side.
- **Swap.** Requires Stage 1 passed as written, the skill gate passed, no guardrail block, and the [2026-10-28] product criterion passed. Stage 3's judgement on operational surface stays the engineer's.

**Revisit trigger:** 14 such vintages exist (≈17 nights after deploy, counting the warm-up). Compute the read before the first of them leaves the 30-day history.

**Review by:** 2026-12-15.

**Domain:** EXP-021a, ADR-006, ADR-007, augur#15.

**Note added 2026-11-07, after ADR-009; the Method above is unchanged.** The dashboard now shows the day-type profile rule, and LightGBM is a shadow. The skill gate still pairs FM with LightGBM as written. The Swap clause's product criterion is against the floor, which is now the incumbent, so a passing swap replaces the rule. Whether the LightGBM skill gate still earns its place is the engineer's call. Changing it is a new entry, written before the 14 vintages are read.

### [2026-11-06] Calibrating CQR on unwidened scores restores P80 coverage without costing either side

**Position (provisional):** `compute_cqr_q` should score the unwidened sorted quantiles, not the stored widened bands. That removes the feedback loop recorded by EXP-015 and stops `q` collapsing to 0.

**What is already known, so this is only part-blind:** on 130 replayed days, overall coverage is 0.701 delivered and 0.788 replayed, mean `q` 13.1 and 23.7 (`memory/gotcha-log.md`). Per-side coverage, median width and Winkler had not been computed when this was written.

**Method (pre-committed 2026-11-06, before those numbers):** ADR-007's skill gate does not apply, because `p50` does not change. Guardrail, from ADR-007: on the same replay, lower-side and upper-side coverage must each be no more than 0.02 below delivered. Pass means implement. Winkler and median width are descriptive only, per ADR-007, and are reported in the verdict.

**Live check:** after 28 post-deploy vintages, scored over all 72 horizons from `calibration_history`. The Position holds iff band coverage is within 0.75–0.85 and `q` is below 1 on at most 2 of those days.

**Alternatives (failure-mode signals):**
1. **The loop was accidentally useful.** **Signal:** the guardrail fails on either side. Then do not implement; open a new entry.
2. **The loop is not the main problem.** **Signal:** live coverage stays below 0.75 with `q` stable. Then the gap is the 7-day window lagging regime shifts, which is EXP-016's first-shift-day finding.

**Replay result (2026-11-06, `scripts/replay_cqr_unwidened.py`, 130 eval days, 8,939 rows):** guardrail **PASS**. Lower side 0.852 → 0.887, upper side 0.851 → 0.901, band 0.703 → 0.788. Descriptive: median width 113.3 → 132.4 EUR/MWh (+17%), Winkler 216.2 → 214.6, lower on 75 of 130 days. Band coverage stays under 0.80, and the replay can't show how the changed band behaves live, so the live check stands.

**Note added 2026-11-06, after review; the Method above is unchanged.**

- **The guardrail PASS is not evidence.** It could not have failed: for the same rows the replay's `q` is never below the delivered `q` (below on 0 of 130 days), so the bands nest and neither side can lose coverage. Alternative 1 could not fire either. The per-day `q` series had been computed before this entry was written, and it wasn't disclosed above, including `q` below 1 on 1 replayed day against 19 delivered. The live gate's "at most 2 days" was therefore set knowing that count.
- **What the evidence is:** the removed collapse, and the trade below. The fix removes a defect; it does not improve the score. In-sample, delivered bands plus a constant 8.5 EUR/MWh reach band 0.790 at Winkler 212.0, so adaptive `q` shows no sharpness gain over a constant.
- **The cost is larger recently** (`--rev acb1a5b`). Since the 2026-09-13 anchor shift: band 0.703 → 0.790, median width 144 → 178 (+24%), Winkler 273.1 → 273.5. November, 288 rows on 5 partly filled days: band 0.701 → 0.934, width 107 → 197 (+84%), Winkler 185.7 → 198.2, so the replay over-covers after the spike. That is the 7-day window lagging, which this fix does not touch.
- **Reading the live check:** coverage is pooled over rows, all 72 horizons, as the replay script prints it; 0.701 elsewhere is the mean of daily values. Read `q` from `last_cqr_q`. Rebuild from git snapshots, because `MAX_HISTORY_DAYS` trims the first vintages before the last one fills. The first vintage is the first run after deploy. In Alternative 2, "`q` stable" means `q` below 1 on at most 2 of the days. A single outcome is noisy: 8.7% of overlapping 28-vintage replay windows fall outside 0.75–0.85.

**Review by:** 2026-12-15.

---

### [2026-10-28] Product criterion: a forecaster earns the dashboard only by ranking cheap hours at least as well as the profile floor, in every horizon group

**Position (provisional):** the dashboard's job is choosing *when* to run a heat pump or charge a car, so the metric that decides what it serves is cheap-hour cost regret, not MAE. EXP-037 showed the two disagree: production LightGBM improves MAE by flattening (forecast amplitude 14–15 vs realised 42 EUR/MWh beyond 24h) and so ranks cheap hours *worse* than the carry (k6 regret 9.2 / 10.7 at h25_48 / h49_72 vs the carry's 5.3 / 4.8). EXP-036 pre-committed that a scalar floor is the wrong shape, so the bar is per horizon group.

**Why now, and why this is a new entry, not an edit:** no fresh-vintage regret has been computed for any arm at the time of writing (the daily eval log carries MAE only). ADR-007's skill gate and EXP-021a's four Stage 1 gates are untouched; this adds a second, product-level condition to the *swap*, written before its data exists.

**Method (pre-committed 2026-10-28):** at the end of any live shadow (first use: the EXP-021a Stage 3 Chronos shadow, 14 evaluable vintages), score each 24-slot block (h1_24, h25_48, h49_72) per vintage with `score_block` from `scripts/exp037_rank_metric.py` (k = 3 and 6, stable-sort ties, partial blocks dropped, never padded). The candidate passes iff, **in each of the three blocks**, its mean **k6** regret is at or below the EXP-036 profile floor's (`naive_profile_prediction`, 5 matching day types) on the same blocks. k3 and Spearman are reported, never gated. A paired DM (HAC lags 3, one-sided) is reported per block as the strength of evidence; it does not gate, because 14 blocks per group cannot carry a p < 0.10 test reliably, and a gate that cannot pass at the available n is an abstention, not a criterion.

**Alternatives (failure-mode signals):**
1. **Regret is too noisy at n = 14 to rank anything.** **Signal:** the per-block regret standard error exceeds the candidate-floor difference in two or more groups. Then extend the shadow to 28 vintages before deciding; do not loosen the bar.
2. **The floor wins at h1_24 only, where both are already good.** **Signal:** the candidate fails h1_24 by under 0.5 EUR/MWh and wins the other two by more than 2. That is a real failure under this Method; a hybrid (floor for h1_24) is a new entry, not a reading of this one.

**Review by:** when the first Stage 3 shadow reaches 14 vintages. Production fails this criterion today (regret k6 about 10–11 against the floor's 5.6–5.8); the engineer decided on 2026-11-06 to keep it until then rather than swap early.

**Related evidence (added 2026-10-29, outside the Method, which is unchanged):** Lipiecki & Weron (2026, arXiv:2609.00089) reach the same split on battery arbitrage. TabPFN has the best CRPS in every market, yet DDNN-JSU earns the most under the risk-averse strategies. Their caveat applies here too: trading profit, like k6 regret, is **not a proper scoring rule**. That supports this entry's shape, regret as an *added* swap condition beside ADR-007's proper-score gate, never a replacement for it. Their gaps between top models are mostly ~1%, and they warn against reading the order of close models, which matches Alternative 1's noise concern.


**Note added 2026-11-07; the Method above is unchanged.** The engineer reversed the 2026-11-06 "keep production until then": since ADR-009 the floor itself drives the dashboard. This criterion now reads as the bar for any challenger to replace it.

### [2026-10-28] Park EXP-018a Stage 1 and EXP-023a Stage B: LightGBM tuning cannot move the decision that is open

**Position:** both entries tune the incumbent (feature set, window length) while every standing finding says the bottleneck is the model class (`memory/model-class-findings.md`: feature engineering closed at 56 days; the FM's context advantage is not recoverable inside LightGBM). Their Methods stand as written and are not edited; they are parked, not refuted. EXP-018a's only downstream role was choosing EXP-021a's incumbent arm, and EXP-021a's own Method already says that, with 018a unconcluded, *"the primary gate stays against `lean`, the harder bar"*.

**Revisit trigger:** EXP-021a fails Stage 1 or Stage 2 (then LightGBM stays in production and tuning it matters again), or the engineer asks.

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

**Review by:** 2026-11-30, after the EXP-021a Stage 1 read (moved from 2026-10-31 by the engineer on 2026-11-06; Method unchanged).

**Domain:** EXP-028a, foundation models (augur#15), exogenous features (augur#3, augur#22), augur#19, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-30, before any fresh vintage was scored.

**Related evidence (added 2026-10-29, outside the Method, which is unchanged):** Lipiecki & Weron (2026, arXiv:2609.00089; deep-dive `docs/foundation-models-epf-literature-review.md`), DE/PL/ES day-ahead 2021–2025. Two points for this review. **(a) Alternative 1 has a cheap, direct test that this Method doesn't contain:** `Chronos-2-synth`, pretrained on synthetic data only, matches Chronos-2 there (CRPS better in DE and PL, 2% worse in ES). Re-running EXP-028's covariate-vs-univariate pair with it would be contamination-free by construction and could use all 260 stored vintages instead of the 77 after 2026-06-05. **(b) Chronos-2 is not the strongest covariate model:** TabPFN-3 (10–22% better CRPS) and TabPFN-2 (8–19%), tabular and also synthetic-only, beat it in every market (backlog EXP-040). Both are new entries. Day-ahead only, so neither speaks to 25–72h. **(c) Alternative 4's mandatory lagged arm has a source:** `scripts/exp028_chronos2_covariates.py` has no `c2_known_future_lagged` arm yet, but the energydatahub repo archives every EDH publish (`data/YYMMDD_HHMMSS_<feed>.json`, encrypted, from 2025-12-01), so covariates as published at t0 can be rebuilt (found 2026-10-29).

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

**Addendum 2026-11-07 (Stage 3 build: a deviation from the Method, whose text stands):**
- **Order: deviation.** The Method runs Stage 3 "only if Stages 1 and 2 pass". By the engineer's call of 2026-11-06 the shadow starts before Stage 1 reads, so it starts collecting vintages while Stage 1 waits for its 14. What still holds is narrower than the Method: no swap unless Stage 1 passes as written. A failed Stage 1 stops the shadow.
- **Overlap.** The first shadow vintages fall inside Stage 1's window. Same frozen model, same hours, so they aren't independent evidence.
- **Context: deviation.** `update_fm.py` keeps the offset and length EXP-038/039 measured (ends at t0 − 1h, prediction length 73), but on price rows only. EXP-038 also dropped rows with exogenous NaNs, which the FM doesn't read, so this isn't EXP-021's exact matched row set and it can hold a few more prices than the incumbent's (median 18 per context across EXP-038's 60 vintages, maximum 18, and for some vintages all 18 fall in the last week).
- **Read.** `fm_state.json` keeps 30 days, and FM regret lands in `ml/shadow/fm_regret_log.jsonl`, separate from production's log. The promotion criterion, which excludes cold-start vintages, is the [2026-11-07] entry.

**What is explicitly not decided by this entry:** whether Augur's production forecaster *should* be a 205M-parameter pretrained model rather than a 1344-row nightly refit is a question about operational surface, reproducibility and the project's ability to debug its own forecasts — not only about quantile score. Stage 3 is where that judgement gets made, with a live shadow in hand. Recording it here so a strong Stage 1 does not read as having settled it.

**Revisit trigger:** ≥14 vintages with `t0 ≥ 2026-08-25` in the parquet — ≈2026-09-09, **after** EXP-018a Stage 1 has run on the same window. Surface in `/curate`.

**Review by:** 2026-10-15.

**Domain:** EXP-021a, augur#15 (foundation models), augur#19 (calibration), model class, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-29 immediately after EXP-021 resolved, before any production path was touched.

**Note added 2026-11-06 (Method unchanged):** the CQR fix in [2026-11-06] shifts CQR-widened live coverage at its deploy date, so read Alternative 4's signal across that date with care. The Stage 1 gate uses raw bands and is unaffected.

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

**Archived to `docs/archive/hypothesis-log-resolved.md`** (2026-10-16), unedited. A citation like `docs/hypothesis-log.md [2026-09-14]` for a resolved entry resolves there. New resolutions move there too, when they are resolved.
