"""EXP-026 part (b) — CPU inference latency for the Chronos-Bolt size ladder.

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29):
EXP-021a Stage 2 gates deployment on **median CPU latency <= 60s** on
sadalsuud, the GPU-less production host, and this entry's own gate is
**<= 10s median / <= 30s max** for the checkpoint that carries the skill.

**This script does NOT discharge that gate, and must not be reported as if it
does.** The pre-commit says "latency measured on the machine that would actually
run it". sadalsuud is production, has no torch installed, and installing a deep
learning stack on the host that runs the nightly job is a production change that
was not authorised. So this measures an **optimistic proxy**:

    sadalsuud   AMD Ryzen 3 5300U   4 cores / 8 threads   Zen 2, low-power mobile
    b650-gpu    AMD Ryzen 7 9700X   8 cores / 16 threads  Zen 5, desktop

Pinning the proxy to 4 threads matches sadalsuud's core count but NOT its
per-core throughput — a Zen 5 desktop core is substantially faster than a Zen 2
mobile one. So the numbers here are a **lower bound on sadalsuud latency**.
Reading them correctly:

  - proxy latency ABOVE the gate  => sadalsuud certainly fails; conclusive.
  - proxy latency BELOW the gate  => suggestive only; the real measurement is
    still required before EXP-021a Stage 2 can pass.

CLI (on b650-gpu):
    ~/augur-run/.venv/bin/python scripts/exp026_cpu_latency.py \
        --contexts ml/shadow/exp021_foundation_aligned \
        --threads 4 --runs 10 --out ml/shadow/exp026_size_ladder
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MODELS = ["amazon/chronos-bolt-tiny", "amazon/chronos-bolt-mini",
          "amazon/chronos-bolt-small", "amazon/chronos-bolt-base"]
PRED_LEN = 73


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contexts", default="ml/shadow/exp021_foundation_aligned")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--out", default="ml/shadow/exp026_size_ladder")
    ap.add_argument("--on-target-host", action="store_true",
                    help="set when running ON sadalsuud itself; the result is then the "
                         "pre-committed measurement, not a proxy, and discharges the gate")
    args = ap.parse_args()

    import torch
    from chronos import BaseChronosPipeline

    torch.set_num_threads(args.threads)
    ctx = pd.read_parquet(Path(args.contexts) / "contexts.parquet")
    # The longest context is the realistic production case (a full 56-day window).
    lens = ctx.groupby("t0").size()
    t0 = lens.idxmax()
    series = ctx[ctx["t0"] == t0].sort_values("pos")["price"].to_numpy(dtype=np.float32)
    print(f"threads={args.threads}  context={len(series)} points  "
          f"prediction_length={PRED_LEN}  runs={args.runs}", flush=True)

    results = {}
    for m in args.models.split(","):
        pipe = BaseChronosPipeline.from_pretrained(m, device_map="cpu",
                                                   torch_dtype=torch.float32)
        n_params = sum(p.numel() for p in pipe.model.parameters())
        x = [torch.tensor(series)]
        with torch.no_grad():
            pipe.predict_quantiles(x, prediction_length=PRED_LEN,
                                   quantile_levels=[0.1, 0.5, 0.9])  # warm-up
            times = []
            for _ in range(args.runs):
                t = time.perf_counter()
                pipe.predict_quantiles(x, prediction_length=PRED_LEN,
                                       quantile_levels=[0.1, 0.5, 0.9])
                times.append(time.perf_counter() - t)
        results[m.split("/")[-1]] = {
            "n_params_millions": round(n_params / 1e6, 1),
            "median_s": float(np.median(times)), "max_s": float(np.max(times)),
            "min_s": float(np.min(times)), "runs": args.runs,
        }
        r = results[m.split("/")[-1]]
        print(f"  {m.split('/')[-1]:<22} {r['n_params_millions']:>7.1f}M  "
              f"median {r['median_s']:>6.2f}s  max {r['max_s']:>6.2f}s", flush=True)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    payload = {
        "proxy_host": "b650-gpu (AMD Ryzen 7 9700X, Zen 5 desktop)",
        "target_host": "sadalsuud (AMD Ryzen 3 5300U, Zen 2 low-power mobile, 4c/8t)",
        "threads_pinned": args.threads,
        "context_points": int(len(series)),
        "prediction_length": PRED_LEN,
        "IS_A_LOWER_BOUND": not args.on_target_host,
        "interpretation": ("Proxy above the gate => sadalsuud certainly fails (conclusive). "
                           "Proxy below the gate => suggestive only; EXP-021a Stage 2 still "
                           "requires the real measurement on sadalsuud."),
        "gate_median_s": 10.0, "gate_max_s": 30.0,
        "stage2_gate_median_s": 60.0,
        "results": results,
    }
    (out / "cpu_latency_proxy.json").write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {out/'cpu_latency_proxy.json'}")
    if args.on_target_host:
        print("Measured ON the target host — this IS the pre-committed measurement.")
    else:
        print("NOTE: proxy only — EXP-021a Stage 2 is NOT discharged by this file.")


if __name__ == "__main__":
    main()
