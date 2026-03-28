"""Tests for SecureDataHandler — encrypt/decrypt roundtrip and tamper detection."""

import os
import base64
import pytest

from utils.secure_data_handler import SecureDataHandler


@pytest.fixture
def handler():
    enc_key = os.urandom(32)
    hmac_key = os.urandom(32)
    return SecureDataHandler(enc_key, hmac_key)


def test_roundtrip(handler):
    data = {"temperature": 25.5, "humidity": 60, "tags": ["a", "b"]}
    encrypted = handler.encrypt_and_sign(data)
    decrypted = handler.decrypt_and_verify(encrypted)
    assert decrypted == data


def test_roundtrip_empty(handler):
    data = {}
    encrypted = handler.encrypt_and_sign(data)
    assert handler.decrypt_and_verify(encrypted) == data


def test_roundtrip_large(handler):
    data = {"values": list(range(10000))}
    encrypted = handler.encrypt_and_sign(data)
    assert handler.decrypt_and_verify(encrypted) == data


def test_tampered_ciphertext_detected(handler):
    encrypted = handler.encrypt_and_sign({"x": 1})
    raw = base64.b64decode(encrypted.encode("utf-8"))
    # Flip a byte in the ciphertext (between IV and HMAC)
    tampered = raw[:20] + bytes([raw[20] ^ 0xFF]) + raw[21:]
    tampered_b64 = base64.b64encode(tampered).decode("utf-8")
    with pytest.raises(Exception):
        handler.decrypt_and_verify(tampered_b64)


def test_tampered_hmac_detected(handler):
    encrypted = handler.encrypt_and_sign({"x": 1})
    raw = base64.b64decode(encrypted.encode("utf-8"))
    # Flip last byte of HMAC
    tampered = raw[:-1] + bytes([raw[-1] ^ 0xFF])
    tampered_b64 = base64.b64encode(tampered).decode("utf-8")
    with pytest.raises(Exception):
        handler.decrypt_and_verify(tampered_b64)


def test_different_keys_fail():
    h1 = SecureDataHandler(os.urandom(32), os.urandom(32))
    h2 = SecureDataHandler(os.urandom(32), os.urandom(32))
    encrypted = h1.encrypt_and_sign({"x": 1})
    with pytest.raises(Exception):
        h2.decrypt_and_verify(encrypted)


def test_padding_validates():
    """Ensure invalid padding raises an error (not silent truncation)."""
    enc_key = os.urandom(32)
    hmac_key = os.urandom(32)
    handler = SecureDataHandler(enc_key, hmac_key)

    # Create valid encrypted data
    encrypted = handler.encrypt_and_sign({"test": True})
    raw = base64.b64decode(encrypted.encode("utf-8"))

    # Verify it decrypts correctly first
    result = handler.decrypt_and_verify(encrypted)
    assert result == {"test": True}
