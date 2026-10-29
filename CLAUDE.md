# Augur

Energy price forecasting platform for the Netherlands. Combines data from 18+ APIs (via energyDataHub), ML-based week-ahead price predictions, and an interactive dashboard for smart consumption (heat pumps, EV charging, industrial thermal).

- **Stack**: Python 3.12 (ML pipeline), Hugo + Plotly.js (dashboard). **LightGBM-Quantile multi-horizon + CQR in production** (ADR-006, promoted EXP-014 2026-05-29); River ARF kept running as a backup signal.
- **Status**: Production. Dashboard live at https://energy.jeroenveen.nl; ML pipeline runs daily on sadalsuud.
- **Repo**: github.com/ducroq/augur
- **agent-ready-projects**: v1.50.0

> Thinned 2026-10-16 from 38k chars. The per-path narrative it carried is in `docs/archive/CLAUDE-2026-10-16.md`. **Keep this file to pointers.** Status and findings live in `memory/MEMORY.md`; reasoning lives in the docs it points to.

## Before You Start

| When | Read |
|------|------|
| **Starting a session — orient first** | `memory/MEMORY.md`. It opens with the **ON "CONTINUE"** queue. Not auto-loaded; read it before reconstructing state from anything deeper. |
| **Stuck or debugging something weird** | `memory/gotcha-log.md` (Promoted patterns + open entries; resolved ones in `memory/archive/`). EDH publish late, short or missing → `memory/upstream-edh.md`. Already done? → `memory/archive/session-archive.md`. |
| **Anything touching experiments or model work** | `docs/experiment-results.md` **Decision state**: closed / live / standing evidence, generated from the registry by `scripts/render_results.py` (never hand-edit). Then `memory/model-class-findings.md`, which **opens with the EXP-036 correction that rescales every effect size here**. Log or cite → `experiments/registry.jsonl` (schema in `experiments/README.md`). Next experiment → `docs/experiment-backlog.md`. |
| **⚠️ Before quoting any effect size** | augur#29: production `p50` doesn't reliably beat a seasonal-naive floor, and against EXP-036's profile floor it sits at **−12.4%**. Every other metric here is *relative*. |
| **ML features, training, forecast logic** | `ml/shadow/` (production) and `ml/features/`, `ml/training/` (ARF). Architecture questions → `memory/ml-decisions.md`, `docs/river-arf-retrospective.md`. Any pipeline/model change → a dated entry in `docs/model-progress-log.md`. |
| **Dashboard or chart rendering** | `static/js/modules/` (ES6). Time axis: ADR-008. |
| **energyDataHub data formats** | `memory/data-formats.md` (schema v2.2 envelope, units, timezones) |
| **Deployment, build pipeline, alarms** | `docs/RUNBOOK.md`: Netlify build, `--force`, every `[ALARM:]`/`[NOTE:]` marker symptom by symptom |
| **Making or parking a decision** | ADRs → `docs/decisions/`. Provisional positions → `docs/hypothesis-log.md` (`## Open` starts with a dated trigger table; resolved entries in `docs/archive/hypothesis-log-resolved.md`). Citations → `docs/literature.md`. |
| **Session rhythm** | Before committing structural changes: `/review-changes` (tiers, guarantees and lenses in `.claude/review-profile.md`; `/code-review` is an optional extra pass for code bugs), then `python -m pytest tests/`. If `experiments/`, `docs/experiment-backlog.md`, `docs/hypothesis-log.md` or `docs/experiment-results.md` changed, also run `scripts/audit_registry.py` and `scripts/render_results.py --check` (both exit non-zero on drift). Ending a session: `/curate`. Monthly: `/audit-context`, then `/update-drift`. |

## Hard Constraints

- Never commit encryption keys or secrets — keys are base64-encoded env vars (`ENCRYPTION_KEY_B64`, `HMAC_KEY_B64`)
- Never use hardcoded +2h timezone offset — use `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'`
- Never claim tests pass without running them. Never claim a file exists without reading it.
- Always verify HMAC before decryption — data integrity is non-negotiable
- ML models must use temporal train/val/test splits, never random — time series data leaks across random splits
- The `--force` flag in `decrypt_data_cached.py` must remain in the Netlify build command — without it, webhook-triggered builds reuse stale cached data

## Decision Framework

Before completing a task, self-assess:
- **PASS**: Tests pass, constraints respected, code matches project patterns
- **REVIEW**: Touches encryption, build pipeline, data schemas, or ML model architecture — flag for human review
- **FAIL**: Tests fail, constraints violated, or approach contradicts an ADR — stop and discuss

## Architecture

```
energyDataHub (separate repo, 18+ API collectors)
    │ daily, encrypted JSON → GitHub Pages (publish time varies; ~11% of days missed)
    ▼
sadalsuud — augur-daily.timer 16:30 UTC, ExecStartPre=scripts/wait_for_edh.sh
    │   gate: content contract (newer than last consumed + entsoe ≥ p75 size) and
    │   clause (c): the report arrived WHILE waiting (augur#34). Deadline 03:00 UTC,
    │   never fail-closed.
    ├── python -m ml.update               → ARF backup signal (NON-FATAL)
    ├── python -m ml.data.consolidate     → training parquet
    ├── python -m ml.shadow.update_shadow → LightGBM: 56-day retrain, 72h predict, CQR (production)
    ├── python -m ml.shadow.evaluate_shadow → eval row (h1–24 only): vs ARF + seasonal-naive + profile floor
    ├── python -m ml.shadow.regret          → cheap-hour regret per 24h block, all 72h (product criterion)
    └── git push augur                    → Netlify rebuild
        Every alarm rides in the COMMIT SUBJECT: [ALARM: …] = fault, [NOTE: …] = result.
        Alerting: OnFailure= (unit dies) + augur-heartbeat.timer 06:00 UTC (no commit >30h,
        timer off, unpushed, ALARM/rc marker). It can't see sadalsuud itself being down.
    ▼
Netlify build: decrypt_data_cached.py --force → hugo --minify → CDN
    ▼
Browser: 5 tabs (Prices, Weather, Grid, Market, Model); augur_forecast_shadow.json
(prices) + augur_forecast.json (Model tab); live Energy Zero every 10 min.
```

**Model**: 9 LGBMRegressor (3 horizon groups × p10/p50/p90), 24 features, split-conformal bands targeting P80. `t0` comes from `latest_feasible_t0` (the last complete feature row), anchored lag-0 since 2026-09-13. Consumer price = wholesale × VAT + ARF's cached surcharge (`update_shadow.py:read_arf_surcharge`). Revert to ARF: change the path in `dashboard.js:loadAugurForecast`.

## Key Paths

| Path | What it is |
|------|-----------|
| `ml/shadow/update_shadow.py` | Nightly LightGBM retrain + predict + CQR + consumer fields; t0 selection and hold-back alarm state |
| `ml/shadow/lightgbm_quantile.py`, `features_pandas.py`, `conformal.py`, `metrics.py` | Forecaster, 24-feature builder, CQR, metric library (pinball, DM with HAC, Winkler…) |
| `ml/shadow/regret.py` → `ml/shadow/regret_log.jsonl` | Nightly k3/k6 cost regret per horizon block for p50, carry and profile; `incomplete` rows mark blocks that can never fill |
| `ml/shadow/evaluate_shadow.py` → `ml/shadow/eval_log.jsonl` | Daily eval rows. `naive_*` fields from 2026-09-06; `naive_profile_*` (EXP-036 floor) from 2026-09-11. Absent = age, not failure |
| `ml/models/shadow/shadow_state.json` | `calibration_history` (count vintages here, not in `eval_log`), CQR stats, t0 hold-back |
| `ml/shadow/secure_pickle.py` | HMAC sidecar; verify before load |
| `ml/data/consolidate.py` → `ml/data/training_history.parquet` | EDH history → training parquet (gitignored, rebuilt nightly on sadalsuud) |
| `ml/update.py`, `ml/models/state.json`, `ml/forecasts/` | ARF backup pipeline, its state (holds the surcharge cache), forecast archives |
| `static/js/dashboard.js`, `static/js/modules/` | Dashboard entry (swap point: `loadAugurForecast`) and modules |
| `decrypt_data_cached.py`, `utils/secure_data_handler.py` | Decryption with `--force` (ADR-003); AES-CBC-256 + HMAC-SHA256 |
| `scripts/daily_update.sh` | The sadalsuud job and every commit-subject marker |
| `scripts/wait_for_edh.sh` | Readiness gate. **Read its header before changing any clause** |
| `scripts/check_gate_lag.sh` | The only detector for gate lag (augur#34); run over ssh with `bash -s` |
| `scripts/heartbeat_check.sh`, `alert_failure.sh`, `notify_email.py`, `scripts/systemd/` | Alerting and the canonical units (install/rollback in its README) |
| `experiments/registry.jsonl`, `scripts/audit_registry.py`, `scripts/render_results.py` | Experiment record (EXP-001..039; EXP-040 is pre-committed in the backlog), its auditor, the generated digest |
| `scripts/exp0NN_*.py` | One runner per experiment; each docstring states its pre-commitment and host |
| `ml/shadow/expNNN_*/summary.json` | Committed experiment records. Gitignored dumps next to them are **links into `/home/jeroen/lab/augur/shadow/`**. They aren't byte-reproducible, so treat them as data |
| `scripts/link_lab.sh` | Recreates the lab links after `git clean -xfd` or in a new worktree. To adopt a new experiment's dumps, move them into the lab tree at the same relative path, then rerun |
| `docs/decisions/` | ADR-001..008 (no 005 on main; ADR-001 superseded by 008; ADR-004 by 006) |
| `tests/` | pytest suite (count is probed in `memory/MEMORY.md`) |

## Compute

- **situla** (this box): dev, CPU sweeps. **sadalsuud**: production job. **b650-gpu**: the GPU arm, a third-party machine (Arian's). Veen data there is a working copy only: pull results to `~/lab/augur`, then delete once a restic snapshot holds them. Setup trap and recipe are in the auto-memory note `gpu-tailscale-hosts`.

## How to Work Here

```bash
# Install dependencies — reproducible venv from the pinned lockfile
scripts/bootstrap_venv.sh --dev     # creates ./.venv from requirements.lock; --dev adds pytest
source .venv/bin/activate
npm install

# Set encryption keys (bash; or use a .env file the daily job sources)
export ENCRYPTION_KEY_B64="your_key"
export HMAC_KEY_B64="your_key"

# Fetch and decrypt data
python decrypt_data_cached.py --force

# Run tests
python -m pytest tests/ -v

# Dev server
hugo server -D
# Visit http://localhost:1313

# Production build
hugo --minify

# After a git clean or in a new worktree: relink the experiment data
scripts/link_lab.sh
```
