"""Canonical JSON, SHA-256 and Ed25519 helpers.

Canonical form ("agenttrust-canonical-json/1"): UTF-8, object keys sorted, no insignificant
whitespace, integers only (floats are rejected). It is similar to, but NOT a full implementation
of, RFC 8785 (JCS). The standalone verifier re-implements the same rules independently.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

GENESIS_HASH = "0" * 64


def _check(o: Any) -> None:
    if isinstance(o, float):
        raise ValueError("floats are not allowed in canonical JSON; use integers or strings")
    if isinstance(o, dict):
        for k, v in o.items():
            if not isinstance(k, str):
                raise ValueError("object keys must be strings")
            _check(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _check(v)


def canonical_json(obj: Any) -> str:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def digest_of(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def raw_public_hex(pub: Ed25519PublicKey) -> str:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def key_id_of(pub: Ed25519PublicKey) -> str:
    return sha256_hex(bytes.fromhex(raw_public_hex(pub)))[:16]


class Signer:
    def __init__(self, private: Ed25519PrivateKey) -> None:
        self._private = private
        self.public = private.public_key()
        self.public_hex = raw_public_hex(self.public)
        self.key_id = key_id_of(self.public)

    def sign_hex(self, digest_hex: str) -> str:
        return self._private.sign(bytes.fromhex(digest_hex)).hex()

    @classmethod
    def load_or_create(cls, path: Path) -> "Signer":
        if path.exists():
            return cls(serialization.load_pem_private_key(path.read_bytes(), password=None))  # type: ignore[arg-type]
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        return cls(key)

    @classmethod
    def ephemeral(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())


def verify_sig(public_hex: str, digest_hex: str, sig_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(bytes.fromhex(sig_hex), bytes.fromhex(digest_hex))
        return True
    except Exception:
        return False
