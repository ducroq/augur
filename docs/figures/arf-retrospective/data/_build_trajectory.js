// One-off helper that walks commits on origin/main touching ml/models/state.json
// and writes metrics_trajectory.csv. Safe to delete after running.
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = 'C:/local_dev/augur';
const OUT_DIR = path.join(REPO, 'docs/figures/arf-retrospective/data');
const OUT = path.join(OUT_DIR, 'metrics_trajectory.csv');

if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

const log = execSync(
  `git -C "${REPO}" log --format="%H %cI" origin/main -- ml/models/state.json`,
  { encoding: 'utf8' }
).trim().split(/\r?\n/);
console.error(`commits: ${log.length}`);

const alpha = 1 - Math.exp(-Math.log(2) / 24);

const rows = [];
for (const line of log) {
  const sp = line.indexOf(' ');
  const h = line.slice(0, sp);
  const ts = line.slice(sp + 1);
  let d;
  try {
    const raw = execSync(
      `git -C "${REPO}" show ${h}:ml/models/state.json`,
      { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }
    );
    d = JSON.parse(raw);
  } catch (err) {
    rows.push({ commit_hash: h, commit_date: ts, error: err.message });
    continue;
  }

  const eh = d.error_history || [];
  let ewm_std = null;
  if (eh.length > 0) {
    let ewm_mean = eh[0];
    let ewm_sq = eh[0] * eh[0];
    for (let i = 1; i < eh.length; i++) {
      const e = eh[i];
      ewm_mean = alpha * e + (1 - alpha) * ewm_mean;
      ewm_sq = alpha * e * e + (1 - alpha) * ewm_sq;
    }
    ewm_std = Math.sqrt(Math.max(0, ewm_sq - ewm_mean * ewm_mean));
  }

  const last24 = eh.slice(-24);
  let last24_std = null;
  if (last24.length > 0) {
    const mu = last24.reduce((s, x) => s + x, 0) / last24.length;
    last24_std = Math.sqrt(
      last24.reduce((s, x) => s + (x - mu) * (x - mu), 0) / last24.length
    );
  }

  const m = d.metrics || {};
  rows.push({
    commit_hash: h,
    commit_date: ts,
    last_timestamp: d.last_timestamp ?? '',
    n_samples: d.n_samples ?? '',
    mae: m.mae ?? '',
    mape: m.mape ?? '',
    last_week_mae: m.last_week_mae ?? '',
    update_mae: m.update_mae ?? '',
    ewm_std_full: ewm_std !== null ? ewm_std.toFixed(4) : '',
    last24_std: last24_std !== null ? last24_std.toFixed(4) : '',
    price_buffer_len: (d.price_buffer || []).length,
    error_history_len: eh.length,
    consumer_surcharge: (d.consumer_surcharge && typeof d.consumer_surcharge === 'object')
      ? (d.consumer_surcharge.value_eur_mwh ?? '')
      : (d.consumer_surcharge ?? ''),
  });
}

rows.sort((a, b) => (a.commit_date < b.commit_date ? -1 : a.commit_date > b.commit_date ? 1 : 0));

const cols = ['commit_hash', 'commit_date', 'last_timestamp', 'n_samples',
              'mae', 'mape', 'last_week_mae', 'update_mae',
              'ewm_std_full', 'last24_std',
              'price_buffer_len', 'error_history_len', 'consumer_surcharge'];

const out = [cols.join(',')];
for (const r of rows) {
  out.push(cols.map(c => {
    const v = r[c];
    if (v === undefined || v === null) return '';
    const s = String(v);
    return s.includes(',') || s.includes('"') ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(','));
}
fs.writeFileSync(OUT, out.join('\n') + '\n', { encoding: 'utf8' });
console.error(`wrote ${rows.length} rows -> ${OUT}`);
console.error('first:', JSON.stringify(rows[0]));
console.error('last:', JSON.stringify(rows[rows.length - 1]));
