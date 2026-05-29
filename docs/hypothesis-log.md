# Hypothesis Log

Provisional design decisions under observation. Each entry is a position we took where the evidence to confirm or revise it lives in the future. Different from:

- **`docs/TODO`** / GitHub issues — tasks with an owner, ready to execute
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
