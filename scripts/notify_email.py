#!/usr/bin/env python3
"""Send an alert email using the credentials the rest of this host already uses.

Channel choice (engineer's call, 2026-07-17: "I do not want more services"):
reuse FluxusSource's gitignored ``secrets.ini`` on sadalsuud rather than adding
a notification service. The same file backs NexusMind's ``alert_failure.sh``.

Stdlib only, and deliberately quiet: this runs inside systemd failure handling
(``augur-alert@.service``) where an alerter that itself errors would only add
noise. Every path exits 0 and prints one status line unless ``--strict``.

Usage:
    printf 'body text' | notify_email.py "Subject line"
    printf 'body text' | notify_email.py "Subject" --secrets /path/to/secrets.ini --strict
"""

from __future__ import annotations

import argparse
import configparser
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

# Overridable via AUGUR_NOTIFY_SECRETS so a dry-run on a dev box cannot
# accidentally pick up real credentials and send a real email.
DEFAULT_SECRETS = Path(
    os.environ.get(
        "AUGUR_NOTIFY_SECRETS",
        "/home/jeroen/local_dev/FluxusSource/config/credentials/secrets.ini",
    )
)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT_S = 20


class CredentialsUnavailable(Exception):
    """Credentials are absent or incomplete — a skip, not an error."""


def load_email_credentials(secrets_path) -> dict:
    """Return sender/password/recipient from ``[email_credentials]``.

    Raises CredentialsUnavailable (with a human-readable reason) when the file
    is missing, unparseable, lacks the section, or leaves any field empty. The
    caller turns that into a log-only skip: a host without the creds file must
    still run the handler to completion.
    """
    path = Path(secrets_path)
    cfg = configparser.ConfigParser()
    try:
        read_ok = cfg.read(path)
    except configparser.Error as exc:
        raise CredentialsUnavailable(f"unparseable secrets file at {path}: {exc}")
    if not read_ok:
        raise CredentialsUnavailable(f"no readable secrets file at {path}")
    if "email_credentials" not in cfg:
        raise CredentialsUnavailable(f"no [email_credentials] section in {path}")

    section = cfg["email_credentials"]
    creds = {k: (section.get(k) or "").strip() for k in ("sender", "password", "recipient")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise CredentialsUnavailable(
            f"incomplete [email_credentials] in {path}: missing {', '.join(missing)}"
        )
    return creds


def send_email(subject: str, body: str, creds: dict) -> None:
    """Send one plain-text message. Raises on any SMTP failure."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = creds["sender"]
    msg["To"] = creds["recipient"]
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_S) as smtp:
        smtp.starttls()
        smtp.login(creds["sender"], creds["password"])
        smtp.send_message(msg)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subject", help="Email subject line")
    parser.add_argument("--secrets", default=str(DEFAULT_SECRETS))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on skip/failure (for manual testing; never in the handler)",
    )
    args = parser.parse_args(argv)

    body = sys.stdin.read()

    try:
        creds = load_email_credentials(args.secrets)
    except CredentialsUnavailable as exc:
        print(f"SKIPPED: {exc}; log-only")
        return 1 if args.strict else 0

    try:
        send_email(args.subject, body, creds)
    except Exception as exc:  # noqa: BLE001 — never propagate out of a handler
        print(f"ERROR: send failed ({type(exc).__name__}: {exc})")
        return 1 if args.strict else 0

    print(f"SENT: to {creds['recipient']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
