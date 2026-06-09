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
