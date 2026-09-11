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

import datetime as dt

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

    def stub_issue_api(self, mode):
        """Point the probe at a local fixture instead of api.github.com.

        `mode` picks what EDH's alert job would look like right now:
          "tonight"   an open publish-failure issue opened while we wait
          "yesterday" one still open from a previous night (EDH only closes it
                      on the next successful publish) -- must NOT count
          "none"      no open issues
          "malformed" a 200 whose body is not what we expect
          "broken"    the read fails outright (offline, DNS, non-200)
        """
        fixture = self.augur / "issues.json"
        now = dt.datetime.now(dt.timezone.utc)
        if mode == "broken":
            self.api_url = "file://" + str(self.augur / "does-not-exist.json")
            return
        if mode == "malformed":
            fixture.write_text('{"message":"rate limit exceeded"}')
        elif mode == "none":
            fixture.write_text("[]")
        else:
            when = now + dt.timedelta(minutes=2) if mode == "tonight" \
                else now - dt.timedelta(days=1)
            fixture.write_text(json.dumps([{
                "number": 70,
                "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }]))
        self.api_url = "file://" + str(fixture)

    def run(self, max_wait=2, poll=1, issue_poll_every=0, env_extra=None):
        env = dict(os.environ)
        env.update({
            "DATAHUB_DIR": str(self.hub),
            "AUGUR_DIR": str(self.augur),
            "EDH_MAX_WAIT_SEC": str(max_wait),
            "EDH_POLL_SEC": str(poll),
            # OFF unless a test opts in. The probe reads the real GitHub API,
            # and no unit test may depend on ducroq/energydatahub's live issues.
            "EDH_ISSUE_POLL_EVERY": str(issue_poll_every),
            # Each sampled publish costs a `git show` plus a python3 start, and
            # the gate samples on every invocation. 3 is enough for a median
            # and keeps this file from dominating the suite's runtime.
            "EDH_SAMPLE_N": "3",
        })
        if getattr(self, "bin", None):
            env["PATH"] = f"{self.bin}:{env['PATH']}"
        if getattr(self, "api_url", None):
            env["EDH_FAILURE_API_URL"] = self.api_url
        env.update(env_extra or {})
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

    def test_short_secondary_is_a_note_not_an_alarm(self, tmp_path):
        """Demoted 2026-09-11.

        heartbeat_check.sh reads any `ALARM:` in the commit subject as a SOFT
        FAILURE and mails "pipeline FAILED". This condition is one the gate is
        explicitly designed to proceed through, so as an ALARM it mailed a
        failure for a healthy run: on 2026-09-10 EDH published
        load_forecast=288/384, the run finished `shadow rc=0/eval rc=0` with
        t0_held_back_hours=0.0, and the 06:00 heartbeat still reported the
        production model down. The real fault detector is downstream and
        measures the feature row rather than a point count --
        `[ALARM: t0 held back Nh]` from latest_feasible_t0.
        """
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-08-30T19:02:00+00:00", SHORT_LOAD)
        r = h.run()
        assert "READY" in r.stdout
        assert "[NOTE: EDH load_forecast short at publish" in h.marker
        assert "ALARM" not in h.marker, (
            "a non-blocking condition must not ride in the ALARM path — "
            f"marker was {h.marker!r}")


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


class TestUpstreamFailureSignal:
    """The gate can tell "EDH is late" from "EDH has failed" (2026-09-10).

    EDH's alert job opens one `publish-failure` issue when a publish fails and
    closes it on the next success. Without reading it, the 2026-09-09 failure
    (issue opened 19:13 UTC) left this gate polling blind until its 03:00
    deadline, after which the run retrained on an unchanged parquet and
    republished a byte-identical vintage over a still-evaluable one.
    """

    def test_failure_reported_while_waiting_ends_the_wait_early(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("tonight")
        r = h.run(max_wait=30, poll=1, issue_poll_every=1)
        assert r.returncode == 0
        assert "UPSTREAM FAILED" in r.stdout
        assert "ducroq/energydatahub#70" in h.marker
        assert "ALARM: EDH publish FAILED upstream" in h.marker

    def test_it_gives_up_well_before_the_deadline(self, tmp_path):
        """The point is the hours saved, so prove it did not just run out."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("tonight")
        r = h.run(max_wait=30, poll=1, issue_poll_every=1)
        assert "DEADLINE reached" not in r.stdout

    def test_consumed_marker_is_not_advanced_on_an_upstream_failure(self, tmp_path):
        """The recovery publish must still be acceptable to the next run."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("tonight")
        h.run(max_wait=30, poll=1, issue_poll_every=1)
        assert h.consumed == "2026-09-08T19:15:52+00:00"

    def test_an_issue_still_open_from_a_previous_night_does_not_count(self, tmp_path):
        """The regression this signal could most easily cause.

        EDH closes the issue only on the next successful publish, so one is
        routinely still open at 16:30 while tonight's run -- deferred by GitHub
        to 17:50-19:30 -- has not started. Treating that as tonight's verdict
        would abandon the wait before EDH had a chance to publish at all.
        """
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("yesterday")
        r = h.run(max_wait=3, poll=1, issue_poll_every=1)
        assert r.returncode == 0
        assert "UPSTREAM FAILED" not in r.stdout
        assert "DEADLINE reached" in r.stdout
        assert "EDH publish FAILED upstream" not in h.marker

    def test_a_good_publish_still_wins_over_an_open_failure_issue(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-01T00:00:00+00:00")
        h.publish("2026-09-10T18:20:00+00:00", NORMAL)
        h.stub_issue_api("tonight")
        r = h.run(max_wait=30, poll=1, issue_poll_every=1)
        assert "READY" in r.stdout
        assert "UPSTREAM FAILED" not in r.stdout
        assert h.consumed == "2026-09-10T18:20:00+00:00"

    def test_broken_gh_changes_nothing(self, tmp_path):
        """No auth, no network, rate limited -- all must fall through to the
        deadline exactly as before. The probe may only ever END a wait early."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("broken")
        r = h.run(max_wait=3, poll=1, issue_poll_every=1)
        assert r.returncode == 0
        assert "UPSTREAM FAILED" not in r.stdout
        assert "DEADLINE reached" in r.stdout

    def test_no_open_issues_changes_nothing(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("none")
        r = h.run(max_wait=3, poll=1, issue_poll_every=1)
        assert "UPSTREAM FAILED" not in r.stdout
        assert "DEADLINE reached" in r.stdout

    def test_the_probe_can_be_disabled_outright(self, tmp_path):
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("tonight")
        r = h.run(max_wait=3, poll=1, issue_poll_every=0)
        assert "UPSTREAM FAILED" not in r.stdout
        assert "DEADLINE reached" in r.stdout

    def test_a_non_json_response_changes_nothing(self, tmp_path):
        """A rate-limit body is a 200 that is not a list -- must not parse."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-09-08T19:15:52+00:00")
        h.stub_issue_api("malformed")
        r = h.run(max_wait=3, poll=1, issue_poll_every=1)
        assert r.returncode == 0
        assert "UPSTREAM FAILED" not in r.stdout
        assert "DEADLINE reached" in r.stdout

    def test_the_probe_needs_no_external_binary(self, tmp_path):
        """Regression: the first cut shelled out to `gh`, which is not installed
        on sadalsuud, so the probe silently no-opped in production."""
        body = SCRIPT.read_text()
        assert "gh issue list" not in body
        assert "command -v gh" not in body


class TestExpectationDoesNotDecay:
    """augur#31: the median slid 192 -> 96 and the gate stopped seeing short.

    `median_points` sampled recent publishes to derive "full", which absorbs an
    upstream resolution change in a few days instead of reading as short
    forever. What it also absorbed was a run of DEGRADED publishes. Over the
    twenty publishes to 2026-09-10, eleven were 192 and nine were 96 -- and the
    nine are over-represented because EDH republishes several times on a
    recovery day (three on 2026-09-04 alone). The median landed on 96, so the
    pre-auction publish the gate correctly refused on 2026-09-04 was accepted
    on 2026-09-10. Per-day dedup was measured and refuted; the 75th percentile
    is the blunter fix, and it says the expectation should sit where a HEALTHY
    publish sits.
    """

    def test_a_run_of_shorts_does_not_teach_the_gate_that_short_is_normal(
            self, tmp_path):
        h = Hub(tmp_path)
        # SAMPLE_N is 3 in tests: two shorts and one healthy publish. The
        # median of that is 96 -- which would make the short publish below
        # read as FULL, which is exactly the live bug.
        h.publish("2026-09-04T06:53:00+00:00", CATCHUP)
        h.publish("2026-09-04T08:13:00+00:00", CATCHUP)
        h.publish("2026-09-06T17:57:00+00:00", NORMAL)
        h.seed("2026-09-06T17:57:00+00:00")
        h.publish("2026-09-10T07:41:00+00:00", CATCHUP)
        r = h.run()
        assert "READY" not in r.stdout, (
            "a 96-point publish must still read as short after a bad week")
        assert "SHORT primary" in r.stdout

    def test_a_genuine_resolution_change_is_still_absorbed(self, tmp_path):
        """The decay fix must not re-break what the median was introduced for."""
        h = Hub(tmp_path)
        for d in (1, 2, 3):
            h.publish(f"2026-09-0{d}T16:20:00+00:00", CATCHUP)
        h.seed("2026-09-03T16:20:00+00:00")
        h.publish("2026-09-04T16:20:00+00:00", CATCHUP)
        r = h.run()
        assert "READY" in r.stdout, (
            "once the NEW size is what everyone publishes, it is the expectation")


class TestBoundedHold:
    """A short primary holds, but not forever (augur#31, 2026-09-11).

    Neither pure position survives the publish record. 2026-09-04 published
    short three times and then FULL at 18:46 -- refusing won that vintage.
    2026-09-08 published short at 19:15 and nothing better ever came, because
    upstream answered a four-day query with one day (EDH d3e540f) -- there,
    refusing only burned hours to the 03:00 deadline. So: hold, bounded.
    """

    def test_short_is_accepted_once_the_hold_expires(self, tmp_path):
        h = Hub(tmp_path)
        h.stub_systemctl("infinity")
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-09-08T19:15:00+00:00", SHORT_ENTSOE)
        r = h.run(max_wait=30, env_extra={"EDH_SHORT_HOLD_SEC": "1"})
        assert "READY" in r.stdout
        assert "accepted after" in h.marker and "ALARM" in h.marker
        assert h.consumed == "2026-09-08T19:15:00+00:00", (
            "an accepted publish must be recorded, or it is re-accepted forever")

    def test_the_vintage_is_degraded_not_lost(self, tmp_path):
        """The marker must name the shortfall, so the t0 guards are read in context."""
        h = Hub(tmp_path)
        h.stub_systemctl("infinity")
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-09-08T19:15:00+00:00", SHORT_ENTSOE)
        h.run(max_wait=30, env_extra={"EDH_SHORT_HOLD_SEC": "1"})
        assert "96/192" in h.marker

    def test_hold_zero_accepts_immediately(self, tmp_path):
        """The escape hatch to the pure accept-and-alarm position."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-09-08T19:15:00+00:00", SHORT_ENTSOE)
        r = h.run(env_extra={"EDH_SHORT_HOLD_SEC": "0"})
        assert "READY" in r.stdout and "accepted after" in h.marker

    def test_a_short_secondary_rides_along_on_the_short_accept(self, tmp_path):
        """Both accept paths share check_secondary; this pins that they do."""
        h = Hub(tmp_path)
        h.stub_systemctl("infinity")
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-09-08T19:15:00+00:00", CATCHUP)   # entsoe 96, load 192
        h.run(max_wait=30, env_extra={"EDH_SHORT_HOLD_SEC": "1"})
        assert "ALARM" in h.marker and "entsoe" in h.marker
        assert "[NOTE: EDH load_forecast short" in h.marker, (
            "the secondary NOTE must not be lost on the short-accept path")

    def test_default_hold_still_refuses_within_the_window(self, tmp_path):
        """With the real 4h default, a short publish does NOT sail through."""
        h = Hub(tmp_path)
        history(h)
        h.seed("2026-08-15T16:20:00+00:00")
        h.publish("2026-09-08T19:15:00+00:00", SHORT_ENTSOE)
        r = h.run()
        assert "READY" not in r.stdout
        assert "Holding up to 4h" in r.stdout
