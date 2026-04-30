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

### [2026-04-30] LightGBM-Quantile shadow will pass plan §6 over a 14-day window

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
n_low = sum(... )  # need to add n_low_price_hours to schema (see prereqs)

# (b) Coverage — both guards
mean_cov = np.mean([r["lightgbm_band_coverage_p80"] for r in rows])
n_low_days = sum(1 for r in rows if r["lightgbm_band_coverage_p80"] < 0.60)

# (c) Peak-hour delta
# Requires arf_peak_hour_mae in schema (see prereqs)
peak_ratios = [(r["lightgbm_peak_hour_mae"] / r["arf_peak_hour_mae"]) for r in rows if r["arf_peak_hour_mae"]]
mean_peak_ratio = np.mean(peak_ratios)

# Decision
PASS_A = ratio_a <= 0.75 and n_low >= 50
PASS_B = 0.75 <= mean_cov <= 0.85 and n_low_days < 3
PASS_C = mean_peak_ratio <= 1.10
PROMOTE = PASS_A and PASS_B and PASS_C
```

Failure of any one criterion **does not** automatically refute the hypothesis — read the signals against the alternatives above. Refutation requires (a) failing AND none of the failure-mode signals firing, or any criterion failing for a reason not anticipated here.

**Prerequisites — schema gaps surfaced by round-2 review (must land before this hypothesis is evaluable):**

- Add `n_low_price_hours` (int) to `evaluate_one_day`'s output dict and write to eval_log. Today the slice n is implicit in `lightgbm_mae_at_low_price is not None` but the count itself isn't recorded.
- Add `arf_peak_hour_mae` (float|null) and `lightgbm_peak_hour_mae` (float|null) to `evaluate_one_day` output and write to eval_log. The current `peak_hour_mae_delta` is in EUR/MWh, not relative — without the two underlying values, criterion (c) cannot be evaluated from the log alone.
- Migrate sadalsuud's existing `static/ml/forecasts/` archives to `ml/forecasts/` (path-fix from M3 review fixup A) so historical ARF predictions are findable by `evaluate_shadow.py`.

**Revisit trigger:** When `ml/shadow/eval_log.jsonl` contains 14 contiguous days of rows (date column), evaluating from the *first* row whose `arf_mae` is non-null. Earliest plausible date assuming sadalsuud cron starts 2026-05-01 and the prerequisites land first: 2026-05-15.

**Review by:** 2026-05-22 (one week buffer past 2026-05-15 to handle cron interruptions or prereq delays).

**Domain:** EXP-009, LightGBM shadow, promotion decision
**Status:** open — blocked on prereqs above

---

### [2026-04-30] Live shadow MAE will be no more than 20% worse than backtest h+1 MAE

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

**Review by:** 2026-05-22.

**Domain:** EXP-009, exogenous data freshness, live-vs-backtest skew
**Status:** open

---

## Resolved

*(none yet — entries move here with a one-line outcome when revisited)*
