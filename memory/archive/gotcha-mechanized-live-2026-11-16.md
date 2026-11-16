# Gotcha log: Mechanized rows, live with no sightings (archive)

Moved out of `memory/gotcha-log.md` ## Mechanized on 2026-11-16, unedited, to cut the read surface. Each check is live (a seeded positive made it fail) and had 0 occurrences at the move. A sighting moves its row back with the count.

| Date | Finding shape | Check | Status | Occurrences |
|------|---------------|-------|--------|-------------|
| 2026-11-16 | Check 5 read a failed `git show` of an archive as an absent file, and kept only the last of two same-id sections in one file | `tests/test_audit_registry.py::test_an_unreadable_home_at_head_fails_closed`, `::test_two_copies_in_one_file_fail` | live (seeded both) | 0 |
| 2026-11-15 | `git log --grep='^X'` matches any message line, so a body quoting a daily subject counts as that day's commit; a word-split awk also accepts `Daily   update` | `tests/test_daily_slot_done.py::test_body_line_does_not_count`, `::test_only_literal_prefix_counts` | live (seeded word-split awk) | 0 |
| 2026-11-15 | The heartbeat's freshness check uses the same `--grep='^Daily update'` (body lines count) | `tests/test_heartbeat_check.py::TestDailyCommitSelection::test_body_quote_does_not_mask_the_last_runs_alarm` | live (seeded: old `--grep` heartbeat) | 0 |
| 2026-11-10 | A staleness check that skips whole lines to ignore a commit hash also ignores what else is on them, or the same text in free-form notes | `tests/test_render_results.py::test_check_catches_tampered_registry_state_line`, `::test_hash_mask_does_not_hide_note_drift` | live | 0 |
| 2026-11-07 | A dashboard forecast step exits 0 with only some of its 72 hours filled, and the commit subject stays clean | `PROFILE_HOURS` guard in `scripts/daily_update.sh` (`[ALARM: profile forecast Nh of 72]`); seeded 24h file made it fire | live | 0 |
| 2026-10-29 | An unreachable pre-commit pin skipped check 5 for **every** entry with a WARN and still exited 0 | `scripts/audit_registry.py` check 5: `CalledProcessError` is a FAIL naming the unread revision | live (seeded `deadbee`) | 0 |
| 2026-10-29 | Run before committing, check 5 hashed HEAD only, so an uncommitted edit to a pinned Method passed | `scripts/audit_registry.py` check 5: the working-tree backlog is hashed too | live (seeded G2 30 → 25) | 0 |
| 2026-10-29 | A dated addendum that supersedes a pinned Method sat in a section check 5 never hashed, so it could be edited after results landed | `scripts/audit_registry.py` `method_sections`: `## Addendum YYYY-MM-DD to EXP-NNN` is keyed `EXP-NNN/addendum-DATE` and must be pinned | live (seeded 28 → 14 days) | 0 |
| 2026-11-06 | A pinned entry added after `PRECOMMIT_REV`, lost from the backlog, was in no key set and passed unchecked | `scripts/audit_registry.py` check 5: `PRECOMMIT_REV_BY_ID` joins the key set; `tests/test_audit_registry.py` seeds the loss | live | 0 |
