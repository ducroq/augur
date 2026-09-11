"""Tests for scripts/heartbeat_check.sh — the daily liveness check's NOTIFICATION policy.

The check itself was already covered by operation; what was not covered, and what
these tests pin, is when it is allowed to send. Check 4 reads an immutable commit
subject, so before 2026-09-01 a soft failure re-alarmed every single morning until
a clean run landed — during the 2026-08-31 ENTSO-E outage that was a fresh
identical email each day about a condition already known and already being worked.

The contract under test:
  * a new finding SHAPE always sends immediately
  * an unchanged shape is suppressed, but re-sent every REMIND_DAYS with a day
    counter, so a persisting problem cannot decay into silence
  * shape is the marker TYPE, not its text: `t0 jumped 2d` and `t0 jumped 3d` are
    one episode, while a marker type not seen in the episode breaks through
  * the reminder clock arms only on a CONFIRMED send, so a degraded channel
    retries rather than buying itself three days of quiet
  * clearing sends exactly one recovery notice, so silence is never ambiguous

The script is driven as a subprocess against a synthetic AUGUR_DIR: a real git
repo, a stubbed notify_email.py that records what it was asked to send, and a
stubbed `systemctl` on PATH so the timer checks are controlled rather than
reflecting whatever the test box happens to be running.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

REAL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "heartbeat_check.sh"

NOTIFY_STUB = """\
import sys
out = open(sys.argv[2] if len(sys.argv) > 2 else "{record}", "a")
out.write("SUBJECT\\t" + sys.argv[1] + "\\n")
out.write("BODY\\t" + sys.stdin.read().replace("\\n", "\\\\n") + "\\n")
out.close()
print("{result}")
"""

SYSTEMCTL_STUB = """\
#!/usr/bin/env bash
case "$1" in
  is-enabled) echo "{enabled}" ;;
  is-active)  echo "{active}" ;;
  show)       echo "n/a" ;;
  *)          echo "" ;;
esac
exit 0
"""


class Env:
    """A synthetic AUGUR_DIR the real script can be pointed at."""

    def __init__(self, tmp_path, notify_result="SENT: to test@example.com",
                 enabled="enabled", active="active"):
        self.root = tmp_path / "augur"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "logs").mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.record = tmp_path / "sent.txt"
        self.state = tmp_path / "hb_state"

        (self.root / "scripts" / "heartbeat_check.sh").write_text(
            REAL_SCRIPT.read_text())
        (self.root / "scripts" / "notify_email.py").write_text(
            NOTIFY_STUB.format(record=self.record, result=notify_result))
        sysctl = self.bin / "systemctl"
        sysctl.write_text(SYSTEMCTL_STUB.format(enabled=enabled, active=active))
        sysctl.chmod(0o755)

        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True,
                       capture_output=True)

    def commit(self, subject):
        (self.root / "f.txt").write_text(str(time.time()))
        self._git("add", "-A")
        self._git("commit", "-q", "-m", subject)

    def run(self, remind_days=3):
        env = dict(os.environ)
        env.update({
            "AUGUR_DIR": str(self.root),
            "HEARTBEAT_STATE": str(self.state),
            "REMIND_DAYS": str(remind_days),
            "PATH": f"{self.bin}:{env['PATH']}",
        })
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "heartbeat_check.sh")],
            env=env, capture_output=True, text=True)

    @property
    def sent(self):
        if not self.record.exists():
            return []
        return [l.split("\t", 1)[1]
                for l in self.record.read_text().splitlines()
                if l.startswith("SUBJECT")]

    @property
    def log(self):
        p = self.root / "logs" / "alerts.log"
        return p.read_text() if p.exists() else ""

    def shape(self):
        return self.state.read_text().split("\t")[0]

    def set_notify_result(self, result):
        """Change what the stubbed channel reports, mid-test."""
        (self.root / "scripts" / "notify_email.py").write_text(
            NOTIFY_STUB.format(record=self.record, result=result))

    def backdate(self, days):
        """Age the open episode by `days`, as if that many mornings had passed."""
        fp, first, last = self.state.read_text().strip("\n").split("\t")
        shift = days * 86400
        self.state.write_text("\t".join([
            fp,
            str(int(first) - shift),
            str(int(last) - shift) if last else "",
        ]) + "\n")


ALARM = "Daily update 2026-08-31 — ARF OK | shadow rc=0/eval rc=0 [ALARM: t0 jumped 2d]"
CLEAN = "Daily update 2026-09-02 — ARF OK | shadow rc=0/eval rc=0"


class TestCleanRun:
    def test_clean_commit_sends_nothing_and_writes_no_state(self, tmp_path):
        env = Env(tmp_path)
        env.commit(CLEAN)
        r = env.run()
        assert r.returncode == 0
        assert env.sent == []
        assert "heartbeat OK" in env.log
        assert not env.state.exists()


class TestNewEpisode:
    def test_alarm_marker_sends_immediately(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        r = env.run()
        assert r.returncode == 0
        assert len(env.sent) == 1
        assert "heartbeat FAILED" in env.sent[0]
        assert "(new," in env.log or "heartbeat ALERT (new" in env.log

    def test_shape_records_marker_type_not_text(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        assert env.shape() == "soft:t0-jumped"


class TestSuppression:
    def test_unchanged_shape_next_morning_is_suppressed(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.backdate(1)
        env.run()
        assert len(env.sent) == 1, "second morning must not re-send"
        assert "suppressed" in env.log

    def test_same_marker_type_different_count_is_the_same_episode(self, tmp_path):
        """`t0 jumped 2d` then `t0 jumped 3d` is one ongoing problem, not two."""
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.backdate(1)
        env.commit("Daily update 2026-09-01 — shadow rc=0/eval rc=0 [ALARM: t0 jumped 3d]")
        env.run()
        assert len(env.sent) == 1
        assert "suppressed" in env.log

    def test_reminder_fires_after_remind_days_with_day_counter(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run(remind_days=3)
        env.backdate(3)
        env.run(remind_days=3)
        assert len(env.sent) == 2
        assert "STILL FAILING" in env.sent[1]
        assert "day 4" in env.sent[1]


class TestBreakThrough:
    def test_new_marker_type_breaks_through_same_day(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.commit("Daily update 2026-09-01 — ARF OK | shadow rc=1/eval rc=skip")
        env.run()
        assert len(env.sent) == 2, "a marker type not in this episode must alert"
        assert env.shape() == "soft:rc-nonzero,rc-skip"

    def test_timer_failure_breaks_through_an_open_soft_episode(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.bin.joinpath("systemctl").write_text(
            SYSTEMCTL_STUB.format(enabled="disabled", active="active"))
        env.bin.joinpath("systemctl").chmod(0o755)
        env.run()
        assert len(env.sent) == 2
        assert "timer-not-enabled" in env.shape()


class TestDegradedChannel:
    def test_unsent_email_does_not_arm_the_reminder_clock(self, tmp_path):
        """A log-only degrade must retry tomorrow, not buy REMIND_DAYS of silence."""
        env = Env(tmp_path, notify_result="SKIPPED: no readable secrets file")
        env.commit(ALARM)
        env.run()
        assert len(env.sent) == 1
        env.backdate(1)
        env.run()
        assert len(env.sent) == 2, "channel never delivered, so it must try again"


class TestRecovery:
    def test_clearing_sends_one_recovery_notice_and_clears_state(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.commit(CLEAN)
        env.run()
        assert len(env.sent) == 2
        assert "recovered" in env.sent[1]
        assert not env.state.exists()

    def test_recovery_is_not_sent_when_no_episode_was_open(self, tmp_path):
        env = Env(tmp_path)
        env.commit(CLEAN)
        env.run()
        env.run()
        assert env.sent == []


ALL_MARKERS = (
    "Daily update 2026-09-10 — ARF OK | shadow rc=0/eval rc=0 "
    "[ALARM: ARF forecast 0h] [ALARM: eval stale 3d] "
    "[ALARM: t0 stale 2026-09-09] "
    "[ALARM: EDH gate timeout — no new publish since "
    "2026-09-08T19:15:52.749879+00:00]"
)


class TestMarkerSeparation:
    """Regression: `paste -sd'; '` cycled TWO delimiters, so every second marker
    was joined to its neighbour by a space instead of ';'. `tr ';' '\n'` then
    left the pair on one line and the first matching rule in marker_kinds
    rewrote the whole line, silently discarding the other marker. On the real
    2026-09-10 commit that dropped `eval-stale` from the fingerprint entirely --
    a marker type that is absent from the shape cannot break through an open
    episode, which is the whole point of the shape.
    """

    def test_every_marker_type_survives_into_the_shape(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALL_MARKERS)
        env.run()
        kinds = env.shape().removeprefix("soft:").split(",")
        assert kinds == ["arf-forecast-short", "edh-gate-timeout",
                         "eval-stale", "t0-stale"]


class TestEdhGateTimeoutShape:
    """The EDH gate-timeout marker embeds the timestamp of the last upstream
    publish. With no rule for it, it entered the fingerprint verbatim, so each
    new stall read as a brand-new episode and reset the day counter.
    """

    def test_timestamp_does_not_leak_into_the_shape(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALL_MARKERS)
        env.run()
        assert "edh-gate-timeout" in env.shape()
        assert "2026-09-08T19:15:52" not in env.shape()

    def test_a_later_stall_timestamp_is_the_same_episode(self, tmp_path):
        env = Env(tmp_path)
        env.commit(ALL_MARKERS)
        env.run()
        env.backdate(1)
        env.commit(
            "Daily update 2026-09-11 — ARF OK | shadow rc=0/eval rc=0 "
            "[ALARM: ARF forecast 0h] [ALARM: eval stale 4d] "
            "[ALARM: t0 stale 2026-09-09] "
            "[ALARM: EDH gate timeout — no new publish since "
            "2026-09-10T04:02:11.000000+00:00]"
        )
        env.run()
        assert len(env.sent) == 1, "a moved stall timestamp is not a new problem"
        assert "suppressed" in env.log


class TestFailedSendAcrossEpisodes:
    """Regression for 2026-09-10: the heartbeat correctly detected the EDH stall
    and then lost the email to a transient SMTPServerDisconnected. Because a new
    episode inherited LAST_EMAIL from the episode that had just closed, the
    reminder arithmetic read the never-delivered alert as already sent and
    suppressed the following morning. TestDegradedChannel did not catch it: its
    episode is the FIRST one, so LAST_EMAIL starts empty either way.
    """

    def test_first_send_of_a_new_episode_failing_still_retries_tomorrow(
            self, tmp_path):
        env = Env(tmp_path)

        # Episode 1 delivers, arming the reminder clock.
        env.commit(ALARM)
        env.run()
        assert len(env.sent) == 1

        # Episode 2 is a different shape, and its first send is lost.
        env.backdate(1)
        env.set_notify_result(
            "ERROR: send failed (SMTPServerDisconnected: Connection "
            "unexpectedly closed: The read operation timed out)")
        env.commit("Daily update 2026-09-10 — shadow rc=0/eval rc=0 "
                   "[ALARM: ARF forecast 0h]")
        env.run()
        assert len(env.sent) == 2
        assert env.shape() == "soft:arf-forecast-short"

        # Nothing was ever delivered for episode 2, so tomorrow must try again.
        env.backdate(1)
        env.run()
        assert len(env.sent) == 3, (
            "a failed first send must not inherit the previous episode's "
            "send clock and suppress itself")

    def test_a_delivered_send_still_suppresses_the_next_morning(self, tmp_path):
        """The fix must not turn every episode into a daily re-send."""
        env = Env(tmp_path)
        env.commit(ALARM)
        env.run()
        env.backdate(1)
        env.commit("Daily update 2026-09-10 — shadow rc=0/eval rc=0 "
                   "[ALARM: ARF forecast 0h]")
        env.run()
        assert len(env.sent) == 2
        env.backdate(1)
        env.run()
        assert len(env.sent) == 2, "a delivered alert still suppresses tomorrow"
        assert "suppressed" in env.log


class TestNoteMarkersAreNotFailures:
    """A `[NOTE: ...]` marker records a condition; it must never mail a failure.

    The 2026-09-06 seasonal-naive split established the rule: a RESULT rides as
    NOTE, a FAULT rides as ALARM, and only the latter reaches this check. On
    2026-09-10 the EDH gate broke it from the other end by emitting its
    non-blocking secondary-feed warning as an ALARM, and the 06:00 heartbeat
    mailed "daily pipeline heartbeat FAILED" for a run that had completed with
    `shadow rc=0/eval rc=0` and a full 72h forecast pushed to origin/main.
    Both halves of that are pinned here: the gate now emits NOTE (see
    test_wait_for_edh.py), and this check ignores NOTE markers.
    """

    NOTE_ONLY = ("Daily update 2026-09-10 — ARF OK | shadow rc=0/eval rc=0 "
                 "[NOTE: EDH load_forecast short at publish 288/384]")

    def test_note_only_subject_sends_nothing(self, tmp_path):
        env = Env(tmp_path)
        env.commit(self.NOTE_ONLY)
        r = env.run()
        assert r.returncode == 0
        assert env.sent == [], (
            "a NOTE marker is a recorded condition, not a soft failure")
        assert not env.state.exists(), "no episode may be opened by a NOTE"

    def test_sub_naive_note_also_sends_nothing(self, tmp_path):
        """The other NOTE producer, pinned so the rule is not marker-specific."""
        env = Env(tmp_path)
        env.commit("Daily update 2026-09-10 — ARF OK | shadow rc=0/eval rc=0 "
                   "[NOTE: sub-naive 5/7]")
        env.run()
        assert env.sent == []

    def test_an_alarm_beside_a_note_still_alerts(self, tmp_path):
        """Ignoring NOTE must not swallow a real alarm sharing the subject."""
        env = Env(tmp_path)
        env.commit("Daily update 2026-09-10 — ARF OK | shadow rc=0/eval rc=0 "
                   "[NOTE: sub-naive 5/7] [ALARM: t0 jumped 2d]")
        env.run()
        assert len(env.sent) == 1
        assert env.shape() == "soft:t0-jumped"


class TestFindingTextMatchesTheFinding:
    """The soft-failure paragraph asserted a non-zero rc unconditionally.

    Until 2026-09-11 it read "a non-zero step rc means that step produced
    nothing. `shadow rc=N` specifically means the PRODUCTION LightGBM model did
    not update and the dashboard forecast is stale" — printed for every alarm,
    including alarms that ride beside `rc=0`. That is a different failure shape
    with a different fix, and stating the worse one sends the reader to
    diagnose a stale forecast that is not stale.
    """

    STALE_CLAIM = "did not update and the dashboard forecast is stale"

    def _body(self, env):
        return [l.split("\t", 1)[1]
                for l in env.record.read_text().splitlines()
                if l.startswith("BODY")][-1]

    def test_alarm_with_rc_zero_does_not_claim_the_model_is_stale(self, tmp_path):
        env = Env(tmp_path)
        env.commit("Daily update 2026-09-08 — ARF OK | shadow rc=0/eval rc=0 "
                   "[ALARM: t0 jumped 2d]")
        env.run()
        body = self._body(env)
        assert "t0 jumped 2d" in body
        assert self.STALE_CLAIM not in body, (
            "every step reported rc=0 — the forecast was produced")
        assert "GUARD firing on a run that" in body

    def test_rc_marker_keeps_the_production_stale_sentence(self, tmp_path):
        """The 2026-08-30 shape this paragraph was written for must be unchanged."""
        env = Env(tmp_path)
        env.commit("Daily update 2026-08-30 — ARF OK | shadow rc=1/eval rc=skip")
        env.run()
        body = self._body(env)
        assert self.STALE_CLAIM in body
        assert "rc=1" in body

    def test_arf_fail_is_an_rc_finding(self, tmp_path):
        env = Env(tmp_path)
        env.commit("Daily update 2026-09-02 — ARF FAIL rc=2 | shadow rc=0/eval rc=0")
        env.run()
        body = self._body(env)
        assert self.STALE_CLAIM in body
        assert "ARF FAIL rc=2" in body
