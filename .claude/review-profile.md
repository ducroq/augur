# Review profile — Augur

Read by `review-changes` Step 1. **This file is the project's half of that skill**: the
skill is the machinery and ships identically everywhere; everything below is specific to
this repo and never travels. Template: `templates/review-profile.md` in agent-ready-projects.

Adopted 2026-10-29, reversing the 2026-10-28 decline of v1.40.0 (`5bef4f9`). `/code-review`
is still useful for code bugs, but it doesn't know this repo's guarantees, and the
pre-commitment record has none of its own.

## Risk tiers

| Tier | File patterns | Depth |
|------|-------------|-------|
| **HIGH** | `.gitignore`, `/netlify.toml`, `/hugo.toml`, `/requirements.lock`, `/requirements.txt`, `/requirements-netlify.txt`, `/decrypt_data_cached.py`, `utils/secure_data_handler.py`, `scripts/*.sh`, `scripts/notify_email.py`, `scripts/systemd/**`, `scripts/audit_registry.py`, `scripts/render_results.py`, `ml/shadow/*.py`, `ml/data/consolidate.py`, `ml/update.py`, `static/js/**`, `layouts/**`, `experiments/registry.jsonl`, `docs/experiment-backlog.md`, `docs/hypothesis-log.md`, `docs/experiment-results.md`, `.claude/review-profile.md` | Full battery (3-4 lenses) |
| **MEDIUM** | `ml/**`, `scripts/**`, `tests/**`, `utils/**`, `static/**`, `content/**`, `config/**`, `experiments/**`, `.github/**`, `/requirements*.txt`, `/package*.json`, `docs/decisions/**`, `docs/RUNBOOK.md`, `/CLAUDE.md` | Two lenses (adversarial + doc-accuracy) |
| **LOW** | `memory/**`, `docs/**`, `/README.md`, `/LICENSE` | One lens (adversarial) |

`**` crosses directory levels; a leading `/` anchors to the repo root. **The most specific
matching pattern wins.** Where no pattern is more specific than another, take the highest tier.

Why the HIGH row holds what it does:

- **Production and deploy**: the sadalsuud job and its units, the Netlify build, the
  production model code under `ml/shadow/` and the dashboard JS reach production overnight,
  with nobody watching.
- **Data integrity**: decryption, HMAC and the pickle sidecar. CLAUDE.md calls this
  non-negotiable.
- **The pre-commitment record**: the backlog, the hypothesis log, the registry and the two
  scripts that check them. A Method edited after its data is seen can't be un-seen, and git
  history doesn't restore trust in the result.

`ml/shadow/` also holds experiment folders (`expNNN_*/summary.json`) and the nightly logs.
Those fall to the MEDIUM `ml/**` row, because `ml/shadow/*.py` doesn't match them. Generated
files the nightly job commits (`ml/models/**`, `static/data/**`, `ml/shadow/*.jsonl`) are
MEDIUM. A hand edit to them is a carve-out below.

## Guarantee surfaces

⚠️ **Every path here must sit in the HIGH row above.** Checked 2026-10-29: all do.

- `/netlify.toml`, `scripts/netlify_build.sh`: the build runs `decrypt_data_cached.py --force`
  (ADR-003). Without it, webhook builds serve stale cached data.
- `/decrypt_data_cached.py`, `utils/secure_data_handler.py`: HMAC is verified **before**
  decryption. The build and nightly paths read keys only from `ENCRYPTION_KEY_B64` /
  `HMAC_KEY_B64`. (The handler's `__main__` self-test reads `secrets.ini`, which is
  gitignored; it isn't on either path.)
- `ml/shadow/secure_pickle.py`: the HMAC sidecar is verified before any unpickle.
- `scripts/daily_update.sh`: every fault reaches the commit subject as `[ALARM: …]` and every
  result as `[NOTE: …]`. The ARF step stays non-fatal, and the job still commits and pushes
  when a step fails.
- `scripts/wait_for_edh.sh`: never fail-closed; deadline 03:00 UTC; the clause semantics in
  its header, including clause (c) (augur#34).
- `scripts/heartbeat_check.sh`, `scripts/alert_failure.sh`, `scripts/notify_email.py`,
  `scripts/systemd/**`: a dead unit, a missed commit (>30h), a disabled timer, an unpushed
  commit or an ALARM marker each produce an alert.
- `ml/shadow/*.py`, `ml/data/consolidate.py`, `ml/update.py`: train/validation/test splits are
  temporal, never random. `t0` comes from `latest_feasible_t0`. The forecast JSON keeps the
  fields `static/js/**` reads.
- `static/js/**`, `layouts/**`: times are rendered with `Intl.DateTimeFormat` and
  `timeZone: 'Europe/Amsterdam'`, never a fixed offset. The swap point stays
  `dashboard.js:loadAugurForecast`.
- `docs/experiment-backlog.md`, `docs/hypothesis-log.md`: **a pre-committed Method body is
  never edited once committed.** A changed method is a new, dated entry. In the hypothesis
  log, dated notes and addenda may follow a Method. In the backlog, check 5 hashes the
  **whole** `## EXP-NNN` section, so anything added later goes in a section of its own
  (`## Addendum YYYY-MM-DD to EXP-NNN`), which check 5 hashes and which must be pinned in
  `PRECOMMIT_REV_BY_ID` too. Check 5 covers the backlog only; the hypothesis log rests on
  review.
- `experiments/registry.jsonl`, `scripts/audit_registry.py`, `scripts/render_results.py`: the
  registry is append-only for decided experiments. The audit exits non-zero on drift,
  including check 5, the sha256 of backlog Method bodies. `docs/experiment-results.md` is only
  ever generated.
- `.gitignore`: `secrets.ini`, `.env` and `.env.*`, `*.key`, and every `.claude/` at any
  depth (except this file at the root) stay untracked.
- `/requirements.lock`: the nightly job's venv (`scripts/bootstrap_venv.sh`) runs the pinned
  versions. ⚠️ The Netlify build doesn't: `scripts/netlify_build.sh` installs `cryptography`
  unpinned, `/requirements-netlify.txt` is read by nothing, and Netlify probably also
  auto-installs the root `/requirements.txt` (loose ranges) because `PYTHON_VERSION` is set.
  That last part is unverified: check a deploy log. Either way it's a known gap, not a
  guarantee.
- `.claude/review-profile.md`: every guarantee surface above stays in the HIGH row.

## Test baseline

```bash
.venv/bin/python -m pytest tests/ -q        # bare `python` fails collection (no deps); use the venv
.venv/bin/python scripts/audit_registry.py  # when experiments/ or the backlog/hypothesis log changed
.venv/bin/python scripts/render_results.py --check
```

Baseline 2026-10-29: 389 passed. The audit passes with 12 standing WARNs, all empty
`commits[]` (EXP-008, 011, 012, 013, 014, 018, 019, 020, 035, 036, 037, 039). A 13th WARN
is new.

## Always-full-depth carve-outs (project additions)

- `scripts/netlify_build.sh` (which carries the `--force`) and `/netlify.toml` (which calls
  it): one dropped flag serves stale data on every webhook build.
- `/requirements.lock`: one changed pin moves production's environment overnight.
- `ml/models/shadow/shadow_state.json`, `ml/models/state.json`: a hand edit (anything not
  committed by the nightly job) rewrites calibration history, t0 hold-back state or the
  surcharge cache that production reads.
- **Any edit inside an existing Method block** (the paragraph opening with `**Method**`) of `docs/experiment-backlog.md` or
  `docs/hypothesis-log.md`, however small: one changed number in a gate is a moved goalpost.

## Project lenses

- `pre-commitment` — fires on: `docs/experiment-backlog.md`, `docs/hypothesis-log.md`,
  `experiments/registry.jsonl`
  *You are checking the integrity of pre-registered experiments (ADR-007). (1) Diff every
  Method, Gates and Alternatives block that existed at the baseline: report any byte that
  changed inside one as REFUTED. In the hypothesis log, notes added after a block are fine.
  In the backlog, any change inside an existing `## EXP-NNN` section is REFUTED, because
  check 5 hashes the whole section. Also check that every new backlog entry is pinned in
  `PRECOMMIT_REV_BY_ID` to a commit that stays reachable (not amended, rebased or left
  unpushed). (2) For each new pre-commit, check that it can actually be decided before data is
  seen. Every gate is numeric with a stated direction and population. Every arm, column,
  script and function it names exists on disk. Nothing in it reads as written after a peek:
  look for numbers that could only come from the data it is about to score. (3) Check that
  numbers quoted from earlier experiments match `experiments/registry.jsonl` or the
  committed `summary.json`. (4) Check that the entry doesn't spend fresh vintages that the
  standing calendar reserves for another entry. A positive looks like a gate threshold that
  differs from the baseline revision, a function name that `grep` can't find, or a quoted
  effect size that disagrees with its registry row.*

## Project additions to the shipped lens prompts

- **adversarial**: Attack effect sizes quoted without the floor. Since augur#29, any skill
  claim must say which baseline it is relative to; check EXP-036's correction in
  `memory/model-class-findings.md`. Attack any time handling that assumes a fixed UTC offset
  or a 24-hour DST day. Attack any split, window or feature that could see the future of
  `t0`. That includes covariates the harness reads at vintage-overwritten values (EXP-028a
  Alternative 4).
- **doc-accuracy**: Check numbers against `experiments/registry.jsonl` and the committed
  `ml/shadow/expNNN_*/summary.json`, not against other prose, because prose here quotes
  prose.

## Reviewer model

None set: every lens runs on the session's model.

## Project procedure kept with the profile

When `experiments/`, `docs/experiment-backlog.md`, `docs/hypothesis-log.md` or
`docs/experiment-results.md` changed, run the two checks in **Test baseline** before the
lenses. Both exit non-zero on drift, and a lens should not spend tokens on what they settle.
