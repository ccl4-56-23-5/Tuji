#!/usr/bin/env python3
"""CLP1 deterministic cross-platform test vector; never use fixed inputs for real data."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"CLP1"
ITERATIONS = 310_000
SALT = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
NONCE = bytes.fromhex("101112131415161718191a1b")
PASSWORD = "CLP1-测试密码-2026"
# Exact UTF-8 bytes for the vector. JSON field order/spacing in real files need not match.
PLAINTEXT = (
    '{"createdUtcMs":1767225600000,"points":['
    '{"alt":0.0,"bearing":null,"hacc":3.5,"lat":0.0,"lon":0.0,'
    '"provider":"gps","speed":0.0,"t":1767225601000},'
    '{"alt":null,"bearing":270.0,"hacc":5.0,"lat":-1.25,"lon":2.5,'
    '"provider":"fused","speed":1.25,"t":1767225606000}'
    '],"schema":"nef-gps-track/1"}'
).encode("utf-8")
VECTOR_PATH = Path(__file__).with_name("clp1_test_vector.json")


def derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=32
    )


def encode(plaintext: bytes, password: str, salt: bytes, nonce: bytes) -> bytes:
    if len(salt) != 16 or len(nonce) != 12:
        raise ValueError("CLP1 requires a 16-byte salt and a 12-byte nonce")
    header = MAGIC + ITERATIONS.to_bytes(4, "big") + salt + nonce
    return header + AESGCM(derive_key(password, salt)).encrypt(
        nonce, plaintext, header
    )


def decode(blob: bytes, password: str) -> bytes:
    if len(blob) < 52 or blob[:4] != MAGIC:
        raise ValueError("invalid CLP1 header")
    iterations = int.from_bytes(blob[4:8], "big")
    if iterations != ITERATIONS:
        raise ValueError("unsupported CLP1 iteration count")
    header, salt, nonce = blob[:36], blob[8:24], blob[24:36]
    return AESGCM(derive_key(password, salt)).decrypt(
        nonce, blob[36:], header
    )


def expected_vector() -> dict[str, object]:
    blob = encode(PLAINTEXT, PASSWORD, SALT, NONCE)
    return {
        "format": "CLP1 public deterministic test vector",
        "warning": "Fictional coordinates and fixed key material: test only",
        "password": PASSWORD,
        "iterations": ITERATIONS,
        "saltHex": SALT.hex(),
        "nonceHex": NONCE.hex(),
        "plaintextUtf8": PLAINTEXT.decode("utf-8"),
        "derivedKeyHex": derive_key(PASSWORD, SALT).hex(),
        "headerHex": blob[:36].hex(),
        "ciphertextHex": blob[36:-16].hex(),
        "tagHex": blob[-16:].hex(),
        "clpHex": blob.hex(),
        "clpSha256": hashlib.sha256(blob).hexdigest(),
    }


def must_reject(blob: bytes, password: str) -> None:
    try:
        decode(blob, password)
    except (ValueError, InvalidTag):
        return
    raise AssertionError("CLP1 unexpectedly accepted an invalid input")


def main() -> None:
    expected = expected_vector()
    if len(sys.argv) == 2 and sys.argv[1] == "--write-vector":
        VECTOR_PATH.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {VECTOR_PATH}")
        return
    if len(sys.argv) != 1:
        raise SystemExit("usage: verify_clp1_vector.py [--write-vector]")

    actual = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    if actual != expected:
        raise AssertionError("test vector differs from cryptographic output")
    blob = bytes.fromhex(actual["clpHex"])
    if decode(blob, PASSWORD) != PLAINTEXT:
        raise AssertionError("CLP1 plaintext round trip failed")
    parsed = json.loads(decode(blob, PASSWORD))
    if parsed["schema"] != "nef-gps-track/1" or len(parsed["points"]) != 2:
        raise AssertionError("CLP1 JSON payload mismatch")

    must_reject(blob, PASSWORD + "-wrong")
    changed_aad = bytearray(blob)
    changed_aad[24] ^= 1
    must_reject(bytes(changed_aad), PASSWORD)
    changed_ciphertext = bytearray(blob)
    changed_ciphertext[36] ^= 1
    must_reject(bytes(changed_ciphertext), PASSWORD)
    print("CLP1 vector: PASS (derive, encrypt, decrypt, wrong password, AAD, ciphertext)")


if __name__ == "__main__":
    main()
