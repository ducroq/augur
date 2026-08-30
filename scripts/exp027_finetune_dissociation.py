"""EXP-027 — does fine-tuning improve point skill while DESTROYING the calibration prior?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29).

EXP-021's Alternative 4 said a strong zero-shot result makes fine-tuning the
natural next move. But EXP-022 established that the calibration advantage is a
**broad pretrained prior** — band coverage flat at ~0.81 across context lengths
from 56 days down to 7 — and EXP-026 showed it survives all the way down to the
tiny checkpoint. That is exactly the kind of thing fine-tuning on a single
narrow series overwrites.

Position: fine-tuning improves MAE by **>=5%** over zero-shot **and
simultaneously degrades raw band coverage by >=0.05** (0.811 -> <=0.76). Point
skill up, calibration down.

This is a **dissociation**, not a direction, which makes it far more falsifiable
than "fine-tuning helps": either half failing selects among the alternatives.
Mechanism: fine-tuning replaces a spread prior learned across a large
heterogeneous corpus with one estimated from ~7900 NL points — the same sample
starvation that gives the incumbent 0.611 raw coverage. A heavily fine-tuned FM
should drift *toward the incumbent's failure mode*, not away from it.

Leakage discipline, stricter than anywhere else in the backlog because
fine-tuning makes contamination trivial to create by accident:
  - Fine-tune ONLY on `timestamp <= 2026-02-28`.
  - Evaluate ONLY on vintages with `t0 >= 2026-03-01`. Every scored target is
    therefore strictly after the fine-tuning data ends.
  - The zero-shot comparator is re-scored on the SAME restricted vintage subset,
    so both arms see an identical evaluation set.
  - Report the **training curve** (several checkpoints), not just an endpoint —
    the Position predicts MAE and coverage move in opposite directions as steps
    increase, and a single endpoint cannot show that.

CLI (on b650-gpu, from ~/augur-run/repo):
    PYTHONPATH=.:scripts ~/augur-run/.venv/bin/python scripts/exp027_finetune_dissociation.py \
        --contexts ml/shadow/exp021_foundation_aligned \
        --train-end 2026-02-28 --eval-start 2026-03-01 \
        --checkpoints 0,250,1000,4000 --out ml/shadow/exp027_finetune
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.metrics import (
    diebold_mariano,
    per_observation_quantile_score,
    winkler_interval_score,
)

QUANTILES = (0.1, 0.5, 0.9)
MAX_HORIZON = 72
HAC_LAGS = MAX_HORIZON - 1
CTX_LEN = 1024          # fits Bolt's 2048 context; sampled windows from history
PRED_LEN = 64           # Bolt's NATIVE prediction length — train in-distribution


def make_training_windows(price: pd.Series, train_end: str, n_windows: int, seed: int):
    """Random (context, target) windows entirely inside the fine-tuning period."""
    s = price[price.index <= pd.Timestamp(train_end, tz="UTC")].dropna()
    arr = s.to_numpy(dtype=np.float32)
    need = CTX_LEN + PRED_LEN
    if len(arr) < need + 10:
        raise SystemExit(f"only {len(arr)} training points, need > {need}")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(arr) - need, size=n_windows)
    ctx = np.stack([arr[i:i + CTX_LEN] for i in starts])
    tgt = np.stack([arr[i + CTX_LEN:i + need] for i in starts])
    return ctx, tgt, len(arr)


def predict_all(pipeline, ctx_df, tgt_df, offset_h, label):
    import torch
    t0s = list(ctx_df["t0"].drop_duplicates())
    series = {t: g.sort_values("pos")["price"].to_numpy(dtype=np.float32)
              for t, g in ctx_df.groupby("t0")}
    tgt_by = {t: g for t, g in tgt_df.groupby("t0")}
    recs = []
    for i in range(0, len(t0s), 32):
        batch = t0s[i:i + 32]
        q, _ = pipeline.predict_quantiles(
            [torch.tensor(series[t]) for t in batch],
            prediction_length=MAX_HORIZON + offset_h, quantile_levels=list(QUANTILES))
        arr = q.numpy() if hasattr(q, "numpy") else np.asarray(q)
        for b, t in enumerate(batch):
            a = arr[b]
            for _, row in tgt_by[t].iterrows():
                j = int(row["horizon_h"]) - 1 + offset_h
                raw, srt = a[j], np.sort(a[j])
                recs.append({"variant": label, "t0": t, "timestamp_utc": row["timestamp_utc"],
                             "horizon_h": int(row["horizon_h"]), "realized": float(row["realized"]),
                             "p10_raw": float(raw[0]), "p50_raw": float(raw[1]),
                             "p90_raw": float(raw[2]), "p10": float(srt[0]),
                             "p50": float(srt[1]), "p90": float(srt[2])})
    return pd.DataFrame.from_records(recs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contexts", default="ml/shadow/exp021_foundation_aligned")
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--model", default="amazon/chronos-bolt-base")
    ap.add_argument("--train-end", default="2026-02-28")
    ap.add_argument("--eval-start", default="2026-03-01")
    ap.add_argument("--checkpoints", default="0,250,1000,4000")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--out", default="ml/shadow/exp027_finetune")
    args = ap.parse_args()

    import torch
    from chronos import BaseChronosPipeline
    from chronos.chronos_bolt import ChronosBoltModelForForecasting

    steps = sorted(int(s) for s in args.checkpoints.split(","))
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    cdir = Path(args.contexts)
    meta = json.loads((cdir / "contexts_meta.json").read_text())
    offset_h = int(meta.get("context_end_offset_h", 0))
    ctx = pd.read_parquet(cdir / "contexts.parquet")
    tgt = pd.read_parquet(cdir / "targets.parquet")

    ev = pd.Timestamp(args.eval_start, tz="UTC")
    keep = set(pd.DatetimeIndex(ctx["t0"].unique())[pd.DatetimeIndex(ctx["t0"].unique()) >= ev])
    ctx = ctx[ctx["t0"].isin(keep)]
    tgt = tgt[tgt["t0"].isin(keep)]
    print(f"eval vintages (t0 >= {args.eval_start}): {ctx['t0'].nunique()} | "
          f"targets {len(tgt)} | context offset {offset_h}h", flush=True)

    price = pd.read_parquet(args.parquet).tz_convert("UTC").sort_index()["price_eur_mwh"]
    n_windows = max(steps) * args.batch_size
    tr_ctx, tr_tgt, n_pts = make_training_windows(price, args.train_end, n_windows, args.seed)
    print(f"fine-tuning pool: {n_pts} points <= {args.train_end}; "
          f"{n_windows} sampled windows ({CTX_LEN}->{PRED_LEN})", flush=True)

    torch.manual_seed(args.seed)
    model = ChronosBoltModelForForecasting.from_pretrained(args.model).to(args.device)
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    frames, losses_log = [], []
    done = 0
    for target_step in steps:
        while done < target_step:
            i = done * args.batch_size
            c = torch.tensor(tr_ctx[i:i + args.batch_size]).to(args.device)
            t = torch.tensor(tr_tgt[i:i + args.batch_size]).to(args.device)
            loss = model(context=c, target=t).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); opt.zero_grad()
            done += 1
            if done % 100 == 0:
                losses_log.append({"step": done, "train_loss": float(loss.item())})
                print(f"  step {done}/{max(steps)} loss {loss.item():.4f}", flush=True)

        ck = out / f"ckpt_{target_step}"
        model.save_pretrained(ck)
        model.eval()
        pipe = BaseChronosPipeline.from_pretrained(ck, device_map=args.device,
                                                   torch_dtype=torch.float32)
        with torch.no_grad():
            frames.append(predict_all(pipe, ctx, tgt, offset_h, f"ft_step{target_step}"))
        model.train()
        print(f"  scored checkpoint step={target_step}", flush=True)

    preds = pd.concat(frames, ignore_index=True)
    preds.to_parquet(out / "ft_predictions.parquet")

    scored, L = {}, {}
    for v, s in preds.groupby("variant"):
        y = s["realized"].to_numpy()
        l = per_observation_quantile_score(
            y, s[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(), list(QUANTILES))
        L[v] = l
        lo, hi = s["p10"].to_numpy(), s["p90"].to_numpy()
        scored[v] = {"n_obs": int(len(s)), "mae": float(np.abs(s["p50"].to_numpy() - y).mean()),
                     "quantile_score": float(l.mean()),
                     "coverage_lower": float((y >= lo).mean()),
                     "coverage_upper": float((y <= hi).mean()),
                     "coverage_band": float(((y >= lo) & (y <= hi)).mean()),
                     "band_width_median": float(np.median(hi - lo)),
                     "winkler": float(winkler_interval_score(y, lo, hi, alpha=0.20).mean())}

    z = f"ft_step{steps[0]}"   # step 0 == zero-shot, same weights, same eval set
    for v, e in scored.items():
        e["mae_delta_pct_vs_zeroshot"] = 100 * (e["mae"] / scored[z]["mae"] - 1)
        e["coverage_band_delta_vs_zeroshot"] = e["coverage_band"] - scored[z]["coverage_band"]
        if v != z:
            e["dm_beats_zeroshot_p"] = float(
                diebold_mariano(L[v], L[z], hac_lags=HAC_LAGS).p_value_one_sided)

    fin = scored[f"ft_step{steps[-1]}"]
    gates = {
        "final_step": steps[-1],
        "mae_improved_ge_5pct": bool(fin["mae_delta_pct_vs_zeroshot"] <= -5.0),
        "coverage_degraded_ge_0.05": bool(fin["coverage_band_delta_vs_zeroshot"] <= -0.05),
        "observed_mae_delta_pct": fin["mae_delta_pct_vs_zeroshot"],
        "observed_coverage_delta": fin["coverage_band_delta_vs_zeroshot"],
    }
    gates["DISSOCIATION_CONFIRMED"] = bool(
        gates["mae_improved_ge_5pct"] and gates["coverage_degraded_ge_0.05"])
    summary = {"config": {"model": args.model, "train_end": args.train_end,
                          "eval_start": args.eval_start, "checkpoints": steps,
                          "context_len": CTX_LEN, "pred_len_train": PRED_LEN,
                          "lr": args.lr, "batch_size": args.batch_size, "seed": args.seed,
                          "n_eval_vintages": int(ctx["t0"].nunique()),
                          "n_finetune_points": n_pts, "hac_lags": HAC_LAGS,
                          "leakage_note": "every scored target is strictly after train_end; "
                                          "contexts may overlap the fine-tuning period, which "
                                          "matches how a deployed fine-tune would operate"},
               "arms": scored, "train_loss_trace": losses_log, "gates": gates}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'checkpoint':<16}{'MAE':>9}{'dMAE%':>8}{'QS':>8}{'cov_band':>10}{'dCov':>8}"
          f"{'width':>8}{'Wink':>8}{'DM p':>9}")
    for st in steps:
        v = f"ft_step{st}"; e = scored[v]
        p = e.get("dm_beats_zeroshot_p")
        print(f"{v:<16}{e['mae']:>9.2f}{e['mae_delta_pct_vs_zeroshot']:>8.1f}"
              f"{e['quantile_score']:>8.2f}{e['coverage_band']:>10.3f}"
              f"{e['coverage_band_delta_vs_zeroshot']:>8.3f}{e['band_width_median']:>8.1f}"
              f"{e['winkler']:>8.1f}{'—' if p is None else format(p,'.4f'):>9}")
    print(f"\nGATES: {gates}")
    print(f"wrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
