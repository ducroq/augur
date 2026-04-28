# Experiment Registry

A lightweight, append-only record of ML experiments run on the Augur model. Designed to support
both day-to-day "did this work?" tracking and a future technical note or publication where each
experiment may need to be cited without re-running it.

## Format

`registry.jsonl` — one JSON object per line, sorted by `id` ascending. UTF-8, no BOM, no trailing
commas. Diffable, grep-able, easy to append.

```bash
# tail
tail -1 experiments/registry.jsonl | python -m json.tool

# filter to one decision class
grep '"decision": "kept"' experiments/registry.jsonl | python -m json.tool -

# count
wc -l experiments/registry.jsonl
```

## Schema (one entry = one line)

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | `EXP-NNN`, zero-padded, monotonic |
| `date` | string (ISO date) | yes | Day the experiment was concluded / decided |
| `title` | string | yes | One-line, human-readable |
| `hypothesis` | string | yes | What we expected to learn or improve, and why |
| `model` | string | yes | E.g., `River ARFRegressor 10-tree`, `LightGBM-Quantile` |
| `branch` | string \| null | yes | Git branch where work landed (or `main` if direct) |
| `commits` | array<string> | yes | 7-char commit hashes |
| `data_window` | object | yes | `{train_start, train_end, holdout_start, holdout_end}` ISO dates; `null` for fields N/A |
| `hyperparameters` | object | yes | Only fields varied or non-default. `{}` if defaults |
| `features` | array<string> | yes | Feature family names (e.g., `price_lags`, `solar_ghi`, `gen_nl_*_lag24h`) |
| `metrics` | object | yes | Headline metrics. Use `null` for unrecoverable values |
| `decision` | string | yes | One of: `kept`, `parked`, `rejected`, `rolled_back`, `superseded` |
| `decision_rationale` | string | yes | 1–2 sentences, why decided that way |
| `artifacts` | array<string> | yes | Paths or commit refs where outputs live |
| `references` | array<string> | yes | Pointers to ADRs, gotcha-log entries, model-progress-log dates, memory files |
| `notes` | string | no | Caveats, environment details, reproducibility gotchas |

### Decision values

- `kept` — merged to `main`, in production
- `parked` — works but not adopted; revisit later
- `rejected` — does not work; abandoned
- `rolled_back` — was deployed, then reverted
- `superseded` — replaced by a later approach

## How to add a new entry

1. Pick the next `EXP-NNN` (`tail -1 registry.jsonl | python -c "import json,sys; print(json.loads(sys.stdin.read())['id'])"`).
2. Append one line. Use `python -m json.tool --no-ensure-ascii < entry.json` to validate before
   appending. Or write the object inline with `python -c "import json; print(json.dumps({...}))" >> registry.jsonl`.
3. Commit with a message that names the experiment: `experiments: add EXP-009 LightGBM-quantile shadow`.
4. If the experiment produced figures or a results doc, drop them under `docs/figures/` or
   `docs/` and reference the path in `artifacts`.

## Example entry (annotated)

```json
{
  "id": "EXP-099",
  "date": "2026-05-15",
  "title": "Example: shorter EWM half-life for confidence bands",
  "hypothesis": "Halving EWM half-life from 24h to 12h will recover band width faster after outlier days.",
  "model": "River ARFRegressor 10-tree",
  "branch": "feat/ewm-tuning",
  "commits": ["abc1234"],
  "data_window": {"train_start": null, "train_end": null, "holdout_start": "2026-04-25", "holdout_end": "2026-05-15"},
  "hyperparameters": {"ewm_halflife_h": 12},
  "features": ["price_lags", "rolling_stats", "solar_ghi", "wind_speed_80m", "load_forecast", "calendar"],
  "metrics": {"mae": null, "ewm_std_recovery_days": 1.5},
  "decision": "parked",
  "decision_rationale": "Faster recovery confirmed but no MAE gain; not worth merging without other changes.",
  "artifacts": ["docs/ewm-tuning-results.md"],
  "references": ["docs/model-progress-log.md#2026-05-15"],
  "notes": "Run on shadow model dir; production untouched."
}
```

## Caveats

- Numbers in entries should match the source artifact (commit, doc, log). If a value is not
  recoverable, use `null` and explain in `notes` — do not invent.
- Entries are append-only. To correct an error, append a follow-up entry referencing the original
  rather than editing in place.
- This is a solo-researcher tool. If the project grows to multiple contributors, swap to MLflow
  or W&B; the JSONL can be migrated.
