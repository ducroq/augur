# Data Formats — energyDataHub

## Schema v2.1 Structure

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
