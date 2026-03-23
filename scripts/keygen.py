#!/usr/bin/env python3
"""
AISTATEweb License Key Generator
=================================

This script is for the DEVELOPER ONLY.  Never distribute it with the app.

Usage:
    # Generate a new Ed25519 keypair (do this ONCE):
    python scripts/keygen.py --generate-keypair

    # Generate a license key:
    python scripts/keygen.py \\
        --email "jan@firma.pl" \\
        --plan pro \\
        --expires perpetual \\
        --updates-until perpetual \\
        --features all

    # Generate a time-limited key:
    python scripts/keygen.py \\
        --email "jan@firma.pl" \\
        --plan pro \\
        --expires 2027-03-22 \\
        --updates-until 2027-03-22

The private key is stored in ~/.aistate_private_key.pem
The public key is printed for embedding in backend/licensing/public_key.py
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import date
from pathlib import Path

PRIVATE_KEY_PATH = Path.home() / ".aistate_private_key.pem"


def generate_keypair() -> None:
    """Generate a new Ed25519 keypair and save the private key."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("ERROR: pip install cryptography")
        sys.exit(1)

    if PRIVATE_KEY_PATH.exists():
        resp = input(f"Private key already exists at {PRIVATE_KEY_PATH}. Overwrite? [y/N] ")
        if resp.lower() != "y":
            print("Aborted.")
            return

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.write_bytes(pem)
    PRIVATE_KEY_PATH.chmod(0o600)

    # Show public key
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub_bytes).decode()

    print(f"\nPrivate key saved to: {PRIVATE_KEY_PATH}")
    print(f"\nPublic key (base64) — paste into backend/licensing/public_key.py:")
    print(f'PUBLIC_KEY_B64: str = "{pub_b64}"')
    print()


def load_private_key():
    """Load the Ed25519 private key from disk."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        print("ERROR: pip install cryptography")
        sys.exit(1)

    if not PRIVATE_KEY_PATH.exists():
        print(f"ERROR: Private key not found at {PRIVATE_KEY_PATH}")
        print("Run: python scripts/keygen.py --generate-keypair")
        sys.exit(1)

    pem = PRIVATE_KEY_PATH.read_bytes()
    return load_pem_private_key(pem, password=None)


def generate_license_key(
    email: str,
    plan: str,
    expires: str,
    updates_until: str,
    features: str,
) -> str:
    """Generate a signed license key."""
    private_key = load_private_key()

    # Build payload
    lid = f"{plan.upper()}-{uuid.uuid4().hex[:8].upper()}"

    payload = {
        "lid": lid,
        "email": email,
        "plan": plan,
        "issued": date.today().isoformat(),
        "expires": expires,
        "updates_until": updates_until,
    }

    # Features
    if features == "all":
        payload["features"] = ["all"]
    else:
        payload["features"] = [f.strip() for f in features.split(",")]

    # Encode
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    data_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("utf-8")

    # Sign
    signature = private_key.sign(data_b64.encode("utf-8"))
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    key = f"AIST-{data_b64}.{sig_b64}"
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="AISTATEweb License Key Generator")
    parser.add_argument("--generate-keypair", action="store_true",
                        help="Generate a new Ed25519 keypair")
    parser.add_argument("--email", default="", help="Customer email")
    parser.add_argument("--plan", default="pro", choices=["community", "pro", "enterprise"],
                        help="License plan (default: pro)")
    parser.add_argument("--expires", default="perpetual",
                        help="Expiry date (YYYY-MM-DD or 'perpetual')")
    parser.add_argument("--updates-until", default="perpetual",
                        help="Updates valid until (YYYY-MM-DD or 'perpetual')")
    parser.add_argument("--features", default="all",
                        help="Comma-separated features or 'all'")

    args = parser.parse_args()

    if args.generate_keypair:
        generate_keypair()
        return

    if not args.email:
        print("ERROR: --email is required when generating a key")
        sys.exit(1)

    key = generate_license_key(
        email=args.email,
        plan=args.plan,
        expires=args.expires,
        updates_until=args.updates_until,
        features=args.features,
    )

    print(f"\nLicense Key:")
    print(f"{key}")
    print(f"\nDetails:")
    print(f"  Email: {args.email}")
    print(f"  Plan: {args.plan}")
    print(f"  Expires: {args.expires}")
    print(f"  Updates until: {args.updates_until}")
    print(f"  Features: {args.features}")
    print(f"\nSend this key to the customer.")


if __name__ == "__main__":
    main()
