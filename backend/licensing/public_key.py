"""
Ed25519 public key for license signature verification.

The private key is kept ONLY on the developer's machine and is used
by scripts/keygen.py to sign license keys.  This file contains only
the public key which is safe to distribute.

Replace the placeholder below with a real key when you generate your
Ed25519 keypair (see scripts/keygen.py --generate-keypair).
"""

from __future__ import annotations

# Base64-encoded Ed25519 public key (32 bytes → 44 chars base64)
# Replace this placeholder with your real public key.
PUBLIC_KEY_B64: str = "PLACEHOLDER_REPLACE_WITH_REAL_PUBLIC_KEY_BASE64"
