# Gotcha Log

Header markers carry entry status so a header-only scan (`grep -nE '^#{2,3} '`) is
enough to see what is still open: `[RESOLVED]` = closed, `[RESOLVED*]` = closed for
the incident with residual follow-ups named in the body, `[xN]` = recurrence count.
Markers were lifted from bodies into headers on 2026-08-26; keep new ones in the
header.

Promoted rows hold the rule and a pointer; the incident detail they carried until 2026-11-06 is in
`memory/archive/gotcha-promoted-rows-2026-11-06.md`. Keep new rows that short.

Residuals of entries archived 2026-11-06, as recorded then and not re-checked: dev/prod Python skew (situla 3.14, sadalsuud 3.12); the 2026-06-10 lightgbm install damage has no known root cause; dashboard silent-empty-state hardening is on augur#24.


### systemd timers: `Persistent=` won't replay a killed run, and a restart won't fire an elapsed `OnBootSec` (2026-11-15)
**Problem**: sadalsuud reset 12 min into the 2026-11-13 run and the day was lost despite `Persistent=true`. The fix's deploy note, following `systemd.timer(5)`, said restarting the timer would fire the new `OnBootSec` at once; on the host nothing fired.
**Root cause**: `Persistent=` tracks triggers, not completions: the trigger had fired, so nothing was missed. And systemd 255 left an elapsed `OnBootSec` unfired after a restart (`NextElapseUSecMonotonic=0`), whatever the man page says.
**Fix**: `OnBootSec=5min` plus an `ExecCondition` guard (augur#39). Smoke-test ExecCondition with a direct `systemctl start`; the boot trigger is proven only by a real boot. **Lesson: a systemd claim from the man page is a hypothesis until it's been seen on the host's version.**

## Promoted

| Date | Gotcha | Occurrences | Promoted to |
|------|--------|-------------|-------------|
| 2026-03-28 | EWM variance formula wrong | 1 — 2026-03-28 | Fixed in `ml/update.py` — now uses signed `ewm_mean` |
| 2026-03-28 | Double push of exchange prices | 1 — 2026-03-28 | Fixed in `ml/update.py` — only push ML predictions |
| 2026-06-06 | Silent-failure factory: collector orchestration needs a workflow-level quality gate, not only per-collector checks | 1 — 2026-06-06 | energydatahub repo: `.github/workflows/collect-data.yml`, `Assert data quality (no silent failures)` step |
| 2026-06-07 | EDH schema bumps need a consumer audit on BOTH sides; neither migrates automatically. Audit (a) `static/js/modules/data-processor.js` + `tab-charts.js`, (b) `ml/data/consolidate.py` parsers, (c) any other `json.load`/`fetch` of EDH files. | 2 — 2026-06-07, amended 2026-06-10 | This table; incidents in `memory/archive/gotcha-log-resolved.md`; checked 2026-11-06. |
| 2026-06-12 | rc=0 is not output quality. Assert on the output artifact at the step that owns it, and ship the assertion with its reader. | **7** — 05-08, 06-06, 06-12, 08-28, 08-31 (×2), 11-07 (24 of 72 h at rc=0), 11-08 (unset rc read as OK). **The promotion did not take.** | `scripts/daily_update.sh` post-run guards; reader: `heartbeat_check.sh` |
| 2026-07-03 | A demoted/backup component must NEVER abort or gate the production path. When demoting, audit every `set -e`, "must succeed" and import-probe site. | 2 — both 2026-07-03 (ARF under `set -e`; `DEP_PROBE` gating on `import river`) | `scripts/daily_update.sh`: ARF under `set +e` with rc in the commit subject; dep-probe is lightgbm/pandas only |
| 2026-08-28 | A freshness gate must test freshness, not a proxy: state the property positively, then ask whether the test implies it. Monotonicity is not freshness. | **3** — 2026-08-28; 2026-09-05..13; 2026-11-15 (subject match / local commit stood in for a delivered run) | `scripts/wait_for_edh.sh` content contract + clause (c); `daily_slot_done.sh`, `heartbeat_check.sh` |
| 2026-08-28 | A data-derived cursor needs an assertion on its rate AND its place: a check on the delta cannot see a constant offset (augur#34). | 1 — 2026-08-28. **The promotion took** (caught the 2026-09-04 outage recovery); limit found 2026-09-14 | `ml/shadow/update_shadow.py:classify_t0_advance` + `scripts/daily_update.sh` t0 marker; place is only probed by hand: `scripts/check_gate_lag.sh` compares report timestamps, not `t0` |
| 2026-08-25 | **Ablate before you expand.** Measure what existing features are worth before plumbing in new ones; it can invert the plan (EXP-018: removing six production features cut MAE 6%). | 2 — 2026-08-25, confirmed 2026-08-29 (EXP-020) | `scripts/exp018_stage0_ablation.py`; `docs/archive/hypothesis-log-resolved.md` [2026-08-25] EXP-018a |
| 2026-08-29 | **A tree model on a short window rejects added *level* columns, whatever their provenance.** Before proposing a feature, ask level or shape: levels are already carried by the price lags and cost skill. | **4** — EXP-019 + EXP-020 (2026-08-29), EXP-024 + EXP-029 (2026-08-30) | `experiments/registry.jsonl` EXP-019, 020, 024, 029 |
| 2026-07-03 | Loose `>=` pins + a fresh venv = an unannounced major upgrade, and pickles don't survive it. Install from a committed exact lockfile, and avoid yanked releases. Bumping river needs a warmup regen of `river_model.pkl`. | 1 — 2026-07-03 | `requirements.lock` + `scripts/bootstrap_venv.sh`; `requirements.txt` has ceilings as a backstop |
| 2026-08-30 | A number in a durable record (registry, ADR, memory) ships with the script that regenerates it, same commit (`audit_registry.py` check 4). | **4** — 2026-08-30; 2026-10-29 (paper % re-typed, wrong twice); 2026-11-08 (hand-counted vintages → `scripts/vintage_counts.py`); 2026-11-15 (EXP-042's `stage1_reading` block and 13-vintage sensitivity came from uncommitted inline scripts) | `experiments/registry.jsonl`, `scripts/posthoc_diagnostics.py` |
| 2026-08-30 | If a cheap pre-screen is meant to veto an expensive test, validate it against that test once before trusting it — EXP-029's screen would have vetoed EXP-028's true positive | 1 — 2026-08-30 | Experiment design (ADR-007) |
| 2026-08-31 | **An integrity check that makes the correct action fail is a defect, not strictness.** Enumerate the legitimate changes an immutability check must permit, give each an auditable route, and keep a hashed slice's boundary independent of what follows it. | **2** — 2026-08-31, 2026-09-10 | `scripts/audit_registry.py:PRECOMMIT_REV_BY_ID`, `method_sections`; `tests/test_audit_registry.py` |
| 2026-08-31 | **A cursor from multi-source data is bounded by the source that ends FIRST.** Derive the anchor from the intersection of availability, and name the short source in the alarm. | 1 — 2026-08-31 | `ml/shadow/update_shadow.py:latest_feasible_t0` |
| 2026-08-31 | **A monitor built for hard failures is not monitoring.** When adding alerting, enumerate the failure modes the pipeline can express and check each has a consumer. | 1 — 2026-08-31 | `scripts/heartbeat_check.sh` commit-subject marker check |
| 2026-09-06 | **A comparison harness needs an absolute floor, not only pairwise tests.** Add the cheapest baseline as a permanent arm, keep "not computed" distinct from "no edge" (null, never 0.0), and ask what the floor's own variance is: a noisy floor manufactures skill (EXP-036: +5.1% became −12.4%). | 1 — 2026-09-06; 2026-09-11 (EXP-036) | `ml/shadow/evaluate_shadow.py` naive fields; `scripts/exp035_naive_floor.py`; `docs/archive/hypothesis-log-resolved.md` [2026-09-06]; augur#29 |
| 2026-09-06 | **Audit an instrument in the direction of its bias**: a failure mode that enlarges your finding is the tell. Derive fixture shape from the code that writes the records. | **3** — 2026-09-06; 2026-09-14; 2026-10-28 (`eval_log` scored only h1_24 → `regret.py`) | `update_shadow.py` `t0_utc`; `evaluate_shadow.py:t0_for_eval_day`; `TestT0Resolution` |
| 2026-09-04 | **A data gate covers some of {presence, structure, span, values, recency}: name which, and what the list omits.** The EDH gate reads only `entsoe` and `load_forecast`, never span. | **3** — 2026-09-04; 2026-09-11 (augur#31); 2026-09-14 (augur#34) | No span check either side. EDH `wind_forecast` in `CRITICAL_FEEDS` is unmerged (`critical-feeds-wind-forecast`). Size expectation: per source, p75 (`docs/archive/hypothesis-log-resolved.md`). Issues: `memory/upstream-edh.md` |
| 2026-09-10 | **A probe whose "cannot tell" reads like its negative result will be inert and look healthy.** If a check may fail open, verify it end to end on the host that runs it, and prefer a dependency that cannot be absent. | **3** — 2026-09-10; 2026-10-29 (`audit_registry.py` check 5, see Mechanized); 2026-11-16 (check 5 again: a failed `git show` read as an absent file) | `scripts/wait_for_edh.sh:upstream_publish_failed` (stdlib, no `gh`); `tests/test_wait_for_edh.py::test_the_probe_needs_no_external_binary` |

## Mechanized

Review findings turned into a deterministic check (`review-changes` Step 3.1). `live` means a seeded positive made the check fail. Occurrences count sightings after it went live. Format: agent-ready-projects `templates/gotcha-log.md`. Rows `live` with 0 occurrences moved unedited to `memory/archive/gotcha-mechanized-live-2026-11-16.md` (the tests speak for themselves); a recurrence moves its row back with the count.

| Date | Finding shape | Check | Status | Occurrences |
|------|---------------|-------|--------|-------------|
| 2026-11-16 | A pre-committed pooled DM set `hac_lags` below the lag at which the same realised hours recur (blocks of one vintage overlap blocks of later ones) | a helper in `ml/shadow/metrics.py` that derives the minimum lag from the rows' realised timestamps, asserted by each runner <!-- placeholder --> | proposed | 1 |
| 2026-11-06 | A scripted row edit left a table with broken `> ` prefixes, invisible in the diff | Blockquote-continuity rule in `~/repos/agent-ready-projects/scripts/md-structure-check.sh` <!-- placeholder --> | proposed | 1 |
| 2026-11-16 | The default pin `PRECOMMIT_REV` is cached before the ancestry test, so an orphaned default pin passes (augur#42) | ancestry test on `PRECOMMIT_REV` in `scripts/audit_registry.py` check 5 <!-- placeholder --> | proposed | 1 |
| 2026-11-15 | A "slot done" check that reads local HEAD counts a commit that never pushed (reboot between commit and push) | `tests/test_daily_slot_done.py::test_unpushed_slot_commit_reruns` | proposed | 1 |
| 2026-11-15 | A vintage window described as "fully realised" held a 71-hour last vintage (EXP-042); the count of vintages said 14, the count of hours did not | `contexts` mode of `scripts/exp021_foundation_zeroshot.py` prints every vintage with fewer than 72 targets <!-- placeholder --> | proposed | 1 |
| 2026-10-29 | An amended or rebased pin still resolves from the reflog, so `git show` alone can't detect it | `scripts/audit_registry.py` check 5: each pin must pass `git merge-base --is-ancestor <pin> HEAD` | live (seeded orphan commit) | 1 (2026-11-16: the default pin skips it, augur#42) |
| 2026-11-07 | Heavy Python deps added to `requirements.txt` could reach the Netlify build (augur#35) | `tests/test_update_fm.py`: `test_torch_stays_out_of_what_netlify_may_install` | proposed | 1 |
| 2026-11-07 | A shadow step's `rc=N` marker read as production down in the heartbeat mail | `tests/test_heartbeat_check.py`: `test_fm_failure_is_not_reported_as_production_down` | proposed | 1 |
| 2026-11-08 | A pipeline step that never ran leaves its rc unset, and `${RC:-0}` reads it as OK | `scripts/daily_update.sh`: `[ALARM: profile forecast t0 behind shadow]` compares the artifact's `t0` with the shadow's | live | 1 |
| 2026-11-08 | Hypothesis-log Methods that gate live swaps were pinned by convention only | `scripts/audit_registry.py` check 6 (`HYPOTHESIS_PINS`, 17 Methods, both files) | live | 1 |

---

**Resolved entries live in `memory/archive/gotcha-log-resolved.md`** (moved 2026-10-16 to cut the read surface). Grep it by mechanism before filing a new entry: a recurrence of an archived gotcha is filed here with `[xN]` and a pointer to the archived one.
