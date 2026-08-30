# systemd units for sadalsuud

Canonical source for the augur daily-update timer + service. Deployed as
**system-level units** (not user-level) so they run regardless of login
state — no `loginctl enable-linger` needed. The service runs as
`User=jeroen` so it still has access to `/home/jeroen/.ssh/`, the augur
venv, the `.env` file, etc.

```bash
# On sadalsuud, after a fresh repo clone:
sudo cp ~/local_dev/augur/scripts/systemd/augur-daily.service /etc/systemd/system/
sudo cp ~/local_dev/augur/scripts/systemd/augur-daily.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now augur-daily.timer
```

Verify:

```bash
systemctl status augur-daily.timer
systemctl list-timers augur-daily.timer
```

## Why this exists (augur#12)

The previous cron at `45 16 * * *` ran at 14:45 UTC — but EDH's GitHub
Actions collector publishes at 16:23–20:13 UTC (empirically observed,
2026-06-08). The cron always ran *before* upstream data was fresh, so
`ml/data/training_history.parquet` trailed 24 hours and the live LightGBM
MAE was ~84% above the backtest h+1.

The systemd unit fires at 16:30 UTC, then `wait_for_edh.sh` polls EDH's
`data_quality_report.json:timestamp` until today's date appears (max wait
4h, proceeds anyway on timeout — `daily_update.sh`'s next-day pre-flight
ALARM surfaces stale-state failures, and a missing daily commit on
origin/main is the external alive signal).

## Rollback

```bash
sudo systemctl disable --now augur-daily.timer
# Then uncomment the cron line that was migrated:
crontab -e
```

## Failure alerting + heartbeat (2026-08-30)

Two units, covering two structurally different silences. Deploy both or
neither — each is blind to what the other catches.

```bash
# On sadalsuud:
sudo cp ~/local_dev/augur/scripts/systemd/augur-alert@.service      /etc/systemd/system/
sudo cp ~/local_dev/augur/scripts/systemd/augur-heartbeat.service   /etc/systemd/system/
sudo cp ~/local_dev/augur/scripts/systemd/augur-heartbeat.timer     /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/augur-daily.service.d
sudo cp ~/local_dev/augur/scripts/systemd/augur-daily.service.d/alert.conf \
        /etc/systemd/system/augur-daily.service.d/
sudo systemctl daemon-reload
sudo systemctl enable --now augur-heartbeat.timer
```

Verify:

```bash
systemctl show augur-daily.service -p OnFailure          # => OnFailure=augur-alert@augur-daily.service.service
systemctl list-timers augur-heartbeat.timer
sudo systemctl start augur-heartbeat.service && tail -3 ~/local_dev/augur/logs/alerts.log
sudo systemctl start augur-alert@augur-daily.service     # end-to-end: expect one email
```

### Why two units

`OnFailure=` fires only when the unit *fails*. It does not fire when
`daily_update.sh` reaches its final

```bash
git diff --cached --quiet && echo "No changes to commit" || { commit; push; }
```

with nothing staged — the run exits 0, the unit succeeds, and the vintage is
lost in silence. Nor when the timer is disabled, nor when the box was down at
16:30 UTC. `augur-heartbeat.timer` covers those by checking, every morning at
06:00 UTC, that a `Daily update` commit landed within 30h and that
`augur-daily.timer` is still enabled and active.

**Limitation, deliberately not hidden:** the heartbeat runs on sadalsuud, so it
cannot report that sadalsuud is down. Closing that needs an off-host dead-man's
switch, i.e. a new notification service — declined 2026-07-17 ("I do not want
more services").

### Channel

Both paths email through `scripts/notify_email.py`, which reads
`[email_credentials]` from FluxusSource's gitignored
`config/credentials/secrets.ini` on this host — the same channel
`nexusmind-alert@.service` already uses. No new service, no new credentials. If
that file is absent or incomplete the alert degrades to a line in
`logs/alerts.log` and still exits 0; an alerter that fails inside systemd's
failure handling would only add noise.

`augur-alert@.service` runs as `jeroen`, not root: it needs the journal
(`jeroen` is in `adm`) and `secrets.ini` (owner, mode 600), and running as root
would leave root-owned files in the repo's `logs/`.

`alert_failure.sh` holds a 3h burst guard, armed only after a *confirmed* send —
a skipped or failed email must not silence the next real alert.

### Rollback

```bash
sudo rm /etc/systemd/system/augur-daily.service.d/alert.conf
sudo systemctl disable --now augur-heartbeat.timer
sudo systemctl daemon-reload
```
