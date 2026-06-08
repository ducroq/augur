# systemd units for sadalsuud

Canonical source for the augur daily-update timer + service. Deployed via symlink:

```bash
# On sadalsuud, after a fresh repo clone:
ln -sf ~/local_dev/augur/scripts/systemd/augur-daily.service ~/.config/systemd/user/augur-daily.service
ln -sf ~/local_dev/augur/scripts/systemd/augur-daily.timer   ~/.config/systemd/user/augur-daily.timer
systemctl --user daemon-reload
systemctl --user enable --now augur-daily.timer
```

Linger must be on for the user-timer to fire while logged out:

```bash
sudo loginctl enable-linger jeroen
```

## Why this exists (augur#12)

The previous cron at `45 16 * * *` ran at 14:45 UTC — but EDH's GitHub
Actions collector publishes at 16:23–20:13 UTC (empirically observed,
2026-06-08). The cron always ran *before* upstream data was fresh, so
`ml/data/training_history.parquet` trailed 24 hours and the live LightGBM
MAE was ~84% above the backtest h+1.

The systemd unit fires at 16:30 UTC, then `wait_for_edh.sh` polls EDH's
`data_quality_report.json:timestamp` until today's date appears (max wait
4h, proceeds anyway on timeout — the absent healthchecks ping is the
absence-detection alarm).

## Rollback

```bash
systemctl --user disable --now augur-daily.timer
# Then uncomment the cron line that was migrated:
crontab -e
```
