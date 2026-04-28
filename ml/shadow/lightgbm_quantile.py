"""LightGBM quantile forecaster for the EXP-009 shadow pipeline.

Three independent LGBMRegressor models, one per target quantile (P10/P50/P90).
Predictions are post-hoc sorted per row so P10 <= P50 <= P90 holds even when
independent fits cross in extrapolation (see lightgbm-quantile-shadow-plan §7).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

DEFAULT_QUANTILES: tuple[float, float, float] = (0.10, 0.50, 0.90)


@dataclass
class LGBMHyperparams:
    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_child_samples: int = 20
    random_state: int = 42
    verbose: int = -1


class LightGBMQuantileForecaster:
    """Wraps three LGBMRegressor instances, one per quantile."""

    def __init__(
        self,
        quantiles: Sequence[float] = DEFAULT_QUANTILES,
        hyperparams: LGBMHyperparams | None = None,
    ):
        qs = tuple(float(q) for q in quantiles)
        if len(qs) != 3:
            raise ValueError(f"Need 3 quantiles, got {len(qs)}")
        if list(qs) != sorted(qs):
            raise ValueError(f"Quantiles must be ascending, got {qs}")
        if not all(0.0 < q < 1.0 for q in qs):
            raise ValueError(f"Quantiles must be in (0, 1), got {qs}")
        self.quantiles: tuple[float, float, float] = qs  # type: ignore[assignment]
        self.hp = hyperparams or LGBMHyperparams()
        self.models: list[LGBMRegressor] = []
        self.feature_names: list[str] | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series | np.ndarray) -> "LightGBMQuantileForecaster":
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a pandas DataFrame")
        if len(X) == 0:
            raise ValueError("Cannot fit on empty DataFrame")
        if len(X) != len(y):
            raise ValueError(f"X/y length mismatch: {len(X)} vs {len(y)}")

        self.feature_names = list(X.columns)
        self.models = []
        for alpha in self.quantiles:
            model = LGBMRegressor(
                objective="quantile",
                alpha=alpha,
                n_estimators=self.hp.n_estimators,
                learning_rate=self.hp.learning_rate,
                num_leaves=self.hp.num_leaves,
                min_child_samples=self.hp.min_child_samples,
                random_state=self.hp.random_state,
                verbose=self.hp.verbose,
            )
            model.fit(X, y)
            self.models.append(model)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Returns shape (n, 3) with sorted [P10, P50, P90] per row."""
        if not self.models:
            raise RuntimeError("Model not fit yet — call .fit() first")
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a pandas DataFrame")
        if self.feature_names is not None:
            missing = set(self.feature_names) - set(X.columns)
            if missing:
                raise ValueError(f"Missing features at predict time: {sorted(missing)}")
            X = X[self.feature_names]
        raw = np.column_stack([m.predict(X) for m in self.models])
        return np.sort(raw, axis=1)

    def save(self, path: Path | str) -> None:
        if not self.models:
            raise RuntimeError("Cannot save unfit model")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "quantiles": self.quantiles,
                    "hp": self.hp,
                    "models": self.models,
                    "feature_names": self.feature_names,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path | str) -> "LightGBMQuantileForecaster":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        inst = cls(quantiles=payload["quantiles"], hyperparams=payload["hp"])
        inst.models = payload["models"]
        inst.feature_names = payload["feature_names"]
        return inst
