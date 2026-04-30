"""Tests for ml/shadow/secure_pickle.py — sidecar HMAC sign/verify helpers."""

from __future__ import annotations

import base64
import os
import pickle
from pathlib import Path

import pytest

from ml.shadow.secure_pickle import (
    HMACVerificationError,
    HMAC_KEY_ENV,
    SIDECAR_SUFFIX,
    load_verified_pickle,
    save_signed_pickle,
    sidecar_path,
    sign_file,
    verify_file,
)


@pytest.fixture
def hmac_key_env(monkeypatch):
    """Set a deterministic HMAC key for the duration of a test."""
    key = base64.b64encode(b"x" * 32).decode("ascii")
    monkeypatch.setenv(HMAC_KEY_ENV, key)
    return key


@pytest.fixture
def alt_hmac_key_env(monkeypatch):
    """A different key, for rotation/mismatch tests."""
    key = base64.b64encode(b"y" * 32).decode("ascii")
    monkeypatch.setenv(HMAC_KEY_ENV, key)
    return key


@pytest.fixture
def signed_pickle(tmp_path, hmac_key_env):
    path = tmp_path / "obj.pkl"
    save_signed_pickle({"a": 1, "b": [2, 3]}, path)
    return path


class TestSidecarPath:
    def test_appends_hmac_suffix(self, tmp_path):
        p = tmp_path / "model.pkl"
        assert sidecar_path(p) == tmp_path / f"model.pkl{SIDECAR_SUFFIX}"

    def test_accepts_string(self, tmp_path):
        s = str(tmp_path / "model.pkl")
        assert sidecar_path(s).name.endswith(SIDECAR_SUFFIX)


class TestSignFile:
    def test_writes_64_char_hex_sidecar(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"hello world")
        sidecar = sign_file(f)
        assert sidecar.exists()
        text = sidecar.read_text(encoding="ascii").strip()
        assert len(text) == 64
        assert all(c in "0123456789abcdef" for c in text)

    def test_missing_file_raises(self, tmp_path, hmac_key_env):
        with pytest.raises(FileNotFoundError):
            sign_file(tmp_path / "nope.bin")

    def test_missing_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv(HMAC_KEY_ENV, raising=False)
        f = tmp_path / "blob.bin"
        f.write_bytes(b"hi")
        with pytest.raises(HMACVerificationError, match="unset"):
            sign_file(f)

    def test_malformed_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HMAC_KEY_ENV, "not!base64!")
        f = tmp_path / "blob.bin"
        f.write_bytes(b"hi")
        with pytest.raises(HMACVerificationError, match="base64"):
            sign_file(f)


class TestVerifyFile:
    def test_happy_path(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"payload")
        sign_file(f)
        verify_file(f)  # no exception

    def test_tamper_payload_raises(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"original")
        sign_file(f)
        f.write_bytes(b"tampered")
        with pytest.raises(HMACVerificationError, match="mismatch"):
            verify_file(f)

    def test_tamper_sidecar_raises(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"x")
        sign_file(f)
        sidecar = sidecar_path(f)
        sidecar.write_text("0" * 64, encoding="ascii")
        with pytest.raises(HMACVerificationError, match="mismatch"):
            verify_file(f)

    def test_missing_sidecar_raises(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"x")
        with pytest.raises(HMACVerificationError, match="sidecar missing"):
            verify_file(f)

    def test_missing_file_raises(self, tmp_path, hmac_key_env):
        with pytest.raises(HMACVerificationError, match="not found"):
            verify_file(tmp_path / "nope.bin")

    def test_malformed_sidecar_raises(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"x")
        sign_file(f)
        sidecar_path(f).write_text("not-hex", encoding="ascii")
        with pytest.raises(HMACVerificationError, match="Malformed"):
            verify_file(f)

    def test_short_sidecar_raises(self, tmp_path, hmac_key_env):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"x")
        sign_file(f)
        sidecar_path(f).write_text("abc", encoding="ascii")
        with pytest.raises(HMACVerificationError, match="Malformed"):
            verify_file(f)

    def test_key_rotation_invalidates_old_sidecar(self, tmp_path, monkeypatch):
        f = tmp_path / "blob.bin"
        f.write_bytes(b"payload")
        # Sign with key A
        monkeypatch.setenv(HMAC_KEY_ENV, base64.b64encode(b"A" * 32).decode())
        sign_file(f)
        # Verify with key B fails
        monkeypatch.setenv(HMAC_KEY_ENV, base64.b64encode(b"B" * 32).decode())
        with pytest.raises(HMACVerificationError, match="mismatch"):
            verify_file(f)


class TestSaveLoadSignedPickle:
    def test_roundtrip(self, tmp_path, hmac_key_env):
        path = tmp_path / "obj.pkl"
        obj = {"name": "augur", "horizons": [1, 6, 24, 72]}
        save_signed_pickle(obj, path)
        assert path.exists()
        assert sidecar_path(path).exists()
        restored = load_verified_pickle(path)
        assert restored == obj

    def test_load_after_payload_tamper_raises(self, signed_pickle):
        signed_pickle.write_bytes(b"\x00\x00\x00")
        with pytest.raises(HMACVerificationError):
            load_verified_pickle(signed_pickle)

    def test_load_with_missing_sidecar_raises(self, signed_pickle):
        sidecar_path(signed_pickle).unlink()
        with pytest.raises(HMACVerificationError, match="sidecar missing"):
            load_verified_pickle(signed_pickle)

    def test_save_creates_parent_dirs(self, tmp_path, hmac_key_env):
        path = tmp_path / "nested" / "deeper" / "obj.pkl"
        save_signed_pickle({"x": 1}, path)
        assert path.exists()
        assert sidecar_path(path).exists()

    def test_no_tmp_files_left_behind(self, tmp_path, hmac_key_env):
        path = tmp_path / "obj.pkl"
        save_signed_pickle({"x": 1}, path)
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == []

    def test_roundtrip_with_complex_object(self, tmp_path, hmac_key_env):
        """Pickle a more realistic shadow-model-shaped payload."""
        import numpy as np

        path = tmp_path / "shadow_model.pkl"
        obj = {
            "groups": ((1, 6), (7, 24), (25, 72)),
            "weights": np.arange(100).reshape(10, 10),
            "feature_names": [f"f{i}" for i in range(15)],
        }
        save_signed_pickle(obj, path)
        restored = load_verified_pickle(path)
        assert restored["groups"] == obj["groups"]
        assert restored["feature_names"] == obj["feature_names"]
        np.testing.assert_array_equal(restored["weights"], obj["weights"])


class TestSidecarFormat:
    def test_sidecar_is_ascii_text(self, tmp_path, hmac_key_env):
        f = tmp_path / "x.bin"
        f.write_bytes(b"data")
        sidecar = sign_file(f)
        # Should be readable as ASCII without UnicodeDecodeError.
        sidecar.read_text(encoding="ascii")

    def test_sidecar_changes_when_payload_changes(self, tmp_path, hmac_key_env):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"alpha")
        b.write_bytes(b"beta")
        sign_file(a)
        sign_file(b)
        digest_a = sidecar_path(a).read_text(encoding="ascii").strip()
        digest_b = sidecar_path(b).read_text(encoding="ascii").strip()
        assert digest_a != digest_b
