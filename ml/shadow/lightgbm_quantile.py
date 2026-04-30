"""LightGBM quantile forecaster for the EXP-009 shadow pipeline.

Two wrappers:

- ``LightGBMQuantileForecaster`` — three LGBMRegressor models (P10/P50/P90),
  single-horizon. Predictions are post-hoc sorted per row so P10 <= P50 <= P90
  holds even when independent fits cross in extrapolation (plan §7).
- ``MultiHorizonLightGBMQuantileForecaster`` — three horizon-grouped
  ``LightGBMQuantileForecaster`` instances (3 groups × 3 quantiles = 9 models,
  matching plan §2). Each group is fit on data stacked across the group's
  horizon range with ``horizon_h`` as an additional feature; this is direct
  multi-horizon forecasting — no recursive lag substitution, no variance
  collapse from feeding predictions back as inputs.
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
# Plan §2 horizon groups: momentum, intraday weather, multi-day weather+calendar.
# Stored as inclusive integer ranges; (1,6) means h+1..h+6.
DEFAULT_GROUPS: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] = (
    (1, 6),
    (7, 24),
    (25, 72),
)
HORIZON_FEATURE = "horizon_h"


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


def _validate_groups(
    groups: Sequence[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    if len(groups) == 0:
        raise ValueError("Need at least one horizon group")
    out: list[tuple[int, int]] = []
    for g in groups:
        if len(g) != 2:
            raise ValueError(f"Each group must be (start, end), got {g!r}")
        s, e = int(g[0]), int(g[1])
        if s < 1:
            raise ValueError(f"Horizons must be positive (>= 1), got group ({s}, {e})")
        if s > e:
            raise ValueError(f"Group start must be <= end (inverted order): ({s}, {e})")
        out.append((s, e))
    for (_, prev_end), (next_start, _) in zip(out, out[1:]):
        if next_start != prev_end + 1:
            raise ValueError(
                f"Groups must be contiguous (no gap, no overlap); "
                f"got {prev_end=} then {next_start=}"
            )
    return tuple(out)


class MultiHorizonLightGBMQuantileForecaster:
    """Direct multi-horizon LightGBM-Quantile forecaster (plan §2 — 9 models).

    Three horizon groups, each backed by its own ``LightGBMQuantileForecaster``
    (P10/P50/P90). Each group is fit on data **stacked across its horizon range**
    with ``horizon_h`` injected as a feature — so the same model trio handles
    every integer horizon in its range without iterated lag substitution.

    At predict time, ``predict_horizons(X, horizons)`` builds one feature row per
    (input row, horizon) pair, routes each row to its group, and returns
    ``(n_rows, n_horizons, 3)`` sorted [P10, P50, P90].
    """

    def __init__(
        self,
        groups: Sequence[tuple[int, int]] = DEFAULT_GROUPS,
        quantiles: Sequence[float] = DEFAULT_QUANTILES,
        hyperparams: LGBMHyperparams | None = None,
    ):
        self.groups: tuple[tuple[int, int], ...] = _validate_groups(groups)
        self.quantiles = tuple(float(q) for q in quantiles)
        self.hp = hyperparams or LGBMHyperparams()
        self.group_models: list[LightGBMQuantileForecaster] = [
            LightGBMQuantileForecaster(quantiles=self.quantiles, hyperparams=self.hp)
            for _ in self.groups
        ]
        self.feature_names: list[str] | None = None

    @property
    def max_horizon(self) -> int:
        return self.groups[-1][1]

    def _group_index_for(self, horizon: int) -> int:
        for i, (s, e) in enumerate(self.groups):
            if s <= horizon <= e:
                return i
        raise ValueError(
            f"Horizon {horizon} out of range "
            f"[{self.groups[0][0]}, {self.max_horizon}]"
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
    ) -> "MultiHorizonLightGBMQuantileForecaster":
        """Fit 9 models on horizon-stacked training data.

        ``X[t]`` paired with ``y[t + h]`` for each h in each group's range.
        Rows where ``y`` shifts off the end (or X has NaN) are dropped.
        """
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a pandas DataFrame")
        if not isinstance(y, pd.Series):
            raise TypeError("y must be a pandas Series")
        if len(X) != len(y):
            raise ValueError(f"X/y length mismatch: {len(X)} vs {len(y)}")
        if not X.index.equals(y.index):
            raise ValueError("X and y must share the same index (alignment required)")
        if HORIZON_FEATURE in X.columns:
            raise ValueError(
                f"Reserved feature name {HORIZON_FEATURE!r} present in X — rename it"
            )
        if len(X) <= self.max_horizon:
            raise ValueError(
                f"too few rows: need > max_horizon={self.max_horizon}, got {len(X)}"
            )

        self.feature_names = list(X.columns)
        for g_idx, (start, end) in enumerate(self.groups):
            chunks_X: list[pd.DataFrame] = []
            chunks_y: list[pd.Series] = []
            for h in range(start, end + 1):
                y_shift = y.shift(-h)  # target at t+h, indexed by t
                X_h = X.assign(**{HORIZON_FEATURE: float(h)})
                # Align on rows where both X is complete and y_shift is present.
                mask = y_shift.notna()
                if not mask.any():
                    continue
                chunks_X.append(X_h.loc[mask])
                chunks_y.append(y_shift.loc[mask])
            if not chunks_X:
                raise ValueError(
                    f"No training pairs for group ({start}, {end}); insufficient data"
                )
            X_stacked = pd.concat(chunks_X, axis=0)
            y_stacked = pd.concat(chunks_y, axis=0)
            self.group_models[g_idx].fit(X_stacked, y_stacked)
        return self

    def predict_horizons(
        self,
        X: pd.DataFrame,
        horizons: Sequence[int] | None = None,
    ) -> np.ndarray:
        """Predict each (row, horizon) pair, returning sorted [P10, P50, P90].

        Returns shape ``(len(X), len(horizons), 3)``.
        """
        if not self.feature_names:
            raise RuntimeError("Model not fit yet — call .fit() first")
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a pandas DataFrame")

        if horizons is None:
            horizons_list = list(range(self.groups[0][0], self.max_horizon + 1))
        else:
            horizons_list = [int(h) for h in horizons]
            for h in horizons_list:
                if h < self.groups[0][0] or h > self.max_horizon:
                    raise ValueError(
                        f"horizon {h} out of range "
                        f"[{self.groups[0][0]}, {self.max_horizon}]"
                    )

        missing = set(self.feature_names) - set(X.columns)
        if missing:
            raise ValueError(f"Missing features at predict time: {sorted(missing)}")
        X_feat = X[self.feature_names]

        n_rows = len(X_feat)
        n_h = len(horizons_list)
        out = np.empty((n_rows, n_h, 3), dtype=float)
        for j, h in enumerate(horizons_list):
            g_idx = self._group_index_for(h)
            X_h = X_feat.assign(**{HORIZON_FEATURE: float(h)})
            preds = self.group_models[g_idx].predict(X_h)  # (n_rows, 3), already sorted
            out[:, j, :] = preds
        return out

    def save(self, path: Path | str) -> None:
        if self.feature_names is None:
            raise RuntimeError("Cannot save unfit model")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "groups": self.groups,
                    "quantiles": self.quantiles,
                    "hp": self.hp,
                    "group_models": self.group_models,
                    "feature_names": self.feature_names,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path | str) -> "MultiHorizonLightGBMQuantileForecaster":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        inst = cls(
            groups=payload["groups"],
            quantiles=payload["quantiles"],
            hyperparams=payload["hp"],
        )
        inst.group_models = payload["group_models"]
        inst.feature_names = payload["feature_names"]
        return inst
