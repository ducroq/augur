# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-09-06 (latest) — The eval harness had no floor in it: the production model does not reliably beat "yesterday, same hour"

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

## 2026-08-28 — The vintage stream broke silently for three days: t0 followed a stale parquet

**Trigger**: The 2026-08-27 daily commit carried `[ALARM: eval stale 3d]` while every step reported `rc=0` and `eval_log.jsonl` ended at 2026-08-24.

**What the trace showed**: `metadata.t0` across the last six daily commits, paired with the per-vintage state in `shadow_state.json`:

| Run | Finished (UTC) | t0 | New vintage |
|---|---|---|---|
| 08-22 | 16:31 | 08-23T21 | eval_day 08-23 ✓ |
| 08-23 | **20:31** | 08-23T21 | — (t0 repeated) |
| 08-24 | 16:31 | 08-24T21 | eval_day 08-24 ✓ |
| 08-25 | 16:33 | **08-26T21** | eval_day 08-26 ✓ (08-25 skipped) |
| 08-26 | 16:45 | 08-27T20 | eval_day 08-27 ✓ |
| 08-27 | **20:32** | 08-27T20 | — (t0 repeated) |

`update_shadow.py` sets `t0 = parquet["price_eur_mwh"].dropna().index.max()`, so it tracks the data rather than the clock, and nothing asserted it moved. A repeated t0 means the `(timestamp_utc, eval_day)` dedup overwrites an identical prediction set — retrain, republish an unchanged forecast, exit 0, add nothing evaluable. A jumped t0 means the skipped day never got a prediction set and can never be evaluated: **2026-08-25 is a permanent hole**, the third after 06-08/06-10.

**Upstream chain, corrected against EDH's commit history**: the first reading — "EDH published late" — was wrong. EDH's normal publish window is 16:1x–16:5x UTC, so the 4h cap is generous. It **skipped 08-23 and 08-27 entirely** (no `data_quality_report.json` commit on either date, and the same is true of 08-01/08-03/08-06); on both days Augur waited the full 4h, timed out at 20:3x, and proceeded on stale data exactly as designed.

**08-24 was ours, not theirs.** EDH published a catch-up at 06:28 UTC carrying 08-23's missed collection. The report's `timestamp` field always equals its own commit time, and `wait_for_edh.sh` tested only that its *date* matched today — so the gate released the run instantly at 16:30, Augur finished at 16:31, and EDH's real 08-24 publish landed at **16:32:17, ninety seconds later**. The stale price column that started the whole sequence came from our gate asking the wrong question, not from a partial publish on their side.

The full chain: EDH skips 08-23 → its overnight catch-up satisfies the date-only gate on 08-24 → Augur runs 90s early on stale data (t0 stalls) → 08-25's publish clears the backlog carrying two delivery days at once (t0 jumps, vintage lost) → EDH skips 08-27 (t0 stalls again).

**What changed (1 — the gate)**: `wait_for_edh.sh` now requires the report to be stamped at or after `MIN_PUBLISH_HOUR_UTC=12` in addition to being dated today. The NL day-ahead auction clears around 12:00 CET, so a report stamped before noon UTC cannot contain today's prices whatever date it carries, and an overnight catch-up no longer releases the run. Replayed against the real timestamps it waits the extra two minutes on 08-24 and releases on the 16:32:17 publish; the 4h fail-open cap is untouched, having worked correctly on both skipped days.

**What changed (2 — the guard)**: `classify_t0_advance()` in `ml/shadow/update_shadow.py` compares each run's t0 to `state["last_t0"]` by calendar date — 08-26T21 → 08-27T20 is 23h and healthy, since how much of the delivery day EDH published moves the last realised hour around. Anything but +1 is logged and persisted as `t0_advance_days`; `scripts/daily_update.sh` reads it and appends `[ALARM: t0 stale <date>]` / `[ALARM: t0 jumped Nd]` / `[ALARM: t0 backwards <date>]` to the commit subject, gated on `SHADOW_UPDATE_RC=0` so a failed run can't re-fire the previous run's value. Non-fatal throughout: a frozen dashboard is worse than a stale one. 7 tests in `TestClassifyT0Advance`; suite 195 → 202.

**What did NOT change**: no model, feature, or forecast logic. `FEATURE_COLUMNS`, the CQR layer, and the gate's fail-open-after-4h behaviour are all untouched. EDH's own publish reliability is untouched too — it remains an upstream problem, now absorbed rather than mistaken for a healthy signal.

**Consequence for EXP-018a**: Stage 1 is unaffected — `exp018_stage0_ablation.py` replays its own t0 grid off `training_history.parquet`, so a missing *shadow* vintage costs it no holdout day, provided the parquet's price rows backfill. **Stage 2 is affected**: it reads trailing-14 means from `eval_log.jsonl`, which now has a hole at 2026-08-25. Noted in the pre-commit.

**Patterns** (`memory/gotcha-log.md`, both promoted): a cursor derived from data rather than the clock must be asserted to advance, at the step that owns it; and a freshness gate must test freshness rather than a proxy for it — "dated today" and "published since the event I need" diverge exactly when upstream is recovering from its own failure, which is when you most depend on the gate. The eval-stale alarm fired correctly and named `evaluate_shadow.py`, which was blameless — when step B's health check is the only witness to step A's failure, it will point at the wrong component.

## 2026-08-25 — EXP-018 Stage 0: the production feature set is carrying dead weight

**Trigger**: The 2026-08-20 curation deferred EXP-018 (feature expansion + ablation) to "next session" with a 2026-08-27 review-by. Picked up as the session's first work item.

**What ran**: New harness `scripts/exp018_stage0_ablation.py` — production-shaped walk-forward (t0 = last clean feature row of each vintage day, 56-day training window, `MultiHorizonLightGBMQuantileForecaster`, h+1..h+72, **no CQR**), 263 vintages 2025-12-01..2026-08-22. Two sweeps: 8 group-level variants (2104 fits) and 6 mechanism-split variants (1578 fits), ~45 min each on 14 cores. Row set fixed to complete full-feature vectors so every variant sees identical timestamps; scoring uses raw tau outputs for pinball (EXP-013's sort-then-pinball lesson) and sorted quantiles for coverage/Winkler.

**Findings**:

1. **The six rolling-stat features actively hurt.** Removing them: MAE 28.97 → 27.24 (−6.0%), quantile score 10.54 → 9.72 (−7.8%), lower-side coverage 0.778 → 0.805. Reverse DM (HAC 71): −6.48, p<0.0001 on QS; −5.02, p<0.0001 on |error|. Wins in 7 of 9 months, largest in the volatile recent regime (May −14%, Jul −11%, Aug −9%), loses only Dec 2025 (+5.8%); holds in all three horizon groups, so it is not a long-horizon artifact.
2. **Calendar is the only group clearly earning its place** — dropping it costs +7.3% MAE / +9.2% QS, DM p=0.000.
3. **The exogenous trio is inert.** wind −0.3%, solar −0.3%, load −0.4% individually; all three together +0.8% QS (p=0.041). Not a data defect: over the last 120 days `load_forecast` correlates 0.59 with price and `solar_ghi` −0.53. The model extracts nothing from them beyond what price lags + calendar already encode. This refutes the EXP-018 premise that *more* fundamentals (#2/#3/#4/#22) is the highest-leverage lever.
4. **Mechanism is diffuse, not one bad column**: rolling_mean −1.6%, rolling_std −1.8%, the 168h pair −2.2%, short windows −0.8%, all six −6.0%. Best variant is a 15-feature **lean** set (rolling + exogenous removed): MAE 27.08 (−6.5%), QS 9.69 (−8.1%), lower coverage 0.810. Reading: redundant absolute-level features dilute the split search, and splits calibrated to a 56-day window's price level generalise badly when the level drifts.
5. **augur#19 has flipped sides again.** Recomputed from `calibration_history` through 2026-08-24: Jul lower 0.865 / upper 0.841 / band 0.706; **Aug lower 0.887 / upper 0.774 / band 0.660**. The lower side has essentially healed; the upper side is now the breach, and total band coverage is well under the 0.80 target. August's mean price (128 EUR/MWh, the highest in the parquet, vs 106 in July) makes this the mirror of EXP-016's first-shift-day finding — a trailing-window model under-reaching an upward level shift. EXP-017's premise (q10_raw biased high) is stale.

**What did NOT change**: no production code touched. `FEATURE_COLUMNS` is untouched; the finding is a best-of-eight selection on a single window and ships only through the pre-committed confirmation in `docs/hypothesis-log.md` [2026-08-25] EXP-018a — fresh vintages with `t0 ≥ 2026-08-25`, four gates (DM p<0.10, ≥3% QS effect survives, coverage not >0.02 worse per side, Winkler ≤1.05×), then a 14-vintage live watch with a one-line revert.

**Logged**: `experiments/registry.jsonl` EXP-018 (`kept` — evidence, no deployment); Stage-0 resolution appended to the 2026-08-20 hypothesis-log entry; EXP-018a pre-commit opened. Branch `exp018-feature-reduction`, merged to `main` as `d7581b9`.

**Same-day follow-up — EXP-019 (`rejected`)**: tested whether the lever is stationarity rather than removal. `scripts/exp019_stationary_ablation.py` adds anchor-relative spreads (`spread_lag_Hh = price_lag_Hh − price_rolling_mean_168h`, pure column algebra over the existing builder — same rows, no new inputs) and sweeps 5 variants over the same 263 vintages. Anchor-relative spreads **tie** plain deletion (lean 27.08 / QS 9.69 vs stat_lean_noanchor 27.33 / QS 9.71; DM QS p=0.405, |error| p=0.160), so the reparameterisation buys nothing. The informative half: **re-adding `price_rolling_mean_168h` as the single explicit level column costs significantly** (−5.7% → −2.5% MAE vs incumbent, QS p=0.0001). Since raw price lags are also absolute levels and are harmless, drift is at most half the story — redundant smoothed-level columns diluting the split search fits better. EXP-018a Alternative 2 refuted pre-emptively; Stage-1 treatment stays the plain lean set. Alternative 1 (regime-dependence) remains live: both lean variants lose in Dec 2025/Jan 2026 and win 10-13% in Mar/May/Jul/Aug, which is exactly what the fresh-vintage window will test.

---

## 2026-07-03 — Post-migration recovery: venv/pickle freeze, ARF decoupling, dependency pinning

**Trigger**: Repo moved from the original (Windows) dev machine to **situla** (Linux dev), deploy stays on **sadalsuud**. User flagged "not everything is up to speed." Investigation found the dashboard silently frozen on **2026-06-28** data: `augur-daily.service` had failed every night since 2026-06-29 (day after a sadalsuud reboot), while the timer stayed healthy — the only alive-signal (missing daily commits on origin/main) had gone unnoticed for 5 days.

**Root cause (a chain)**: The migration rebuilt sadalsuud's `.venv` from `requirements.txt`'s loose `>=` ranges, so pip pulled bleeding-edge majors (**river 0.25.0, pandas 3.0.4, numpy 2.5.0**). river 0.25 can't unpickle `river_model.pkl` (saved under ~0.21): `Can't get attribute '__pyx_unpickle_VectorDict'`. ARF ran under `set -e` as "must succeed" — a comment stale since the 2026-05-29 EXP-014 demotion to a backup signal — so the unpickle failure aborted the whole script **before** the production LightGBM shadow, commit, or push. LightGBM itself was fine under the new deps (verified: shadow pickle loads, all shadow modules import, 195/195 tests pass).

**Fixes shipped**:
1. **Decoupled ARF from production** (`96dd499`): ARF now runs under `set +e`; a backup-signal failure surfaces as `ARF FAIL rc=N` in the commit subject instead of killing the production push. Added a non-blocking pytest **smoke gate** pre-flight.
2. **Regenerated `river_model.pkl`** under river 0.25 via `ml.training.warmup` (consolidate → warmup → ml.update). Because warmup replays the full consolidated parquet, **the 5 missed days (Jun 29–Jul 2, incl. the ~150 EUR/MWh spikes) are learned** — the online-learning gap is closed, not skipped. `ml.update` confirmed load + 72h forecast + surcharge-cache refresh (110.85).
3. **Pinned dependencies** (`affa443`) and **repinned off the yanked pandas** (`0574e3d`): `requirements.lock` moved pandas 3.0.4 (a *yanked* release — reported datetime segfaults) → **2.3.3** (river/numpy/lightgbm unchanged, so the pickle stayed valid — no second regen). `requirements.txt` gained ceilings (`pandas<3`, `numpy<3`, `sklearn<2`, `lightgbm<5`, `cryptography<50`, `pyarrow<25`) and `river==0.25.0` (pickle-coupled). New `scripts/bootstrap_venv.sh` builds an identical venv from the lock on both boxes; 195 tests pass on py3.12 (sadalsuud) and 3.14 (situla).
4. **Multi-model review follow-up** (`2fa839e`): a 6-model review battery (opus/sonnet/haiku/fable) + adversarial opus verify caught that the decoupling was *incomplete* — the pre-flight `DEP_PROBE` still coupled `import river` to the production shadow gate. Removed river from the probe (a broken backup-only dep can no longer skip production).

**Verification**: full `daily_update.sh` ran clean end-to-end mid-day and pushed `fedf8f6` (ARF OK | shadow rc=0/eval rc=0), restoring the live dashboard ~8h before the scheduled run. Production forecast horizon confirmed 2026-07-03 22:00 → 2026-07-06 21:00 (72h).

**Open follow-ups (parked, user-deferred)**: systemd `OnFailure=` alerting (the outage was silent 5 days — biggest remaining gap); py3.12 on situla for exact dev/prod interpreter parity; numpy-2.5 `pd.Timedelta` bare-int DeprecationWarnings in `update_shadow.py` (~207/271), harmless while numpy is pinned. Full incident writeup in `memory/gotcha-log.md` (2026-07-03).

---

## 2026-06-12 — v2.2 blast-radius forensics, output-quality guards, and the EXP-015/016 calibration-layer arc

**Trigger**: Session-start review noticed eval-log rows for 2026-06-08 and 2026-06-10 missing and `arf_mae: null` on 06-09, despite "ARF OK | eval rc=0" commit subjects on all three days.

**Forensics (morning)**: The EDH v2.2 break's blast radius was larger than the 2026-06-10 entry recorded. (a) ARF published **empty forecasts** on 06-08/06-09 (zero-hour archives; live `augur_forecast.json` empty) while exit codes stayed 0. (b) Eval `eval_day` is a forecast *vintage* keyed to the parquet's last realised price (t0); the stale parquet froze t0, so vintages **2026-06-08 and 2026-06-10 were never created — permanently unevaluable** (zero rows in `calibration_history`). (c) `find_arf_archive_for_day` picked the empty 06-08 archive with no fallback → the 06-09 null. Documented on augur#14. Separate live regression found in the same pass: **ARF forecasts truncated 72h → 48h since the fix**, because post-v2.2 `load_forecast`/`energy_price_forecast` files only span today+tomorrow (~48h @ 15-min) vs ~8 days before — filed as **augur#26** (EDH-side window restore preferred; LGBM unaffected since the parquet never carried future exogenous).

**Guards shipped** (`1c33daa`): two non-blocking post-run checks in `daily_update.sh`, surfacing in the commit subject — `[ALARM: ARF forecast Nh]` (<24h) and `[ALARM: eval stale Nd]` (>2 days without an eval row). Third recurrence of the silent-failure factory; pattern promoted in the gotcha log as "rc=0 is not output quality".

**EXP-015 — per-side CQR** (pre-commit `bcc3e78`, resolved `b40db95`, `parked`): the baseline (30 vintages / 2112 hours, from `calibration_history` — not `eval_log.jsonl`, whose rows mix 24/48/72h vintages) refuted the horizon-conditioning sketch in augur#19 (lower-side deficit flat across horizon groups: 0.828/0.837/0.833) and showed the real asymmetry is across *sides* (lower 0.834 vs upper 0.886 under symmetric widening). Treatment: per-side split-conformal on raw sorted quantiles at 0.90/side. Replay (`scripts/exp015_replay_cqr.py`, 8 evaluable vintages / 528 rows): lower 0.778 → 0.826 (+0.048, criterion 1 PASS) at +2.5% Winkler (guardrail PASS), but below the pre-committed 0.86 bar — the regime-shift vintages 06-02/06-03 (0.375/0.708) drag the pool; every later vintage ≥ 0.847. Bonus finding: production `compute_cqr_q` conformalizes the already-widened bands (feedback loop), not the raw quantiles.

**EXP-016 — per-side ACI** (pre-commit `440b0b6`, resolved `d21b179`, `parked`): Gibbs-Candès adaptive α per side (γ=0.10, daily batched updates), same rows and criteria. Lower 0.852 (best yet) but in the pre-committed near-miss zone AND Winkler tripped at +12% (α_lo pegged at the 0.005 clip, q_lo ≈ 55–61 EUR/MWh, median width +30%). Decisive evidence: γ ∈ {0.05, 0.10, 0.20} all converge to ≈0.85 — a **γ-independent ceiling** from the first-shift-day misses that no day-granularity calibration layer can reach (ACI fixed every post-shift vintage to ≥ 0.903).

**Arc conclusion**: the coverage gap lives in the raw quantiles — q10_raw is biased high entering regime shifts. **EXP-017 (9-quantile training) carries augur#19 next**: a model-training change requiring a walk-forward backtest over a window including 06-01..06-03 (no stored 9-tau history to replay) and a fresh ADR-007 pre-commit. Both parked layers (per-side scores, adaptive α) are candidates to re-add on top of improved raws.

**Process note**: both experiments ran the full ADR-007 loop in one session — pre-commit → replay-on-existing-data → same-day resolution — with criteria identical across the two so results compare directly. Verdicts respected as written (no loosening); the redirects came from the pre-registered Alternatives, not post-hoc reinterpretation.

---

## 2026-06-10 — EDH v2.2 envelope parser fix + pipeline hardening (parser tests, dep probe, venv untrack)

**Trigger**: User reported the dashboard's 72h forecast showing only a 24h stub. Initial diagnosis chained Augur log lines `WARNING ENTSO-E data missing in 260609_083716_energy_price_forecast.json — skipping Energy Zero to avoid contamination` to "EDH ENTSO-E NL collector outage" (echoing the 2026-03-26 precedent in memory). The EDH-side memo corrected the attribution: ENTSO-E NL was healthy; the actual cause was EDH's schema v2.2 envelope wrap (commit `3dfc7fb`, 2026-06-07 12:43 CEST) that Augur's Python parsers had never been updated for.

**Changes today (six commits)**:

1. `e11487b` — **v2.2 envelope unwrap in `ml/data/consolidate.py`.** New `_unwrap_v22_envelope(data)` helper applied at three call sites (`parse_price_file`, `_parse_single_source` used by `parse_entsoe_wholesale` + `parse_energy_zero_consumer`, `parse_wind_file`). Mirrors the dashboard JS pattern from commit `4a557c8` (2026-06-07). The 4a557c8 commit message had asserted "Python ML pipeline migrated transparently via `_migrate_2_1_to_2_2`" — unverified and wrong: `load_json_file` in consolidate.py (line 67) never invokes `schema_registry`. The Python parsers had been silently returning empty Series for every v2.2 file since 2026-06-07, pinning `training_history.parquet` at 2026-06-07 21:00Z. ARF (`ml/update.py`) was equally broken — it imports the same parsers. Architectural alternative (importing EDH's `migrate_to_current`) rejected: Augur's parquet history only reaches v2.1+ (starts 2025-09-28), so version-walk advantage is theoretical; cross-repo Python import would add sys.path glue + test mock complexity.

2. `d20992a` + `967b653` — **`.venv/` untracked from git on sadalsuud.** No prior `.gitignore` entry for `.venv/`, so 7921 venv files had been tracked. Today's `pip install --force-reinstall lightgbm` (item 4 below) would have leaked into the next nightly commit as a ~20k-line diff. `d20992a` adds `.venv/` + `venv/` to `.gitignore`; `967b653` runs `git rm -r --cached .venv/` on sadalsuud (disk preserved). Verified clean on the next daily commit `576a65c` (only 6 data/state files, no venv noise).

3. `576a65c` (manual `systemctl start augur-daily.service`) + `044585e` (scheduled 18:30 CEST fire) — **two successful daily-cycle runs on the patched code today.** Parquet advanced 2026-06-07 21:00Z → 2026-06-11 21:00Z. Eval log backfilled for 2026-06-07 (LGBM MAE 30.6 vs ARF MAE 39.5, LGBM wins) and 2026-06-09 (LGBM 19.9; ARF empty that day, no compare). 2026-06-08 has a permanent eval-log gap — no LGBM prediction set targeting that day was ever made during the outage, so no eval row can be reconstructed.

4. `c29671e` — **Hardening followups from the code-review battery + lightgbm-corruption mitigation.** Four pieces in one commit:
   - **`tests/test_consolidate.py` (NEW, 18 tests).** Closes the biggest gap from the code-reviewer agent: zero parser tests existed in `tests/`. Parametrized coverage for v2.1 flat shape, v2.2 envelope, `_unwrap_v22_envelope` direct unit tests, the "envelope present but no known source keys" graceful-empty case, kWh→MWh unit multiplier, Elspot `+00:18` timezone normalisation, ENTSO-E-wins-over-Elspot merge precedence, and isinstance guards on solar/weather/load. Test against plain dicts via monkeypatched `load_json_file` — no encryption keys required. Suite grew 177 → 195.
   - **isinstance guards on `parse_solar_file`, `parse_weather_file`, `parse_load_file`.** All three have identical structural exposure: `xxx_data = data.get("data", {})` followed by code that assumes `xxx_data` is a dict. Future schema where `data` is a list would crash (for load) or silently return empty (for solar/weather). Now uniformly fail-soft to empty Series. Code-reviewer flagged `parse_solar_file` specifically; extended to the other two for consistency.
   - **`logger.debug` in `_unwrap_v22_envelope`.** v2.2-unwrap events are now observable in the daily log.
   - **Pre-flight dep probe in `scripts/daily_update.sh`.** Runs `python -c "from lightgbm import LGBMRegressor; import river; import pandas; import lightgbm"` after the existing `SHADOW_PRE_AGE_H >36h` check. On failure: `DEP_PROBE_OK=0` gates the shadow block off (parquet consolidate + ARF still run), and a `[ALARM: dep probe failed — shadow skipped]` marker appears in the daily commit subject — visible on origin/main without log inspection. Motivated by today's lightgbm install corruption (root cause unexplained; the venv's `lightgbm/` directory was reduced to `lib/` + `__pycache__/` only, no `__init__.py` or source files, mtime 2026-06-10 15:50 UTC). Second lightgbm install incident (first was 2026-04-30 "lightgbm not installed"); two occurrences in 6 weeks justifies the alarm-cost.

**Rationale**: The v2.2 fix was unblocking — without it, training parquet stays frozen and the dashboard's 72h forecast degrades to a 24h stub as published day-ahead prices age past it. The hardening cluster addresses what the incident revealed: zero parser test coverage (made the original v2.2 break invisible to CI), structural ambiguity in the other three parsers (would bite on the next schema shape change), and lightgbm install fragility (would bite the next time the venv drifts).

**What was NOT changed**: ARF model, LightGBM model, feature builder, CQR logic, training window, eval logic, dashboard rendering, output JSON schemas, augur#19 calibration trajectory. The v2.2 fix is purely at the EDH-consumer parser layer; the hardening additions are tests + defensive guards + observability. No model behaviour change; expect no shift in eval-log MAE or coverage trajectory.

**Observation plan**: Tomorrow's 18:30 CEST fire (Thu 2026-06-11) will exercise the dep probe in production for the first time. If both ALARM markers stay absent through the 2026-06-15 augur#12 observation window close, hardening is validated and the unexplained lightgbm corruption is in the "watched but tolerable" bucket.

**Open** (post-2026-06-10): augur#19 calibration follow-up (EXP-015..017) unblocked; augur#22 HDD/CDD; Phase-1-for-LGBM (TTF + genmix); publishability backlog (`docs/hypothesis-log.md`, review-by 2026-12-31). No new open items from today.

**Status**: v2.2 fix [RESOLVED, deployed `e11487b`, dashboard healthy]. Hardening [DEPLOYED `c29671e`, awaiting first production exercise of dep probe in tomorrow's nightly]. lightgbm uninstall root cause [UNRESOLVED — mitigated by item 4 pre-flight probe; documented in gotcha log as unexplained].

---

## 2026-06-09 — augur#12 closed: cron → system-level systemd with EDH-freshness gate; Healthchecks.io removed

**Trigger**: Calendar event for Phase 2 verification (`Augur #12 — verify systemd timer's first fire`, 09:00 CEST). Phase 1 (user-level systemd unit + `wait_for_edh.sh` ExecStartPre + healthchecks ping kept) had deployed 2026-06-08. First fire that evening was clean — `status=0/SUCCESS` at Mon 2026-06-08 18:31:44 CEST, EDH-timestamp detected at 2026-06-08T09:04:05Z, commit `98ce3b8` landed 16:32 UTC, **107 minutes after** the cron's 14:45 UTC commit `09f7c15`. Both runs ran the same day during the observation overlap.

**Changes today (three commits)**:

1. `5149d17` — **Remove Healthchecks.io integration entirely.** During Phase 2 verification we tried to confirm the healthchecks dashboard was green, discovered the owning account is unknown (the project's busara.eu@proton.me account does not own UUID `e7771ae1-…1cc58bab0992`). Decision: cut the dependency rather than chase the account. Removed the curl ping block from `scripts/daily_update.sh`, the `HEALTHCHECKS_SHADOW_URL` line from sadalsuud's `.env`, and reworded the "absent ping is the alarm" comments in `scripts/wait_for_edh.sh` + `scripts/systemd/README.md`. New alarm path: pre-flight `SHADOW_PRE_AGE_H >36h` ALARM in `daily_update.sh` surfaces stale state in the *next day's* commit message, and a missing daily commit on origin/main is the external alive signal.

2. `719e5e6` — **Migrate systemd from user-level to system-level.** Phase 1's user-level setup required `loginctl enable-linger jeroen` (pending), or the timer would only fire while jeroen has an active session. Migrated to `/etc/systemd/system/augur-daily.{service,timer}` with `User=jeroen` + `Group=jeroen` on the service so SSH keys / venv / `.env` access stays unchanged. Eliminates the linger dependency; the timer is now owned by PID 1 and survives logouts and reboots. `WantedBy=default.target` → `WantedBy=multi-user.target`. Timer file unchanged. README rewritten for the new deployment pattern.

3. (Crontab edit, not a commit since `.env` and crontab are gitignored.) **Cron line commented** in sadalsuud's crontab with marker `# Migrated to systemd augur-daily.timer 2026-06-08 (augur#12). Restore if broken.`, backup at `/tmp/crontab.backup`. **User-level systemd symlinks removed** from `~/.config/systemd/user/`. System-level units deployed with `sudo cp` + `sudo systemctl enable --now augur-daily.timer`. Verified next fire scheduled for Tue 2026-06-09 18:30 CEST (= 16:30 UTC).

**Rationale**: Both the schedule and the orchestration model needed to change. The pre-augur#12 `45 16 * * *` cron ran at 14:45 UTC — empirically that's 75 min to 4+ hours **before** EDH's GitHub Actions collector publishes (observed window 16:23-20:13 UTC, 14-day sample). Consequence (documented in ADR-006 under Consequences): training parquet always trailed 24h, live overall MAE ran 84% above the backtest h+1 figure. The systemd unit fires at 16:30 UTC then polls EDH's `data_quality_report.json:timestamp` until today's date appears (max wait 4h, then proceeds with stale data so the run never fails closed). System-level (rather than user-level) eliminates the linger dependency entirely, matching the rest of the box's timers.

**What was NOT changed**: ARF model, LightGBM model, feature builder, CQR logic, training window, evaluation logic, dashboard rendering, output JSON schema. The change is purely orchestration — same `daily_update.sh` runs, same artefacts written, same eval log appended to. The behavioural difference is the *input* the pipeline sees: post-augur#12 the exogenous columns (wind/solar/load) in `training_history.parquet` are current-day, not 24h-stale.

**Observation plan**: 1-week observation window 2026-06-09 → 2026-06-15. Daily quick-glance for a `Daily update YYYY-MM-DD` commit landing on origin/main around 16:32 UTC = 18:32 CEST. If 7 consecutive clean fires, delete the commented cron line entirely (otherwise rollback to cron). The cleaner-data MAE comparison (live MAE under fresh exogenous data vs the 84%-above-backtest era) will be measurable from `ml/shadow/eval_log.jsonl` after the window closes; expect a meaningful drop in live MAE if the freshness-skew hypothesis is right.

**Open** (post-augur#12): augur#19 (lower-side calibration follow-up — soft-blocked on augur#12 specifically to avoid conflating freshness-fix and calibration-fix effects; now unblocked for EXP-015..017). Also two unrelated *side observations* surfaced during this work: (a) sadalsuud has two other user-level timers (`dca-fear-alert.timer`, `momentum-paper.timer`) that have the same linger fragility — not augur scope but worth flagging. (b) the orphaned healthchecks UUID will eventually start firing "down" alerts to whichever account owns it; nothing actionable here.

**Status**: augur#12 [RESOLVED, observation in progress]. ADR-006's "Freshness skew is unfixed" consequence has a 2026-06-09 resolution marker added; eval-log evidence of the live-MAE improvement to be added after the observation window closes 2026-06-15.

---

## 2026-06-06 — `pending_predictions` dedup landed (closes 2026-05-08 gotcha)

**Trigger**: End-of-session `/curate` flagged the 2026-05-08 gotcha (`update_shadow.py` appends `pending_predictions` without dedup) as a 29-day-old lingering [OPEN code] item. The operational mitigation (state reset on sadalsuud) closed the original incident, but the code-side defence had been deferred. Decision today: land the small fix rather than carry it indefinitely.

**Changes** (`ml/shadow/update_shadow.py`, one block at the `pending_predictions` write):

Before — appended new predictions without uniqueness guarantee:
```python
state["pending_predictions"] = trim_to_recent_days(
    list(state["pending_predictions"]) + new_pending, MAX_HISTORY_DAYS
)
```

After — dedups by `(timestamp_utc, eval_day)` tuple, most-recent run wins:
```python
merged = list(state["pending_predictions"]) + new_pending
deduped = {(r["timestamp_utc"], r["eval_day"]): r for r in merged}
state["pending_predictions"] = trim_to_recent_days(
    list(deduped.values()), MAX_HISTORY_DAYS
)
```

The comment block above the new code explicitly cites the 2026-05-08 incident (silent-failure recovery; three runs in one day against a stalled parquet; 144 then 216 stacked predictions for the same `eval_day`; polluted the M4 promotion metrics). Future engineers who see "why are we deduping here?" land on the answer in-file.

**Rationale**: Dict-comprehension dedup is idempotent — re-running gives the same output state. New entries (`new_pending`) append AFTER existing state in `merged`, so they win in the dict comprehension. Trims by recency happen after dedup so the `MAX_HISTORY_DAYS` cap still applies. No behaviour change in the normal (parquet-advancing) case; only kicks in when a duplicate `(timestamp_utc, eval_day)` key already exists.

**Tests**: All 20 `test_update_shadow.py` tests pass. Full 177-test augur suite green. No new tests added — the smoke test (`test_first_run_produces_artifacts`) confirms the non-duplicate path; the duplicate-input regression test would require substantial fixture setup and the existing operational mitigation (state-reset script on sadalsuud) handles the rare case where this would matter in practice.

**What was NOT changed**: ARF model, LightGBM model, feature builder, CQR logic, training window, output JSON schema, dashboard rendering. The change is purely defensive on the `pending_predictions` list-merge step.

**Status**: Gotcha 2026-05-08 marked [RESOLVED]. The code-side defence pattern (dedup at write time on append-only state) is now applied; this matches the pattern in the gotcha entry's recommendation.

---

## 2026-05-18 — M4 mid-window preview: CQR healthy, low-price failure is structural, methodology ambiguity surfaces

**Trigger**: Calendar-scheduled mid-window sanity-check on M4 collection. 9 contiguous eval rows accumulated (2026-05-08 → 2026-05-16), 5 short of the 14-row formal Method run (review-by 2026-05-22 / buffer 2026-05-29 per `docs/hypothesis-log.md`).

**Pipeline health**: ✅ — cron firing on schedule (last run 2026-05-17 14:45 UTC), state file healthy, shadow JSON written, 7 CQR calibration days active, 9 contiguous eval rows. Observability hardening from 2026-05-08 is doing its job.

**Method snippet preview against 9 rows (non-binding, framework-explicit: preview ≠ Method run)**:

| Criterion | All 9 rows | 8 rows (drop 05-08 cron-shake-out) | Threshold |
|---|---|---|---|
| (a) low-price MAE ratio | 0.94 ❌ | 1.10 ❌ | ≤ 0.75 |
| (a) n_low_price hours | 35 ❌ | 28 ❌ | ≥ 50 |
| (b) mean P80 coverage | 0.722 ❌ | 0.786 ✅ | [0.75, 0.85] |
| (b) days < 0.60 | 2 ✅ | 1 ✅ | < 3 |
| (c) peak-hour ratio | 0.484 ✅✅ | 0.484 ✅✅ | ≤ 1.10 |
| overall MAE ratio | 0.58 | 0.57 | (informational) |
| live/backtest ratio | 1.41 ⚠️ | 1.34 ⚠️ | [1.0, 1.20] |

**Three threads investigated to root cause:**

**1. `last_cqr_q = 0.0` is correct behavior, not a bug.**
- Diagnostic: 7-day calibration window has 81.7% inside-band rate (target 80%); p80 of nonconformity is **−1.09 EUR/MWh** — even the 80th-percentile residual sits *inside* the band. `conformal.py:74` clamps `max(q, 0.0)` correctly.
- Implication: LGBM's nominal P10/P90 are intrinsically calibrated on the 7-day window. Criterion (b) aggregate target is structurally achievable; per-day volatility (0.21 → 1.00 range) is the residual concern.

**2. Criterion (a) low-price MAE failure has a structural cause — not data-thin.**
- Both models miss solar-driven negative midday prices badly; ARF "wins" by accident via mean-reversion bias.
- Sample evidence (eval_day=2026-05-15 low-price hours, 14 hours, h=19..h=48):
  - LGBM p50: 57-100 EUR/MWh, mean error **74 EUR/MWh**
  - ARF: 25-40 EUR/MWh, mean error **31 EUR/MWh**
  - Realized: −1 to +20 EUR/MWh
- LGBM errors scale with horizon: h≤24 mean 64 EUR/MWh, h>24 mean 81 EUR/MWh. Long-horizon weakness consistent with weather-lag feature thinning at h>48.
- ARF's accidental win: its mean-reversion toward ~30 EUR/MWh anchors closer to realized 0 than LGBM's "midday is expensive" prior (~70 EUR/MWh).
- **This is structural**, not a sample-size issue. Extending the window won't fix it. Path C (extend) is therefore *not* the framework-correct triage if (a) fails with n_low ≥ 50 on 2026-05-22.

**3. Live-vs-backtest skew (hypothesis #2): real but secondary.**
- Live MAE 17.73 / backtest h+1 MAE 13.21 = ratio 1.34, outside [1.0, 1.20] band. Roughly +10% explainable by horizon-mix (backtest h+1 only, live h+1..h+72); residual ~+24% likely freshness skew per Alternative 1 (`consolidate.py` overwrite semantics, augur#12 territory). Doesn't change the M4 decision; corroborates the post-decision investigation.

**Methodology ambiguity surfaced (relevant for 2026-05-22 read, not changeable now):**

`evaluate_one_day(eval_day=D)` scores **predictions made on D** (h+1..h+72), not **predictions for D from various horizons**. Criterion (a) plan-text "MAE on hours where realised < 30 EUR/MWh" is therefore evaluated on a 72-hour forward window where long-horizon errors dominate the low-price slice — and LGBM is structurally weak there. ARF gets scored on the same target hours but from its own earlier forecast issuance, so the comparison is apples-to-apples for *target timestamps* even though horizons differ between models. Decision deferred to 2026-05-22 interpretation: report decomposed-by-horizon as supplementary evidence; do not modify Method or eval_log schema mid-window (framework: "Don't loosen Method when the answer arrives").

**Expected 2026-05-22 outcome (pre-committed prediction, framework-allowed)**: (a) fails for structural reasons, (b) passes once 05-08 ages out of the window, (c) crushes it. **Triage path → B (park) with structural-failure-mode reason**, not C (extend window). The postmortem becomes a useful next-bet seed: longer training history to capture multi-year solar evolution, separate model heads per horizon group, or explicit solar-forecast features at long horizons.

**Verdict**: No code changes today. Findings logged here as pre-existing context for the 2026-05-22 formal Method run. Calendar hold for 2026-05-22 stands as scheduled.

---

## 2026-05-08 — M4 collection delayed 8 days by silent CLI failure; observability hardening shipped

**Trigger**: Day-7 sanity check on `ml/shadow/eval_log.jsonl` ahead of the M4 promotion vote (~2026-05-22 expected). File didn't exist; `shadow_state.json:last_run_utc` was frozen at 2026-04-30; calibration_history empty.

**Root cause**: `scripts/daily_update.sh:63` invoked `python -m ml.shadow.update_shadow --augur-dir $AUGUR_DIR`, but `update_shadow.py`'s argparse only defines `--parquet/--shadow-dir/--forecast-out`. argparse exited rc=2 every night from 2026-05-01 to 2026-05-07. Failure was hidden by three concurrent factors: shadow block runs under `set +e` (correct, ARF must not be blocked), git step uses `[ -f ... ] && git add` (correct, must tolerate missing files), and the commit message was hardcoded as "ARF + LGBM-shadow" regardless of which steps actually ran. See `memory/gotcha-log.md` top entry for the silent-failure mechanism in full.

**Impact on M4**: 7 nights of shadow-step failures = zero eval rows logged. M4 14-day window cron-effective start slipped from 2026-04-30 → **2026-05-08**. First real eval row expected 2026-05-09; promotion review **2026-05-29** (per updated `docs/hypothesis-log.md`).

**Fixes shipped (5 commits, all on main)**:
- `d620b45` — drop the rejected flag (the actual bug)
- `8c217a6` — docstring CLIs corrected, pre-flight heartbeat on `last_run_utc` (alarms if >36h), dynamic commit message reflecting `SHADOW_UPDATE_RC`/`SHADOW_EVAL_RC`/staleness, env-gated Healthchecks.io ping at end of script
- `0225fe1` — heartbeat alarms on missing/malformed state too (was only stale)
- `c135b4a` — `umask 027` + self-heal `chmod 640` on cron log file (security-auditor MEDIUM finding)

**Live wiring on sadalsuud (2026-05-08)**: `HEALTHCHECKS_SHADOW_URL` appended to `~/local_dev/augur/.env`; first ping registered (HC dashboard green); cron log mode hardened to 640. HC alerts within 25h of any shadow silence going forward.

**Bootstrap state cleanup**: A manual rehearsal of `update_shadow.py` produced a structurally-anomalous eval row (72h forced into one `eval_day=2026-04-30`, ARF archive coverage matched only 40 of 72 LGBM hours). Row was deleted from `eval_log.jsonl` and the 72 corresponding entries purged from `shadow_state.json:calibration_history`; `last_cqr_q` and `last_cqr_n_calib_days` reset to 0. Method snippet in hypothesis-log starts cleanly from real nightly data.

**Verdict**: Pipeline back online. Observability now solid for the silent-failure mode that bit. Open follow-ups (deferred): CI smoke test on `daily_update.sh`, CLI harmonization across the two shadow scripts, `update_shadow.py` pending-dedup logic (see gotcha-log "appends to pending_predictions without dedup" entry). M4 collection in progress.

---

## 2026-04-29 — LightGBM-Quantile shadow: backtest + band fix (EXP-009, EXP-010)

**Trigger**: Plan milestone 2 (`docs/lightgbm-quantile-shadow-plan.md`) — first comparison numbers vs ARF on the regime-shift period.

**What ran**: Walk-forward backtest harness (`ml/shadow/backtest.py`, `ml/shadow/features_pandas.py`) over 2026-04-01 → 2026-04-28, fitting `LightGBMQuantileForecaster` on a rolling 28-day window per evaluation day, predicting the next 24 hours with realised lag inputs. Single-horizon, perfect-lag — apples-to-apples with River ARF's `update_mae`. 24-column ARF parity feature set; `renewable_pressure` not yet included.

**Result vs ARF (apples-to-apples h+1 window 2026-04-14 → 04-28)**: 15 calendar days, ARF cron skipped 04-22 so 14 days are merge-evaluable. All MAE numbers below are h+1 perfect-lag (next-hour given realised lag inputs) — apples-to-apples with ARF's `update_mae`. Iterated 72h behaviour is a separate question and is deferred to milestone 3.

| | LightGBM | ARF (`update_mae`) |
|---|---|---|
| Mean MAE h+1 | **13.21** | **21.95** |
| Wins | **14 / 14 evaluable days** | — |
| Mean improvement | **+46 %** | — |
| Worst day (04-26, min realised −413 EUR/MWh) | 60.72 | 69.05 |
| Recovery 04-27/-28 | 12.25 / 8.67 | 27.79 / 28.96 |

LightGBM beats ARF on every evaluable day of the comparison window, including the regime-shift extreme days; the recovery on 04-27/-28 is the cleanest signal that the new architecture handles the regime that broke ARF. (LightGBM also has predictions for 04-22 with MAE 8.17, but ARF skipped that date so it's not in the merged comparison.)

**Issue surfaced — band miscalibration**: Raw P80 empirical coverage was 56.3 %, well below the [75 %, 85 %] target in plan §6 (b). Diagnostic (`ml/shadow/backtest_results/diagnose_bands.py`) showed the miss is **chronic** (24 / 28 days under target, 0 over) and **bilateral** (25 % below P10, 19 % above P90), correlated negatively with realised volatility. Pinball-loss minimization on small finite samples gives systematically narrow quantile estimates.

**Fix — split-conformal correction (EXP-010)**: `ml/shadow/conformal.py` adds CQR (Romano, Patterson, Candès 2019) with a 7-day rolling calibration window. 2x2 matrix `{28d, 56d} × {raw, CQR}` showed both CQR variants land in target (28d: 0.768, 56d: 0.765); 56d marginally improves point predictions (MAE 12.20 vs 12.83, evening peak 11.42 vs 13.26) without extra infrastructure. Per-day coverage is bimodal (over-cover calm, under-cover volatile) but the 14-day aggregate is stably 0.775 — and the 14-day aggregate is what plan §6 actually measures.

**Decision — final design for milestone 3**: `window_days=56` + CQR(7-day calibration, target 0.80). Plan §6 readings:

- (a) MAE on realised < 30 EUR/MWh ≥ 25 % better than ARF — **Likely PASS**, formally TBD (ARF slice MAE not in `metrics_history.csv`; milestone 3 cron will log it alongside).
- (b) P80 empirical coverage in [75 %, 85 %] — **PASS** (0.775 over the 14-day window).
- (c) Weekday evening peak (16-19 UTC) MAE ≤ +10 % of ARF — **PASS** (11.42 vs ARF 21.95 mean).

**Open items for milestone 3** (gathered from this work + a review battery on 2026-04-29):

- **HMAC-sign pickle artifacts before sadalsuud writes one.** `LightGBMQuantileForecaster.load` uses `pickle.load` with no integrity check; reuse existing `HMAC_KEY_B64` infrastructure (precedent: `utils/secure_data_handler.py`). Security MEDIUM, prereq for any cron landing.
- **ARF slice-MAE logging in cron** so promotion criterion (a) becomes formally evaluable rather than "Likely PASS, formally TBD".
- **`renewable_pressure` ablation** on the 56d_cqr backtest harness before the 14-day shadow window starts.
- **Per-day coverage caveat for criterion (b)**. Aggregate P80 = 0.775 passes [75%, 85%], but 04-25 / 04-26 (the regime-shift days) sit at ~0.46 / ~0.50 even with CQR. Show per-day alongside aggregate in any promotion doc; consider ACI (Gibbs & Candès 2021) if per-day stability becomes a criterion.
- **Always state h+1 qualifier with MAE headlines** until iterated multi-horizon validation lands.
- Code nits worth folding in along the way: warning instead of silent skip on short training windows in `backtest.py:73`; `pd.to_datetime(..., utc=True)` in `compute_metrics`; build prediction DataFrames from `X_eval.index` instead of positional `zip`.

**Branch**: `feat/lightgbm-shadow`. ARF cron continues to drive the dashboard.

**Artifacts**:
- `ml/shadow/backtest_results/summary.md` — milestone 2 detailed summary
- `ml/shadow/backtest_results/milestone_2_5_summary.md` — milestone 2.5 detailed summary
- `ml/shadow/backtest_results/predictions.parquet`, `predictions_28d.parquet`, `predictions_56d.parquet` — full per-hour predictions
- `ml/shadow/backtest_results/comparison.csv`, `matrix_summary.csv`, `band_diagnostic.csv`, `matrix_per_day.csv`
- `experiments/registry.jsonl` — EXP-009 (backtest), EXP-010 (CQR)

---

## 2026-04-28 — River ARF retired (end-of-run)

**Trigger**: Live `mae` climbed from 12.16 (04-21) to 35.58 (04-28) — roughly 3× the post-warmup baseline. Forecast forensics on the 04-25 → 04-28 archives localised the failure to the 09–13 UTC solar trough where the model overpredicts by 55–80 EUR/MWh while realised prices crash to −20 to −30 EUR/MWh.

**Decision**: Retire `River ARFRegressor`. The failure is structural, not tunable: tree ensembles predict the mean of leaf-bound training samples, so leaves never trained on negative prices cannot output negative values. Compounded by `ml/update.py:337` clamping the lower confidence band at 0, the entire prediction-plus-uncertainty channel is incompatible with a regime that now produces ~20% negative quarter-hourly prices.

**Replacement direction**: LightGBM with quantile (pinball) loss, retrained nightly on a rolling window. Shadow-mode validation alongside ARF for ≥2 weeks before promotion. Plan to be drafted separately.

**Artifacts**:
- `docs/river-arf-retrospective.md` — neutral postmortem with 5 figures (trajectory, peak-day forecast vs actual, hour-of-day bias, negative-price prevalence, distribution shift).
- `docs/figures/arf-retrospective/data/` — 35-row daily metrics CSV, 25-row metrics_history CSV, 4 forecast archives, MANIFEST.
- `experiments/registry.jsonl` — EXP-008 records the retirement decision; EXP-001 → EXP-007 back-fill the full ARF lifecycle for future citation.

**Status**: ARF cron continues to run (do not remove infrastructure prematurely); replacement to land in a future EXP-009 entry.

---

## 2026-04-14 — Forecast collapse: model outputs flat mean

**Trigger**: Noticed the live forecast on the dashboard barely moves — temporal price swings are suppressed. The model outputs what looks like an average price estimate regardless of time of day.

**Evidence**:

| Metric | Value |
|--------|-------|
| Actual price range (buffer, 200 pts) | -2.09 to 213.31 EUR/MWh (range 215) |
| 72h forecast range | 108.94 to 133.08 EUR/MWh (range 24) |
| Forecast std dev | 5.12 EUR/MWh |
| Range compression | ~89% — nearly flat output |

Daily `update_mae` has been running 25-36 EUR/MWh since April 3, roughly 2-3x the warmup-era MAE.

### Root cause 1: Recursive forecast loop (architectural)

`generate_forecast()` in `ml/update.py:258-298` predicts hour-by-hour and **feeds each prediction back as a lag feature for the next hour**. Combined with MSE-based tree splits (River ARF default), predictions regress toward the mean at every step. Over 72 hours this compounds into a flat line around ~119 EUR/MWh.

The exchange day-ahead prices (~24h horizon) partially mask this — the first day of forecast has real lags and looks reasonable. But beyond the exchange horizon, every lag is a stale prediction, and the forecast collapses.

### Root cause 2: Frozen aggregate metrics (bug)

`update_model()` in `ml/update.py:191-195` writes the metrics history but copies `mae` and `last_week_mae` from existing state instead of recalculating them:

```python
"mae": round(state["metrics"].get("mae", mae), 2),        # frozen at 13.8 since warmup
"last_week_mae": round(state["metrics"].get("last_week_mae", mae), 2),  # frozen at 21.12
```

These have been stuck at warmup values (13.8 / 21.12) since April 2, while real daily errors were 25-39. The degradation was invisible in the dashboard metrics.

### Possible remedies (under consideration)

1. **Direct multi-horizon models** — Train separate models for h+1, h+6, h+24 etc., each predicting directly from current known features. No recursive lag feeding, no mean collapse.
2. **Exchange price anchoring** — Beyond the exchange horizon, anchor lags to last known exchange price rather than recursive predictions.
3. **Loss function change** — ARFRegressor uses variance reduction (MSE). A MAE/quantile objective would reduce mean-reversion bias, but River ARF doesn't expose this easily.
4. **Fix the frozen metrics** — Recalculate `mae` and `last_week_mae` from `error_history` each update so degradation is visible immediately.

### Context

- Model was rolled back to pre-contamination checkpoint on April 2 (commit `27b9876`) after ENTSO-E collector outage caused 5 days of training on wrong price series (Energy Zero consumer prices instead of wholesale).
- Model has been retraining daily since then (5703 samples as of April 13), but the recursive forecast architecture means even a healthy model will produce flat multi-day predictions.
- Model pickle shrank from 1.75 MB to 616 KB at some point — may indicate tree pruning or state loss.

---

## 2026-04-14 — Fix: variance-preserving recursion + metrics bug

**Changes** (`ml/update.py`):

1. **Fixed frozen metrics bug** — `mae` and `last_week_mae` were copied from stale warmup values on every update instead of being recalculated. Now recomputed from `error_history` (last 500 errors for MAE, last 168 for weekly MAE) on each daily run.

2. **Historical rolling stats override** — Added `_historical_rolling_stats(fb)` helper that computes typical price mean/std by hour-of-day from the real price buffer. During recursive forecasting (beyond exchange horizon), `price_rolling_mean_6h` and `price_rolling_std_6h` are overridden with these historical values instead of being computed from artificial predictions. Prevents the rolling stats from collapsing to near-zero variance.

3. **Calibrated noise injection** — When feeding a prediction back as a lag for the next forecast hour, noise drawn from `N(0, ewm_std)` is added. `ewm_std` is the model's own exponentially-weighted error standard deviation (already computed for confidence bands). This prevents correlated lag sequences from converging to the mean. RNG seeded per-hour for reproducibility.

**Rationale**: The model was trained on real data with natural price variance. Recursive predictions created an out-of-distribution input pattern (smooth, correlated lags and collapsed rolling stats). These fixes restore realistic variance in the feature space without changing the model itself.

**What was NOT changed**: Model training path (warmup + learn_one), feature builder, exchange-horizon forecasts (first ~24h still use real lags), model artifact.

**Expected outcome**: Wider forecast range beyond exchange horizon. Actual improvement measurable after next daily update on sadalsuud.

---

## 2026-04-30 — EXP-009 milestone 3: LightGBM-Quantile shadow pipeline shipped + deployed

**Changes** (merge `84a1af4`/`f77aa5d` to `main`, 14 commits — 6 step + 3 review-fixup A/B/C + 2 prereq + 1 dry-run-fix D + 1 hypothesis-log seed):

1. **`ml/shadow/lightgbm_quantile.py`** — `MultiHorizonLightGBMQuantileForecaster`: 9 LGBM models (3 horizon groups × 3 quantiles), direct multi-horizon via `horizon_h` as a stacked feature. No recursive lag substitution → no variance-collapse pathology. Default groups `(1,6), (7,24), (25,72)`.

2. **`ml/shadow/secure_pickle.py`** — HMAC-SHA256 sidecar (`*.pkl.hmac`) sign/verify. Used by `MultiHorizonLightGBMQuantileForecaster.save/load` so deserialization never runs on an unverified file. Closes the unsigned-pickle RCE risk before sadalsuud writes its first artifact.

3. **`ml/update.py`** — added `error_prices` parallel array + `mae_at_low_price` (slice-MAE on realised < 30 EUR/MWh) so promotion criterion (a) is formally evaluable from ARF state.json. Backward-compatible with legacy state.json (only tail-aligned window contributes).

4. **`ml/shadow/update_shadow.py`** — nightly retrain + predict orchestration. Backfills realised prices into `pending_predictions` from prior runs, computes CQR q (7-day calibration, target 0.80), trains on rolling 56-day window, predicts 72 horizons, widens bands by q. Writes signed pickle + `shadow_state.json` + `static/data/augur_forecast_shadow.json` (NOT consumed by dashboard during shadow phase per plan §5).

5. **`ml/shadow/evaluate_shadow.py`** — daily LightGBM-vs-ARF metrics logger. Cross-references shadow predictions against ARF archives at `ml/forecasts/{YYYYMMDD_HHMM}_forecast.json`, writes one JSON line per fully-realised eval day to `ml/shadow/eval_log.jsonl`. Schema includes `n_low_price_hours`, `lightgbm_peak_hour_mae`, `arf_peak_hour_mae` so all three plan §6 criteria are evaluable directly from the log.

6. **`scripts/daily_update.sh`** — extended with the shadow block under `set +e` so shadow failures don't block the ARF commit. Re-consolidates parquet from energyDataHub each run. Best-effort-adds shadow artifacts (`shadow_state.json`, `augur_forecast_shadow.json`, `eval_log.jsonl`); `shadow_model.pkl` + sidecar are gitignored (regenerated nightly from rolling window).

7. **Path-fix in `ml/update.py:540`** — ARF forecast archive_dir was `output_dir.parent / ml / forecasts` (resolved to `static/ml/forecasts`); now `output_dir.parent.parent / ml / forecasts`. Without this, eval_log.jsonl could never populate `arf_*` fields. Sadalsuud archive history migrated 2026-04-30.

8. **`docs/hypothesis-log.md`** — adopted from ovr.news pattern, M4 promotion-decision hypothesis seeded with falsification criteria pre-committed (concrete numbers, failure-mode signals, runnable Method snippet).

**Reviews**: two rounds of review battery (code-reviewer, security-auditor, data-analyzer, deployment-troubleshooter). Round 1 found 2 HIGH (archive path, gitignore exception), 1 HIGH security (`.load` HMAC bypass), 1 medium (xargs `.env`), 5 medium/low — all CLOSED in fixups A/B/C. Round 2 found 1 BLOCKER (`.env` source under `set -e` would kill ARF cron) — closed in fixup D. Two open caveats deferred to documentation: exogenous-freshness skew (round-1) and bimodal P80 coverage (M2.5).

**Deployment**: merged to `main` 2026-04-30; sadalsuud pulled the merge after archive-path migration (`mv static/ml/forecasts/* ml/forecasts/`); manual dry-run of consolidate + update_shadow + evaluate_shadow succeeded end-to-end. Caught one real bug (lightgbm not in venv, installed manually). First production cron run with the new pipeline: 2026-05-01 14:45 UTC.

**Tests**: 158 passing (was 35 pre-M3). New suites: `test_lightgbm_quantile.py` (37 incl. multi-horizon + HMAC enforcement), `test_secure_pickle.py` (22), `test_update_slice_mae.py` (10), `test_update_shadow.py` (20), `test_evaluate_shadow.py` (22), `test_update_archive_path.py` (1).

**M4 expected outcome**: 14 days of `eval_log.jsonl` rows. Hypothesis log pre-commits: criterion (a) ≥25% relative MAE win at realised<30 with ≥50 low-price hours; (b) coverage in [0.75, 0.85] AND fewer than 3 days below 0.60; (c) peak-hour delta ≤ +10% relative. First eval row covers `eval_day=2026-04-30`. Cron will continue ARF in production until M5 (promotion decision) ratifies replacement.

**What was NOT changed**: ARF model architecture, dashboard frontend (still reads `augur_forecast.json`), Netlify build pipeline. Shadow artifacts are committed to the repo but not consumed by the dashboard.

---
