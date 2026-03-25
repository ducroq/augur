"""
Augur inference pipeline — runs during Netlify build.

Steps:
1. Load latest decrypted data from energyDataHub
2. Build feature matrix for the forecast window
3. Load trained model
4. Generate week-ahead predictions
5. Output forecast JSON to static/data/ for the dashboard

This script is called by netlify.toml after decrypt_data_cached.py
and before hugo --minify.
"""

import json
from pathlib import Path
from datetime import datetime, timezone


OUTPUT_DIR = Path("static/data")


def run_inference():
    """Main inference entry point for build pipeline."""
    # TODO: Implement once trainer and feature builder are ready
    # 1. Load model from ml/models/
    # 2. Build features from decrypted data in static/data/
    # 3. Generate predictions for next 168 hours
    # 4. Format as JSON with metadata
    # 5. Write to static/data/augur_forecast.json
    print("Augur inference: not yet implemented (model not trained)")
    print("Dashboard will use energyDataHub forecasts only")


if __name__ == "__main__":
    run_inference()
