"""
Feature builder for Augur energy price forecasting.

Constructs feature matrices from energyDataHub's collected data sources:
- Price lags (t-1, t-24, t-168 for weekly seasonality)
- Weather forecasts (temperature, wind speed, solar irradiance)
- Calendar features (hour, day-of-week, month, holidays, DST)
- Grid features (cross-border flows, load forecasts, generation mix)
- Market proxies (gas prices, carbon prices, gas storage levels)

Input: energyDataHub v2.1 JSON files (decrypted)
Output: pandas DataFrame with aligned timestamps, ready for model training/inference
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np


class FeatureBuilder:
    """Builds feature matrices from energyDataHub data sources."""

    # Lag features for capturing temporal patterns
    PRICE_LAGS = [1, 2, 3, 6, 12, 24, 48, 168]  # hours
    ROLLING_WINDOWS = [6, 12, 24, 48, 168]  # hours

    def __init__(self, data_dir: str | Path):
        """
        Args:
            data_dir: Path to directory containing decrypted energyDataHub JSON files
        """
        self.data_dir = Path(data_dir)

    def load_dataset(self, filename: str) -> dict:
        """Load a single energyDataHub JSON file."""
        path = self.data_dir / filename
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def build_price_features(self, prices: pd.Series) -> pd.DataFrame:
        """Create lag and rolling features from price time series."""
        features = pd.DataFrame(index=prices.index)

        # Lag features
        for lag in self.PRICE_LAGS:
            features[f"price_lag_{lag}h"] = prices.shift(lag)

        # Rolling statistics
        for window in self.ROLLING_WINDOWS:
            features[f"price_rolling_mean_{window}h"] = prices.rolling(window).mean()
            features[f"price_rolling_std_{window}h"] = prices.rolling(window).std()
            features[f"price_rolling_min_{window}h"] = prices.rolling(window).min()
            features[f"price_rolling_max_{window}h"] = prices.rolling(window).max()

        return features

    def build_calendar_features(self, index: pd.DatetimeIndex) -> pd.DataFrame:
        """Create calendar-based features."""
        features = pd.DataFrame(index=index)
        features["hour"] = index.hour
        features["day_of_week"] = index.dayofweek
        features["month"] = index.month
        features["is_weekend"] = (index.dayofweek >= 5).astype(int)

        # Cyclical encoding for hour and day
        features["hour_sin"] = np.sin(2 * np.pi * index.hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * index.hour / 24)
        features["dow_sin"] = np.sin(2 * np.pi * index.dayofweek / 7)
        features["dow_cos"] = np.cos(2 * np.pi * index.dayofweek / 7)

        return features

    def build_feature_matrix(self) -> pd.DataFrame:
        """
        Build complete feature matrix from all available data sources.

        Returns:
            DataFrame with features aligned by timestamp, NaN for missing data
        """
        # TODO: Implement full pipeline once energyDataHub integration is wired up
        # 1. Load price data -> build_price_features()
        # 2. Load weather data -> extract temperature, wind, solar
        # 3. Load calendar features from energyDataHub
        # 4. Load grid data (flows, load, generation)
        # 5. Load market proxies (gas, carbon)
        # 6. Align all on hourly timestamps
        # 7. Handle missing data (forward-fill for slow-changing, interpolate for others)
        raise NotImplementedError("Wire up energyDataHub data sources first")
