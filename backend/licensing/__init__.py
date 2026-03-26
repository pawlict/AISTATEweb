"""
AISTATEweb Licensing Module
===========================

Controls whether the application requires a license key to operate.

When LICENSING_ENABLED = False (default):
  - All features are unlocked
  - No license key required
  - The license panel is visible but informational only
  - @require_feature() decorators pass through everything

When LICENSING_ENABLED = True:
  - A valid license key is required
  - Features are gated by the plan encoded in the key
  - Expired licenses allow read-only access
"""

from __future__ import annotations

# ============================================================
# MASTER SWITCH
# Set to True when you are ready to enforce licensing.
# While False, the app works without restrictions.
# ============================================================
LICENSING_ENABLED: bool = True
