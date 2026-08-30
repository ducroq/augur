"""Tests for scripts/notify_email.py — the alerting channel's credential layer.

The alert path runs inside systemd failure handling (augur-alert@.service),
where an alerter that itself errors only adds noise. So the contract under
test is: every degraded credential state produces a *skip* with a readable
reason and exit 0, never an exception and never a silent success.

SMTP itself is not exercised — the boundary tested here is everything up to
the socket. `send_email` is monkeypatched where the exit contract needs it.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "notify_email.py"


@pytest.fixture(scope="module")
def notify():
    """Load notify_email.py by path — scripts/ is not an importable package."""
    spec = importlib.util.spec_from_file_location("notify_email", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["notify_email"] = module
    spec.loader.exec_module(module)
    return module


def write_secrets(tmp_path, body):
    path = tmp_path / "secrets.ini"
    path.write_text(body)
    return path


class TestLoadEmailCredentials:
    def test_complete_credentials_are_returned(self, notify, tmp_path):
        path = write_secrets(tmp_path, (
            "[email_credentials]\n"
            "sender = bot@example.com\n"
            "password = hunter2\n"
            "recipient = engineer@example.com\n"
        ))
        creds = notify.load_email_credentials(path)
        assert creds == {
            "sender": "bot@example.com",
            "password": "hunter2",
            "recipient": "engineer@example.com",
        }

    def test_other_sections_are_ignored(self, notify, tmp_path):
        """secrets.ini is shared with FluxusSource; unrelated sections must not break it."""
        path = write_secrets(tmp_path, (
            "[storage_box]\nhost = u1.your-storagebox.de\n\n"
            "[email_credentials]\n"
            "sender = bot@example.com\npassword = hunter2\nrecipient = e@example.com\n"
        ))
        assert notify.load_email_credentials(path)["sender"] == "bot@example.com"

    def test_missing_file_is_a_skip_not_a_crash(self, notify, tmp_path):
        with pytest.raises(notify.CredentialsUnavailable, match="no readable secrets file"):
            notify.load_email_credentials(tmp_path / "absent.ini")

    def test_missing_section_names_the_path(self, notify, tmp_path):
        path = write_secrets(tmp_path, "[storage_box]\nhost = example\n")
        with pytest.raises(notify.CredentialsUnavailable, match="no \\[email_credentials\\]"):
            notify.load_email_credentials(path)

    @pytest.mark.parametrize("missing", ["sender", "password", "recipient"])
    def test_each_empty_field_is_reported_by_name(self, notify, tmp_path, missing):
        fields = {"sender": "b@example.com", "password": "pw", "recipient": "e@example.com"}
        fields[missing] = ""
        path = write_secrets(tmp_path, "[email_credentials]\n" + "".join(
            f"{k} = {v}\n" for k, v in fields.items()))
        with pytest.raises(notify.CredentialsUnavailable, match=missing):
            notify.load_email_credentials(path)

    def test_whitespace_only_field_counts_as_missing(self, notify, tmp_path):
        path = write_secrets(tmp_path, (
            "[email_credentials]\nsender = b@example.com\n"
            "password =    \nrecipient = e@example.com\n"
        ))
        with pytest.raises(notify.CredentialsUnavailable, match="password"):
            notify.load_email_credentials(path)


class TestMainExitContract:
    """Never propagate a failure out of a systemd failure handler."""

    def test_absent_credentials_exit_zero_and_say_skipped(self, notify, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("body"))
        rc = notify.main(["subject", "--secrets", str(tmp_path / "absent.ini")])
        assert rc == 0
        assert capsys.readouterr().out.startswith("SKIPPED:")

    def test_smtp_failure_exits_zero_and_says_error(self, notify, tmp_path, monkeypatch, capsys):
        path = write_secrets(tmp_path, (
            "[email_credentials]\nsender = b@example.com\npassword = pw\nrecipient = e@example.com\n"
        ))
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("body"))
        monkeypatch.setattr(notify, "send_email", lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
        rc = notify.main(["subject", "--secrets", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.startswith("ERROR:") and "no route" in out

    def test_strict_mode_surfaces_failure_for_manual_testing(self, notify, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("body"))
        rc = notify.main(["subject", "--secrets", str(tmp_path / "absent.ini"), "--strict"])
        assert rc == 1

    def test_successful_send_reports_recipient(self, notify, tmp_path, monkeypatch, capsys):
        path = write_secrets(tmp_path, (
            "[email_credentials]\nsender = b@example.com\npassword = pw\nrecipient = e@example.com\n"
        ))
        sent = {}
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("the body"))
        monkeypatch.setattr(notify, "send_email",
                            lambda subject, body, creds: sent.update(subject=subject, body=body))
        rc = notify.main(["[Augur] unit FAILED", "--secrets", str(path)])
        assert rc == 0
        assert sent == {"subject": "[Augur] unit FAILED", "body": "the body"}
        assert "e@example.com" in capsys.readouterr().out
