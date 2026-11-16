"""Consumer surcharge, derived without ARF (augur#32, step 1 of ARF retirement).

The consumer price the dashboard shows is ``wholesale * VAT_RATE + surcharge``.
The surcharge (energy tax, ODE, supplier margin, all incl. VAT) is not in any
feed, so it is backed out of the hours where Energy Zero's consumer price and
ENTSO-E's wholesale price overlap:

    surcharge = median(ez_consumer - entsoe_wholesale * VAT_RATE)

This is ``ml.update.derive_surcharge`` moved out of the ARF pipeline unchanged.
The nightly job runs it as its own step (``python -m ml.shadow.surcharge``),
which caches the value in ``ml/models/shadow/surcharge.json``; every forecaster
step reads that cache through ``read_surcharge``.

Fallback order when no recent file has a usable overlap: the last cached value,
then ARF's ``state.json`` cache (the seed, until ARF is removed in step 2), then
``DEFAULT_SURCHARGE_EUR_MWH``. During step 1 the CLI also prints ARF's value
for the same night; ``daily_update.sh`` parses its last line
(``SURCHARGE <v> ARF <v|none> derived|fallback``) and puts a ``[NOTE:]`` in the
commit subject when the two differ or the value is a fallback, and an
``[ALARM:]`` when the step fails or the line is malformed.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ml.data.consolidate import glob_sorted, parse_energy_zero_consumer, parse_entsoe_wholesale

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
SURCHARGE_PATH = _REPO_ROOT / "ml" / "models" / "shadow" / "surcharge.json"
ARF_STATE_PATH = _REPO_ROOT / "ml" / "models" / "state.json"
VAT_RATE = 1.21
DEFAULT_SURCHARGE_EUR_MWH = 95.0
RECENT_FILES = 5
MIN_OVERLAP_HOURS = 3


def _finite(value) -> float | None:
    """value as a float if it is a finite number, else None (bad cache or seed)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:  # an int too large for a float
        return None


def _load(path: Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cached_value(path: Path) -> float | None:
    return _finite(_load(path).get("value_eur_mwh"))


def arf_cached_value(arf_state_path: Path = ARF_STATE_PATH) -> float | None:
    """ARF's cached surcharge, or None. Seed and step-1 cross-check only."""
    block = _load(arf_state_path).get("consumer_surcharge")
    return _finite(block.get("value_eur_mwh")) if isinstance(block, dict) else None


def read_surcharge(
    path: Path = SURCHARGE_PATH, arf_state_path: Path = ARF_STATE_PATH
) -> float:
    """The surcharge every forecaster applies: cache, else ARF's seed, else default.

    A valid cache returns without reading ARF, so a broken ARF state cannot
    reach the forecasters once the cache exists.
    """
    value = _cached_value(path)
    if value is not None:
        return value
    value = arf_cached_value(arf_state_path)
    if value is not None:
        logger.warning("No valid surcharge cache at %s; using ARF's value %.2f", path, value)
        return value
    logger.warning("No surcharge cache or ARF seed; using default %.2f", DEFAULT_SURCHARGE_EUR_MWH)
    return DEFAULT_SURCHARGE_EUR_MWH


def derive_surcharge(data_dir: Path) -> tuple[float, str] | None:
    """Median overlap surcharge from the newest usable price file, or None.

    Tries the ``RECENT_FILES`` newest ``*_energy_price_forecast.json`` files,
    newest first (the latest may lack a source). Returns (value, file name).
    """
    for pf in reversed(glob_sorted(Path(data_dir), "*_energy_price_forecast.json")[-RECENT_FILES:]):
        ez = parse_energy_zero_consumer(pf)
        ws = parse_entsoe_wholesale(pf)
        if ez.empty or ws.empty:
            continue
        ez_hourly = ez.resample("h").mean().dropna()
        ws_hourly = ws.resample("h").mean().dropna()
        overlap = ez_hourly.index.intersection(ws_hourly.index)
        if len(overlap) < MIN_OVERLAP_HOURS:
            continue
        surcharges = ez_hourly[overlap] - ws_hourly[overlap] * VAT_RATE
        value = _finite(float(np.median(surcharges)))
        if value is None:
            continue
        logger.info(
            "Surcharge derived: %.2f EUR/MWh (incl. VAT) from %d overlapping hours in %s, "
            "range [%.2f, %.2f]",
            value, len(overlap), pf.name, surcharges.min(), surcharges.max(),
        )
        return value, pf.name
    return None


def update_surcharge(
    data_dir: Path, path: Path = SURCHARGE_PATH, arf_state_path: Path = ARF_STATE_PATH
) -> dict:
    """Derive tonight's surcharge, write the cache atomically, return the record.

    ``derived_at`` moves only on a real derivation; on fallback it keeps the
    previous one, so a run of fallback nights stays visible in the cache.
    """
    now = datetime.now(timezone.utc).isoformat()
    derived = derive_surcharge(data_dir)
    if derived is None:
        value, source = read_surcharge(path, arf_state_path), "fallback"
        # Keep the old derivation time only if the retained value is that cache's.
        derived_at = _load(path).get("derived_at") if _cached_value(path) is not None else None
        logger.warning("No usable EZ/ENTSO-E overlap in recent files; keeping %.2f", value)
    else:
        (value, source), derived_at = derived, now
    record = {
        "value_eur_mwh": round(value, 2),
        "source": source,
        "derived_at": derived_at,
        "last_updated": now,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return record


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Derive and cache the consumer surcharge")
    parser.add_argument("--data-dir", required=True, help="energyDataHub data directory")
    parser.add_argument("--out", default=str(SURCHARGE_PATH))
    args = parser.parse_args()
    record = update_surcharge(Path(args.data_dir), Path(args.out))
    arf = arf_cached_value()
    # Machine-readable last line for daily_update.sh's step-1 parity marker.
    fallback = "fallback" if record["source"] == "fallback" else "derived"
    print(f"SURCHARGE {record['value_eur_mwh']:.2f} ARF {'none' if arf is None else f'{arf:.2f}'} {fallback}")


if __name__ == "__main__":
    main()
