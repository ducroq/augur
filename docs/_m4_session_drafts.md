# M4 session drafts (2026-05-23)

**Purpose**: Pre-staged drafts of small artifacts needed during the 2026-05-23
M4 promotion-decision session. NOT to be merged as-is — these are inputs to be
pasted into their target locations after the Method numbers are filled in.

This file is itself transient; delete it as part of the 05-23 commit (or move
it to `_archive/` if you want to keep the pre-staging audit trail).

---

## A. `experiments/registry.jsonl` — EXP-011 outcome line (Path B template)

Append to `experiments/registry.jsonl` after replacing all `[FILL]` placeholders
with the values printed by `scripts/m4_method_run.py`. Validate with
`python -m json.tool` before appending (per `experiments/README.md`).

```json
{"id": "EXP-011", "date": "2026-05-23", "title": "LightGBM-Quantile shadow 14-day promotion decision (M4)", "hypothesis": "Per docs/hypothesis-log.md: LightGBM-Quantile multi-horizon model will pass plan §6 criteria (a)/(b)/(c) over a 14-contiguous-day shadow window, justifying promotion to production.", "model": "LightGBM-Quantile multi-horizon (3 horizon groups × 3 quantiles = 9 LGBMRegressor) + CQR (7-day calibration, target 0.80)", "branch": "main", "commits": ["[FILL post-commit: 7-char hash of the M4-verdict commit — backfill in a follow-up amend or note]"], "data_window": {"train_start": "[FILL: 56 days before train_end, ISO date]", "train_end": "[FILL: last realised day, typically the last eval_log row date]", "holdout_start": "2026-05-08", "holdout_end": "[FILL: last eval_log row date]"}, "hyperparameters": {"window_days": 56, "conformal_calib_days": 7, "conformal_target_coverage": 0.8, "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 20, "horizon_strategy": "horizon_as_feature_three_groups"}, "features": ["price_lags", "rolling_stats", "wind_speed_80m", "solar_ghi", "load_forecast", "calendar"], "metrics": {"n_eval_days": 14, "lgbm_mae_overall": "[FILL]", "arf_mae_overall": "[FILL]", "lgbm_mae_at_low_price_mean": "[FILL]", "arf_mae_at_low_price_mean": "[FILL]", "ratio_a": "[FILL]", "n_low_price_hours_sum": "[FILL]", "mean_band_coverage_p80": "[FILL]", "n_days_low_coverage": "[FILL]", "mean_peak_hour_ratio": "[FILL]", "promote": "[FILL: true | false from script verdict]"}, "decision": "[FILL: parked | kept | <see Path C note>]", "decision_rationale": "[FILL: 1-2 sentences. Path B template: 'Criterion (a) failed for structural reasons identified in 2026-05-18 mid-window preview: 72h aggregation means low-price slice is dominated by h>24 hours where LGBM cannot extrapolate to midday negative-price hours. n_low ≥ 50 rules out Path C (extend window). Shadow infrastructure validated and remains in tree; cron disabled pending next-bet experiment.']", "artifacts": ["docs/lightgbm-shadow-postmortem.md", "ml/shadow/eval_log.jsonl", "scripts/m4_method_run.py"], "references": ["docs/hypothesis-log.md", "docs/lightgbm-quantile-shadow-plan.md", "docs/model-progress-log.md#2026-05-18", "docs/lightgbm-shadow-postmortem.md", "memory/arf-retired.md"], "notes": "14-day window cron-effective 2026-05-08 (after the 2026-05-01..07 silent-failure recovery documented in model-progress-log 2026-05-08 entry). Per-day low-price MAEs are unweighted in (a) ratio (matches pre-committed Method exactly); see postmortem §3 if borderline. If verdict deviates from expected Path B, rewrite this entry — decision_rationale must reflect what actually happened."}
```

**Variant for Path A (promote)** — if the Method surprises and PROMOTE = True,
change `decision` to `kept`, set `promote: true` in metrics, rewrite
`decision_rationale` to reflect what carried the criteria.

**Variant for Path C (extend)** — do NOT append EXP-011 yet. Update
`docs/hypothesis-log.md` with a new review-by date and continue collecting.
EXP-011 closes only when the hypothesis closes.

---

## B. augur#13 closing comment (Path B template)

Posted with `gh issue comment 13 --body-file - <<EOF ... EOF` (or web UI). Path
B is the expected outcome per the 2026-05-18 mid-window preview.

```markdown
M4 hypothesis resolved 2026-05-23 — outcome **Path B (park)**.

**Method run** (see `scripts/m4_method_run.py` output in commit `[FILL]`):
- (a) ratio_a = `[FILL]` (threshold ≤ 0.75): `[FILL: PASS/FAIL]`; n_low = `[FILL]` (≥ 50): `[FILL]`
- (b) mean coverage = `[FILL]` (target [0.75, 0.85]): `[FILL]`; days <0.60 = `[FILL]` (<3): `[FILL]`
- (c) mean peak ratio = `[FILL]` (≤ 1.10): `[FILL]`

**Primary failure**: criterion (a). Structural per the 2026-05-18 mid-window
preview — 72h aggregation means the low-price slice is dominated by h > 24
hours where LGBM cannot extrapolate to midday negative prices. Horizon
decomposition confirms: |p50 − realized| on low-price hours was `[FILL]`
EUR/MWh at h ≤ 24 vs `[FILL]` EUR/MWh at h > 24.

**Why not Path C**: n_low = `[FILL]` ≥ 50, so the failure isn't sample-size,
it's structural. More days won't fix a model-design limit.

**Closing checklist (per this issue's Path B):**
- [x] Diagnose which alternative the data supports — see postmortem §3
- [x] Park shadow cron — shadow block commented out in `scripts/daily_update.sh` (commit `[FILL]`)
- [x] Write postmortem — `docs/lightgbm-shadow-postmortem.md`
- [x] Mark hypothesis as **resolved (refuted)** in `docs/hypothesis-log.md`
- [x] Register EXP-011 outcome in `experiments/registry.jsonl`
- [ ] Open follow-up issue for the next bet — `[FILL: link to new issue]`

ARF cron continues to drive the dashboard. Shadow code stays in tree for the
follow-up experiment.

Closing this issue.
```

**Variant for Path A** — open with "outcome **Path A (promote)**", swap the
checklist to the Path A list, and link the dashboard config-flag PR.

---

## C. `scripts/daily_update.sh` — shadow-block disable (do at runtime, not from this template)

**Do not paste a diff from this file.** The actual flags and variable names in
`scripts/daily_update.sh` (and the dynamic commit-message logic that depends on
`SHADOW_UPDATE_RC` / `SHADOW_EVAL_RC` / `SHADOW_CONSOLIDATE_RC`) drifted from
what this draft was written against. Inspect the real file on 05-23 and:

1. `cat scripts/daily_update.sh` — locate the `update_shadow` and
   `evaluate_shadow` invocations
2. Wrap each invocation in `# DISABLED 2026-05-23 per M4 outcome (Path B park).`
   plus a one-line pointer to `docs/lightgbm-shadow-postmortem.md`. Leave the
   `consolidate` step running — the parquet has other uses.
3. Set the RC variables to a sentinel the downstream commit-message logic
   already tolerates (check the existing fallback wording — `${VAR:-skip}`
   pattern or similar). If it doesn't tolerate one, update the message-building
   block to print a `"shadow=disabled"` token instead of an RC.
4. Mirror the edit on sadalsuud after committing locally (`git pull` on the
   server). Verify the next cron night runs ARF cleanly with the shadow steps
   skipped (no Healthchecks alarm, no `--shadow-dir` argparse error).

If any of this drifts in scope (e.g., the commit-message logic isn't easily
made tolerant), the conservative fallback is to leave the shadow block running
silently — its outputs aren't dashboard-consumed and ARF is unaffected.

---

## D. `docs/hypothesis-log.md` resolution edit

**Important ordering**: fill in §A's numbers FIRST, then return here. The
Resolution text below references values from the Method verdict block.

After the Method run, move the entire "[2026-04-30] LightGBM-Quantile shadow
will pass plan §6 over a 14-day window" entry to `## Resolved` and append the
appropriate variant:

### Path B (expected — refuted)

```markdown
**Resolution (2026-05-23):** Refuted. Method verdict PROMOTE = False on
criterion (a) (ratio_a = `[FILL from §A]`, threshold ≤ 0.75). Failure-mode
signal: structural — long-horizon (h > 24) low-price weakness, not sample-size
and not freshness skew. See `docs/lightgbm-shadow-postmortem.md` for full
diagnosis and next-bet seed. Path B (park) executed in augur#13.
```

### Path A (confirmed)

```markdown
**Resolution (2026-05-23):** Confirmed. Method verdict PROMOTE = True
(ratio_a = `[FILL]`, mean_cov = `[FILL]`, mean_peak_ratio = `[FILL]`). All
three §6 criteria passed cleanly with no failure-mode signal firing. Path A
(promote) executed in augur#13.
```

### Path C (extend) — do NOT move to Resolved

If criterion (a) failed with n_low < 30 (power deficit signal fired), or some
other Alternative fired in a way that argues "not enough days" rather than
"wrong model class", keep the entry in `## Open` and edit only the
**Review by:** field:

```markdown
**Review by:** [FILL: new date, typically +7 days from today]
**Extension note (2026-05-23):** Method on initial 14-day window was
ambiguous — `[FILL: which criterion, which failure mode]`. Extending to
21 days per augur#13 Path C; new threshold rerun at the updated review-by.
```

The companion entry "[2026-04-30] Live shadow MAE will be no more than 20%
worse than backtest h+1 MAE" should ALSO be moved to Resolved (Path A/B) or
extended (Path C) using `overall_lgbm_mae / 13.21` from the Method output:
ratio < 1.05 → alternative confirmed; ratio in [1.0, 1.20] → position
confirmed; ratio > 1.20 → position refuted, investigate `consolidate.py`.

---

## E. `memory/MEMORY.md` & `arf-retired.md` updates

The current `arf-retired.md` entry mentions "M4 cron-effective 2026-05-08,
9/14 rows collected as of 2026-05-18. Mid-window preview: (c) crushes, (a)
preview-failing for structural reason — expect Path B (park) at 05-22." On
05-23, update that body to record the actual outcome and shift the focus to
the next bet (or, if Path A surprised, the promotion timeline).

---

## F. Run-day order of operations

**Fill order matters**: §A → postmortem → §B → §D. §B and §D both reference
numbers that originate in §A's `metrics` block, and the postmortem §3 narrative
references the §A `decision_rationale` text. Don't paste downstream sections
before upstream numbers exist.

**Path branches**: every step below assumes Path B (expected). If the script
verdict is Path A or Path C, see the variants in §A/§B/§D — the order stays
the same, but step 8 (daily_update.sh edit) and step 11 (augur#13 close) change.

1. `cd /c/local_dev/augur && git pull` — fresh local state
2. `ssh sadalsuud "cd ~/local_dev/augur && git pull && wc -l ml/shadow/eval_log.jsonl"` —
   verify row 14 landed. If <14, **STOP**: defer to 2026-05-24 morning. Buffer
   to 2026-05-29 still intact.
3. Pull fresh eval_log and shadow_state down:
   `scp sadalsuud:~/local_dev/augur/ml/shadow/eval_log.jsonl ml/shadow/`
   `scp sadalsuud:~/local_dev/augur/ml/models/shadow/shadow_state.json ml/models/shadow/`
4. `python scripts/m4_method_run.py` — verdict block. **Save the output** to a
   scratch file or scrollback; every downstream section reads from it.
5. **Fill `docs/lightgbm-shadow-postmortem.md`** placeholders (§2 table, §3
   diagnosis, §4 Path-C-elimination, §5 metrics, §6 next-bet). The §3 primary-
   diagnosis paragraph is the most consequential prose — pause here.
6. **Fill §A** (EXP-011 metrics + train_window dates from the eval_log + decision_rationale).
   Validate the JSON line with `python -m json.tool` before appending to
   `experiments/registry.jsonl`.
7. **Fill §D** (hypothesis-log resolution text) using §A's ratio_a / mean_cov /
   mean_peak_ratio. Move the entry to `## Resolved`. Move the companion
   live-vs-backtest entry too.
8. **Apply §C** (daily_update.sh edit, inspecting the actual file — do NOT paste
   the template diff). For Path A: do not disable shadow, instead wire the
   dashboard config flag per augur#13 Path A checklist. For Path C: do not edit
   `daily_update.sh` at all.
9. **Fill §B** (augur#13 closing comment) using §A's numbers and §3's primary
   diagnosis. For Path C: skip §B, instead post an "extending window" comment
   per augur#13 Path C checklist.
10. **Update `memory/MEMORY.md` + `arf-retired.md`** (§E) with the actual outcome.
11. **Stage the single commit**, including `git rm docs/_m4_session_drafts.md`
    so the drafts file is removed *as part of* the verdict commit, not as an
    afterthought:
    ```
    git add docs/lightgbm-shadow-postmortem.md docs/hypothesis-log.md
    git add experiments/registry.jsonl scripts/daily_update.sh
    git rm docs/_m4_session_drafts.md
    git status   # final sanity check — no [FILL] strings in staged content
    grep -n "\[FILL" $(git diff --cached --name-only)  # belt-and-suspenders
    git commit -m "EXP-011: M4 verdict — [outcome]"
    ```
12. `git push`. The script's verdict-commit hash is now known; if §A's
    `commits` field still has `[FILL post-commit]`, append a follow-up
    one-line amend or note it in the next commit message.
13. `gh issue comment 13 --body-file path/to/§B-text` then `gh issue close 13`
    (Path A/B) or leave open with the new review-by date (Path C).
14. Mirror the `daily_update.sh` edit on sadalsuud: `ssh sadalsuud "cd
    ~/local_dev/augur && git pull"`. Confirm the next cron night runs clean.

**Budget**: 90 minutes wall-clock. If row 14 hasn't landed by 09:00 local on
05-23, defer to 05-24 morning — buffer to 2026-05-29 still intact.

**Hard gate before step 11**: `grep "\[FILL" docs/lightgbm-shadow-postmortem.md
experiments/registry.jsonl scripts/daily_update.sh` must return nothing.
