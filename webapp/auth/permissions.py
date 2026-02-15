from __future__ import annotations

from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Module definitions — each module groups page routes + API prefixes
# ---------------------------------------------------------------------------

MODULES: Dict[str, Dict[str, List[str]]] = {
    "transcription": {
        "pages": ["/transcription"],
        "api_prefixes": ["/api/transcribe", "/api/projects/"],
        "api_keywords": ["transcript", "sound-detection", "asr/models_state", "asr/installed"],
    },
    "diarization": {
        "pages": ["/diarization"],
        "api_prefixes": ["/api/diarize"],
        "api_keywords": ["diarized", "speaker_map", "asr/models_state", "asr/installed"],
    },
    "translation": {
        "pages": ["/translation"],
        "api_prefixes": ["/api/translation/"],
        "api_keywords": ["nllb/models_state"],
    },
    "analysis": {
        "pages": ["/analysis", "/analiza"],
        "api_prefixes": ["/api/analysis/", "/api/finance/", "/api/documents/"],
        "api_keywords": ["ollama/status", "ollama/models", "settings/models", "settings/analysis", "models/list"],
    },
    "chat": {
        "pages": ["/chat"],
        "api_prefixes": ["/api/chat/"],
        "api_keywords": ["ollama/models"],
    },
    "projects": {
        "pages": ["/new-project", "/save", "/nowy-projekt", "/zapis"],
        "api_prefixes": ["/api/projects"],
        "api_keywords": [],
    },
    "admin_settings": {
        "pages": [
            "/settings", "/llm-settings", "/asr-settings",
            "/nllb-settings", "/tts-settings", "/admin", "/logs",
            "/ustawienia", "/ustawienia-llm", "/logi",
        ],
        "api_prefixes": [
            "/api/settings", "/api/asr/", "/api/nllb/",
            "/api/tts/", "/api/admin/", "/api/ollama/",
            "/api/sound-detection/",
        ],
        "api_keywords": [],
    },
    "user_mgmt": {
        "pages": ["/users"],
        "api_prefixes": ["/api/users", "/api/auth/audit", "/api/auth/password-blacklist"],
        "api_keywords": ["settings/security"],
    },
}

# ---------------------------------------------------------------------------
# Role → modules mapping
# ---------------------------------------------------------------------------

ROLE_MODULES: Dict[str, List[str]] = {
    "Transkryptor":   ["projects", "transcription", "diarization"],
    "Lingwista":      ["projects", "translation"],
    "Analityk":       ["projects", "analysis"],
    "Dialogista":     ["projects", "chat"],
    "Strateg":        ["projects", "translation", "analysis", "chat"],
    "Mistrz Sesji":   ["projects", "transcription", "diarization", "translation", "analysis", "chat"],
}

ADMIN_ROLE_MODULES: Dict[str, List[str]] = {
    "Architekt Funkcji":  ["admin_settings"],
    "Strażnik Dostępu":   ["user_mgmt"],
}

# Główny Opiekun (Super Admin) always has everything
SUPER_ADMIN_MODULES: List[str] = list(MODULES.keys())

ALL_USER_ROLES: List[str] = list(ROLE_MODULES.keys())
ALL_ADMIN_ROLES: List[str] = list(ADMIN_ROLE_MODULES.keys())

# ---------------------------------------------------------------------------
# Public routes (no auth needed)
# ---------------------------------------------------------------------------

PUBLIC_ROUTES: Set[str] = {
    "/login",
    "/register",
    "/pending",
    "/setup",
    "/banned",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/request-reset",
    "/api/auth/password-policy",
    "/api/setup/mode",
    "/api/setup/admin",
    "/api/setup/migrate",
}

PUBLIC_PREFIXES: List[str] = [
    "/static/",
    "/api/auth/login",
    "/api/auth/register",
    "/api/setup/",
]

# Routes accessible by any logged-in user (regardless of role)
COMMON_ROUTES: Set[str] = {
    "/",
    "/info",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/auth/language",
    "/api/auth/my-audit",
    "/api/auth/password-policy",
}

COMMON_PREFIXES: List[str] = [
    "/api/projects/",  # filtered by ownership in the handler
    "/api/tts/voices",  # read-only: all users can list available TTS voices
    "/api/tts/engines",  # read-only: TTS engine info
    "/api/messages",  # call center messaging system (matches /api/messages and /api/messages/*)
    "/api/tasks/",  # task progress checking — used by all modules (analysis, transcription, etc.)
]


def get_user_modules(role: Optional[str], is_admin: bool, admin_roles: Optional[List[str]], is_superadmin: bool = False) -> List[str]:
    """Return the full list of modules a user may access."""
    if is_superadmin:
        return SUPER_ADMIN_MODULES[:]

    modules: List[str] = []

    # User role modules
    if role and role in ROLE_MODULES:
        modules.extend(ROLE_MODULES[role])

    # Admin role modules
    # If is_admin but admin_roles is empty/None, grant ALL admin modules
    # (prevents lockout when admin_roles was not set during user creation)
    if is_admin:
        if admin_roles:
            for ar in admin_roles:
                if ar in ADMIN_ROLE_MODULES:
                    modules.extend(ADMIN_ROLE_MODULES[ar])
        else:
            # Fallback: admin without specific roles gets all admin modules
            for ar_mods in ADMIN_ROLE_MODULES.values():
                modules.extend(ar_mods)

    # Deduplicate keeping order
    seen: Set[str] = set()
    result: List[str] = []
    for m in modules:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def is_route_allowed(path: str, user_modules: List[str]) -> bool:
    """Check if a request path is permitted for a user's module set."""
    # Public routes always allowed
    if path in PUBLIC_ROUTES:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True

    # Common routes for any logged-in user
    if path in COMMON_ROUTES:
        return True
    for prefix in COMMON_PREFIXES:
        if path.startswith(prefix):
            return True

    # Check each module the user has
    for mod_name in user_modules:
        mod = MODULES.get(mod_name)
        if not mod:
            continue
        # Page match
        if path in mod["pages"]:
            return True
        # API prefix match
        for prefix in mod["api_prefixes"]:
            if path.startswith(prefix):
                return True
        # API keyword match (for sub-paths like /api/projects/{id}/transcript_segments)
        for kw in mod.get("api_keywords", []):
            if kw in path:
                return True

    return False
