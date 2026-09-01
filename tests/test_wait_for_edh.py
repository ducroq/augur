"""Tests for scripts/wait_for_edh.sh — the EDH readiness gate.

Rewritten 2026-09-01 from a clock rule to a content contract. The old gate read
one field of data_quality_report.json (`timestamp`) and decided readiness from
the wall clock: date must be today, publish hour >= 12 UTC. That failed two ways
— a fixed 16:30+4h window against a GitHub cron observed starting anywhere from
00:18 to 21:14 UTC, and an hour heuristic standing in for a question the report
already answers per-dataset.

The contract these tests pin:
  * READY requires BOTH a strictly newer report than the last consumed AND the
    primary dataset at full size
  * "full size" is the MEDIAN of recent publishes, not a constant, so an
    upstream resolution change is absorbed instead of jamming the gate forever
  * a short SECONDARY feed never blocks — it proceeds and names itself, because
    2026-08-26's only publish was short and refusing it would have cost the
    vintage rather than two hours of provenance
  * every failure path exits 0 (fail open) and reports through the verdict file
  * a deadline exit does NOT record the timestamp as consumed, so the next run
    can still accept that publish

The real script is driven as a subprocess against a synthetic energyDataHub git
repo. `origin/main` is faked with update-ref, so no remote is needed.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wait_for_edh.sh"

NORMAL = {"entsoe": 192, "load_forecast": 384}
CATCHUP = {"entsoe": 96, "load_forecast": 192}
SHORT_LOAD = {"entsoe": 192, "load_forecast": 192}
SHORT_ENTSOE = {"entsoe": 96, "load_forecast": 384}


def report(ts, points):
    return {
        "timestamp": ts,
        "overall_status": "warning",
        "dataset_reports": [
            {"dataset_name": n, "data_points": p, "status": "info"}
            for n, p in points.items()
        ],
    }


class Hub:
    """A synthetic EDH repo plus an AUGUR_DIR for the gate's state files."""

    def __init__(self, tmp_path):
        self.hub = tmp_path / "edh"
        (self.hub / "data").mkdir(parents=True)
        self.augur = tmp_path / "augur"
        (self.augur / "logs").mkdir(parents=True)
        self.state = self.augur / "logs" / ".edh_gate_state"
        self.verdict = self.augur / "logs" / ".edh_gate_verdict"
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")

    def _git(self, *a):
        subprocess.run(["git", *a], cwd=self.hub, check=True, capture_output=True)

    def publish(self, ts, points):
        path = self.hub / "data" / "data_quality_report.json"
        path.write_text(json.dumps(report(ts, points)))
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "Update energy data")
        self._git("update-ref", "refs/remotes/origin/main", "HEAD")

    def stub_systemctl(self, timeout_value):
        """Fake `systemctl show ... TimeoutStartUSec --value` on PATH."""
        self.bin = self.augur / "bin"
        self.bin.mkdir(exist_ok=True)
        sc = self.bin / "systemctl"
        sc.write_text("#!/usr/bin/env bash\necho '%s'\n" % timeout_value)
        sc.chmod(0o755)

    def run(self, max_wait=2, poll=1):
        env = dict(os.environ)
        env.update({
            "DATAHUB_DIR": str(self.hub),
            "AUGUR_DIR": str(self.augur),
            "EDH_MAX_WAIT_SEC": str(max_wait),
            "EDH_POLL_SEC": str(poll),
            # Each sampled publish costs a `git show` plus a python3 start, and
            # the gate samples on every invocation. 3 is enough for a median
            # and keeps this file from dominating the suite's runtime.
            "EDH_SAMPLE_N": "3",
        })
        if getattr(self, "bin", None):
            env["PATH"] = f"{self.bin}:{env['PATH']}"
        return subprocess.run(["bash", str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=90)

    def seed(self, ts):
        self.state.write_text(ts + "\n")

    @property
    def consumed(self):
        return self.state.read_text().strip() if self.state.exists() else None

    @property
    def marker(self):
        return self.verdict.read_text() if self.verdict.exists() else ""


def history(hub, n=6, base="2026-08-%02dT16:20:00+00:00"):
    """A run of normal publishes, so the median expectation settles on 192/384."""
    for d in range(10, 10 + n):
        hub.publish(base % d, NORMAL)


class TestReady:
    def test_full_publish_proceeds_and_records_it(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T16:17:00+00:00", NORMAL)
        r = h.run()
        assert r.returncode == 0
        assert "READY" in r.stdout
        assert h.consumed == "2026-08-22T16:17:00+00:00"
        assert h.marker == ""

    def test_late_publish_is_accepted_no_clock_rule(self, tmp_path):
        """A 21:20 UTC publish was invisible to the old 16:30+4h window."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T21:20:00+00:00", NORMAL)
        r = h.run()
        assert "READY" in r.stdout
        assert h.consumed == "2026-08-22T21:20:00+00:00"


class TestContentContract:
    def test_catchup_half_size_publish_is_refused(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-28T00:44:00+00:00", CATCHUP)
        r = h.run()
        assert r.returncode == 0, "gate must never fail closed"
        assert "READY" not in r.stdout
        assert "DEADLINE" in r.stdout
        assert "ALARM: EDH gate timeout" in h.marker

    def test_deadline_does_not_consume_the_publish(self, tmp_path):
        """Refusing today must not stop tomorrow's run accepting a better one."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-28T00:44:00+00:00", CATCHUP)
        h.run()
        assert h.consumed == "2026-08-15T16:20:00+00:00"

    def test_short_primary_at_a_normal_hour_is_refused(self, tmp_path):
        """2026-08-26: right time, half-size ENTSO-E. The hour rule waved it through."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-26T16:44:00+00:00", SHORT_ENTSOE)
        r = h.run()
        assert "READY" not in r.stdout
        assert "entsoe only 96" in h.marker or "entsoe only 96" in r.stdout

    def test_short_secondary_proceeds_but_names_itself(self, tmp_path):
        """2026-08-30: full prices, halved load. Must run, and must say so."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-30T19:02:00+00:00", SHORT_LOAD)
        r = h.run()
        assert "READY" in r.stdout
        assert "load_forecast short at publish" in h.marker
        assert h.consumed == "2026-08-30T19:02:00+00:00"


class TestMonotonic:
    def test_already_consumed_publish_is_not_reused(self, tmp_path):
        """No new EDH publish must not read as 'ready' — that is the t0-overwrite shape."""
        h = Hub(tmp_path)
        history(h)
        h.publish("2026-08-30T19:02:00+00:00", NORMAL)
        h.seed("2026-08-30T19:02:00+00:00")
        r = h.run()
        assert "READY" not in r.stdout
        assert "no new publish" in h.marker

    def test_older_publish_than_consumed_is_refused(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.publish("2026-08-20T16:20:00+00:00", NORMAL)
        h.seed("2026-08-30T19:02:00+00:00")
        r = h.run()
        assert "READY" not in r.stdout


class TestExpectationTracksUpstream:
    def test_hourly_resolution_history_accepts_hourly_publishes(self, tmp_path):
        """If EDH halves resolution, the median follows and the gate keeps working.

        A hardcoded 192 would make every publish read as short forever.
        """
        h = Hub(tmp_path)
        for d in range(10, 18):
            h.publish("2026-08-%02dT16:20:00+00:00" % d, {"entsoe": 48, "load_forecast": 96})
        h.seed("2026-08-01T16:20:00+00:00")
        h.publish("2026-08-22T16:20:00+00:00", {"entsoe": 48, "load_forecast": 96})
        r = h.run()
        assert "READY" in r.stdout


class TestFailOpen:
    def test_malformed_report_still_exits_zero(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        (h.hub / "data" / "data_quality_report.json").write_text("{not json")
        h._git("add", "-A")
        h._git("commit", "-q", "-m", "Update energy data")
        h._git("update-ref", "refs/remotes/origin/main", "HEAD")
        r = h.run()
        assert r.returncode == 0
        assert "unreadable" in h.marker

    def test_missing_primary_dataset_still_exits_zero(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T16:20:00+00:00", {"load_forecast": 384})
        r = h.run()
        assert r.returncode == 0
        assert "READY" not in r.stdout

    def test_bootstrap_with_no_state_proceeds_and_seeds(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.publish("2026-08-22T16:20:00+00:00", NORMAL)
        r = h.run()
        assert "READY" in r.stdout
        assert "bootstrapping" in r.stdout
        assert h.consumed == "2026-08-22T16:20:00+00:00"


class TestUnitTimeoutCap:
    """The gate must never outlive augur-daily.service's own start timeout.

    If it does, systemd kills the unit and the run is skipped entirely — the
    fail-CLOSED outcome this gate exists to prevent. It is an easy mistake:
    deploy the script without the updated unit file and the intended 03:00
    deadline sits well past a 5h30min timeout. So the deadline is capped
    against whatever the running unit actually allows.
    """

    def test_short_unit_timeout_caps_the_deadline_and_says_so(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.stub_systemctl("5h 30min")
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T16:17:00+00:00", NORMAL)
        # 24h requested, but the stubbed unit only allows 5h30m minus the run reserve.
        r = h.run(max_wait=86400)
        assert "capping deadline" in r.stdout
        assert "5h 30min" in r.stdout

    def test_generous_unit_timeout_does_not_cap(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.stub_systemctl("12h 30min")
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T16:17:00+00:00", NORMAL)
        r = h.run(max_wait=2)
        assert "capping deadline" not in r.stdout
        assert "READY" in r.stdout

    def test_infinity_timeout_does_not_cap(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.stub_systemctl("infinity")
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-22T16:17:00+00:00", NORMAL)
        r = h.run(max_wait=2)
        assert "capping deadline" not in r.stdout
        assert "READY" in r.stdout
