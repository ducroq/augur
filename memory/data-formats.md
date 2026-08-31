# Data Formats — energyDataHub

> **Last verified 2026-08-31**: unit conventions and endpoint list still match
> the published energyDataHub artefacts on sadalsuud. **The schema is now v2.2,
> not v2.1** — see the envelope section directly below before reading the v2.1
> structure. Re-verify if energyDataHub bumps its schema version again.
>
> *This banner said "v2.1 … re-verify if energyDataHub bumps its schema" from
> 2026-05-29 until 2026-08-31. EDH bumped to v2.2 on 2026-06-07 and nobody
> re-verified for 85 days, so this file documented a superseded schema as
> current while `CLAUDE.md` pointed sessions at it. A self-declared re-verify
> trigger is only worth as much as the thing that checks it fired.*

## Schema v2.2 envelope (current since 2026-06-07)

EDH commit `3dfc7fb` wrapped the per-source feeds under a `{metadata, data: {...}}`
envelope. Everything in the v2.1 section below still describes the **inner**
shape — v2.2 adds one layer above it, it did not change what is inside.

```json
{
  "metadata": { ... },
  "data": {
    "<source>": { ... }      // <- the v2.1 structure, one level down
  }
}
```

**Neither side auto-migrates, and both had to be patched by hand.** The JS shim
is `obj.data ?? obj` (commit `4a557c8`, `data-processor.js`, `tab-charts.js`,
`dashboard.js`); the Python shim is `_unwrap_v22_envelope` in
`ml/data/consolidate.py` (commit `e11487b`), called at **eight** parser sites.
`load_json_file` never invokes the schema registry, so the claim that Python
"migrated transparently" was wrong and the parsers silently returned empty
Series for every v2.2 file until `e11487b`. Detail and the audit rule in
`memory/gotcha-log.md`.

The unwrap is deliberately tolerant: it returns `data["data"]` only when that
value is a `dict`, otherwise the original object. So a pre-v2.2 file and a
v2.2 file both parse, and a feed whose `data` key holds a list is not mangled.

**Coverage is never taken from metadata.** The envelope's declared `start_time`
/ `end_time` can assert a span the payload does not contain — observed
2026-08-30, when `load_forecast` declared 48h and delivered 24h
(energydatahub#51). Nothing in Augur reads those fields; every coverage
decision derives from actual non-NaN data. Keep it that way.

## Schema v2.1 Structure (the inner shape — still current, one level down)

All data published as standardized JSON:

```json
{
  "version": "2.1",
  "dataset_name": {
    "metadata": {
      "data_type": "energy_price",
      "source": "ENTSO-E Transparency Platform",
      "units": "EUR/MWh",
      "country": "NL",
      "schema_version": "2.1",
      "start_time": "2025-10-25T00:00:00+02:00",
      "end_time": "2025-10-26T00:00:00+02:00"
    },
    "data": {
      "2025-10-25T00:00:00+02:00": 45.32
    }
  }
}
```

## Unit Conventions

- Energy prices: EUR/MWh (EnergyZero sends EUR/kWh — multiply by 1000)
- Wind/solar generation: MW
- Temperature: Celsius
- Gas storage: % fill level

## Timezone Convention

All timestamps normalized to Europe/Amsterdam (UTC+1 winter, UTC+2 summer). Energy Zero API returns UTC — conversion required.

## Published Endpoints (GitHub Pages)

- `energy_price_forecast.json` — 5 price sources combined
- `weather_forecast_multi_location.json` — 100+ locations
- `wind_forecast.json`, `solar_forecast.json` — renewable generation
- `grid_imbalance.json` — TenneT 15-min data
- `cross_border_flows.json`, `load_forecast.json`, `generation_forecast.json`
- `calendar_features.json` — holidays, DST, seasons
- `market_proxies.json` — gas/carbon prices
- `gas_storage.json`, `gas_flows.json`
- `data_quality_report.json` — FMEA validation results

## Data Resolutions

| Dataset | Resolution | Horizon |
|---------|-----------|---------|
| Energy prices | Hourly | Day-ahead |
| Wind/solar forecast | Hourly | 7-10 days |
| Weather | Hourly | 10 days |
| Grid imbalance | 15-min | Historical |
| Gas storage | Daily | ~2-3 day publication delay |
