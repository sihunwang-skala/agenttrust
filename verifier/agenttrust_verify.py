#!/usr/bin/env python3
"""AgentTrust offline receipt verifier (standalone; depends only on `cryptography`).

Verifies, using only a PUBLIC key:
  1. current_hash == SHA-256(canonical JSON of the receipt without current_hash/signature)
  2. Ed25519 signature over the raw hash bytes
  3. previous_hash links and contiguous `seq` (chain integrity)
  4. optionally the embedded mock-merchant signatures (--merchant-public-key)

Canonical JSON: UTF-8, sorted keys, separators (",", ":"), no floats (agenttrust-canonical-json/1).

Limits: this proves the records are internally consistent and were signed by the holder of the key.
It cannot detect omitted trailing receipts, nor prove the signer was honest or independent.

Usage:
  python agenttrust_verify.py export.json --public-key <hex-or-file> [--merchant-public-key <hex-or-file>]
Exit status: 0 = all checks passed, 1 = verification failed, 2 = usage/input error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

GENESIS = "0" * 64


def canonical(obj) -> str:
    def chk(o):
        if isinstance(o, float):
            raise ValueError("float not allowed")
        if isinstance(o, dict):
            [chk(v) for v in o.values()]
        elif isinstance(o, list):
            [chk(v) for v in o]
    chk(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sig_ok(pub_hex: str, digest_hex: str, sig_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), bytes.fromhex(digest_hex))
        return True
    except Exception:
        return False


def load_key(v: str) -> str:
    p = Path(v)
    return p.read_text().strip() if p.exists() else v.strip()


def verify(receipts: list[dict], pub_hex: str, merchant_pub_hex: str | None = None) -> list[str]:
    problems: list[str] = []
    prev_hash, prev_seq = GENESIS, 0
    for r in receipts:
        tag = f"seq={r.get('seq')} id={r.get('receipt_id')}"
        core = {k: v for k, v in r.items() if k not in ("current_hash", "signature")}
        try:
            h = sha(canonical(core))
        except Exception as e:  # noqa: BLE001
            problems.append(f"{tag}: not canonicalizable ({e})")
            continue
        if h != r.get("current_hash"):
            problems.append(f"{tag}: HASH_MISMATCH (content altered)")
        elif not sig_ok(pub_hex, h, r.get("signature", "")):
            problems.append(f"{tag}: BAD_SIGNATURE")
        if r.get("previous_hash") != prev_hash:
            problems.append(f"{tag}: BROKEN_CHAIN_LINK")
        if r.get("seq") != prev_seq + 1:
            problems.append(f"{tag}: SEQUENCE_GAP (expected {prev_seq + 1})")
        if r.get("verification_level") == "PAYMENT_CONFIRMED":
            problems.append(f"{tag}: PAYMENT_CONFIRMED is not valid for this MVP")
        m = r.get("merchant_response")
        if merchant_pub_hex and m:
            if m.get("payload_digest") != sha(canonical(m["payload"])) or not sig_ok(merchant_pub_hex, m["payload_digest"], m["signature"]):
                problems.append(f"{tag}: MERCHANT_SIGNATURE_INVALID")
        prev_hash, prev_seq = r.get("current_hash"), r.get("seq", prev_seq)
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="export JSON ({'receipts': [...]} or a bare list)")
    ap.add_argument("--public-key", required=True, help="gateway Ed25519 public key (raw hex, or a file containing it)")
    ap.add_argument("--merchant-public-key", help="mock merchant public key (hex or file)")
    a = ap.parse_args(argv)
    try:
        data = json.loads(Path(a.file).read_text())
        receipts = data["receipts"] if isinstance(data, dict) else data
        pub = load_key(a.public_key)
        mpub = load_key(a.merchant_public_key) if a.merchant_public_key else None
    except Exception as e:  # noqa: BLE001
        print(f"input error: {e}", file=sys.stderr)
        return 2
    problems = verify(receipts, pub, mpub)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {len(receipts)} receipt(s)")
        for p in problems:
            print("  -", p)
        return 1
    print(f"OK: {len(receipts)} receipt(s): hashes, signatures and chain links verified with the supplied public key.")
    print("Note: this does not prove completeness (no omitted receipts) or signer independence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
