"""HMAC-signed pickle helpers for the EXP-009 shadow pipeline.

Why: unsigned pickles are a remote code execution risk on load. The shadow
pipeline writes 9 model pickles + state JSON nightly on sadalsuud, then commits
them to the repo. A signed sidecar lets the loader verify the file was produced
by code holding the same ``HMAC_KEY_B64`` we already use for energyDataHub data
integrity, before pickle.load runs any deserialization.

Sidecar scheme:
    file.pkl       -> the pickle (or any binary artifact)
    file.pkl.hmac  -> hex-encoded HMAC-SHA256 of file.pkl, ASCII text

verify_file() raises HMACVerificationError on any failure (missing key,
missing sidecar, malformed sidecar, mismatched digest). Callers should treat
verification failure as fatal and re-train rather than fall back to unsigned.
"""

from __future__ import annotations

import base64
import hmac as _stdlib_hmac
import os
import pickle
from hashlib import sha256
from pathlib import Path
from typing import Any

SIDECAR_SUFFIX = ".hmac"
HMAC_KEY_ENV = "HMAC_KEY_B64"


class HMACVerificationError(Exception):
    """Raised when a signed file fails HMAC verification."""


def _load_key() -> bytes:
    raw = os.environ.get(HMAC_KEY_ENV)
    if not raw:
        raise HMACVerificationError(
            f"{HMAC_KEY_ENV} env var is unset; cannot sign or verify pickle"
        )
    try:
        return base64.b64decode(raw)
    except Exception as e:
        raise HMACVerificationError(f"{HMAC_KEY_ENV} is not valid base64: {e}") from e


def _digest(path: Path, key: bytes) -> str:
    mac = _stdlib_hmac.new(key, digestmod=sha256)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            mac.update(chunk)
    return mac.hexdigest()


def sidecar_path(path: Path | str) -> Path:
    return Path(str(path) + SIDECAR_SUFFIX)


def sign_file(path: Path | str) -> Path:
    """Compute HMAC-SHA256 of *path* and write it to ``path.hmac``.

    Returns the sidecar path. Atomic via a ``.tmp`` rename.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Cannot sign — file not found: {path}")
    key = _load_key()
    digest = _digest(path, key)
    sidecar = sidecar_path(path)
    tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
    tmp.write_text(digest, encoding="ascii")
    os.replace(tmp, sidecar)
    return sidecar


def verify_file(path: Path | str) -> None:
    """Verify *path* against its ``.hmac`` sidecar. Raises on any failure."""
    path = Path(path)
    if not path.is_file():
        raise HMACVerificationError(f"File not found: {path}")
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        raise HMACVerificationError(f"HMAC sidecar missing: {sidecar}")
    expected = sidecar.read_text(encoding="ascii").strip()
    if len(expected) != 64 or not all(c in "0123456789abcdef" for c in expected):
        raise HMACVerificationError(f"Malformed sidecar (not 64-char hex): {sidecar}")
    key = _load_key()
    actual = _digest(path, key)
    if not _stdlib_hmac.compare_digest(actual, expected):
        raise HMACVerificationError(f"HMAC mismatch on {path}")


def save_signed_pickle(obj: Any, path: Path | str) -> Path:
    """Pickle *obj* to *path* atomically and write the HMAC sidecar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f)
    os.replace(tmp, path)
    sign_file(path)
    return path


def load_verified_pickle(path: Path | str) -> Any:
    """Verify the sidecar, then ``pickle.load`` *path*. Raises on verification failure."""
    verify_file(path)
    with open(path, "rb") as f:
        return pickle.load(f)
