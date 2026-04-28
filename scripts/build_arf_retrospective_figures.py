"""Build the figures embedded in docs/river-arf-retrospective.md.

Reads recovered data from docs/figures/arf-retrospective/data/ and writes PNGs to
docs/figures/arf-retrospective/. Pure stdlib + matplotlib/pandas/numpy. Idempotent —
overwrites existing PNGs each run.

Usage:
    python scripts/build_arf_retrospective_figures.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "figures" / "arf-retrospective" / "data"
OUT = ROOT / "docs" / "figures" / "arf-retrospective"

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.5,
        "legend.frameon": False,
    }
)

C_BLUE = "#1f6feb"
C_ORANGE = "#d97706"
C_RED = "#b91c1c"
C_GREEN = "#15803d"
C_GREY = "#6b7280"


def _git_show(ref: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{ref}:{path}"], text=True
    )


def _load_trajectory() -> pd.DataFrame:
    traj = pd.read_csv(DATA / "metrics_trajectory.csv")
    traj["commit_date"] = pd.to_datetime(traj["commit_date"], utc=True)
    traj["date"] = pd.to_datetime(traj["commit_date"].dt.date)
    return traj


def fig1_trajectory() -> None:
    """Daily MAE trajectory over the ARF lifetime, with annotated milestones."""
    df = pd.read_csv(DATA / "metrics_history.csv", parse_dates=["date"])
    traj_daily = _load_trajectory().drop_duplicates("date", keep="last")

    fig, ax = plt.subplots(figsize=(10, 5))

    # Frozen-metrics period (mae stuck at 13.8 from 03-29 to 04-13)
    ax.axvspan(
        pd.Timestamp("2026-03-29"),
        pd.Timestamp("2026-04-13"),
        color=C_GREY,
        alpha=0.08,
        label="frozen-metrics bug active",
    )

    ax.plot(
        df["date"],
        df["update_mae"],
        marker="o",
        markersize=4,
        linewidth=1.4,
        color=C_BLUE,
        label="daily update_mae (96 new samples)",
    )
    ax.plot(
        df["date"],
        df["mae_vs_exchange"],
        marker="s",
        markersize=4,
        linewidth=1.4,
        color=C_ORANGE,
        label="mae_vs_exchange (vs EPEX)",
    )
    ax.plot(
        df["date"],
        df["last_week_mae"],
        linestyle="--",
        linewidth=1.2,
        color=C_RED,
        alpha=0.85,
        label="last_week_mae (7d rolling)",
    )

    milestones = [
        ("2026-03-28", "ENTSO-E backfill\nre-warmup"),
        ("2026-04-02", "Energy-Zero contamination\nrollback"),
        ("2026-04-14", "variance + frozen-metrics\nfix"),
        ("2026-04-25", "regime onset:\nnegative midday prices"),
    ]
    ymax = 75
    for date_str, label in milestones:
        d = pd.Timestamp(date_str)
        ax.axvline(d, color="black", alpha=0.4, linewidth=0.7, linestyle=":")
        ax.text(
            d,
            ymax * 0.97,
            label,
            rotation=90,
            va="top",
            ha="right",
            fontsize=7.5,
            color="black",
            alpha=0.7,
        )

    # Cron-skip markers
    for d_str in ["2026-04-08", "2026-04-22"]:
        ax.axvline(
            pd.Timestamp(d_str), color=C_GREY, alpha=0.5, linewidth=0.7, linestyle="-."
        )
    ax.text(
        pd.Timestamp("2026-04-22"),
        2,
        "cron skip",
        fontsize=6.5,
        color=C_GREY,
        ha="center",
    )

    ax.set_xlim(pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-29"))
    ax.set_ylim(0, ymax)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_minor_locator(mdates.DayLocator())

    ax.set_ylabel("MAE [EUR/MWh]")
    ax.set_title(
        "Figure 1 — ARF daily error trajectory, 2026-04-02 to 2026-04-28\n"
        "Stable performance until late-April spring solar regime",
        loc="left",
    )
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(OUT / "fig1_trajectory.png")
    plt.close(fig)
    print("wrote fig1_trajectory.png")


def fig2_forecast_vs_actual() -> None:
    """The peak-failure-day forecast (issued 2026-04-26 14:45 UTC) plotted against
    the realised quarter-hourly prices recovered from the 04-28 state.json
    price_buffer.
    """
    fc = json.loads((DATA / "forecast_2026-04-26.json").read_text(encoding="utf-8"))
    fc_ts = pd.to_datetime(list(fc["forecast"].keys()), utc=True)
    fc_mean = np.array(list(fc["forecast"].values()), dtype=float)
    fc_lo = np.array(list(fc["forecast_lower"].values()), dtype=float)
    fc_hi = np.array(list(fc["forecast_upper"].values()), dtype=float)

    state = json.loads(_git_show("origin/main", "ml/models/state.json"))
    buf = state["price_buffer"]
    buf_ts = pd.to_datetime([t for t, _ in buf], utc=True)
    buf_p = np.array([p for _, p in buf], dtype=float)

    actual = pd.DataFrame({"ts": buf_ts, "price": buf_p}).set_index("ts")
    # average to hourly to compare against hourly forecast
    actual_h = actual["price"].resample("1h").mean().dropna()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(
        fc_ts, fc_lo, fc_hi, color=C_BLUE, alpha=0.15, label="80% confidence band"
    )
    ax.plot(fc_ts, fc_mean, color=C_BLUE, linewidth=1.8, label="ARF forecast (mean)")
    ax.plot(
        actual_h.index,
        actual_h.values,
        color=C_RED,
        marker="o",
        markersize=3,
        linewidth=1.2,
        label="realised price (hourly mean)",
    )

    ax.axhline(0, color="black", linewidth=0.8, alpha=0.5)
    ax.text(
        fc_ts[0],
        2,
        "  zero line — model rarely crosses despite real prices to −50",
        fontsize=7.5,
        color=C_GREY,
        ha="left",
        va="bottom",
    )

    overlap = actual_h.reindex(fc_ts).dropna()
    if len(overlap) > 0:
        bias = (
            pd.Series(fc_mean, index=fc_ts).reindex(overlap.index) - overlap
        ).mean()
        mae = (
            (pd.Series(fc_mean, index=fc_ts).reindex(overlap.index) - overlap)
            .abs()
            .mean()
        )
        ax.text(
            0.99,
            0.02,
            f"overlap n={len(overlap)} h    MAE={mae:.1f}    bias={bias:+.1f} EUR/MWh",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            color=C_GREY,
        )

    ax.set_ylabel("Price [EUR/MWh]")
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
    fig.autofmt_xdate(rotation=30, ha="right")
    ax.set_title(
        "Figure 2 — peak-failure forecast: 2026-04-26 14:45 UTC issue\n"
        "Forecast plateaus while realised prices crash to −50 EUR/MWh",
        loc="left",
    )
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(OUT / "fig2_forecast_vs_actual.png")
    plt.close(fig)
    print("wrote fig2_forecast_vs_actual.png")


def fig3_hour_of_day_bias() -> None:
    """Signed bias (forecast − actual) by UTC hour-of-day, aggregated across the four
    recovered forecasts. Quantifies the structural midday miss.
    """
    state = json.loads(_git_show("origin/main", "ml/models/state.json"))
    buf = state["price_buffer"]
    actual = pd.DataFrame(
        {"ts": pd.to_datetime([t for t, _ in buf], utc=True), "price": [p for _, p in buf]}
    ).set_index("ts")
    actual_h = actual["price"].resample("1h").mean().dropna()

    rows = []
    for date_str in ["2026-04-25", "2026-04-26", "2026-04-27", "2026-04-28"]:
        fc = json.loads(
            (DATA / f"forecast_{date_str}.json").read_text(encoding="utf-8")
        )
        for ts_str, fc_v in fc["forecast"].items():
            ts = pd.Timestamp(ts_str)
            if ts in actual_h.index:
                rows.append(
                    {
                        "issue_date": date_str,
                        "ts": ts,
                        "hour_utc": ts.hour,
                        "fc": fc_v,
                        "actual": actual_h.loc[ts],
                    }
                )
    df = pd.DataFrame(rows)
    df["bias"] = df["fc"] - df["actual"]
    by_hour = df.groupby("hour_utc")["bias"].agg(["mean", "std", "count"]).reset_index()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    colors = [C_RED if 9 <= h <= 13 else C_BLUE for h in by_hour["hour_utc"]]
    ax1.bar(by_hour["hour_utc"], by_hour["mean"], color=colors, alpha=0.85, width=0.7)
    ax1.errorbar(
        by_hour["hour_utc"],
        by_hour["mean"],
        yerr=by_hour["std"],
        fmt="none",
        ecolor="black",
        elinewidth=0.8,
        capsize=2,
        alpha=0.5,
    )
    ax1.axhline(0, color="black", linewidth=0.8)
    ax1.axvspan(8.5, 13.5, color=C_RED, alpha=0.07)
    ax1.set_ylabel("signed bias  fc − actual\n[EUR/MWh]")
    ax1.set_title(
        "Figure 3 — error structure by hour-of-day (UTC), four forecasts pooled\n"
        "Solar trough (09–13 UTC) shows large positive bias — model can't bend below ~0",
        loc="left",
    )

    pivot = df.pivot_table(
        index="hour_utc", columns="issue_date", values="actual", aggfunc="mean"
    )
    for col in pivot.columns:
        ax2.plot(
            pivot.index,
            pivot[col],
            marker="o",
            markersize=3,
            linewidth=1.2,
            label=col,
            alpha=0.85,
        )
    ax2.axhline(0, color="black", linewidth=0.8, alpha=0.6)
    ax2.axvspan(8.5, 13.5, color=C_RED, alpha=0.07)
    ax2.set_xlabel("hour of day (UTC)")
    ax2.set_ylabel("realised price\n[EUR/MWh]")
    ax2.set_xticks(range(0, 24, 2))
    ax2.legend(loc="upper right", fontsize=7, ncol=4)

    fig.savefig(OUT / "fig3_hour_of_day_bias.png")
    plt.close(fig)
    print("wrote fig3_hour_of_day_bias.png")


def fig4_negative_price_prevalence() -> None:
    """Share of price_buffer entries below zero across each daily commit snapshot —
    visualises the regime onset.
    """
    daily = _load_trajectory().drop_duplicates("date", keep="last")

    pct_neg = []
    pct_lt_30 = []
    min_price = []
    for h in daily["commit_hash"]:
        try:
            state = json.loads(_git_show(h, "ml/models/state.json"))
            buf = [p for _, p in state["price_buffer"]]
            if not buf:
                pct_neg.append(np.nan)
                pct_lt_30.append(np.nan)
                min_price.append(np.nan)
            else:
                pct_neg.append(100.0 * sum(1 for p in buf if p < 0) / len(buf))
                pct_lt_30.append(100.0 * sum(1 for p in buf if p < 30) / len(buf))
                min_price.append(min(buf))
        except subprocess.CalledProcessError:
            pct_neg.append(np.nan)
            pct_lt_30.append(np.nan)
            min_price.append(np.nan)

    daily = daily.assign(pct_neg=pct_neg, pct_lt_30=pct_lt_30, min_price=min_price)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax1.fill_between(
        daily["date"], 0, daily["pct_lt_30"], color=C_BLUE, alpha=0.25, label="% < 30"
    )
    ax1.fill_between(
        daily["date"], 0, daily["pct_neg"], color=C_RED, alpha=0.5, label="% < 0"
    )
    ax1.set_ylabel("share of trailing\n50h buffer [%]")
    ax1.set_title(
        "Figure 4 — low- and negative-price prevalence in the trailing price buffer\n"
        "Regime onset visible from 2026-04-21; sustained negative-price hours from 04-25",
        loc="left",
    )
    ax1.legend(loc="upper left", fontsize=8)

    ax2.plot(daily["date"], daily["min_price"], color=C_RED, marker="o", markersize=3)
    ax2.axhline(0, color="black", linewidth=0.8, alpha=0.6)
    ax2.set_ylabel("min price in\nbuffer [EUR/MWh]")
    ax2.set_xlabel("date")
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

    fig.autofmt_xdate(rotation=30, ha="right")
    fig.savefig(OUT / "fig4_negative_price_prevalence.png")
    plt.close(fig)
    print("wrote fig4_negative_price_prevalence.png")


def fig5_distribution_shift() -> None:
    """Price distribution comparison: warmup-era buffer (early April, post-rollback)
    vs the most-recent week. Approximates the regime gap that ARF cannot extrapolate
    across because tree leaves don't extend below their training cells.
    """
    traj = _load_trajectory().drop_duplicates("date", keep="last")

    # Pick representative snapshots: early April (post-rollback baseline) vs recent
    early = traj[traj["date"] == pd.Timestamp("2026-04-02")].iloc[0]
    recent = traj[traj["date"] == pd.Timestamp("2026-04-28")].iloc[0]

    early_buf = [
        p for _, p in json.loads(_git_show(early["commit_hash"], "ml/models/state.json"))["price_buffer"]
    ]
    recent_buf = [
        p
        for _, p in json.loads(_git_show(recent["commit_hash"], "ml/models/state.json"))[
            "price_buffer"
        ]
    ]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    bins = np.arange(-60, 250, 10)
    ax.hist(
        early_buf,
        bins=bins,
        alpha=0.55,
        color=C_BLUE,
        label=f"~04-02 buffer  (n={len(early_buf)}, min={min(early_buf):.0f})",
    )
    ax.hist(
        recent_buf,
        bins=bins,
        alpha=0.55,
        color=C_RED,
        label=f"~04-28 buffer  (n={len(recent_buf)}, min={min(recent_buf):.0f})",
    )
    ax.axvline(0, color="black", linewidth=0.8)
    ax.text(
        2,
        ax.get_ylim()[1] * 0.92,
        "zero",
        fontsize=8,
        color=C_GREY,
        va="top",
    )
    ax.set_xlabel("price [EUR/MWh]")
    ax.set_ylabel("count")
    ax.set_title(
        "Figure 5 — price-distribution shift between 50h windows, ~early-April vs late-April\n"
        "Trees fit on the blue distribution have no leaves for the red tail",
        loc="left",
    )
    ax.legend(loc="upper right")
    ax.text(
        0.02,
        0.95,
        "note: full training corpus lives in ml/data/training_history.parquet on sadalsuud only.\n"
        "the 50h price-buffer snapshots are used here as a proxy.",
        transform=ax.transAxes,
        fontsize=7,
        color=C_GREY,
        va="top",
    )
    fig.savefig(OUT / "fig5_distribution_shift.png")
    plt.close(fig)
    print("wrote fig5_distribution_shift.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig1_trajectory()
    fig2_forecast_vs_actual()
    fig3_hour_of_day_bias()
    fig4_negative_price_prevalence()
    fig5_distribution_shift()
    print(f"\nAll figures written to {OUT}")
