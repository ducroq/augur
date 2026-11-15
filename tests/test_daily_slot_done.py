"""Tests for scripts/daily_slot_done.sh, the ExecCondition behind the timer's boot trigger (augur#39).

The contract:
  * the normal 16:30 UTC trigger always runs (yesterday's commit is before the slot)
  * a boot after the slot's commit landed skips (exit 1, a clean skip)
  * a boot after a run was killed mid-way runs again (2026-11-13)
  * the slot comes from commit TIME, not the subject's date, so a commit after
    midnight UTC still counts for the previous evening's slot
  * only the SUBJECT counts: a body line starting "Daily update" doesn't
  * a slot commit that never reached origin/main doesn't count (reboot between
    commit and push), so the job runs again
  * fails open: no repo, no Daily update commit, or a bad clock value means run
  * AUGUR_FORCE_RUN=1 always runs
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "daily_slot_done.sh"


def epoch(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "augur"
    root.mkdir()

    def git(*args, env=None):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                       env={**os.environ, **(env or {})})

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")

    def commit(subject, when, body=None, push=True):
        stamp = f"@{epoch(when)} +0000"
        msg = ["-m", subject] + (["-m", body] if body else [])
        git("commit", "-q", "--allow-empty", *msg,
            env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        if push:  # stand-in for a push: move the tracking ref
            git("update-ref", "refs/remotes/origin/main", "HEAD")

    class Repo:
        pass
    r = Repo()
    r.path, r.commit = root, commit
    return r


def run(target, now, **extra):
    augur_dir = getattr(target, "path", target)
    env = {k: v for k, v in os.environ.items() if k != "AUGUR_FORCE_RUN"}
    env.update(AUGUR_DIR=str(augur_dir), NOW_EPOCH=str(epoch(now)), **extra)
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    return r.returncode, r.stdout


def test_normal_timer_trigger_runs(repo):
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    rc, out = run(repo, "2026-11-13 16:30")
    assert rc == 0, out


def test_boot_after_completed_run_skips(repo):
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23")
    rc, out = run(repo, "2026-11-15 06:00")
    assert rc == 1, out
    assert "skipping" in out


def test_boot_after_killed_run_reruns(repo):
    # 2026-11-13: last commit is the 11-12 run, box resets at 16:42 UTC mid-gate.
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    rc, out = run(repo, "2026-11-13 16:48")
    assert rc == 0, out


def test_boot_next_morning_after_missed_slot_runs(repo):
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    rc, _ = run(repo, "2026-11-14 07:00")
    assert rc == 0


def test_after_midnight_commit_counts_for_previous_slot(repo):
    # The gate polls to 03:00 UTC, so the 11-09 slot's commit can land on 11-10 UTC.
    repo.commit("Daily update 2026-11-09 — ARF OK", "2026-11-10 00:30")
    rc, _ = run(repo, "2026-11-10 08:00")
    assert rc == 1


def test_boot_before_slot_uses_previous_slot(repo):
    # Boot at 10:00 UTC; the run from yesterday's 16:30 slot is done -> skip.
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23")
    rc, _ = run(repo, "2026-11-15 10:00")
    assert rc == 1


def test_non_daily_commits_are_ignored(repo):
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    repo.commit("Curate 2026-11-13: something", "2026-11-13 18:00")
    rc, _ = run(repo, "2026-11-13 19:00")
    assert rc == 0


def test_fails_open_without_repo(tmp_path):
    rc, out = run(tmp_path / "nope", "2026-11-15 06:00")
    assert rc == 0
    assert "fail open" in out


def test_fails_open_without_daily_commit(repo):
    repo.commit("Initial", "2026-11-01 10:00")
    rc, _ = run(repo, "2026-11-15 06:00")
    assert rc == 0


def test_force_run_overrides(repo):
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23")
    rc, _ = run(repo, "2026-11-15 06:00", AUGUR_FORCE_RUN="1")
    assert rc == 0


def test_body_line_does_not_count(repo):
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    repo.commit("Document incident", "2026-11-13 18:00",
                body="Daily update 2026-11-13 — quoted from the log")
    rc, out = run(repo, "2026-11-13 19:00")
    assert rc == 0, out


def test_unpushed_slot_commit_reruns(repo):
    repo.commit("Daily update 2026-11-13 — ARF OK", "2026-11-12 22:06")
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23", push=False)
    rc, out = run(repo, "2026-11-15 06:00")
    assert rc == 0, out
    assert "not on origin/main" in out


def test_no_tracking_ref_reruns(tmp_path, repo):
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23")
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/main"],
                   cwd=repo.path, check=True)
    rc, _ = run(repo, "2026-11-15 06:00")
    assert rc == 0


def test_bad_clock_value_fails_open(repo):
    repo.commit("Daily update 2026-11-14 — ARF OK", "2026-11-14 20:23")
    env = {k: v for k, v in os.environ.items() if k != "AUGUR_FORCE_RUN"}
    env.update(AUGUR_DIR=str(repo.path), NOW_EPOCH="invalid")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fail open" in r.stdout


@pytest.mark.parametrize("subject", ["Daily   update bogus", "Daily\tupdate bogus",
                                     "Daily update", "daily update 2026-11-14"])
def test_only_literal_prefix_counts(repo, subject):
    repo.commit("Daily update 2026-11-12 — ARF OK", "2026-11-12 22:06")
    repo.commit(subject, "2026-11-14 20:23")
    rc, out = run(repo, "2026-11-15 06:00")
    assert rc == 0, out
