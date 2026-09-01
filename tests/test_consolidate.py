"""Tests for ml/data/consolidate.py parser layer.

Covers the v2.1 (flat) and v2.2+ ({metadata, data: {...}} envelope) EDH
shapes, the kWh→MWh unit multiplier, the Elspot `+00:18`/`+00:09` timezone
quirk, and the isinstance guards on parsers whose `data["data"]` could be
non-dict.

The parsers normally call `load_json_file`, which does decryption. Tests
bypass that by monkeypatching `load_json_file` to return a plain dict
directly — no encryption keys needed.
"""
import logging
import pandas as pd
import pytest

from ml.data import consolidate
from ml.data.consolidate import (
    _unwrap_v22_envelope,
    parse_price_file,
    parse_price_source_file,
    parse_wind_file,
    parse_solar_file,
    parse_weather_file,
    parse_load_file,
    parse_entsoe_wholesale,
    parse_wind_generation_file,
    parse_solar_generation_file,
    parse_gas_price_file,
    parse_calendar_file,
)


# --- _unwrap_v22_envelope: direct unit tests -------------------------------

class TestUnwrapV22Envelope:
    def test_v22_wrapped_returns_inner(self):
        payload = {"metadata": {"schema_version": "2.2"}, "data": {"entsoe": {"data": {}}}}
        assert _unwrap_v22_envelope(payload) == {"entsoe": {"data": {}}}

    def test_v21_flat_returns_self(self):
        payload = {"entsoe": {"data": {}}, "metadata": {"schema_version": "2.1"}}
        assert _unwrap_v22_envelope(payload) is payload

    def test_data_key_present_but_not_dict_returns_self(self):
        # e.g., a future shape where `data` is a list — don't unwrap.
        payload = {"data": [1, 2, 3], "entsoe": {"data": {}}}
        assert _unwrap_v22_envelope(payload) is payload

    def test_no_data_key_returns_self(self):
        payload = {"entsoe": {"data": {}}}
        assert _unwrap_v22_envelope(payload) is payload


# --- parse_price_file ------------------------------------------------------

def _wholesale_inner(prices_eur_mwh: dict[str, float]) -> dict:
    """Inner shape: a single ENTSO-E source dict."""
    return {
        "entsoe": {
            "metadata": {"units": "EUR/MWh"},
            "data": prices_eur_mwh,
        }
    }


class TestParsePriceFile:
    def test_v22_envelope(self, monkeypatch, tmp_path):
        prices = {"2026-06-09T00:00:00+00:00": 50.0, "2026-06-09T01:00:00+00:00": 55.0}
        payload = {"metadata": {"schema_version": "2.2"}, "data": _wholesale_inner(prices)}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_price_file(tmp_path / "fake.json")
        assert len(out) == 2
        assert out.iloc[0] == 50.0

    def test_v21_flat(self, monkeypatch, tmp_path):
        prices = {"2026-06-06T00:00:00+00:00": 40.0}
        payload = {"metadata": {"schema_version": "2.1"}, **_wholesale_inner(prices)}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_price_file(tmp_path / "fake.json")
        assert len(out) == 1
        assert out.iloc[0] == 40.0

    def test_envelope_without_known_sources_returns_empty_and_warns(
        self, monkeypatch, tmp_path, caplog
    ):
        # data['data'] is a dict but contains no recognised source keys —
        # parser should return empty Series + log the "ENTSO-E missing" warning,
        # not crash.
        payload = {"metadata": {}, "data": {"unknown_source": {"data": {}}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        with caplog.at_level(logging.WARNING):
            out = parse_price_file(tmp_path / "fake.json")
        assert out.empty
        assert any("ENTSO-E data missing" in r.message for r in caplog.records)

    def test_kwh_units_apply_multiplier(self, monkeypatch, tmp_path):
        # EUR/kWh → multiply by 1000 to get EUR/MWh.
        inner = {
            "entsoe": {
                "metadata": {"units": "EUR/kWh"},
                "data": {"2026-06-09T00:00:00+00:00": 0.075},
            }
        }
        payload = {"metadata": {}, "data": inner}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_price_file(tmp_path / "fake.json")
        assert out.iloc[0] == pytest.approx(75.0)

    def test_elspot_plus_00_18_timezone_normalised(self, monkeypatch, tmp_path):
        # The legacy nordpool collector emitted `+00:18` offsets; consolidate
        # rewrites them to `+01:00` before parsing.
        inner = {
            "elspot": {
                "metadata": {"units": "EUR/MWh"},
                "data": {"2026-01-15T12:00:00+00:18": 60.0},
            }
        }
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        out = parse_price_file(tmp_path / "fake.json")
        assert len(out) == 1
        # Original local time 12:00 +01:00 → 11:00 UTC.
        assert out.index[0] == pd.Timestamp("2026-01-15T11:00:00+00:00")

    def test_entsoe_preferred_over_elspot_on_same_timestamp(self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {
            "elspot": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 30.0}},
            "entsoe": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 50.0}},
        }
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        out = parse_price_file(tmp_path / "fake.json")
        # WHOLESALE_SOURCES is ordered elspot -> epex -> entsoe; entsoe
        # writes last and wins on shared timestamps.
        assert out.iloc[0] == 50.0


class TestEpexIsMarkedNotDropped:
    """epex is known bad and deliberately still in the merge.

    Measured against entsoe over 7886 matched hours it runs +16.13 mean /
    +10.72 median EUR/MWh (corr 0.859) versus elspot at +0.86 / 0.00 (corr
    0.954), a level bias flat across lags -4h..+4h. It also OUTRANKS elspot, so
    on the 1.16% of hours entsoe misses it supplies the target and discards the
    better fallback.

    Removing it is not safe yet: it would send 93 hours to NaN and the row-drop
    below would punch a 21h hole into 2026-08-27, which features_pandas'
    POSITIONAL `shift(h)` would turn into misaligned lags for ~7 days after it.
    So these tests pin the interim contract -- the value is still used, and it
    is LABELLED so readers can exclude it. See WHOLESALE_SOURCES.
    """

    def test_epex_still_supplies_the_target_for_now(self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {"epex": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 99.0}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        assert parse_price_file(tmp_path / "fake.json").iloc[0] == 99.0

    def test_epex_hour_is_flagged_not_entsoe(self, monkeypatch, tmp_path):
        """The label is what makes the bias excludable without dropping a row."""
        ts = "2026-06-09T00:00:00+00:00"
        inner = {"epex": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 99.0}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        assert parse_price_source_file(tmp_path / "fake.json").iloc[0] == 0.0

    def test_epex_still_outranks_elspot_documenting_the_known_defect(
            self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {
            "elspot": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 30.0}},
            "epex": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 88.0}},
        }
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        assert parse_price_file(tmp_path / "fake.json").iloc[0] == 88.0

    def test_entsoe_still_outranks_both_fallbacks(self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {
            "elspot": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 30.0}},
            "epex": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 88.0}},
            "entsoe": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 50.0}},
        }
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        assert parse_price_file(tmp_path / "fake.json").iloc[0] == 50.0
        assert parse_price_source_file(tmp_path / "fake.json").iloc[0] == 1.0


class TestPriceProvenance:
    """`price_is_entsoe` is additive provenance, never a feature.

    Numeric rather than a label because consolidate resamples every column with
    `.resample("h").mean()`, which raises on object dtype -- and a mean over a
    sub-hourly bin reads as the fraction of that hour sourced from ENTSO-E.
    """

    def _parse(self, monkeypatch, tmp_path, inner):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        return parse_price_source_file(tmp_path / "fake.json")

    def test_entsoe_hour_flags_one(self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {"entsoe": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 50.0}}}
        assert self._parse(monkeypatch, tmp_path, inner).iloc[0] == 1.0

    def test_elspot_fallback_hour_flags_zero(self, monkeypatch, tmp_path):
        ts = "2026-06-09T00:00:00+00:00"
        inner = {"elspot": {"metadata": {"units": "EUR/MWh"}, "data": {ts: 30.0}}}
        assert self._parse(monkeypatch, tmp_path, inner).iloc[0] == 0.0

    def test_provenance_index_matches_the_price_index_exactly(self, monkeypatch, tmp_path):
        inner = {
            "elspot": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T00:00:00+00:00": 30.0,
                                "2026-06-09T01:00:00+00:00": 31.0}},
            "entsoe": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T01:00:00+00:00": 51.0}},
        }
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        price = parse_price_file(tmp_path / "fake.json")
        prov = parse_price_source_file(tmp_path / "fake.json")
        assert list(price.index) == list(prov.index)
        assert list(prov.values) == [0.0, 1.0]

    def test_provenance_is_float_so_resample_mean_survives(self, monkeypatch, tmp_path):
        inner = {"entsoe": {"metadata": {"units": "EUR/MWh"},
                            "data": {"2026-06-09T00:00:00+00:00": 50.0,
                                     "2026-06-09T00:15:00+00:00": 52.0}}}
        prov = self._parse(monkeypatch, tmp_path, inner)
        assert prov.dtype.kind == "f"
        assert prov.resample("h").mean().iloc[0] == 1.0


# --- parse_entsoe_wholesale (via _parse_single_source) ---------------------

class TestParseEntsoeWholesale:
    def test_v22_envelope(self, monkeypatch, tmp_path):
        prices = {"2026-06-09T00:00:00+00:00": 50.0}
        payload = {"metadata": {}, "data": _wholesale_inner(prices)}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_entsoe_wholesale(tmp_path / "fake.json")
        assert len(out) == 1
        assert out.name == "entsoe_wholesale_eur_mwh"

    def test_v21_flat(self, monkeypatch, tmp_path):
        prices = {"2026-06-06T00:00:00+00:00": 40.0}
        payload = {"metadata": {}, **_wholesale_inner(prices)}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_entsoe_wholesale(tmp_path / "fake.json")
        assert len(out) == 1


# --- parse_wind_file -------------------------------------------------------

def _wind_inner() -> dict:
    return {
        "offshore_wind": {
            "metadata": {},
            "data": {
                "NL_IJmuiden": {
                    "2026-06-09T00:00:00+00:00": {"wind_speed_80m": 8.5},
                    "2026-06-09T01:00:00+00:00": {"wind_speed_80m": 9.2},
                }
            },
        }
    }


class TestParseWindFile:
    def test_v22_envelope(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, "data": _wind_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_file(tmp_path / "fake.json")
        assert len(out) == 2
        assert out.iloc[0] == 8.5

    def test_v21_flat(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, **_wind_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_file(tmp_path / "fake.json")
        assert len(out) == 2


# --- isinstance guards on solar/weather/load (defensive) -------------------

class TestNonDictDataGuards:
    """Future schema where `data` is a list (or other non-dict) should yield
    empty Series rather than crash. Matches the v2.2 fix's spirit: parsers
    fail soft on unexpected shapes."""

    def test_parse_solar_with_list_data_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": [1, 2, 3]}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_solar_file(tmp_path / "fake.json")
        assert out.empty

    def test_parse_weather_with_list_data_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": [1, 2, 3]}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_weather_file(tmp_path / "fake.json")
        assert out.empty

    def test_parse_load_with_list_data_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": [1, 2, 3]}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_load_file(tmp_path / "fake.json")
        assert out.empty

    def test_parse_load_with_non_dict_nl_returns_empty(self, monkeypatch, tmp_path):
        # data.NL is a list, not the expected dict-of-timestamps.
        payload = {"data": {"NL": ["bad", "shape"]}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_load_file(tmp_path / "fake.json")
        assert out.empty


# --- EXP-020 fundamentals parsers ------------------------------------------

def _wind_gen_inner() -> dict:
    """`entsoe_wind_generation` sits beside `offshore_wind` in the same file."""
    return {
        "entsoe_wind_generation": {
            "metadata": {"units": "MW", "forecast_type": "day-ahead"},
            "data": {
                "NL": {
                    "2026-08-24T00:00:00+02:00": {
                        "wind_offshore": 134.0,
                        "wind_onshore": 224.0,
                        "wind_total": 358.0,
                    },
                    "2026-08-24T00:15:00+02:00": {
                        "wind_offshore": 140.0,
                        "wind_onshore": 230.0,
                        "wind_total": 370.0,
                    },
                },
                "DE_LU": {
                    "2026-08-24T00:00:00+02:00": {"wind_total": 11387.45},
                },
            },
        },
        "offshore_wind": {"data": {"NL_HKZ": {"2026-08-24T00:00:00+02:00": {"wind_speed_80m": 8.5}}}},
    }


class TestParseWindGenerationFile:
    def test_v22_envelope_reads_nl_wind_total(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, "data": _wind_gen_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_generation_file(tmp_path / "fake.json")
        assert len(out) == 2
        assert out.iloc[0] == 358.0
        assert out.name == "wind_gen_forecast_mw"

    def test_v21_flat(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, **_wind_gen_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_generation_file(tmp_path / "fake.json")
        assert len(out) == 2

    def test_timestamps_normalised_to_utc(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, "data": _wind_gen_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_generation_file(tmp_path / "fake.json")
        # +02:00 local midnight is 22:00 UTC the previous day.
        assert out.index[0] == pd.Timestamp("2026-08-23T22:00:00+00:00")

    def test_does_not_read_the_offshore_wind_speed_subdataset(self, monkeypatch, tmp_path):
        """Regression guard: the same file carries an Open-Meteo wind *speed*
        series that `parse_wind_file` reads. Confusing the two would feed m/s
        into an MW column."""
        payload = {"metadata": {}, "data": _wind_gen_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_wind_generation_file(tmp_path / "fake.json")
        assert 8.5 not in out.values

    def test_missing_subdataset_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": {"offshore_wind": {"data": {}}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_wind_generation_file(tmp_path / "fake.json").empty

    def test_non_dict_nl_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": {"entsoe_wind_generation": {"data": {"NL": ["bad"]}}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_wind_generation_file(tmp_path / "fake.json").empty


def _ned_inner() -> dict:
    return {
        "solar": {
            "forecast": {
                "2026-08-24T12:15:00+02:00": {
                    "capacity_kw": 16007908.0,
                    "volume_kwh": 4001977.0,
                    "utilization_pct": 0.6364,
                },
                "2026-08-24T12:30:00+02:00": {
                    "capacity_kw": 15393975.0,
                    "volume_kwh": 3848493.75,
                    "utilization_pct": 0.6120,
                },
            },
            "actual": {"2026-08-24T12:15:00+02:00": {"capacity_kw": 999999.0}},
        },
        "wind_onshore": {"forecast": {}},
    }


class TestParseSolarGenerationFile:
    def test_converts_kw_to_mw(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, "data": _ned_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_solar_generation_file(tmp_path / "fake.json")
        assert len(out) == 2
        assert out.iloc[0] == pytest.approx(16007.908)
        assert out.name == "solar_gen_forecast_mw"

    def test_capacity_kw_is_block_power_not_installed_capacity(self):
        """Pins the unit reading the parser depends on: NED's `capacity_kw`
        equals `volume_kwh * 4` for quarter-hourly blocks, i.e. it is the
        block's average power, not installed capacity (which `utilization_pct`
        is measured against)."""
        for fields in _ned_inner()["solar"]["forecast"].values():
            assert fields["capacity_kw"] == pytest.approx(fields["volume_kwh"] * 4)

    def test_reads_forecast_not_actual(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, "data": _ned_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_solar_generation_file(tmp_path / "fake.json")
        assert 999.999 not in out.values

    def test_v21_flat(self, monkeypatch, tmp_path):
        payload = {"metadata": {}, **_ned_inner()}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert len(parse_solar_generation_file(tmp_path / "fake.json")) == 2

    def test_missing_solar_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": {"wind_onshore": {"forecast": {}}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_solar_generation_file(tmp_path / "fake.json").empty

    def test_non_dict_forecast_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": {"solar": {"forecast": ["bad"]}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_solar_generation_file(tmp_path / "fake.json").empty


class TestParseGasPriceFile:
    def _payload(self, **over):
        ttf = {"ticker": "TTF=F", "price": 68.41, "date": "2026-08-24", "units": "EUR/MWh"}
        ttf.update(over)
        return {"metadata": {}, "data": {"carbon": {"price": 80.0}, "gas_ttf": ttf}}

    def test_indexes_on_trade_date_not_collection_time(self, monkeypatch, tmp_path):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: self._payload())
        out = parse_gas_price_file(tmp_path / "260825_161500_fake.json")
        assert len(out) == 1
        assert out.index[0] == pd.Timestamp("2026-08-24T00:00:00+00:00")
        assert out.iloc[0] == pytest.approx(68.41)

    def test_does_not_read_carbon(self, monkeypatch, tmp_path):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: self._payload())
        out = parse_gas_price_file(tmp_path / "fake.json")
        assert 80.0 not in out.values

    def test_missing_gas_ttf_returns_empty(self, monkeypatch, tmp_path):
        payload = {"data": {"carbon": {"price": 80.0}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_gas_price_file(tmp_path / "fake.json").empty

    def test_non_numeric_price_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: self._payload(price=None))
        assert parse_gas_price_file(tmp_path / "fake.json").empty

    def test_unparseable_date_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: self._payload(date="not-a-date"))
        assert parse_gas_price_file(tmp_path / "fake.json").empty


class TestParseCalendarFile:
    def _payload(self):
        return {
            "metadata": {},
            "data": {
                "2026-04-27T00:00:00+02:00": {"is_holiday_nl": True, "is_holiday_de": False},
                "2026-04-27T01:00:00+02:00": {"is_holiday_nl": True, "is_holiday_de": False},
                "2026-04-28T00:00:00+02:00": {"is_holiday_nl": False, "is_holiday_de": False},
            },
        }

    def test_bools_become_floats(self, monkeypatch, tmp_path):
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: self._payload())
        out = parse_calendar_file(tmp_path / "fake.json")
        assert len(out) == 3
        assert out.iloc[0] == 1.0
        assert out.iloc[2] == 0.0
        assert out.name == "is_holiday_nl"

    def test_reads_nl_not_de(self, monkeypatch, tmp_path):
        payload = {"data": {"2026-10-03T00:00:00+02:00": {"is_holiday_nl": False, "is_holiday_de": True}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        out = parse_calendar_file(tmp_path / "fake.json")
        assert out.iloc[0] == 0.0

    def test_entries_without_the_flag_are_skipped(self, monkeypatch, tmp_path):
        payload = {"data": {"2026-04-27T00:00:00+02:00": {"season": "spring"}}}
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: payload)
        assert parse_calendar_file(tmp_path / "fake.json").empty


# --- consolidate(): end-to-end through resample/dropna --------------------

class TestConsolidateEndToEnd:
    """The provenance column has to survive the whole pipeline, not just the parser.

    `consolidate` runs `df.resample("h").mean()` over every column, which is
    exactly why `price_is_entsoe` is a float flag and not a source label — an
    object column raises there. This exercises the real function so that
    constraint cannot be quietly broken by a later edit.
    """

    def _run(self, monkeypatch, tmp_path, inner):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "260609_180000_energy_price_forecast.json").write_text("{}")
        monkeypatch.setattr(consolidate, "load_json_file", lambda _: {"data": inner})
        out = tmp_path / "hist.parquet"
        consolidate.consolidate(data_dir, out)
        return pd.read_parquet(out)

    def test_entsoe_hours_are_kept_and_flagged(self, monkeypatch, tmp_path):
        inner = {"entsoe": {"metadata": {"units": "EUR/MWh"},
                            "data": {"2026-06-09T00:00:00+00:00": 50.0,
                                     "2026-06-09T01:00:00+00:00": 55.0}}}
        df = self._run(monkeypatch, tmp_path, inner)
        assert list(df["price_eur_mwh"]) == [50.0, 55.0]
        assert list(df["price_is_entsoe"]) == [1.0, 1.0]

    def test_epex_hour_is_kept_and_flagged_so_the_grid_stays_intact(
            self, monkeypatch, tmp_path):
        """No row is dropped: a hole here would misalign positional lag shifts."""
        inner = {
            "entsoe": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T00:00:00+00:00": 50.0}},
            "epex": {"metadata": {"units": "EUR/MWh"},
                     "data": {"2026-06-09T01:00:00+00:00": 120.0}},
        }
        df = self._run(monkeypatch, tmp_path, inner)
        assert list(df["price_eur_mwh"]) == [50.0, 120.0]
        assert list(df["price_is_entsoe"]) == [1.0, 0.0]

    def test_elspot_filled_hour_is_kept_and_flagged_zero(self, monkeypatch, tmp_path):
        inner = {
            "entsoe": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T00:00:00+00:00": 50.0}},
            "elspot": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T01:00:00+00:00": 31.0}},
        }
        df = self._run(monkeypatch, tmp_path, inner)
        assert list(df["price_eur_mwh"]) == [50.0, 31.0]
        assert list(df["price_is_entsoe"]) == [1.0, 0.0]

    def test_fallback_hours_are_logged_loudly(self, monkeypatch, tmp_path, caplog):
        inner = {
            "entsoe": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T00:00:00+00:00": 50.0}},
            "elspot": {"metadata": {"units": "EUR/MWh"},
                       "data": {"2026-06-09T01:00:00+00:00": 31.0}},
        }
        with caplog.at_level(logging.WARNING):
            self._run(monkeypatch, tmp_path, inner)
        assert any("price provenance" in r.message and "NOT fully ENTSO-E" in r.message
                   for r in caplog.records)
