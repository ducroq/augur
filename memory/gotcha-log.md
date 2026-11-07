# Gotcha Log

Header markers carry entry status so a header-only scan (`grep -nE '^#{2,3} '`) is
enough to see what is still open: `[RESOLVED]` = closed, `[RESOLVED*]` = closed for
the incident with residual follow-ups named in the body, `[xN]` = recurrence count.
Markers were lifted from bodies into headers on 2026-08-26; keep new ones in the
header.

Promoted rows hold the rule and a pointer; the incident detail they carried until 2026-11-06 is in
`memory/archive/gotcha-promoted-rows-2026-11-06.md`. Keep new rows that short.

Residuals of entries archived 2026-11-06, as recorded then and not re-checked: dev/prod Python skew (situla 3.14, sadalsuud 3.12); the 2026-06-10 lightgbm install damage has no known root cause; dashboard silent-empty-state hardening is on augur#24.

### A rollback trap ran in the directory the script had moved to (2026-11-07)
**Problem**: On sadalsuud, the venv rebuild's `trap rollback ERR` fired after a `cd` into the rehearsal copy. Its relative `rm -rf .venv; mv OLD .venv` ran there and found nothing. Nothing was lost, by luck.
**Root cause**: The rollback used relative paths and an ERR trap that outlived the `cd`.
**Fix**: In a rollback, `cd` to an absolute path first, or use absolute paths throughout. Clear the trap before leaving the directory it protects. Also: a venv can't be renamed into place, because `activate` hardcodes `VIRTUAL_ENV`; move the old one aside and build at the final path.

### A full review battery cost ~528k tokens on a 566-line change (2026-11-07)
**Problem**: `/review-changes` ran five Opus lenses without stating a ceiling; the engineer flagged the cost. One Codex pass on the fixes cost 56k and still found a real defect.
**Root cause**: The skill's budget step was skipped, and the profile names no cheaper reviewer.
**Fix**: State the lens set and a token ceiling before spawning. Prefer fewer lenses or an outside model (`codex exec -s read-only`) when the change is mostly new code. A profile rule needs the engineer's wording.

## Promoted

| Date | Gotcha | Occurrences | Promoted to |
|------|--------|-------------|-------------|
| 2026-03-28 | EWM variance formula wrong | 1 — 2026-03-28 | Fixed in `ml/update.py` — now uses signed `ewm_mean` |
| 2026-03-28 | Double push of exchange prices | 1 — 2026-03-28 | Fixed in `ml/update.py` — only push ML predictions |
| 2026-06-06 | Silent-failure factory: collector orchestration needs a workflow-level quality gate, not only per-collector checks | 1 — 2026-06-06 | energydatahub repo: `.github/workflows/collect-data.yml`, `Assert data quality (no silent failures)` step |
| 2026-06-07 | EDH schema bumps need a consumer audit on BOTH sides; neither migrates automatically. Audit (a) `static/js/modules/data-processor.js` + `tab-charts.js`, (b) `ml/data/consolidate.py` parsers, (c) any other `json.load`/`fetch` of EDH files. | 2 — 2026-06-07, amended 2026-06-10 | This table; incidents in `memory/archive/gotcha-log-resolved.md`; checked 2026-11-06. |
| 2026-06-12 | rc=0 is not output quality. Assert on the output artifact, at the step that owns it. An assertion is done only when something reads it, so ship it with its reader. | **5** — 2026-05-08, 2026-06-06, 2026-06-12, 2026-08-28, 2026-08-31 (twice in one day). **The promotion did not take.** | `scripts/daily_update.sh` post-run guards; reader: `scripts/heartbeat_check.sh` commit-subject grep |
| 2026-07-03 | A demoted/backup component must NEVER abort or gate the production path. When demoting, audit every `set -e`, "must succeed" and import-probe site. | 2 — both 2026-07-03 (ARF under `set -e`; `DEP_PROBE` gating on `import river`) | `scripts/daily_update.sh`: ARF under `set +e` with rc in the commit subject; dep-probe is lightgbm/pandas only |
| 2026-08-28 | A freshness gate must test freshness, not a proxy. State the property positively (this publish is the one upstream made for today), then ask whether the test implies it. "Dated today" and "newer than what I have" both failed; monotonicity is not freshness. | **2** — 2026-08-28; 2026-09-05..13 (two episodes, after the promotion was removed) | `scripts/wait_for_edh.sh`: content contract + clause (c); checked 2026-11-06 (the clock floor this row used to name is gone) |
| 2026-08-28 | A data-derived cursor needs an assertion on its rate AND its place: a check on the delta cannot see a constant offset (augur#34). | 1 — 2026-08-28. **The promotion took** (caught the 2026-09-04 outage recovery); limit found 2026-09-14 | `ml/shadow/update_shadow.py:classify_t0_advance` + `scripts/daily_update.sh` t0 marker; place is only probed by hand: `scripts/check_gate_lag.sh` compares report timestamps, not `t0` |
| 2026-08-25 | **Ablate before you expand.** Measure what existing features are worth before plumbing in new ones; it can invert the plan (EXP-018: removing six production features cut MAE 6%). | 2 — 2026-08-25, confirmed 2026-08-29 (EXP-020) | `scripts/exp018_stage0_ablation.py`; `docs/archive/hypothesis-log-resolved.md` [2026-08-25] EXP-018a |
| 2026-08-29 | **A tree model on a short window rejects added *level* columns, whatever their provenance.** Before proposing a feature, ask level or shape: levels are already carried by the price lags and cost skill. | **4** — EXP-019 + EXP-020 (2026-08-29), EXP-024 + EXP-029 (2026-08-30) | `experiments/registry.jsonl` EXP-019, 020, 024, 029 |
| 2026-07-03 | Loose `>=` pins + a fresh venv = an unannounced major upgrade, and pickles don't survive it. Install from a committed exact lockfile, and avoid yanked releases. Bumping river needs a warmup regen of `river_model.pkl`. | 1 — 2026-07-03 | `requirements.lock` + `scripts/bootstrap_venv.sh`; `requirements.txt` has ceilings as a backstop |
| 2026-08-30 | If a number goes into a durable record (registry, ADR, memory), commit the script that regenerates it in the same commit — `scripts/audit_registry.py` check 4 enforces it | **2** — 2026-08-30 <br> **recurred 2026-10-29**: paper percentages re-typed across four docs, wrong twice; see the 2026-10-29 entry | `experiments/registry.jsonl`, `scripts/posthoc_diagnostics.py` |
| 2026-08-30 | If a cheap pre-screen is meant to veto an expensive test, validate it against that test once before trusting it — EXP-029's screen would have vetoed EXP-028's true positive | 1 — 2026-08-30 | Experiment design (ADR-007) |
| 2026-08-31 | **An integrity check that makes the correct action fail is a defect, not strictness.** Enumerate the legitimate changes an immutability check must permit, give each an auditable route, and keep a hashed slice's boundary independent of what follows it. | **2** — 2026-08-31, 2026-09-10 | `scripts/audit_registry.py:PRECOMMIT_REV_BY_ID`, `method_sections`; `tests/test_audit_registry.py` |
| 2026-08-31 | **A cursor from multi-source data is bounded by the source that ends FIRST.** Derive the anchor from the intersection of availability, and name the short source in the alarm. | 1 — 2026-08-31 | `ml/shadow/update_shadow.py:latest_feasible_t0` |
| 2026-08-31 | **A monitor built for hard failures is not monitoring.** When adding alerting, enumerate the failure modes the pipeline can express and check each has a consumer. | 1 — 2026-08-31 | `scripts/heartbeat_check.sh` commit-subject marker check |
| 2026-09-06 | **A comparison harness needs an absolute floor, not only pairwise tests.** Add the cheapest baseline as a permanent arm, keep "not computed" distinct from "no edge" (null, never 0.0), and ask what the floor's own variance is: a noisy floor manufactures skill (EXP-036: +5.1% became −12.4%). | 1 — 2026-09-06; 2026-09-11 (EXP-036) | `ml/shadow/evaluate_shadow.py` naive fields; `scripts/exp035_naive_floor.py`; `docs/archive/hypothesis-log-resolved.md` [2026-09-06]; augur#29 |
| 2026-09-06 | **An instrument built to test your own hypothesis must be audited in the direction of its bias.** Before trusting a result that agrees with you, ask which way each failure mode of the measurement points; a claim that makes your finding bigger is the tell. Derive test-fixture shape from the code that writes the records. | **3** — 2026-09-06; 2026-09-14 (the "two series" claim, self-caught); 2026-10-28 (`eval_log` scored only h1_24, fixed by `ml/shadow/regret.py`) | `ml/shadow/update_shadow.py` `t0_utc`; `evaluate_shadow.py:t0_for_eval_day`; `TestT0Resolution` |
| 2026-09-04 | **A data gate covers some of {presence, structure, span, values, recency}: name which, and ask what the list itself omits.** A registry of "important" inputs implies none of the rest. EDH's quality report carries no time range and the payloads are encrypted, so the gate can't assert span. It reads only `entsoe` and `load_forecast`; `wind_speed_80m` and `solar_ghi` are live features it never examines. | **3** — 2026-09-04; 2026-09-11 (augur#31); 2026-09-14 (augur#34, recency) | No span check on either side, none coming, and nothing upstream blocks one. EDH PR #64 did **not** add `wind_forecast` to `CRITICAL_FEEDS`; that sits unmerged on `critical-feeds-wind-forecast`. A derived size expectation must be per source and use a high percentile (p75 shipped); median and per-day dedup were refuted (`docs/archive/hypothesis-log-resolved.md`, "The EDH gate's derived size expectation"). Issue numbers: `memory/upstream-edh.md`. |
| 2026-09-10 | **A probe whose "cannot tell" reads like its negative result will be inert and look healthy.** If a check may fail open, verify it end to end on the host that runs it, and prefer a dependency that cannot be absent. | **2** — 2026-09-10; 2026-10-29 (`audit_registry.py` check 5, see Mechanized) | `scripts/wait_for_edh.sh:upstream_publish_failed` (stdlib, no `gh`); `tests/test_wait_for_edh.py::test_the_probe_needs_no_external_binary` |


## Mechanized

Review findings turned into a deterministic check (`review-changes` Step 3.1). `live` means a seeded positive made the check fail. Occurrences count sightings after it went live. Format: agent-ready-projects `templates/gotcha-log.md`.

| Date | Finding shape | Check | Status | Occurrences |
|------|---------------|-------|--------|-------------|
| 2026-11-06 | A scripted row edit left a table with broken `> ` prefixes, invisible in the diff | Blockquote-continuity rule in `~/repos/agent-ready-projects/scripts/md-structure-check.sh` <!-- placeholder --> | proposed | 1 |
| 2026-10-29 | An unreachable pre-commit pin skipped check 5 for **every** entry with a WARN and still exited 0 | `scripts/audit_registry.py` check 5: `CalledProcessError` is a FAIL naming the unread revision | live (seeded `deadbee`) | 0 |
| 2026-10-29 | An amended or rebased pin still resolves from the reflog, so `git show` alone can't detect it | `scripts/audit_registry.py` check 5: each pin must pass `git merge-base --is-ancestor <pin> HEAD` | live (seeded orphan commit) | 0 |
| 2026-10-29 | Run before committing, check 5 hashed HEAD only, so an uncommitted edit to a pinned Method passed | `scripts/audit_registry.py` check 5: the working-tree backlog is hashed too | live (seeded G2 30 → 25) | 0 |
| 2026-10-29 | A dated addendum that supersedes a pinned Method sat in a section check 5 never hashed, so it could be edited after results landed | `scripts/audit_registry.py` `method_sections`: `## Addendum YYYY-MM-DD to EXP-NNN` is keyed `EXP-NNN/addendum-DATE` and must be pinned | live (seeded 28 → 14 days) | 0 |
| 2026-11-06 | A pinned entry added after `PRECOMMIT_REV`, lost from the backlog, was in no key set and passed unchecked | `scripts/audit_registry.py` check 5: `PRECOMMIT_REV_BY_ID` joins the key set; `tests/test_audit_registry.py` seeds the loss | live | 0 |
| 2026-11-07 | Heavy Python deps added to `requirements.txt` could reach the Netlify build (augur#35) | `tests/test_update_fm.py`: `test_torch_stays_out_of_what_netlify_may_install` | proposed | 1 |
| 2026-11-07 | A shadow step's `rc=N` marker read as production down in the heartbeat mail | `tests/test_heartbeat_check.py`: `test_fm_failure_is_not_reported_as_production_down` | proposed | 1 |

---

**Resolved entries live in `memory/archive/gotcha-log-resolved.md`** (moved 2026-10-16 to cut the read surface). Grep it by mechanism before filing a new entry: a recurrence of an archived gotcha is filed here with `[xN]` and a pointer to the archived one.

### A known defect fell out of the index, and its cost was never measured (2026-11-06) [DEPLOYED, live check open]
**Problem**: delivered P80 coverage is well under target, and `last_cqr_q` swings hard: 72 on 10-29, 0 from 11-03, while `calibration_history` coverage fell to 0.44–0.62 on eval days 11-03..11-05 (partly filled vintages).
**Root cause**: `compute_cqr_q` (`ml/shadow/update_shadow.py`) passes the stored `p10`/`p90`, which are already CQR-widened, to `apply_cqr`. After a wide spell the scores go negative, `max(q, 0.0)` gives 0, the band collapses to raw, and the cycle restarts. EXP-015 recorded this on 2026-06-12 as a standing finding; the 2026-10-16 index rewrite did not carry it over, and EXP-025's "lean + production CQR 0.788" applies CQR once, so it is not what production ships.
**Measured**: causal replay over `calibration_history` rebuilt from committed state, 130 days 2026-06..11, all 72 horizons, 7-day window. Mean of daily coverage: delivered 0.701; same bands with q from unwidened scores (sorted `*_raw`) 0.788; no CQR 0.574. Pooled over rows: 0.703 and 0.788. Mean q 13.1 vs 23.6. `q` below 1 on 19 days vs 1. Paired gain +0.086 per day; days are autocorrelated, so no significance is claimed. Median width +17%, +24% since 09-13, Winkler level (`scripts/replay_cqr_unwidened.py --rev acb1a5b` prints the pooled figures, width, Winkler and q; the rest were one-off).
**Fix**: `unwidened_bands` in `compute_cqr_q`, merged 2026-11-06 after engineer review. Stored rows hold `*_raw` from 2026-05-29, so no backfill is needed. Verdict in `docs/hypothesis-log.md` [2026-11-06].
**Pattern**: when an index is rewritten lean, check standing defects survive as open items, not only as caveats inside experiment records.

### A rolling cap read as a count (2026-11-06)
**Problem**: The 2026-10-16 trigger table said "30 vintages" and "EXP-023a Stage B 30 of 45". The true figure was about twice that; EXP-038 used 60 on 10-28.
**Root cause**: `calibration_history` is trimmed to `MAX_HISTORY_DAYS = 30`, so any count over it returns 30. `CLAUDE.md` said to count there.
**Fix**: Count recent vintages there and older ones from `eval_log` dates. A round number equal to a constant is a cap until shown otherwise.

### Effect sizes quoted from a paper went wrong twice in one session (2026-10-29)
**Problem**: A CRPS range true for one model variant (TabPFN-3) was written as true for all three. The fix then rounded 22.5% to "23" and changed the base of a second percentage. Each was caught only by a review lens.
**Root cause**: Percentages were computed in my head from tables read once, and re-typed per doc (four files quote them).
**Fix**: Before quoting a paper's relative numbers, parse its tables and compute every quoted figure with one script, kept in the scratchpad. Re-run it over every file that quotes them after any edit. See the deep-dive's numbers in `docs/foundation-models-epf-literature-review.md`.

### A paired harness re-run on fewer arms kept the full run's row set (2026-10-28)
**Problem**: EXP-038's FM contexts read COMPROMISED at 17.5% missing, while the incumbents it was paired with trained on far fewer dropped rows.
**Root cause**: `exp021_foundation_zeroshot.py` contexts mode built its row set from a hardcoded `CTL_VARIANTS` (four variants, including `lean_residual` and its 12%-missing solar column); the incumbent re-run used `--variants full,lean`. Same window, different rows.
**Fix**: `--ctl-variants`, defaulting to the old list; EXP-038 passes `full,lean` (6.67%, matching 4,108 targets on both sides). If you re-run a paired harness with a subset of arms, re-derive every shared input from the arms actually run, and check the pair counts match before scoring.
