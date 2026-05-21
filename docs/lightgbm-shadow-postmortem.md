# LightGBM-Quantile Shadow — M4 outcome

**Status**: DRAFT (placeholders to fill on 2026-05-23 after the Method run)
**Run window**: 2026-05-08 → 2026-05-21 (14 contiguous days of nightly cron;
preceded by EXP-009 backtest milestones M0–M3 on `feat/lightgbm-shadow`).
**Outcome (expected)**: parked — structural failure on criterion (a).
**Hypothesis tested**: `docs/hypothesis-log.md` "LightGBM-Quantile shadow will
pass plan §6 over a 14-day window" (open since 2026-04-30, mid-window preview
2026-05-18 already flagged structural (a) failure).

This is a neutral postmortem. The shadow design did the job it was scoped to
do — produce daily forecasts, log per-day metrics, and let us read a falsifiable
verdict from the pre-committed Method. The verdict is what it is; this document
records it and points at the next bet.

---

## 1. What the shadow was meant to prove

`docs/lightgbm-quantile-shadow-plan.md` §6 set three promotion gates over 14
contiguous days:

| Criterion | Threshold |
|---|---|
| (a) MAE on hours where realised < 30 EUR/MWh | LightGBM beats ARF by ≥ 25% relative |
| (b) P10/P90 band empirical coverage | Mean in [0.75, 0.85] AND <3 days <0.60 |
| (c) Weekday-evening-peak (16–19 UTC) MAE | LightGBM no more than +10% worse than ARF |

All three had to hold to justify replacing ARF on the dashboard. The plan
explicitly: "Doesn't auto-promote on the 14-day mark — promotion is a manual
decision after reading the eval log." This file is that manual decision.

## 2. Results — 14-day window 2026-05-08 → 2026-05-21

Numbers from `scripts/m4_method_run.py` (pre-staged 2026-05-21, executed
2026-05-23 against a sadalsuud-fresh `ml/shadow/eval_log.jsonl`):

| Criterion | Value | Threshold | Verdict |
|---|---|---|---|
| (a) ratio = lgbm_low / arf_low | `[FILL]` | ≤ 0.75 | `[FILL]` |
| (a) n_low_price_hours (sum) | `[FILL]` | ≥ 50 | `[FILL]` |
| (b) mean P80 coverage | `[FILL]` | [0.75, 0.85] | `[FILL]` |
| (b) days < 0.60 coverage | `[FILL]` | < 3 | `[FILL]` |
| (c) mean peak-hour ratio | `[FILL]` | ≤ 1.10 | `[FILL]` |
| Informational: overall LGBM/ARF MAE | `[FILL]` / `[FILL]` | (n/a) | (n/a) |

**Headline**: `[FILL — one sentence on PROMOTE = True/False and which criteria
drove the outcome]`.

### Supplementary — horizon-decomposed (a)

Per the 2026-05-18 mid-window preview, criterion (a)'s 72-hour aggregation
means the low-price slice is dominated by long-horizon hours where LGBM is
structurally weakest. Reported alongside the Method, not in place of it:

| Horizon group | n_low hours | LGBM `|p50 − realized|` mean |
|---|---|---|
| h ≤ 24 | `[FILL]` | `[FILL]` EUR/MWh |
| h > 24 | `[FILL]` | `[FILL]` EUR/MWh |

If the gap between h ≤ 24 and h > 24 is large, the failure is in long-horizon
solar/low-price prediction, not the model class.

## 3. Diagnosis — which failure-mode signal fired

Hypothesis-log Alternatives (named pre-commitment):

1. **Live exogenous freshness skew** — signal: 14-day mean `lightgbm_mae` >
   15.85 EUR/MWh (>20% worse than backtest h+1).
   Observed: `[FILL — value, fired Y/N]`. If fired alongside (a) failing, that
   argues investigating `consolidate.py` overwrite semantics (augur#12 territory),
   *not* parking the model.
2. **Bimodal coverage breaks the aggregate** — signal: ≥3 days below 0.60.
   Observed: `[FILL — value, fired Y/N]`. If fired, the CQR window isn't
   reactive enough — investigate adaptive calibration (ACI, Gibbs & Candès 2021).
3. **Power deficit on (a)** — signal: n_low < 30. Observed: `[FILL — value,
   fired Y/N]`. If fired, the regime moved; the right move is Path C (extend
   window), not Path B.

**Primary diagnosis**: `[FILL — one paragraph naming the dominant failure mode
and the evidence. The mid-window preview's expected outcome was: (a) fails for
structural reasons, (b) passes once 05-08 ages out, (c) crushes it. Confirm or
revise here.]`

**Known Method limitation (for completeness, not a re-litigation)**: criterion
(a) ratio_a is the mean of per-day `lightgbm_mae_at_low_price` values divided
by the mean of per-day `arf_mae_at_low_price` values. Each per-day MAE is
already an average over that day's low-price hours, so the ratio is an
unweighted mean of per-day averages — a day with 1 low-price hour weighs the
same as a day with 12. The pre-committed Method is identical (`hypothesis-
log.md:46-48`), so this is not a re-evaluation, but if `ratio_a` is borderline
the hours-weighted version (`sum(mae_i * n_i) / sum(n_i)`) is the first
robustness check to run before drawing a firm conclusion.

### Companion hypothesis — Live shadow MAE vs backtest h+1 MAE

The second open entry in `docs/hypothesis-log.md` predicted `overall_lgbm_mae`
in [13.5, 16.0] EUR/MWh (ratio vs backtest h+1 MAE of 13.21 in [1.0, 1.20]).

| Quantity | Observed | Interpretation |
|---|---|---|
| `overall_lgbm_mae` | `[FILL]` EUR/MWh | (from Method block) |
| ratio = observed / 13.21 | `[FILL]` | `[FILL — pick one]` |

- ratio < 1.05 → Alternative confirmed (freshness skew is theoretical not empirical); still open augur#12 to investigate `consolidate.py` overwrite semantics.
- ratio in [1.0, 1.20] → Position confirmed.
- ratio > 1.20 → Position refuted; freshness skew dominates. Argues for prioritising augur#12 before any next-bet shadow experiment.

This companion hypothesis is recorded separately from the §6 promotion
decision because it tests *exogenous data freshness*, not *model class*. Its
resolution is independent of Path A/B/C and goes to its own entry in
hypothesis-log resolution.

## 4. Why this is not Path C (extend window)

`[FILL — only if Path B is the call. The argument: criterion (a) failed and
n_low ≥ 50, so the failure isn't sample-size, it's structural. The horizon-
decomposed split (§2) makes this concrete: LGBM at h > 24 cannot extrapolate to
midday negative-price hours because the long-horizon weather signal in the
feature set has thinned out. More days won't fix a model-design limit. Path C
is the right call ONLY if n_low < 50 — i.e. the data didn't get a chance to
trigger the criterion.]`

## 5. What carries forward

- ✅ Shadow infrastructure (`ml/shadow/`, CQR, eval_log, secure_pickle) is
  proven by `[FILL: N]` days of nightly operation across the 14-day window
  (`[FILL: any data-quality gaps observed during the window]`). Code stays in
  tree, cron is disabled (not deleted) — re-enableable by uncommenting the
  shadow block in `scripts/daily_update.sh`.
- ✅ Conformal calibration (EXP-010) earned its keep — `[FILL: per-day coverage
  observation, e.g., mean cov 0.78, n_days_low_cov = 1].`
- ✅ Healthchecks.io + dynamic commit-message observability survived the M4
  window without false negatives (recall the 2026-05-01..07 silent-failure
  episode this hardening was designed to prevent).
- ❌ The multi-horizon-as-feature stacking did not deliver low-price extrapolation
  at h > 24. Treat this as a constraint on the next bet, not a critique of LGBM.

## 6. The next bet

`[FILL — one paragraph naming the candidate next experiment. Seeds from the
mid-window preview: (1) longer training history to capture multi-year solar
evolution, (2) separate model heads per horizon group instead of horizon-as-
feature, (3) explicit solar-forecast features at long horizons. Pick one as
EXP-012 (or however the registry numbers fall) and open the scoping issue.]`

## 7. Decisions logged

- `experiments/registry.jsonl` — append EXP-011 outcome row (decision: parked,
  rationale references this file).
- `docs/hypothesis-log.md` — move the "LightGBM-Quantile shadow will pass §6"
  entry to ## Resolved with outcome: refuted, primary signal = `[FILL]`.
- `scripts/daily_update.sh` — shadow block commented out, leave the code in tree.
- `CLAUDE.md` — ML Pipeline section updated to "ARF still in production,
  LGBM-shadow parked pending next-bet experiment".
- `memory/MEMORY.md` — `arf-retired.md` entry updated to close the M4 chapter.
- augur#13 — closing comment posted, issue closed.

## 8. References

- `docs/lightgbm-quantile-shadow-plan.md` — the plan being evaluated
- `docs/hypothesis-log.md` — pre-committed Method and Alternatives
- `docs/model-progress-log.md` 2026-05-18 entry — mid-window preview that
  flagged the structural (a) failure
- `docs/river-arf-retrospective.md` — the prior model's retirement; useful
  template for what a postmortem looks like when the model genuinely worked
- `experiments/registry.jsonl` EXP-009, EXP-010 — backtest evidence that led
  to the shadow window in the first place
- `ml/shadow/eval_log.jsonl` — primary evidence; 14 rows 2026-05-08 → 2026-05-21
- `scripts/m4_method_run.py` — verdict generator
