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
    parse_wind_file,
    parse_solar_file,
    parse_weather_file,
    parse_load_file,
    parse_entsoe_wholesale,
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
        # The merge loop's iteration order is elspot, epex, entsoe — entsoe
        # writes last and wins on shared timestamps.
        assert out.iloc[0] == 50.0


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
