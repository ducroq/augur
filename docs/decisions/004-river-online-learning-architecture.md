# ADR-004: River Online Learning Architecture

**Status**: Accepted
**Date**: 2026-03-28
**Context**: Choosing the ML architecture for continuous energy price forecasting

## Decision

Use River's ARFRegressor (Adaptive Random Forest, 10 trees) with online learning instead of the originally planned XGBoost batch training approach.

## Context

The initial design (documented in the now-removed `ml/training/trainer.py` and `ml/features/builder.py`) proposed a two-phase approach:
1. Phase 1: XGBoost batch model retrained periodically
2. Phase 2: River online model for continuous learning

After evaluating both approaches during development, we went directly to Phase 2.

## Rationale

- **Daily data cadence**: energyDataHub publishes once daily at 16:00 UTC. Batch retraining on ~4000 rows is wasteful when online learning achieves the same result incrementally.
- **No retraining downtime**: The model is always up-to-date. Each daily `ml.update` run calls `predict_one` then `learn_one` for new prices, taking seconds rather than minutes.
- **Concept drift handling**: ARF includes built-in drift detection. Energy markets shift seasonally and with policy changes; an adaptive model handles this without manual intervention.
- **Shared feature builder**: `OnlineFeatureBuilder` is used by both `warmup.py` (historical replay) and `update.py` (daily), eliminating feature drift between training and inference.
- **Simplicity**: No batch scheduling, no train/val split management, no model versioning. One model file, one state file, updated atomically.

## Consequences

- **Warmup required**: A new model must replay all historical data via `warmup.py` before it can forecast. This takes ~20 seconds for 4000+ rows.
- **No ensemble**: River's ARFRegressor is the sole model. Future work (augur#10) may add ensemble methods.
- **Feature changes require re-warmup**: Adding new features means re-running `consolidate.py` + `warmup.py` to rebuild the model with the expanded feature set.
- **Model artifact is binary**: `river_model.pkl` is committed daily, growing git history. Consider git-lfs or artifact storage if this becomes a problem.

## Alternatives Considered

- **XGBoost batch**: Higher accuracy ceiling on static datasets, but requires scheduled retraining and has no built-in drift handling.
- **LightGBM incremental**: Supports `init_model` for warm starts, but still fundamentally batch-oriented.
- **River HoeffdingTreeRegressor**: Simpler single-tree alternative, but ARF's ensemble provides better accuracy and drift resilience.
