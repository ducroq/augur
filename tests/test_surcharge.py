"""ml.shadow.surcharge: the consumer surcharge, derived without ARF (augur#32)."""

import json

import pandas as pd
import pytest

from ml.shadow import surcharge as sc


def _price_file(path, ez_kwh, ws_mwh, start="2026-11-15T00:00:00+01:00"):
    ts = pd.date_range(start, periods=len(ez_kwh), freq="h")
    path.write_text(json.dumps({
        "energy_zero": {"metadata": {"units": "EUR/kWh"},
                        "data": {t.isoformat(): v for t, v in zip(ts, ez_kwh)}},
        "entsoe": {"metadata": {"units": "EUR/MWh"},
                   "data": {t.isoformat(): v for t, v in zip(ts, ws_mwh)}},
    }))


def test_derive_is_median_of_consumer_minus_vat_wholesale(tmp_path):
    ws = [50.0, 100.0, 80.0, 10.0]
    extra = [130.0, 131.0, 150.0, 129.0]  # median 130.5
    ez = [(w * sc.VAT_RATE + e) / 1000 for w, e in zip(ws, extra)]
    _price_file(tmp_path / "20261115_energy_price_forecast.json", ez, ws)

    value, name = sc.derive_surcharge(tmp_path)

    assert value == pytest.approx(130.5)
    assert name == "20261115_energy_price_forecast.json"


def test_derive_skips_a_newest_file_without_overlap(tmp_path):
    _price_file(tmp_path / "20261114_energy_price_forecast.json",
                [(100 * sc.VAT_RATE + 120) / 1000] * 4, [100.0] * 4)
    _price_file(tmp_path / "20261115_energy_price_forecast.json", [0.3] * 2, [90.0] * 2)

    value, name = sc.derive_surcharge(tmp_path)

    assert value == pytest.approx(120.0)
    assert name.startswith("20261114")


def test_update_falls_back_to_cache_then_arf_then_default(tmp_path):
    out = tmp_path / "surcharge.json"
    arf = tmp_path / "state.json"

    assert sc.update_surcharge(tmp_path, out, arf)["value_eur_mwh"] == sc.DEFAULT_SURCHARGE_EUR_MWH

    arf.write_text(json.dumps({"consumer_surcharge": {"value_eur_mwh": 111.1}}))
    out.unlink()
    assert sc.update_surcharge(tmp_path, out, arf)["value_eur_mwh"] == 111.1

    out.write_text(json.dumps({"value_eur_mwh": 122.2}))
    rec = sc.update_surcharge(tmp_path, out, arf)
    assert rec["value_eur_mwh"] == 122.2 and rec["source"] == "fallback"


def test_read_prefers_cache_over_arf(tmp_path):
    out, arf = tmp_path / "surcharge.json", tmp_path / "state.json"
    arf.write_text(json.dumps({"consumer_surcharge": {"value_eur_mwh": 111.1}}))
    assert sc.read_surcharge(out, arf) == 111.1
    out.write_text(json.dumps({"value_eur_mwh": 122.2}))
    assert sc.read_surcharge(out, arf) == 122.2


@pytest.mark.parametrize("arf_block", ['"broken"', "null", '{"value_eur_mwh": "broken"}', '{"value_eur_mwh": NaN}'])
def test_valid_cache_survives_broken_arf_state(tmp_path, arf_block):
    out, arf = tmp_path / "surcharge.json", tmp_path / "state.json"
    out.write_text(json.dumps({"value_eur_mwh": 110.85}))
    arf.write_text('{"consumer_surcharge": %s}' % arf_block)
    assert sc.read_surcharge(out, arf) == 110.85
    assert sc.arf_cached_value(arf) is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", '"110"', "true", "null"])
def test_non_finite_or_non_numeric_cache_is_rejected(tmp_path, bad):
    out = tmp_path / "surcharge.json"
    out.write_text('{"value_eur_mwh": %s}' % bad)
    assert sc.read_surcharge(out, tmp_path / "absent.json") == sc.DEFAULT_SURCHARGE_EUR_MWH


def test_fallback_keeps_the_last_derivation_time(tmp_path):
    ws = [100.0] * 4
    _price_file(tmp_path / "20261115_energy_price_forecast.json",
                [(w * sc.VAT_RATE + 120) / 1000 for w in ws], ws)
    out = tmp_path / "surcharge.json"
    first = sc.update_surcharge(tmp_path, out, tmp_path / "absent.json")
    assert first["source"] != "fallback" and first["derived_at"] == first["last_updated"]

    (tmp_path / "20261115_energy_price_forecast.json").unlink()
    second = sc.update_surcharge(tmp_path, out, tmp_path / "absent.json")
    assert second["source"] == "fallback"
    assert second["value_eur_mwh"] == first["value_eur_mwh"]
    assert second["derived_at"] == first["derived_at"]


def test_huge_int_cache_is_rejected_not_raised(tmp_path):
    out = tmp_path / "surcharge.json"
    out.write_text('{"value_eur_mwh": 1%s}' % ("0" * 400))
    assert sc.read_surcharge(out, tmp_path / "absent.json") == sc.DEFAULT_SURCHARGE_EUR_MWH


def test_fallback_over_a_rejected_cache_drops_its_derivation_time(tmp_path):
    out = tmp_path / "surcharge.json"
    out.write_text('{"value_eur_mwh": NaN, "derived_at": "2026-01-01T00:00:00+00:00"}')
    rec = sc.update_surcharge(tmp_path, out, tmp_path / "absent.json")
    assert rec["value_eur_mwh"] == sc.DEFAULT_SURCHARGE_EUR_MWH and rec["derived_at"] is None
