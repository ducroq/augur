// Extracts the embedded `metrics_history` array from the latest origin/main
// state.json and writes it as metrics_history.csv. This is daily rolling
// metrics tracked inside the model state itself; it includes mae_vs_exchange
// which is not present in the per-commit metrics object.
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = 'C:/local_dev/augur';
const OUT = path.join(REPO, 'docs/figures/arf-retrospective/data/metrics_history.csv');

const raw = execSync(
  `git -C "${REPO}" show origin/main:ml/models/state.json`,
  { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }
);
const d = JSON.parse(raw);
const mh = d.metrics_history || [];
console.error(`metrics_history entries: ${mh.length}`);

const cols = ['date', 'update_mae', 'mae', 'last_week_mae', 'n_samples', 'mae_vs_exchange'];
const out = [cols.join(',')];
for (const e of mh) {
  out.push(cols.map(c => (e[c] ?? '')).join(','));
}
fs.writeFileSync(OUT, out.join('\n') + '\n', { encoding: 'utf8' });
console.error(`wrote ${mh.length} rows -> ${OUT}`);
console.error('first:', JSON.stringify(mh[0]));
console.error('last:', JSON.stringify(mh[mh.length - 1]));
