from __future__ import annotations
from dataclasses import dataclass

# ====== App identity (used by UI + reports) ======
# NOTE: Name/version are intentionally sourced from this file.
APP_NAME: str = "AISTATEweb"
APP_VERSION: str = "3.7 beta"
AUTHOR_EMAIL: str = "pawlict@proton.me"
AUTHOR_NAME: str = "pawlict"

@dataclass
class Settings:
    hf_token: str = ""
    opencellid_token: str = ""
    default_language: str = "auto"
    whisper_model: str = "base"
    theme: str = "Fusion Light (Blue)"
    ui_language: str = "pl"
    session_timeout_hours: int = 8
    # Security: account lockout
    account_lockout_threshold: int = 5      # failed attempts before lock (0 = disabled)
    account_lockout_duration: int = 15      # minutes of lockout
    # Security: password policy ("none", "basic", "medium", "strong")
    password_policy: str = "basic"
    # Security: password expiration (days, 0 = disabled)
    password_expiry_days: int = 0
    # Map source: "auto" (offline if available, else online), "offline", "online"
    map_source: str = "auto"
    # Encryption policy
    encryption_enabled: bool = False                # global toggle
    encryption_method: str = "standard"             # "light", "standard", "maximum"
    encryption_force_new_projects: bool = False      # force encryption on all new projects
    encryption_master_key_initialized: bool = False  # True once Master Key is created
    # ARIA HUD — Analytical Response & Intelligence Assistant
    aria_enabled: bool = False                        # admin toggle — show ARIA HUD globally
    aria_voice: str = "pl_PL-gosia-medium"            # Piper TTS voice model
    aria_tts_enabled: bool = True                     # enable TTS in ARIA responses
