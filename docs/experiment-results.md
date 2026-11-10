# Experiment Results

**Generated file — do not edit.** Rendered from `experiments/registry.jsonl` and the `summary.json` artifacts it references, by `scripts/render_results.py`. Regenerate after appending to the registry; `--check` fails if this file is stale. Per-experiment sections (every metric, caveat, artifact, commit) are in `experiment-results-detail.md`: grep it by id rather than reading it whole.

Registry state: **37 entries**, rendered at `8b52ab1`. Integrity of the underlying record is verified separately by `scripts/audit_registry.py` (schema, id order, artifact existence, number traceability, and sha256 proof that no pre-committed Method was edited after its result landed).

Decision values: `kept` (evidence stands / in production) · `parked` (works, not adopted, revisit) · `rejected` (does not work) · `rolled_back` · `superseded`.

## Decision state — read this before proposing new work

Derived from each entry's `decision` field, so it cannot drift from the record.

> **augur#29 verdict, 2026-11-06:** every effect size from before 2026-09-06 is measured against a reference that doesn't beat the seasonal-naive floor. Entry: `docs/archive/hypothesis-log-resolved.md` [2026-09-06].

### Closed — refuted, do not re-run as-is

Per ADR-007 a refuted position is **not** re-run with a looser Method. Re-opening one of these needs a *new* entry with a new Position and a mechanism that says why the earlier test could not have seen the effect — the way EXP-020 narrowed EXP-018, and EXP-028 narrowed EXP-020.

| id | what is closed | why |
|---|---|---|
| EXP-008 | River ARF retirement decision | Three independent failure modes confirmed in postmortem: (1) trees can't extrapolate to negative prices, (2) lower-band clamp at 0 in update.py:337 makes uncertainty channel also blind, (3) regime… |
| EXP-019 | Stationary reparameterisation (anchor + spreads) | Hypothesis refuted |
| EXP-020 | Market fundamentals (residual load, TTF gas, holiday) | Position refuted on both bases |
| EXP-024 | Lag richness refuted | Position REFUTED: adding raw lags does not recover the FM's context advantage, it costs. lean (15 feat) QS 9.51; lean_lag24 (33) +1.6% worse; lean_lag168 (37) +2.5% worse (DM p=1.0000, decisively the… |
| EXP-025 | Band transplant refuted — but production CQR already reaches most of the foundation model's calibration, and a weighted blend beats the FM alone | Position REFUTED |
| EXP-027 | Fine-tuning destroys the calibration prior — and point skill too | Position REFUTED, Alternative 2 confirmed decisively, and the mechanism half was right for the wrong overall outcome |
| EXP-029 | Residual pre-screen | The Position's NUMBER was confirmed (OOS R^2 = -2.00, far below the 0.05 bar; the correction makes MAE 79% worse) but the INFERENCE it existed to support was wrong, and that is the finding |
| EXP-004 | ENTSO-E contamination rollback (Energy Zero consumer-price leak) | Model rolled back to pre-contamination checkpoint bbaa2c8 (4119 samples) |

### Open — works, not adopted. **These are the live decisions.**

The registry records *what was found*; the **revisit trigger and review-by date live in `docs/hypothesis-log.md`**, which is the file to check for what each of these is actually waiting on.

| id | finding | why it did not ship |
|---|---|---|
| EXP-006 | Long-history mini-warmup leakage probe (ADR-005 Phase A paused) | Calibrated noise improved rather than degraded the model (noisy beat clean by ~1.7 EUR/MWh) |
| EXP-007 | Phase 1 A/B | Direction is positive across MAE/MAPE/RMSE but the 1.28 EUR/MWh MAE delta is below the >=2 EUR/MWh decision gate |
| EXP-011 | LightGBM-Quantile shadow 14-day promotion decision (M4) | Criterion (a) failed (ratio 1.61, threshold <=0.75) and (b) failed both guards (mean cov 0.696, 3 days <0.60); (c) crushed it (0.450). n_low=69 >= 50 rules out Path C (extend window) - failure isn't… |
| EXP-015 | Per-side CQR on raw quantiles (offline replay) | Pre-committed Stage-1 verdict IMPLEMENT=False: lower-side 0.826 < 0.86 bar despite +0.048 over incumbent on same rows and Winkler within guardrail |
| EXP-016 | Per-side ACI (offline replay) | Pre-committed verdict IMPLEMENT=False: lower 0.852 in the Alternative-1 near-miss zone AND Winkler guardrail tripped (+12%, Alternative 3) |
| EXP-022 | Context ladder | Diagnostic, nothing to adopt |
| EXP-023 | Window-length sweep | All four pre-committed gates PASS at 112 days: DM p<0.0001, QS 3.0% better than 56d, coverage better on both sides (lower 0.857->0.877, upper 0.761->0.776), Winkler better (173.2->169.4) |
| EXP-028 | Covariates DO help a covariate-capable foundation model | The Position's skill claim is CONFIRMED and the exogenous question genuinely re-opens with model class. chronos-2 with the seven known-future covariates scores QS 7.30 vs 7.96 univariate — 8.3%… |
| EXP-032 | EXP-023a Stage A | The advantage does NOT reproduce |
| EXP-035 | Every stored arm re-scored against a seasonal-naive floor | PARKED, matching EXP-022's treatment of a mechanism diagnostic: this changes no production path and authorises no swap |

### Standing evidence — `kept`

| id | finding |
|---|---|
| EXP-002 | Re-warmup after ENTSO-E historical backfill |
| EXP-003 | Extend forecast horizon 48h -> 72h |
| EXP-005 | Variance-preserving recursion + frozen-metrics fix |
| EXP-009 | LightGBM-Quantile beats River ARF on April 2026 next-hour MAE (shadow milestone 2) |
| EXP-010 | Split-conformal correction fixes LightGBM band under-coverage (shadow milestone 2.5) |
| EXP-012 | Metric-redesign validation on M4 window (no retraining) |
| EXP-013 | EXP-012 corrections following code-review battery (no new experiment) |
| EXP-014 | LightGBM-Quantile promoted to production (redesigned-criterion pass) |
| EXP-018 | Stage-0 per-feature-group ablation |
| EXP-021 | Zero-shot foundation model (Chronos-Bolt) beats the tuned LightGBM incumbent by 20% quantile score with no features at all — model class confirmed as the live lever |
| EXP-026 | Model-size ladder |
| EXP-030 | EXP-026 part (b) completed by proxy |
| EXP-031 | Documentation-integrity audit of EXP-021..030 |
| EXP-033 | EXP-021a Stage 2 latency gate discharged on the real host |
| EXP-036 | The skill floor was too weak |
| EXP-037 | The product lens does not rescue the incumbent |
| EXP-038 | Chronos-Bolt's zero-shot win reproduces on 60 fresh vintages |
| EXP-039 | Chronos-Bolt is feasible on sadalsuud |
| EXP-001 | Initial ARF warmup baseline (pre-backfill) |

## Summary

| id | date | decision | headline | outcome |
|---|---|---|---|---|
| EXP-001 | 2026-03-26 | superseded | — | Initial ARF warmup baseline (pre-backfill) |
| EXP-002 | 2026-03-28 | **kept** | — | Re-warmup after ENTSO-E historical backfill |
| EXP-003 | 2026-04-01 | **kept** | — | Extend forecast horizon 48h -> 72h |
| EXP-004 | 2026-04-02 | rolled back | — | ENTSO-E contamination rollback (Energy Zero consumer-price leak) |
| EXP-005 | 2026-04-14 | **kept** | — | Variance-preserving recursion + frozen-metrics fix |
| EXP-006 | 2026-04-19 | parked | — | Long-history mini-warmup leakage probe (ADR-005 Phase A paused) |
| EXP-007 | 2026-04-23 | parked | — | Phase 1 A/B: TTF gas + NL generation-mix lag24h features |
| EXP-008 | 2026-04-28 | rejected | — | River ARF retirement decision |
| EXP-009 | 2026-04-29 | **kept** | — | LightGBM-Quantile beats River ARF on April 2026 next-hour MAE (shadow milestone 2) |
| EXP-010 | 2026-04-29 | **kept** | — | Split-conformal correction fixes LightGBM band under-coverage (shadow milestone 2.5) |
| EXP-011 | 2026-05-29 | parked | — | LightGBM-Quantile shadow 14-day promotion decision (M4) |
| EXP-012 | 2026-05-29 | **kept** | — | Metric-redesign validation on M4 window (no retraining) |
| EXP-013 | 2026-05-29 | **kept** | — | EXP-012 corrections following code-review battery (no new experiment) |
| EXP-014 | 2026-05-29 | **kept** | — | LightGBM-Quantile promoted to production (redesigned-criterion pass) |
| EXP-015 | 2026-06-12 | parked | — | Per-side CQR on raw quantiles (offline replay): improves lower-side, fails implement bar |
| EXP-016 | 2026-06-12 | parked | — | Per-side ACI (offline replay): post-shift adaptation works, first-shift-day ceiling + Winkler trip |
| EXP-018 | 2026-08-25 | **kept** | — | Stage-0 per-feature-group ablation: rolling stats are harmful, exogenous trio is inert |
| EXP-019 | 2026-08-25 | rejected | — | Stationary reparameterisation (anchor + spreads): refuted |
| EXP-020 | 2026-08-29 | rejected | — | Market fundamentals (residual load, TTF gas, holiday): refuted |
| EXP-021 | 2026-08-29 | **kept** | `fm_qs_delta_pct_vs_lean`=-20.3<br>`fm_mae`=23.23<br>`lean_mae`=27.77<br>`fm_coverage_band`=0.811 | Zero-shot foundation model (Chronos-Bolt) beats the tuned LightGBM incumbent by 20% quantile score with no features at all |
| EXP-022 | 2026-08-29 | parked | `prior_share_of_gap_pct_points`=12.5<br>`context_share_of_gap_pct_points`=7.8 | Context ladder: most of Chronos-Bolt's win is pretrained prior, not context volume |
| EXP-023 | 2026-08-29 | parked | `w112_dqs_pct_vs_56d`=-3.05<br>`w112_dm_p_beats_56d`=1.57415e-05 | Window-length sweep: 112 days beats the production 56-day window by 3.0% quantile score, all four gates pass |
| EXP-024 | 2026-08-30 | rejected | `lean_lag168_dqs_pct_vs_lean`=2.52<br>`lean_lag168_derived_dqs_pct_vs_lean`=12.21 | Lag richness refuted: more raw lags do not recover the foundation model's context advantage |
| EXP-025 | 2026-08-29 | rejected | `transplant_band_coverage`=0.733<br>`lean_cqr_band_coverage`=0.788<br>`fm_band_coverage`=0.811 | Band transplant refuted |
| EXP-026 | 2026-08-29 | **kept** | `bolt_tiny_retention_pct`=93.5<br>`bolt_small_retention_pct`=98.3 | Model-size ladder: chronos-bolt-tiny retains 93.5% of base's advantage |
| EXP-027 | 2026-08-30 | rejected | `final_mae_delta_pct`=19<br>`final_coverage_delta`=-0.431 | Fine-tuning destroys the calibration prior |
| EXP-028 | 2026-08-29 | parked | `known_future_dqs_pct_vs_univariate`=-8.3<br>`known_future_dm_p`=0.00509474 | Covariates DO help a covariate-capable foundation model: Chronos-2 gains 8.3% quantile score from exogenous that LightGBM cannot use |
| EXP-029 | 2026-08-29 | rejected | `oos_r2_all`=-2.0031<br>`oos_r2_wind_only`=-0.0576 | Residual pre-screen: null as predicted, but the screen is invalid as a gate |
| EXP-030 | 2026-08-30 | **kept** | `chronos-bolt-base_median_s`=0.521586<br>`chronos-bolt-tiny_median_s`=0.0291883 | EXP-026 part (b) completed by proxy: CPU inference latency is a non-issue |
| EXP-031 | 2026-08-30 | **kept** | `untraceable_before`=19<br>`untraceable_after`=0<br>`numeric_metrics_checked`=241 | Documentation-integrity audit of EXP-021..030: 19 registry numbers were untraceable to any artifact; all now regenerable, and the check is automated |
| EXP-032 | 2026-08-30 | parked | — | EXP-023a Stage A: the 112-day window's advantage does NOT reproduce on unscored vintages |
| EXP-033 | 2026-08-30 | **kept** | — | EXP-021a Stage 2 latency gate discharged on the real host: chronos-bolt-base runs a 72h forecast in 1.16s on sadalsuud |
| EXP-035 | 2026-09-06 | parked | — | Every stored arm re-scored against a seasonal-naive floor: the foundation model clears it in all 9 months, no LightGBM configuration clears it in August |
| EXP-036 | 2026-09-11 | **kept** | — | The skill floor was too weak: every profile baseline beats the single-day carry, and against the best one the incumbent is 12.4% BELOW the floor |
| EXP-037 | 2026-09-11 | **kept** | — | The product lens does not rescue the incumbent: on cost regret it is WORSE than the carry it already barely beat on MAE, and the cause is amplitude collapse |
| EXP-038 | 2026-10-28 | **kept** | — | Chronos-Bolt's zero-shot win reproduces on 60 fresh vintages: 21.5% better quantile score than lean LightGBM, better calibrated, and best on cheap-hour regret at h1-48 |
| EXP-039 | 2026-10-28 | **kept** | — | Chronos-Bolt is feasible on sadalsuud: 1.2s per forecast on CPU, installs beside every pin, and no heavier error tail than lean |
