# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-10-28 (latest) — Live cheap-hour regret: hours 25–72 were never scored, and the profile floor ranks twice as well everywhere

**No model or forecast logic changed.** A new nightly step, `python -m ml.shadow.regret`, appends k3/k6 cost regret per 24-slot horizon block (h1_24, h25_48, h49_72) for the shipped `p50`, the carry and the EXP-036 profile to `ml/shadow/regret_log.jsonl`. It is its own step in `daily_update.sh`, and a failure rides the subject as `[ALARM: regret pass failed rc=N]`. It serves the product criterion pre-committed in `docs/hypothesis-log.md` [2026-10-28].

**Why it could not live in `eval_log.jsonl`.** A day is logged once, as soon as 24 hours are realised, so every eval row covers horizons 1–24 (`naive_min/max_horizon_h` = 1/24 on every recent row). Hours 25–72, where EXP-037 found the amplitude collapse, have never been scored live. Every live MAE or skill number quoted from `eval_log` is an h1_24 number.

**First reading** (backfilled from the committed states of 2026-10-14 and 2026-10-28; vintages with t0 ≥ 2026-09-14 where all three arms are complete; 36–38 per block; mean k6 regret, EUR/MWh):

| block | LightGBM | carry | profile | LightGBM amplitude | realised amplitude |
|---|---|---|---|---|---|
| h1_24 | 12.32 | 10.68 | 6.37 | 31.6 | 51.8 |
| h25_48 | 11.03 | 11.09 | 6.25 | 23.8 | 54.1 |
| h49_72 | 9.65 | 11.63 | 6.40 | 20.5 | 54.4 |

Descriptive, not a gate (the criterion gates a future shadow, not the incumbent). It reproduces EXP-037's mechanism live: the shipped forecast carries 40–60% of the real daily swing, and the seven-line profile floor picks cheap hours about twice as well as production in every block. Re-derive from the log: rows with `date >= 2026-09-14`, not `incomplete`, and non-null `naive_regret_k6` and `profile_regret_k6`.

**Blocks that can never complete** (a withheld or non-ENTSO-E hour) are logged once as `incomplete: true` with their slot count, 48h after the block's last hour, rather than dropped silently. 9 of 126 rows at backfill.

## 2026-09-14 — The forecast anchor moved 24h, because the readiness gate never tested freshness

**No model or forecast logic changed today**, and no production path was touched. What changed is the *meaning* of every forecast the pipeline has published since 2026-09-13, which is why it is in this log rather than only in the gotcha record.

**What prompted it.** A heartbeat mail for `[ALARM: t0 jumped 2d]` on the 2026-09-13 run. The RUNBOOK attributed that marker to "the run after an EDH skip", so the first hour went upstream. EDH had published normally on 09-12 **and** 09-13. The skip was ours.

**The mechanism.** `wait_for_edh.sh` releases when the EDH report is strictly newer than the last consumed one. That is monotonicity — it stops a publish being used twice — and it is not freshness. The unit fires 16:30 UTC; EDH publishes ~18:00–18:56 UTC. So any EDH day carrying more than one publish leaves one unconsumed, and every later run then finds it waiting at 16:30 and releases on it within seconds. A stable fixed point: seeded 2026-09-04 (four publishes), cleared by accident on 09-08 when an EDH outage forced the gate to wait, re-seeded 09-10 (two publishes), cleared again on 09-13 when augur#31's 4h short-hold delayed the run past 18:29. Five lagged nights of nine, seeded twice in seven days.

**Why no guard saw it.** `classify_t0_advance` asserts `t0` advances one calendar day per run. A uniformly-lagged pipeline satisfies that exactly. **A guard on a delta cannot see a constant offset** — and the only run that ever alarmed was the one that *recovered*, which then got blamed for the vintage the lag had been quietly costing.

**What it cost.** `t0=2026-09-13` never got a prediction set and is permanently unevaluable — the fourth such hole, and the first that was not upstream. And the anchor moved: `t0` is now `<run date +1> 21:00Z` where it had been `<run date> 21:00Z`.

**The first reading of that shift was wrong, and the correction is the useful part.** It was written up as a regime break splitting the vintage series either side of 2026-09-13. Checking rather than reasoning: `evaluate_shadow.py:t0_for_eval_day` records that `eval_day` **is** `t0`'s date, so a row is tagged by its vintage's anchor and not a delivery date. The lag never changed the *set* of `t0` values — the same daily `…21:00Z` sequence under both regimes, produced 24h earlier under lag-0. `calibration_history` confirms it is continuous with holes and no re-basing. And for a given `t0` the forecast is built identically either way: `select_training_window` and the feature row both end at `t0`, not at the wall clock. **EXP-018a / EXP-021a / EXP-028a therefore need one more vintage hole marked, not a break.**

**What genuinely changed, and it is the one thing worth deciding.** augur#30's cleared-auction block is gone *at publish time*. Under the lag, `h=1..24` covered a day whose day-ahead auction had cleared hours before the forecast was published — the "zero-latency self-test" CLAUDE.md recorded as deliberate. It was neither deliberate nor stable: it was a property of a lag nobody had noticed, and it returns silently if the lag re-seeds. Under lag-0, `h=1..24` covers a day whose auction clears roughly 16h *after* publication, so that region is now a genuine test. EXP-037's finding that the block *flatters* the scores argues for ratifying lag-0 — but it should be ratified, not inherited by accident.

**Residual, unquantified.** `apply_cqr`'s window is anchored on `t0` but populated from rows realised *by run time*, and a lag-0 run happens 24h earlier, so bands for a given `t0` may be widened from a less-complete calibration window. Band width only; point forecasts untouched. Cheap check is `last_cqr_n_calib_days` across the break — flagged on augur#19 because it points the same way as that issue's existing under-coverage symptom and would be easy to mistake for a real calibration change.

**Not fixed, deliberately.** The gate. The two candidate regimes imply opposite changes to it, so hardening it now would cement whichever one today happens to be in. Position with pinned Method in `docs/hypothesis-log.md` [2026-09-14]; augur#34. augur#25 (event-driven EDH trigger) is the structural fix — if the run is started *by* the publish there is no window in which an older unconsumed publish can satisfy the gate at all.

**Standing lesson**, recorded as recurrence #2 of the 2026-08-28 gotcha row *"a freshness gate must test freshness, not a proxy for it"* — whose own promoted fix (`MIN_PUBLISH_HOUR_UTC`) was removed on 2026-09-01, with the replacement reintroducing the same bug in a new form. Third distinct proxy this gate has used for freshness; third to diverge from it. State the property positively — *this publish is the one upstream made for today* — then ask whether the test actually implies it. Both "dated today" and "newer than what I have" are satisfiable by data that is not that.

---

## 2026-09-10 — Three detectors that were reporting success while doing nothing

**No model or forecast logic changed today.** Everything below is the pipeline's *observability* layer. It is in this log because each item is a case of an instrument that looked healthy and was inert — the failure family this project keeps rediscovering — and because one of them silently degraded a live safety property.

**What prompted it.** A heartbeat alert that never arrived. The check itself was fine: it ran at 06:04 UTC, detected the upstream stall correctly, exited 0, and then lost the email to a transient `SMTPServerDisconnected`. Pulling that thread found two more defects behind it and one in the gate.

**1. The heartbeat could silence itself for a day after a dropped send.** `LAST_EMAIL` is deliberately armed only on a confirmed send, so a degraded channel retries tomorrow. But it was never *cleared* when the fingerprint changed, so a new episode inherited the previous episode's send clock: the failed first send of a new episode read as already delivered and suppressed the next morning. Reproduced, then fixed by clearing it on the episode boundary. `TestDegradedChannel` had missed it because its episode is the first one, where `LAST_EMAIL` starts empty either way.

**2. A cycling `paste` delimiter was dropping marker types out of the fingerprint.** `paste -sd'; '` passes a *list* of delimiters applied cyclically, so markers joined with alternating `;` and space. `tr ';' '\n'` then left every second marker merged onto its neighbour's line, where the first matching rule in `marker_kinds` rewrote the whole line and discarded it. On the real 2026-09-10 commit this dropped `eval-stale` from the shape entirely:

```
actual shape          : ...,arf-forecast-short,t0-stale
with single delimiter : ...,arf-forecast-short,eval-stale,t0-stale
```

A marker type absent from the shape cannot break through an open episode, which is the entire purpose of the shape — so this was a live detection gap, not cosmetics.

**3. The EDH gate could not tell "late" from "failed", and now can.** The readiness contract answers *has a good publish landed?*, which is silent on whether one is still coming. Both outcomes spent the full window polling to the 03:00 UTC deadline. EDH's alert job opens exactly one issue labelled `publish-failure` per failed publish and closes it on recovery (#69 opened 09-07 19:51, closed 09-08 19:16 — 27s after the recovery publish), so the signal tracks tightly. The gate now reads it and gives up early with `[ALARM: EDH publish FAILED upstream — repo#N]`.

Two design points worth keeping. The reference is **this run's start**, not the last consumed report: EDH closes the issue only on the next *successful* publish, so one is routinely still open at 16:30 while tonight's GitHub-deferred run (17:50–19:30) has not begun — comparing against the last publish would abandon the wait every night until upstream recovered. And the probe can only ever *end* a wait, never start or extend one; every way of not knowing falls through to the deadline, preserving fail-open.

**The correction that matters most.** The first cut shelled out to `gh`. **`gh` is not installed on sadalsuud**, so `command -v gh` failed there and the probe returned nothing on every poll — correct fail-open behaviour, and completely inert in the only place it needed to work. It would have looked fine forever, because "no information" and "no failure" are the same output by design. Rewritten on python3 stdlib `urllib` against the public REST API — no binary, no auth, no secret — and verified end-to-end *from sadalsuud*, which returns `#70 created 2026-09-09T19:13:45Z`.

**4. A live safety property has quietly decayed, and is not fixed.** The gate derives its size expectation as the median `entsoe` point count over the last 10 publishes, so an upstream resolution change is absorbed in days rather than reading as short forever. That median is now **96, not 192** — six of the last ten publishes were half-size, and 2026-09-04 alone contributed four publishes, three of them short. The consequence is specific: this gate *earned its place* on 2026-09-04 by refusing a 06:53 UTC recovery publish whose `entsoe` held same-day prices only (96 vs 192), the day-ahead auction not having cleared. **That protection is currently absent** — a same-day-only publish tonight would be accepted as full. Position and options pre-committed in `docs/hypothesis-log.md` [2026-09-10]; not changed today because picking the estimator is a real decision, not a bug fix.

**Known limitation of the new probe, stated rather than discovered later.** EDH opens **one** issue per failure *streak*. #70 has been open since 09-09 with `updatedAt == createdAt` and zero comments, so on the second and later nights of a streak nothing is newer than our start and the gate waits to the deadline exactly as before. The probe helps on the first night of a streak — which is when a still-evaluable vintage is at risk — and not after. Making it work every night needs EDH to touch the issue per failure; asked, not yet answered.

**Upstream, for the record.** Confirmed with the energyDataHub session rather than inferred: **09-07 was genuinely ENTSO-E** (outage, their breaker opened, run exited 1, self-healed by 09-08). **09-09 was not** — NED.nl timed out on all six fetches, their collector swallowed each one and returned a truthy envelope with `data={}`, and their completeness gate scored that CRITICAL and aborted the publish of **all 19 healthy feeds**, including the `entsoe` Augur was waiting on. Their fix exists but is uncommitted and unreviewed. There is no backfill: 09-07 and 09-09 are permanently gone. Details in `memory/upstream-edh.md`.

**A fourth instrument, found while adding EXP-036.** `audit_registry.py` check 5 reported `EXP-034: Method body EDITED since pre-commit eedf7b2`. It was not edited — `method_sections` splits on `\n## ` and lets the *last* section run to EOF, so appending an entry changed the previous one's captured body. The whole diff was the `\n\n---\n` separator. This is the **second** occurrence of the promoted rule *an integrity check that makes the correct action fail is a defect, not strictness* (first: 2026-08-31, the global pre-commit revision). Fixed by normalising section bodies; all existing pins still validate.

**Backlog.** EXP-036 pre-committed (`2113e1f`, pinned): the skill floor is a single-day carry, and an averaged daily profile is the obvious strengthening. Position — against the best profile arm, `lgbm_full`'s +5.1% falls to ≤2% overall and goes negative in ≥4 of 9 months. Explicitly bounded so it cannot move augur#29 retroactively.

**Tests**: suite 310 → 329. `test_heartbeat_check.py` +5 (11→16), `test_wait_for_edh.py` +10 (15→25), new `test_audit_registry.py` (4). Of the new tests, 4+2+2 fail against their respective unfixed code; the remainder are over-correction guards that must pass both ways.

---

## 2026-09-06 — The eval harness had no floor in it: the production model does not reliably beat "yesterday, same hour"

**What prompted it.** The pipeline recovered from the 2026-08-30..09-04 EDH outage and every health signal was green — clean commit subject, `t0` held back 0.0h, coverage healing. The observation that started this was not a metric: *the dashboard still isn't producing useful forecasts.* It wasn't, and nothing in the project could have said so.

**The structural blind spot.** Every instrument here is **relative**. `eval_log.jsonl` scores LightGBM against ARF; `experiments/registry.jsonl` scores variants against production; `metrics.diebold_mariano` compares two candidates. The case where *every arm is worse than a trivial baseline* is invisible to all of them — it reads as a healthy log with a clear winner. Two models racing each other to last place look exactly like progress.

**Measurement 1 — the live record.** Horizon-matched, production `p50` vs seasonal-naive ("same clock hour, last day available at t0") on identical timestamps from `calibration_history`, 24 eval days, `t0 ∈ [2026-07-30, 2026-08-24]`:

| horizon | n | LGBM p50 | naive | winner |
|---|---|---|---|---|
| 1–24h | 576 | 26.92 | **23.34** | naive |
| 25–48h | 576 | 33.87 | **28.94** | naive |
| 49–72h | 552 | 36.92 | **32.71** | naive |

Over 96 mixed-horizon eval days back to 2026-05-08 the model leads on 42 — **44%**.

**Measurement 2 — EXP-035, the offline vintages, and a correction to measurement 1's reading.** Re-scoring every stored EXP-018/EXP-021 arm against the same floor on 260 vintages (2025-12-05..2026-08-21), no GPU and no fresh vintages consumed — ADR-007 layer 2:

| arm | MAE | naive | skill | DM p |
|---|---|---|---|---|
| chronos_bolt_base | 22.72 | 30.31 | **+0.250** | <1e-6 |
| lgbm_drop_rolling | 27.07 | 30.31 | +0.107 | 3.2e-5 |
| lgbm_full (production) | 28.76 | 30.31 | +0.051 | 0.033 |
| lgbm_drop_calendar | 30.82 | 30.31 | −0.017 | 0.720 |

**"Never better than a coin flip" was too strong.** Across the full year LightGBM does edge naive, by 5%. The true statement is narrower and worse: the edge is **regime-dependent**, and it collapses where a forecast is actually worth having. `lgbm_full` is below naive in 2 of 9 months, and in **August 2026 — the regime the live pipeline is in — all eight LightGBM variants are below naive** (best `drop_rolling` −0.104). Chronos-bolt-base is above naive in **9 of 9 months** and at every horizon group.

**The correction runs against the incumbent, not for it.** EXP-021's headline −20.3% QS was measured against a model barely above a free baseline, so the model-class gap is *larger* than the registry states. This is the reverse of the usual direction a caveat travels, and worth saying out loud.

**Shipped.** `evaluate_shadow.py` logs six new fields per row (`n_naive_hours`, `naive_mae`, `lightgbm_mae_on_naive_hours`, `lightgbm_skill_vs_naive`, `naive_min/max_horizon_h`). The baseline may only read `24*ceil(h/24)` hours back — for a 72h vintage always the single window `[t0-23h, t0]`. LGBM is re-scored on only the paired hours, so a gappy baseline cannot manufacture skill. Any unusable input leaves the fields **null, never 0.0**: "not computed" must not read as "no edge", which is the exact ambiguity that hid this for four months.

**A bug the code review caught, worth recording because of its direction.** The first implementation inferred the anchor as `min(timestamp) - 1h` over `calibration_history` — which holds **realised rows only** (`backfill_realized` never promotes unrealised or non-ENTSO-E hours). A vintage whose *leading* hours were withheld would infer an anchor too late and source prices from after the true `t0`. That leak biases skill **downward — toward the very conclusion the field exists to test.** Fixed by recording `t0_utc` at prediction time (`update_shadow.py` step 7) and refusing to score rather than infer when it is absent and the leading hours are gone. Two related lessons: my test fixtures were day-aligned rather than production-shaped (72 rows spanning three dates, all tagged with t0's date), which is *why* it passed CI; and I had described the guard in the pre-committed Method as "pinned" by a test that hands the true `t0` in as an argument and can therefore only ever check arithmetic. Both corrected before any `naive_*` row landed — the only window in which editing a Method is legitimate under ADR-007.

**Not done, deliberately.** The first ~24 forecast hours predict a day-ahead auction that clears ~4h *before* the run starts, and `api-client.js:226` already fetches those published prices for today, tomorrow and the day after. `data-processor.js:256` draws the forecast line across them anyway, so the chart shows a ~27 EUR/MWh error on top of the correct answer. That is a **product** change, not a model finding, it needs its own pre-commitment, and it hinges on whether EDH's file already carries tomorrow's prices — unverifiable on a box without decryption keys. Filed as augur#30 (the skill-floor verdict itself is augur#29).

**What this does not change.** Nothing is deployed differently. EXP-035 is `parked` (matching EXP-022's treatment of a mechanism diagnostic): no calibration guardrail is evaluated and ADR-007 requires one for a swap. It discharges neither EXP-018a nor EXP-021a — both remain gated on 14 fresh vintages, **7 counted 2026-09-06**. The live verdict is pre-committed in `docs/hypothesis-log.md` [2026-09-06] on ≥21 rows carrying non-null `lightgbm_skill_vs_naive`, ≈2026-09-27.

**Tests**: `TestT0Resolution` (6), `TestNaiveSourceTimestamp` (6), `TestLoadPriceHistory` (4), `TestNaiveSkillInRow` (9). Suite 285 → 310.

---

## 2026-08-31 — Production model down a night: t0 followed the longest feed, not the shortest

**What happened.** The 2026-08-30 nightly run crashed inside `predict_72h` with `No clean feature row at t0=Timestamp('2026-08-31 21:00:00+0000') (NaNs in lags)`. `shadow rc=1/eval rc=skip`. No forecast was written, the dashboard served 2026-08-29's forecast for ~24h, and the 2026-08-30 vintage is permanently lost. `shadow_state.json` was untouched (`last_t0` still `2026-08-29T21:00`) because the crash preceded the state write — nothing was corrupted.

**Root cause: the feeds do not share a horizon, and t0 assumed they did.** EDH publishes each feed independently. Measured across the last ten publishes:

| publish | price | load |
|---|---|---|
| 08-20, 08-21, 08-24 16:32, 08-25 | 48h | **48h** |
| 08-26 16:44 | 46h | 48h |
| **08-30 19:02** | **48h** | **24h** |

`load_forecast` halved to 24h while price stayed at 48h. **Corrected 2026-08-31 after the energyDataHub session decrypted the publish**: this was *not* an EDH collector change. The request window was unchanged at 48h and the envelope still declared `end_time 2026-08-31T23:59:59+02:00`; ENTSO-E returned A44 day-ahead prices for 08-31 but not A65 day-ahead load, following a total 503 outage on 08-29 that made EDH's 08-30 run its first success after the gap. The divergence is transient outage residue upstream of EDH. **Augur's exposure, however, was structural and would have fired on any future divergence.** `update_shadow.py` anchored `t0 = parquet["price_eur_mwh"].dropna().index.max()` — the *longest* column — while `predict_72h` needs *all five* feature columns at t0. t0 landed 18h past the end of load. Matched horizons are the only reason this had never fired.

The upstream trigger deserves recording too: EDH's 08-29 publish came at 00:20 UTC, an overnight catch-up that `MIN_PUBLISH_HOUR_UTC=12` correctly refused, so the 08-29 run timed out its gate and ran on stale data with a short price horizon (t0 = 08-29). The 08-30 run then caught up two days at once. The `t0 jumped 2d` alarm fired correctly.

**Fix** (`87ed30c`): `latest_feasible_t0` returns the last timestamp at or before `price_t0` with a complete feature row, plus the names of the columns whose coverage ends early, and `run_shadow_update` logs `ALARM: t0 held back Nh ... short feeds: ...`. Verified on the live parquet: anchor moves 08-31 21:00 → **08-31 03:00**, held back 18h, short feeds `load_forecast, wind_gen_forecast_mw, solar_gen_forecast_mw`, feature row clean. Deployed; tonight's run will produce a forecast.

**Three things the fix explicitly does not do**, recorded because each is a tempting misreading:
1. **It does not recover the 08-30 vintage.** The held-back anchor is still two calendar days on from the last good run, so `t0 jumped 2d` still fires. A test whose name implied otherwise was reworded before it landed. The fix stops the crash; it does not resurrect data.
2. **It does not touch the feature set.** Dropping `load_forecast` is the obvious move — EXP-018 measured the exogenous trio inert at ±0.4% MAE — and it is exactly what **EXP-018a** decides ~2026-09-07. Letting an incident fix pre-empt a pre-committed experiment would contaminate it. The feature stays.
3. **It does not fix the upstream truncation**, which is EDH's to restore; filed as **energydatahub#51** with the publish-by-publish horizon table (caveated: one publish observed, may be transient). The forecast horizon stays short by the hold-back while the feed is short, so the dashboard shows a forecast partly anchored in the past. That is the intended degradation.

**Cost to the September schedule.** One vintage (08-30). EXP-018a needs 14 consecutive vintages from `t0 >= 2026-08-25`; this pushes its earliest date and, with EDH already skipping ~11% of days, makes the "only if no day is missed" caveat materially more binding.

**The alerting, one day old, missed it — and that is the more useful lesson.** See the 2026-08-31 alerting entry in `memory/gotcha-log.md`: `OnFailure=` covers a unit that dies, the heartbeat covers a run that never commits, and this was a third mode — completed, committed, exit 0, `shadow rc=1` in the subject. Coverage had been scoped to the failure that motivated the work instead of to the failure modes the pipeline can express. The heartbeat now reads the commit subject for alarm markers, and the alert email now carries the run log instead of a journal that structurally cannot hold script output (`da57139`, `c9c113e`).

**Tests**: `TestLatestFeasibleT0`, 7 cases. Suite 234 → 241.

---

## 2026-08-30 — Failure alerting built: the OnFailure gap, and the larger gap OnFailure cannot see

**Context.** `OnFailure=` alerting on `augur-daily.service` was parked 2026-07-03 as a monitoring nicety. It stopped being one on 2026-08-29: EXP-018a, EXP-021a and EXP-028a are all gated on an *uninterrupted* run of fresh vintages from `t0 >= 2026-08-25`, so a silent freeze no longer costs a day of dashboard data — it costs a week of the September schedule, unrecoverably (there is no backfill; a reconstructed vintage built from fresher exogenous is not comparable with the live ones beside it — augur#14).

**The gap, stated precisely.** Every in-script alarm the pipeline has — `ARF FAIL rc=N`, `DEP_MARKER`, `SMOKE_MARKER`, the ARF-forecast-<24h and eval-stale guards, and the `t0` stale/jumped markers added 2026-08-28 — surfaces *in the daily commit subject*. That is a good channel for a run that finishes. It is no channel at all for a run that dies first, which is exactly the 2026-06-29 → 07-03 shape: five consecutive nightly failures, zero notification, discovered only when someone noticed missing `Daily update` commits on origin/main.

**The second gap, which is the one worth recording.** Adding `OnFailure=` closes the *hard-failure* case and nothing else. `daily_update.sh` ends with

```bash
git diff --cached --quiet && echo "No changes to commit" || { git commit ...; git push; }
```

so a run that stages nothing prints a line, **exits 0, and the unit succeeds**. The vintage is lost and `OnFailure=` structurally cannot fire. The same holds for a timer that got disabled and for a box that was down at 16:30 UTC. Alerting only on unit failure would have produced a monitor that looks complete on paper and stays silent through a realistic subset of the failures it was built for.

**What shipped** (all in the repo; deployment to sadalsuud is a separate step):

1. **`scripts/notify_email.py`** — stdlib-only sender reading `[email_credentials]` from FluxusSource's gitignored `secrets.ini` on sadalsuud. Deliberately **no new notification service** (engineer's call, 2026-07-17); this is the channel `nexusmind-alert@.service` on the same host already uses. Missing or incomplete creds degrade to log-only and still exit 0 — an alerter that throws inside systemd's failure handling only adds noise. `AUGUR_NOTIFY_SECRETS` overrides the path so a dev-box dry-run cannot send a real email.

2. **`scripts/alert_failure.sh` + `scripts/systemd/augur-alert@.service` + `augur-daily.service.d/alert.conf`** — the hard-failure path. A drop-in rather than an edit to `augur-daily.service`, so it detaches without touching the `ExecStartPre` gate ordering declared there (the convention `nexusmind.service.d/alert.conf` already sets on this host). Runs as `jeroen`, not root: it needs only the journal (`adm` group) and `secrets.ini` (owner, mode 600), and root would leave root-owned files in `logs/`. 3h burst guard, armed **only after a confirmed send** — a skipped or failed email must not silence the next real alert. The email names *hypotheses* for the failure (git pull/commit/push, venv outside the dep probe, disk, the 5h30m unit timeout) and explicitly excludes the `set +e` steps, which cannot land there; a hardcoded "most likely cause" is what misdiagnosed the first NexusMind version.

3. **`scripts/heartbeat_check.sh` + `augur-heartbeat.{service,timer}`** — the silent-success path. 06:00 UTC daily: alarms if the newest `Daily update` commit is older than 30h, if `augur-daily.timer` is not enabled and active, or if commits sit unpushed (Netlify never rebuilt). The threshold and hour are chosen together: a healthy run commits ~18:30–21:00 UTC, so at 06:00 a good state is ~10h old and a *single* missed day is ~34h — one silent miss alarms the next morning, and a legitimately late run never does. It exits 0 when it *sends* an alert, reserving its own `OnFailure=` for a broken watchman.

**Accepted blind spot, recorded rather than papered over:** the heartbeat runs *on* sadalsuud, so it cannot report sadalsuud being down. Closing that requires an off-host dead-man's switch — a new service, which is the thing that was declined. The residual exposure is "box down through 06:00 UTC", which is also the case where the daily commits stop, i.e. the pre-existing manual signal still applies.

**Tests**: `tests/test_notify_email.py`, 12 tests on the credential layer and the exit contract — every degraded state produces a readable skip and exit 0, never an exception, never a silent success. SMTP itself is not exercised; the tested boundary stops at the socket.

**What was NOT changed**: `daily_update.sh`, `wait_for_edh.sh`, `augur-daily.service`, `augur-daily.timer`, the model, and the forecast path. The alerting attaches entirely through a drop-in and a new independent timer.

---

## 2026-08-30 (later) — Follow-through: two confirmations pre-committed, one already fails, and the latency gate is discharged for real

**EXP-023a and EXP-028a pre-committed** before the fresh-vintage windows open, because writing confirmation gates after the data lands is not a pre-commitment. EXP-023a's design states its power problem openly: the discovery effect is 3.0%, so matching EXP-018a's power needs ~7× the vintages, and the fresh-vintage bar is therefore set at **1.5%**, not the in-sample 3.0% — demanding zero shrinkage on an underpowered sample is a coin flip dressed as a test.

**A feasibility defect, caught before it could contaminate anything.** EXP-023a's Stage A range turned out to be unrunnable: `load_frame_ext` drops rows on the EXP-020 fundamentals columns (which start 2025-12-01), so the *feature frame* begins 2025-12-02, not the parquet's 2025-09-28. The earliest 112d-usable `t0` is 2026-03-24, and the pre-committed range yielded zero vintages. Corrected in a dated addendum with the four Stage B gates untouched. **The same error means EXP-023's discovery window was `2026-05-19..2026-08-21` — three months, May–August — not the "Mar–Aug" recorded** in the registry, CLAUDE.md, memory and this log. Corrected everywhere; the registry correction rides in EXP-032 since that file is append-only.

**EXP-032 — Stage A does not reproduce.** On the 56 vintages a 112d window can reach that the discovery sweep never scored: **112d is 1.4% *worse* than 56d** (QS 12.50 vs 12.32, DM p=0.8935), with 56d also better on coverage both sides and on Winkler. Against a discovery estimate of −3.0%, **the sign flipped**. EXP-023a's Alternative 1 (regime artifact) is the reading this supports — 112d wins in the May–Aug rising-price stretch and loses in calmer Mar–May, consistent with a longer window helping only when the level trends. Stage A is a *quasi*-holdout and the pre-commit says it informs rather than gates, so EXP-023 is **not** formally refuted — but the 112-day window is no longer a cheap near-certain win, and it drops off the top of the live-decisions list. Stage B (≥45 fresh vintages, ≈2026-10-09) is now the test that decides it.

This is the pre-commit doing its job inside an hour: had the confirmation gates been written after Stage A, the temptation to reframe a sign flip as "regime-conditional, still promising" would have been considerable.

**EXP-033 — the latency gate is discharged on the real host.** torch installed into an **isolated** venv on sadalsuud (`~/augur-latency/.venv`, uv managed CPython, torch 2.13.0+cpu), never the one the nightly job uses; no production dependency, unit, timer or data path touched. Measured: tiny 0.11s, mini 0.22s, small 0.46s, **base 1.16s** median (max 1.17s) for one 1343-point / 72h forecast on 4 threads. That is ~52× headroom on EXP-021a Stage 2's 60s gate. EXP-030's proxy understated by 2.2×, inside the 3–5× band it predicted, so the proxy was sound. Stage 2's *other* half — per-vintage MAE tail risk and the torch footprint — remains open.

**Status**: nothing shipped, no production model path touched. `experiments/registry.jsonl` EXP-032, EXP-033.

---

## 2026-08-30 — EXP-031: documentation audit found 19 untraceable numbers; the check is now automated

**Trigger**: a direct question — was the experiment documentation actually done right, and can that be shown rather than asserted?

**One real defect.** 19 of 241 numeric metrics across EXP-021/022/025/030 could not be traced to any committed artifact. None was invented — every one recomputed to the exact recorded value — but 16 came from throwaway inline analyses whose outputs were never saved. Among them were the per-tau pinball decomposition and the signed-bias panel that *corrected EXP-021's stated mechanism*, so the numbers that overturned a claim were themselves unverifiable. This is the failure `experiments/README.md` names directly ("numbers should match the source artifact ... do not invent") and the same class as leaving results in `/tmp`. Remediated by `scripts/posthoc_diagnostics.py`, which regenerates all 16 into two committed `diagnostics.json` files, every value reproducing identically; the remaining 3 are arithmetic derivations, each verified and whitelisted with its formula. **Untraceable is now 0 of 241.**

**Confirmed clean.** Schema on all session entries; id order and uniqueness across the registry; artifact existence; and all seven pre-committed Method bodies **sha256-identical** between `4024420` and HEAD, proving no Method was edited after its result landed.

**Two pre-existing issues surfaced, neither introduced nor fixed here**: eight older entries (EXP-008..020) carry empty `commits[]`, and five annotate artifact paths as `file.md (note)` — the auditor now strips the annotation and verifies the base path rather than silently rewriting older entries.

**A second gap, found on re-check and fixed the same day**: the backlog's own promotion rule (copy each entry into `hypothesis-log.md` before running) was skipped for all seven batch-run experiments, leaving that log with no trace of them. A consolidated Resolved entry now records the arc, and the rule has been amended — dated and reasoned — to cover batch runs via the git-pinned Method plus the auditor's sha256 check.

**Status**: `scripts/audit_registry.py` runs five checks and exits non-zero on failure, so `/curate` can gate on it instead of trusting a claim. No model or production path touched.

---

## 2026-08-30 — EXP-024 and EXP-027: the last two backlog experiments, both refuted, both informative

Completes the backlog written on 2026-08-29 (`4024420`). Both Methods were fixed before the data existed and neither was edited.

### EXP-024 — more raw lags do not recover the FM's context advantage

| variant | nfeat | MAE | QS | dQS% | cov_lo | Winkler | DM p |
|---|---|---|---|---|---|---|---|
| lean | 15 | 26.66 | 9.51 | 0.0 | 0.811 | 150.9 | — |
| lean_lag24 | 33 | 26.98 | 9.66 | +1.6 | 0.812 | 153.9 | 0.9979 |
| lean_lag168 | 37 | 27.34 | 9.75 | +2.5 | 0.813 | 154.8 | 1.0000 |
| **lean_lag168_derived** (control) | 37 | 29.17 | 10.67 | **+12.2** | 0.780 | 172.1 | 1.0000 |

Position refuted — raw lags cost rather than help, so Alternative 1 ("dilution is about dimensionality per se") is supported. **But the dimensionality-matched control turns a flat negative into a decomposition, which is exactly why the pre-commit made it load-bearing.** At *identical* width (37 vs 37), raw lags cost +2.5% and derived columns cost **+12.2%** — a ~5× difference — and the derived arm additionally breaks coverage (0.780 vs 0.811) and Winkler (172.1 vs 150.9) where the raw-lag arm holds both. So **count and kind both matter**: pure dimensionality costs ~2.5pp, and making those same-count columns smoothed/derived costs a further ~9.7pp.

The consequential result is the negative one. **The ~8 percentage points EXP-022 attributed to context volume are not recoverable by widening the incumbent's feature vector.** The bottleneck is not the feature row's width but the model class's ability to consume a long context — which strengthens the model-class reading and removes the cheapest hoped-for alternative to it. This is also the fourth independent confirmation of the EXP-019/020 dilution mechanism (after EXP-019 internal rolling mean, EXP-020 exogenous gas, EXP-029 residual-regression level columns) and the first to isolate it from dimensionality by construction.

### EXP-027 — fine-tuning destroys the calibration prior, and buys nothing

| checkpoint | MAE | ΔMAE% | band cov | Δcov | width | Winkler |
|---|---|---|---|---|---|---|
| step 0 (zero-shot) | 26.75 | 0.0 | 0.825 | — | 85.5 | 138.2 |
| step 250 | 30.13 | +12.6 | 0.488 | −0.337 | 43.3 | 179.1 |
| step 1000 | 30.47 | +13.9 | 0.443 | −0.382 | 40.0 | 193.6 |
| **step 4000** | **31.85** | **+19.0** | **0.394** | **−0.431** | 33.9 | 218.5 |

The Position predicted a **dissociation** — point skill up, calibration down. The calibration half is confirmed roughly nine times over (−0.431 against a predicted −0.05) and the *mechanism* is visible precisely as described: median band width collapses 85.5 → 33.9, i.e. the model overwrites a broad pretrained spread prior with a narrow single-series one and becomes wildly overconfident. **The skill half is refuted**: MAE gets 19% worse, not 5% better. There was nothing to buy in exchange.

Alternative 2 confirmed: the corpus is far too small. Only **3578 hourly points** exist before the 2026-02-28 cutoff — the pre-commit's ~7900 estimate was the *full* parquet, not the pre-cutoff half — giving ~2490 distinct window starts against 32 000 sampled windows, ~13× repetition. **Verified as overfitting, not a broken optimiser**: training loss fell steadily 10.74 → 5.69 (binned means, −45%) while held-out MAE rose 19%. Even the first checkpoint at 250 steps has already destroyed calibration, so it is not a schedule-length artifact.

**Operational conclusion: zero-shot is the deployment mode for this asset.** EXP-021's Alternative 4 ("fine-tuning is the real bet") is closed.

**Scope limit, recorded because it bounds the conclusion:** this tests *naive* fine-tuning — fixed lr=1e-4, no schedule, no validation split, no early stopping, no checkpoint selection. The pre-commit fixed the leakage discipline and the checkpoint grid but not a recipe, and no recipe search was run. A careful recipe with early stopping would very likely land between step 0 and step 250 and could plausibly avoid the collapse. What is established is that the corpus is far too small for the naive approach.

### EXP-030 (EXP-026 part b) — CPU latency is a non-issue

| checkpoint | params | median | max |
|---|---|---|---|
| bolt-tiny | 8.7M | 0.03s | 0.03s |
| bolt-mini | 21.2M | 0.06s | 0.06s |
| bolt-small | 47.7M | 0.13s | 0.13s |
| bolt-base | 205.3M | **0.52s** | 0.52s |

One 1343-point / 72h forecast on 4 pinned threads. Against EXP-026's own 10s gate the *base* model has ~19× headroom; against EXP-021a Stage 2's 60s gate, ~115×. Combined with EXP-026's skill result (tiny retains 93.5%), the "205M-parameter model in the nightly path" objection dissolves twice over — the small checkpoint is nearly as good *and* the large one is already fast enough. **Deployment cost is dominated by the torch dependency footprint, not inference time.**

**This is a proxy and does not discharge EXP-021a Stage 2.** The pre-commit requires measurement on the host that would run it; sadalsuud is production, has no torch, and installing a deep-learning stack there is a production change that was not authorised. Measured on b650-gpu (Ryzen 7 9700X, Zen 5 desktop) pinned to 4 threads to match sadalsuud's core count (Ryzen 3 5300U, Zen 2 mobile) — core count matches, per-core throughput does not, so these are a **lower bound**. What makes the proxy adequate here is the *margin*: 19–115× is far larger than any plausible Zen2-mobile-vs-Zen5-desktop gap (~3–5×), so the conclusion survives pessimistic scaling. Had it landed near the gate it would have been uninformative. Filed as its own registry entry rather than edited into EXP-026, which was already committed.

**Status**: nothing shipped, no production path touched. The 2026-08-29 backlog is now fully executed (EXP-023/024/025/026/028/029 + EXP-027), all seven `parked` or `rejected` except EXP-026's skill half. Full numbers in `experiments/registry.jsonl`.

---

## 2026-08-29 (overnight) — Five backlog experiments run: a longer window works, covariates work in the right model class, and the calibration claim needed correcting

**Setup**: EXP-023..029 were pre-committed in `docs/experiment-backlog.md` at commit `4024420` *before* any of them ran, so the Methods below are fixed-before-data by git rather than by assertion. Compute moved to `b650-gpu` (jwasys): a second venv (`~/augur-run`) pinned to `requirements.lock` exactly. **Before any sweep result was trusted, a 56-day validation rung on that box reproduced situla's EXP-020 `lean` predictions bit-identically across 14 901 overlapping cells** — environment parity verified, not assumed.

### EXP-023 — a 112-day window beats production's 56 (all four gates pass)

| window | ntrain | MAE | QS | dQS% | cov_lo | cov_hi | Winkler | DM p |
|---|---|---|---|---|---|---|---|---|
| 28 | 654 | 33.22 | 11.80 | +5.2 | 0.817 | 0.751 | 184.9 | 0.9999 |
| **56 (production)** | 1308 | 32.37 | 11.22 | 0.0 | 0.857 | 0.761 | 173.2 | — |
| 84 | 1963 | 31.63 | 11.07 | −1.4 | 0.864 | 0.771 | 173.0 | 0.0456 |
| **112** | 2634 | **31.26** | **10.88** | **−3.0** | 0.877 | 0.776 | 169.4 | **0.0000** |
| 168 | 3943 | 31.34 | 10.94 | −2.5 | 0.876 | 0.799 | 171.3 | 0.0139 |

An inverted U with a genuine interior optimum, so Alternative 2 (monotone to the data limit) is refuted. All four gates pass at 112d. But the Position's stronger 5% claim is **not** met, and its *mechanism* is **not** supported: the gain is near-uniform across quantiles (p10 −3.6%, p50 −3.5%, p90 −1.8%), not tail-concentrated, so "the quantile heads are sample-starved" is not what the window buys. Parked, not shipped: 112d is the best of five rungs picked on the discovery window — the exact selection bias EXP-018a exists to guard against.

**The confound control cost more than the pre-commit predicted** — it estimated ~150 usable vintages, actual is **95**, because the parquet starts 2025-09-28 and a 168d window needs 168 days of pre-history. The evaluation window is therefore **2026-05-19..2026-08-21** — three months, May–August. (Corrected 2026-08-30: this entry originally said "Mar–Aug". The feature frame starts 2025-12-02, not the parquet's 2025-09-28, because `load_frame_ext` drops rows on the EXP-020 fundamentals columns, pushing the earliest 168d-usable t0 to 2026-05-19.) The rule was pre-committed and followed unchanged, but the result should not be assumed to hold in calm months.

### EXP-025 — the transplant fails, and it forces a correction to last night's calibration claim

Transplanting Chronos's spread onto the incumbent's median reaches band coverage **0.733**, below the 0.76 gate, at 20% worse QS than the full FM. Position refuted; the prior is not cleanly separable from the median it was fitted alongside.

**The important result is Alternative 3.** Production CQR on the incumbent reaches band coverage **0.788** — better than the transplant and close to the FM's 0.811. **This materially deflates the calibration framing in EXP-021/022 and in CLAUDE.md**, which quoted the incumbent at 0.611. That figure is *pre-conformal*, and production does not ship a pre-conformal band. The honest live comparison is **FM 0.811 vs lean+CQR 0.788**, a gap of 0.023 rather than 0.200. The FM's remaining calibration edge is one of **efficiency, not coverage**: it reaches 0.811 at median width 73.4 where CQR needs 89.2 for 0.788 (Winkler 119.8 vs 148.9). Arm D used the *charitable* one-shot CQR rather than production's widened-band feedback loop, so this refutes Alternative 3's optimistic reading more strongly than a faithful replication would. This discharges EXP-021a's Alternative 4.

Alternative 2 also fires: a median blend at **w=0.80** toward the FM scores QS 7.756 vs the FM's 7.864 (−1.4%, DM p=0.0042), so ensembling does beat the FM alone once the weight is not fixed at the 50/50 EXP-021 tried. `w` was chosen in-sample and means nothing until confirmed out-of-sample.

### EXP-029 → EXP-028 — the pre-screen was wrong, and its own pre-commit is why we found out

EXP-029 predicted a null and got one: residual OOS R² = **−2.00**, correction makes MAE 79% worse, gates say *do not promote EXP-028*. Its failure is cleanly monotone in level columns — R² −2.00 (all covariates) → −0.41 (no levels) → −0.058 (wind only), with `gas_ttf` and `temperature` the top features of the worst model. That is a **third independent confirmation** of the EXP-019/020 mechanism, now in a third estimator.

EXP-028 was run anyway, because the pre-commit's Alternative 3 said in advance that a null here is *evidence against, not proof of absence*. It found the opposite:

| arm | MAE | QS | dQS% vs c2-univariate | band cov | DM p |
|---|---|---|---|---|---|
| c2_univariate | 23.10 | 7.96 | 0.0 | 0.803 | — |
| **c2_known_future** | **21.14** | **7.30** | **−8.3** | 0.742 | **0.0051** |
| c2_all (+gas) | 21.24 | 7.37 | −7.4 | 0.749 | 0.0177 |
| bolt_base | 24.41 | 8.40 | +5.5 | 0.870 | 0.9980 |
| lean / full LGBM | 32.89 / 34.58 | 11.31 / 12.46 | +42 / +57 | 0.619 / 0.618 | 1.0000 |

**Augur's first positive exogenous result.** It qualifies EXP-020's standing conclusion precisely: exogenous data is not useless, it was *unusable by LightGBM at this window*. Gate 3 fails — covariates buy skill and sharpness (Winkler 123.3→113.3) at a coverage cost on both sides — so ALL_PASS is False and this is a trade, not a free win. Two caveats that matter: chronos-2 **univariate** already beats bolt-base by 5.5% here, so part of the headline is the newer model rather than the covariates; and **chronos-2's weights were modified 2026-06-05, inside EXP-021's window**, so unlike bolt-base contamination cannot be ruled out by construction — all arms were restricted to `t0 > 2026-06-05`, and the internally valid comparison is covariate-vs-univariate (same weights), not c2-vs-bolt. Gas is unhelpful even here (7.37 vs 7.30), a fourth strike against added level columns.

**Methodological lesson worth keeping:** a cheap pre-screen must be validated against the expensive test it replaces at least once before it is trusted to veto. Here they disagreed on the first try, and only the pre-registered Alternative 3 kept the real finding from being discarded unseen.

### EXP-026 — the prior is cheap

`chronos-bolt-tiny` retains **93.5%** of base's advantage over lean (−18.9% QS vs −20.3%), mini 97.1%, small 98.3%, all at DM p<0.0001, with band coverage essentially flat across the ladder (0.815/0.819/0.829/0.811). Alternative 1 (skill scales strongly with size) refuted; Alternative 3 (skill and calibration scale differently) does not fire. The "205M-parameter model in the nightly path" objection to EXP-021a Stage 3 largely dissolves — tiny would likely do. **Half the pre-committed Method is outstanding**: the CPU latency benchmark must run on sadalsuud and was not run, so EXP-021a Stage 2 is *not* discharged.

**Status**: nothing shipped. No production path touched. EXP-024 (lag richness) and EXP-027 (fine-tuning dissociation) were not run. Full numbers in `experiments/registry.jsonl` EXP-023/025/026/028/029.

---

## 2026-08-29 — EXP-022: the context ladder says it is mostly pretrained prior, and it corrects EXP-021's stated mechanism

**Trigger**: EXP-021 measured a 20.3% quantile-score gap but only *asserted* why. Its Position credited Chronos with "not being recalibrated nightly to one 56-day price level" — the level-drift mechanism this project has carried since EXP-018. That was reasoning from an accumulated story rather than from evidence, and it turned out to be wrong.

**Method** (exploratory, not pre-committed, no gates, nothing shipped — descriptive in the same sense EXP-018 Stage 0 was): starve the FM of context while leaving the incumbent untouched. Truncate EXP-021's *matched-information* contexts to their last 168h / 336h / 672h, re-run the identical predict path, and score every rung against the same `lean`/`full` arms with the same functions and HAC 71. If Chronos on 7 days still beats LightGBM trained on 56, the surviving margin is prior rather than information.

| arm | MAE | QS | dQS% vs lean | band cov | DM p |
|---|---|---|---|---|---|
| lean LGBM (56d train) | 27.77 | 9.86 | 0.0 | 0.611 | — |
| Chronos, 56d context | 23.23 | 7.86 | −20.3 | 0.811 | <0.0001 |
| Chronos, 28d context | 23.70 | 7.97 | −19.2 | 0.804 | <0.0001 |
| Chronos, 14d context | 24.23 | 8.19 | −16.9 | 0.813 | <0.0001 |
| **Chronos, 7d context** | **25.37** | **8.63** | **−12.5** | **0.823** | **<0.0001** |

**Chronos with one week of history beats LightGBM trained on eight weeks.** ~12 of the 20.3 points are pretrained prior; ~8 are context volume — and that second part is a critique of *our feature design*, not of gradient boosting: the incumbent predicts all 72 horizons from a single ~14-number feature row (8 lags + 6 rolling stats) while the FM reads the raw series.

**The calibration half is entirely prior.** Band coverage is flat down the ladder — 0.811 / 0.804 / 0.813 / 0.823 — so it does not depend on information at all. That matches where the gain sits by quantile: p10 26.3%, p90 19.5%, p50 16.3%. Tail quantiles are exactly what a 1344-row nightly refit, split across 3 horizon groups, can least afford to estimate; pretrained heads get them for free. Two supporting probes: the bands are better **shaped**, not merely wider (lean needs 2.0x inflation to reach 0.811 coverage, ending 1.7x wider than the FM's; at matched width it reaches only 0.682), and the win is **routine rather than extremal** — the FM takes 75% of vintages with median per-vintage MAE 19.89 vs 26.62, but p95 is a tie at 48.55 vs 48.39. **It is better on ordinary days and no better on hard ones.**

**What this corrects.** The level-drift story does not explain the gap. Mean signed error is +0.34 (FM) vs −0.52 (lean) EUR/MWh overall, and lean's worst month is **June (−15.5), not the August level-shift month (−4.7)**. Both models are near-unbiased; the difference is in distributional shape and spread. EXP-021's prediction was right and its stated reason was wrong — recorded because the registry's append-only correction rule exists for exactly this, and because the level-drift mechanism had begun to be reused as an explanation across EXP-018/019/020 without being tested directly.

**What it does not settle**: Chronos's pretraining corpus almost certainly contains electricity-domain series, so "zero-shot" means zero-shot on *this series*, not on this *kind* of data. And the incumbent has never had a hyperparameter sweep (publishability entry item 5, never run), so this compares our production model to Chronos, not the best possible GBM to Chronos. Both caveats carry into EXP-021a.

**Consequence for the roadmap**: context length demonstrably matters (−12.5% → −20.3% from 7d to 56d), which makes the untested **window-length** lever for the incumbent more interesting, not less — and it is a CPU job on the existing EXP-018 harness, needing no GPU and not blocked by the 2026-09-09 vintage gate. Registered as EXP-022 (`parked`). Runner `scripts/exp022_context_ladder.py`.

---

## 2026-08-29 — EXP-021: a zero-shot foundation model with no features beats the tuned LightGBM by 20%

**Trigger**: EXP-020, earlier the same day, closed the feature lever with a test that could have refuted it — at a 56-day window this model gains nothing from added exogenous columns and *loses* from added level columns. Two levers were left standing: window length and model class. This is the model-class arm, and the first arm of augur#15.

**Setup**: `amazon/chronos-bolt-base` (205M, Apache-2.0, revision `5d9f166d`), zero-shot, no fine-tuning, on `b650-gpu`. Everything except the estimator held fixed against EXP-020's control run: same parquet, same 260-vintage t0 grid, same 56-day context, same h+1..h+72, same scoring functions, HAC 71, exact pairing on `(t0, timestamp_utc)`. The FM gets **only the price series** — no engineered features, no exogenous, no calendar, no nightly retraining.

**Result** (matched-information arm, 18 717 paired observations):

| variant | MAE | QS | dQS% vs lean | cov_lo | cov_hi | cov_band | Winkler |
|---|---|---|---|---|---|---|---|
| **chronos_bolt_base** | **23.23** | **7.86** | **-20.3** | 0.898 | 0.913 | **0.811** | **119.8** |
| lean (15 feat) | 27.77 | 9.86 | 0.0 | 0.814 | 0.797 | 0.611 | 155.6 |
| full (24 feat, production) | 29.36 | 10.62 | +7.7 | 0.778 | 0.816 | 0.595 | 169.9 |

All four pre-committed gates pass against **both** bases (DM p<0.0001 each). The pre-commit predicted parity; the measurement is superiority.

**The calibration half may matter more than the skill half.** The FM's **raw** band coverage is 0.811 against the 0.80 nominal target *with no conformal layer at all*, where the incumbent sits at 0.611. Monthly upper-side coverage beats lean in 8 of 9 months, and the two largest gaps are precisely the months that motivated augur#19: **Jul +0.232, Aug +0.174** (August: FM upper 0.930 vs lean 0.756, at the highest monthly mean in the parquet, 128 EUR/MWh). The band is ~20% wider but Winkler is 0.77x. EXP-015 and EXP-016 both failed to close this gap by bolting a smarter conformal layer onto the incumbent's quantiles; this closes it by not needing one.

**The horizon result runs the wrong way for the obvious objection.** Bolt's native `prediction_length` is 64, so h+65..h+72 is an off-distribution autoregressive rollout — pre-registered as the failure mode most likely to be contaminating the comparison. It is not: the FM is -19.9% QS on h1-64 and **-22.8% on h65-72**, its MAE barely moving across the boundary (23.15 -> 23.88) while the incumbent's climbs (27.51 -> 29.87). The advantage grows with horizon.

**The code-review battery is the load-bearing part of this entry**, per ADR-007, because a result this large is more likely to be a bug than a discovery. Six checks: (1) the `lean`/`full` arms re-scored inside this harness reproduce the EXP-020 control **bit-identically**, so the join is exact; (2) zero context/target overlap, context ends exactly at t0, minimum target offset exactly +1h, and the scorer refuses to run if realised prices disagree across arms; (3) **a real defect the pre-commit missed** — `build_features` is `shift(1)`, so the incumbent's feature row stops at t0-1h while the FM's context ran through t0, a one-hour edge; a matched arm was run (context held to t0-1h, rolling out 73 steps to read the same 72 target hours) and is what is reported above, costing 0.8pp of 21; (4) batch invariance to 3e-5 despite contexts spanning 72..1343 points with NaN left-padding; (5) pretraining contamination is *impossible*, not merely unlikely — the pinned weights were last modified 2025-11-21 and the window opens 2025-12-05; (6) naive baselines confirm the incumbent is not simply broken (rMAE vs seasonal-naive: persistence 1.249, seasonal-naive 1.000, full 0.921, lean 0.871, **FM 0.729**).

**A methodological note worth keeping.** The Method's own regularity tripwire fired on the first run: 19h context gaps on 125 of 260 vintages. These turned out not to be parquet holes but `dropna` losses on exogenous NaNs — *exactly the rows the incumbent also drops*, so the information sets matched all along; what did not match was the spacing. A tabular model is indifferent to row spacing; Chronos reads its context as regularly spaced, so the compressed array silently shifted every hour-of-day across each hole. Fixed by regridding onto the complete hourly grid with holes marked NaN, which adds no data and uses Bolt's own missing-value marker — and verified before being relied on: on a synthetic series with an 18h block removed, the NaN-marked context tracks the clean forecast to 0.08 MAE while the compressed one deviates by 0.92. The general lesson: **a sequence model and a tabular model do not have the same notion of "the same rows."**

**Status**: evidence only — **nothing shipped**. `FEATURE_COLUMNS`, `ml/shadow/`, `dashboard.js` and `daily_update.sh` are untouched. The pre-committed decision rule makes superiority trigger a fresh-vintage confirmation before any production path moves, so **EXP-021a** was opened the same day with a raised effect-size bar (10%, not 3% — the in-sample effect is 20% and a 3% bar would let a 90%-shrunken result pass as confirmation), an operational-feasibility stage (CPU latency on sadalsuud, per-vintage tail risk), and a live-shadow stage before any ADR-006 amendment. EXP-020's standing conclusion is now half-resolved: **model class is confirmed live and large; window length remains untested and is a more interesting question than it was this morning**, given that a 2048-context pretrained model beats a 1344-row nightly refit. Full numbers in `docs/hypothesis-log.md` [2026-08-29 -> resolved] and `experiments/registry.jsonl` EXP-021.

**Environment note**: `b650-gpu` has no `pip`, no `python3-venv`, no `python3-dev` and no sudo. Triton cannot JIT without `Python.h`, so torch fails at first CUDA op. Fixed with a userland `uv` install plus uv-managed CPython 3.12, which ships headers. Recorded because the next GPU arm will hit it again.

---

## 2026-08-29 — EXP-020 Step 0: four fundamentals columns land in the parquet, inert by construction

**Trigger**: An external literature pass (see below) put *residual load* — load minus renewable generation, in MW — at ρ≈0.53 with NL day-ahead price, materially above load or renewables alone. Augur's three exogenous columns are a single offshore point's wind *speed*, a single point's GHI, and load, and EXP-018 Stage 0 found all three inert (±0.4%). The two statements are compatible only if the trio is the wrong *shape* of exogenous rather than exogenous being useless — which the ablation could not separate, because it only ever removed columns and never tested a combination or a fuel-cost level anchor.

**What was already sitting unused**: energyDataHub collects ~11 series; `consolidate.py` read 4. Two of the new columns come out of files the pipeline *already opens and parses*:

| Column | File | Path | Note |
|---|---|---|---|
| `wind_gen_forecast_mw` | `*_wind_forecast.json` | `entsoe_wind_generation.data.NL[ts].wind_total` | same file `parse_wind_file` reads for `wind_speed_80m`; it took the `offshore_wind` sub-dataset and left the TSO's own MW forecast untouched |
| `solar_gen_forecast_mw` | `*_ned_production.json` | `solar.forecast[ts].capacity_kw / 1000` | not previously read at all |
| `gas_ttf_eur_mwh` | `*_market_proxies.json` | `gas_ttf.price` | one daily scalar, stamped with its own trade date |
| `is_holiday_nl` | `*_calendar_features.json` | `[ts].is_holiday_nl` | the 24-feature set has no holiday flag |

**Unit trap worth recording**: NED's `capacity_kw` is *not* installed capacity. It varies through the day and satisfies `capacity_kw == volume_kwh * 4` on the quarter-hourly blocks, i.e. it is the block's average power in kW. `utilization_pct` is measured against true installed capacity (~25 GW: 16008 MW ÷ 0.6364 ≈ 25.2 GW at the 2026-08-24 midday peak), so multiplying capacity by utilization would double-discount. The parser divides `capacity_kw` by 1000 and a test pins the `volume_kwh * 4` identity so a future NED resolution change fails loudly rather than silently rescaling the column.

**Additive-only, verified not asserted**: EXP-018a Stage 1 fires ≈2026-09-09 off this same parquet, so the plumbing had to leave it undisturbed. Rebuilding from one data directory with and without the new parsers gives an identical index and bit-identical values for all five original columns. Nothing was added to `FEATURE_COLUMNS`, so no model reads the new columns yet.

**Coverage over 2025-12-01..2026-08-25**: `is_holiday_nl` 0.0% NaN, `wind_gen_forecast_mw` 0.8%, `solar_gen_forecast_mw` 1.7% — and **`gas_ttf_eur_mwh` 24.6%, all of it one contiguous leading hole**. EDH's `market_proxies` collector only added TTF on 2026-02-05 (its own changelog); from that date the column is complete. So the EXP-020 sweep runs on 2026-02-05..2026-08-22 (~199 vintages) rather than the 263 EXP-018 used, with the no-gas arms replayed on the full window as a control. Backfilling TTF from yfinance was declined: the daily snapshot is vintage data and a backfill is revised data, and mixing the two would disguise exactly the failure mode (effect confined to the recent level shift) the experiment needs to be able to see.

**Tests**: 20 new cases in `tests/test_consolidate.py` (38 in that file, up from 18) — envelope v2.1/v2.2 shapes, UTC normalisation, the NED unit identity, forecast-not-actual, gas indexed on trade date not collection time, TTF-not-carbon, wind-MW-not-wind-speed, and fail-soft on every malformed shape.

**Result (same day) — refuted.** `scripts/exp020_fundamentals_ablation.py`, 7 arms x 195 paired vintages (14 037 paired obs) plus a 4-arm control on the full 263-vintage window. Primary gate `lean_fund` vs `lean`: **FAIL** — DM p=0.9929 (decisively the wrong direction), QS 3.4% *worse* not 3% better. Confirmatory `full_fund` vs `full`: **FAIL** (p=0.6150). Residual load is inert (p=0.648 main, p=0.899 control) and so is plain `load_forecast` (p=0.851). Gas actively degrades (+3.2% QS, p=0.991).

The informative half is the gas result, which corrects the entry's own mechanism. The hypothesis was that a trailing-56-day model *lacks* a fuel-cost level anchor. It does not want one. That is the second independent confirmation of EXP-019's finding — re-adding `price_rolling_mean_168h` as a single explicit level column cost significantly there, read as redundant smoothed-level columns diluting the split search. TTF gas is exactly that kind of column, and EXP-019's reading predicted this outcome before the sweep ran. Generalised: **at a 56-day window this model rejects added level columns whatever their provenance, internal or exogenous.** The monthly panel rules out a regime artifact (worse in 5 of 7 months, Jul +16.7%, no rescue in August). Consequence: the next lever is window length or model class, not feature engineering. Full numbers and the four gate verdicts in `docs/hypothesis-log.md` [2026-08-29 -> resolved] and `experiments/registry.jsonl` EXP-020.

**Status**: evidence-gathering only, no production path touched. `FEATURE_COLUMNS` untouched; the Step-0 columns are kept because they are additive-only and cost nothing. Full suite 222 passed. Pre-committed criteria and the arm design are in `docs/hypothesis-log.md` [2026-08-29]. Provenance for the mechanism claim is external — a HAN BDSD minor project on week-ahead NL price forecasting (`FyE/core/sources/bdsd-minor-electricity-price-prediction-2026-01-19.pdf`, Jan 2026) and its cited sources (Aščerić 2021, Tschora 2022). That report independently discarded the energyDataHub feed as too gappy to train on and rebuilt from ENTSO-E + Open-Meteo — corroboration for ducroq/energyDataHub#50, not acted on here.

---


---

**Older entries** (up to 2026-08-28) are verbatim in [`archive/model-progress-log-2026-03-to-08-28.md`](archive/model-progress-log-2026-03-to-08-28.md). Registry references `docs/model-progress-log.md#<date>` with an older date resolve there.
