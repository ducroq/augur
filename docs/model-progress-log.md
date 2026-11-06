# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-11-06 (latest) — CQR stops scoring its own widening

`compute_cqr_q` scored the stored bands, which already included each day's `q`. EXP-015 recorded this on 2026-06-12, but it dropped out of the index on 2026-10-16 and its cost was never measured. After a wide spell the scores went negative, `q` clipped to 0 and the band collapsed: `last_cqr_q` went from 72 on 10-29 to 0 from 11-03.

The fix scores the sorted, unwidened quantiles (`unwidened_bands`). `p50`, the forecast and the widening step don't change. On a 130-day replay, pooled band coverage goes from 0.703 to 0.788, lower side 0.852 to 0.887, upper side 0.851 to 0.901. Median width rises 17% (113 to 132 EUR/MWh) and Winkler is level (216.2 to 214.6). Since the 2026-09-13 anchor shift width rises 24% (144 to 178) with Winkler level; on November's 288 rows it rises 84% and Winkler worsens (185.7 to 198.2). This removes a defect; it doesn't improve the score. The pre-committed guardrail passes by construction, so it isn't evidence: `docs/hypothesis-log.md` [2026-11-06]. Live check after 28 post-deploy vintages.

**Reading across a deploy:** coverage in `eval_log.jsonl` and band width in `calibration_history` change at the deploy date for this reason, not because the model changed. The confound also touches augur#19 and any before/after coverage comparison. On the first run `q` steps from 0 to about 27. A rollback would probably collapse `q` for up to 7 days, because the old code would score the newly wider stored bands (reasoned, not measured).

## 2026-10-28 — Live cheap-hour regret: hours 25–72 were never scored, and the profile floor ranks twice as well everywhere

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

Entries up to 2026-08-31 are in `docs/archive/model-progress-log-2026-03-to-08-28.md`.
