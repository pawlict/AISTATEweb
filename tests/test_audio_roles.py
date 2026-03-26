"""Tests for audio processing access by different user roles.

Verifies that:
- Transkryptor and Mistrz Sesji have access to transcription/diarization endpoints
- No role-based audio duration or file size limits exist
- All roles with the transcription/diarization module can access the same endpoints
- GPUResourceManager has no per-user limits
- Upload endpoint has no file size validation

NOTE: Tests that inspect webapp.server source code read the file directly
to avoid importing heavy dependencies (PyMuPDF, torch, etc.) that may
not be available in all test environments.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Path to server.py for source-level inspection
SERVER_PY = ROOT / "webapp" / "server.py"
AUTH_PY = ROOT / "webapp" / "routers" / "auth.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_test_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite database in tmp_path and configure the engine."""
    from backend.db.engine import set_db_path, init_db
    db_path = tmp_path / "test_audio.db"
    set_db_path(db_path)
    init_db(db_path)
    return db_path


def _read_source(path: Path) -> str:
    """Read a Python source file as text."""
    return path.read_text(encoding="utf-8")


def _extract_function_source(full_source: str, func_name: str) -> str:
    """Extract a function/method body from source text (simple heuristic)."""
    lines = full_source.splitlines()
    start = None
    indent = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {func_name}(") or stripped.startswith(f"async def {func_name}("):
            start = i
            indent = len(line) - len(stripped)
            continue
        if start is not None and i > start:
            # End of function: next line at same or lower indent (non-empty)
            if stripped and not line.startswith(" " * (indent + 1)) and not stripped.startswith("#") and not stripped.startswith("@"):
                return "\n".join(lines[start:i])
    if start is not None:
        return "\n".join(lines[start:])
    return ""


# ---------------------------------------------------------------------------
# 1. Permissions: roles and audio-related route access
# ---------------------------------------------------------------------------

class TestRoleAudioAccess:
    """Verify that roles with transcription/diarization modules can access
    all relevant API endpoints identically."""

    def test_transkryptor_has_transcription_module(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules("Transkryptor", False, [])
        assert "transcription" in modules
        assert "diarization" in modules

    def test_mistrz_sesji_has_transcription_module(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules("Mistrz Sesji", False, [])
        assert "transcription" in modules
        assert "diarization" in modules

    def test_superadmin_has_transcription_module(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules(None, True, [], is_superadmin=True)
        assert "transcription" in modules
        assert "diarization" in modules

    def test_transcription_routes_identical_access(self):
        """All roles with transcription module should access exact same routes."""
        from webapp.auth.permissions import get_user_modules, is_route_allowed

        routes_to_test = [
            "/transcription",
            "/api/transcribe",
            "/api/projects/",
        ]

        roles = ["Transkryptor", "Mistrz Sesji"]
        superadmin_modules = get_user_modules(None, True, [], is_superadmin=True)

        for role in roles:
            modules = get_user_modules(role, False, [])
            for route in routes_to_test:
                user_allowed = is_route_allowed(route, modules)
                admin_allowed = is_route_allowed(route, superadmin_modules)
                assert user_allowed == admin_allowed, (
                    f"Route access mismatch for {route}: "
                    f"{role}={user_allowed}, superadmin={admin_allowed}"
                )

    def test_diarization_routes_identical_access(self):
        """All roles with diarization module should access exact same routes."""
        from webapp.auth.permissions import get_user_modules, is_route_allowed

        routes_to_test = [
            "/diarization",
            "/api/diarize",
            "/api/projects/",
        ]

        roles = ["Transkryptor", "Mistrz Sesji"]
        superadmin_modules = get_user_modules(None, True, [], is_superadmin=True)

        for role in roles:
            modules = get_user_modules(role, False, [])
            for route in routes_to_test:
                user_allowed = is_route_allowed(route, modules)
                admin_allowed = is_route_allowed(route, superadmin_modules)
                assert user_allowed == admin_allowed, (
                    f"Route access mismatch for {route}: "
                    f"{role}={user_allowed}, superadmin={admin_allowed}"
                )

    def test_analityk_cannot_transcribe(self):
        """Analityk role should NOT have transcription/diarization access."""
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        modules = get_user_modules("Analityk", False, [])
        assert "transcription" not in modules
        assert "diarization" not in modules
        assert not is_route_allowed("/transcription", modules)
        assert not is_route_allowed("/diarization", modules)

    def test_lingwista_cannot_transcribe(self):
        """Lingwista role should NOT have transcription/diarization access."""
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        modules = get_user_modules("Lingwista", False, [])
        assert "transcription" not in modules
        assert "diarization" not in modules

    def test_api_keyword_access_identical(self):
        """API keyword routes (transcript, diarized, etc.) should be accessible
        identically for all roles with the corresponding module."""
        from webapp.auth.permissions import get_user_modules, is_route_allowed

        keyword_routes = [
            "/api/projects/abc123/transcript_segments",
            "/api/projects/abc123/diarized_segments",
            "/api/projects/abc123/sound-detection",
            "/api/asr/models_state",
            "/api/asr/installed",
        ]

        roles = ["Transkryptor", "Mistrz Sesji"]
        superadmin_modules = get_user_modules(None, True, [], is_superadmin=True)

        for role in roles:
            modules = get_user_modules(role, False, [])
            for route in keyword_routes:
                user_allowed = is_route_allowed(route, modules)
                admin_allowed = is_route_allowed(route, superadmin_modules)
                assert user_allowed == admin_allowed, (
                    f"API keyword route mismatch for {route}: "
                    f"{role}={user_allowed}, superadmin={admin_allowed}"
                )


# ---------------------------------------------------------------------------
# 2. No per-role audio limits in code (source-level inspection)
# ---------------------------------------------------------------------------

class TestNoAudioLimits:
    """Verify that there are no hidden file size or duration limits
    in the upload and processing pipeline (via source inspection)."""

    def test_save_upload_no_size_check(self):
        """save_upload should accept files of any size without validation."""
        source = _extract_function_source(_read_source(SERVER_PY), "save_upload")
        assert source, "save_upload function not found in server.py"
        assert "max_size" not in source, \
            "save_upload should not enforce max file size"
        assert "content-length" not in source.lower(), \
            "save_upload should not check Content-Length"
        assert "file_size" not in source.lower(), \
            "save_upload should not check file size"
        assert "shutil.copyfileobj" in source, \
            "save_upload should use streaming copy"

    def test_transcribe_endpoint_no_role_check(self):
        """api_transcribe does not inspect request.state.user for role-based limits."""
        source = _extract_function_source(_read_source(SERVER_PY), "api_transcribe")
        assert source, "api_transcribe function not found in server.py"
        assert "request.state.user" not in source, \
            "api_transcribe should not check user role"
        assert "max_duration" not in source, \
            "api_transcribe should not have duration limits"
        assert "max_size" not in source, \
            "api_transcribe should not have file size limits"

    def test_diarize_endpoint_no_role_check(self):
        """api_diarize_voice does not inspect request.state.user for role-based limits."""
        source = _extract_function_source(_read_source(SERVER_PY), "api_diarize_voice")
        assert source, "api_diarize_voice function not found in server.py"
        assert "request.state.user" not in source, \
            "api_diarize_voice should not check user role"
        assert "max_duration" not in source, \
            "api_diarize_voice should not have duration limits"
        assert "max_size" not in source, \
            "api_diarize_voice should not have file size limits"

    def test_no_role_based_limits_in_entire_server(self):
        """The entire server.py should not have per-role audio limits."""
        source = _read_source(SERVER_PY)
        # These patterns would indicate per-role limits
        assert "max_audio_duration" not in source, \
            "server.py should not define max_audio_duration"
        assert "role_audio_limit" not in source, \
            "server.py should not define role_audio_limit"
        assert "user_file_limit" not in source, \
            "server.py should not define user_file_limit"


# ---------------------------------------------------------------------------
# 3. GPU Resource Manager: no per-user limits (source-level inspection)
# ---------------------------------------------------------------------------

class TestGPUResourceManagerLimits:
    """Verify GPUResourceManager has no per-user job limits."""

    def test_no_per_user_limit_in_enqueue(self):
        """enqueue_subprocess should not check user identity or enforce per-user limits."""
        source = _extract_function_source(_read_source(SERVER_PY), "enqueue_subprocess")
        assert source, "enqueue_subprocess not found in server.py"
        assert "user_id" not in source, \
            "enqueue_subprocess should not filter by user_id"

    def test_no_per_user_limit_in_loop(self):
        """The scheduling loop should not enforce per-user concurrency limits."""
        source = _read_source(SERVER_PY)
        # Find the _loop method within GPUResourceManager
        loop_source = _extract_function_source(source, "_loop")
        assert loop_source, "_loop method not found in server.py"
        assert "user_id" not in loop_source, \
            "_loop should not filter by user_id"
        assert "per_user" not in loop_source, \
            "_loop should not have per_user limits"

    def test_gpu_init_has_no_user_limits(self):
        """GPUResourceManager __init__ should not define per-user limits."""
        source = _read_source(SERVER_PY)
        # Find __init__ for GPUResourceManager
        # Look for the class and its __init__
        lines = source.splitlines()
        in_gpu_rm = False
        init_source = []
        for line in lines:
            if "class GPUResourceManager" in line:
                in_gpu_rm = True
                continue
            if in_gpu_rm and "def __init__" in line:
                init_source.append(line)
                continue
            if init_source:
                if line.strip() and not line.startswith("    ") and not line.startswith("\t"):
                    break
                if line.strip().startswith("def ") and "def __init__" not in line:
                    break
                init_source.append(line)

        init_text = "\n".join(init_source)
        assert "max_per_user" not in init_text, \
            "GPUResourceManager should not have max_per_user"
        assert "user_quota" not in init_text, \
            "GPUResourceManager should not have user_quota"
        assert "user_limit" not in init_text, \
            "GPUResourceManager should not have user_limit"

    def test_priority_categories_are_global(self):
        """Priority categories should be by feature kind, not per-user."""
        source = _read_source(SERVER_PY)
        # Find category_priorities definition
        assert "category_priorities" in source
        # Extract the dict
        start = source.find("category_priorities")
        chunk = source[start:start + 500]
        assert "user" not in chunk.lower() or "user" in "enqueue_subprocess", \
            "Priority categories should not be user-specific"
        # Verify key features are prioritized
        assert '"transcription"' in chunk or "'transcription'" in chunk
        assert '"diarization"' in chunk or "'diarization'" in chunk


# ---------------------------------------------------------------------------
# 4. Module definition consistency for audio roles
# ---------------------------------------------------------------------------

class TestModuleDefinitionConsistency:
    """Verify that the transcription/diarization modules define
    consistent API prefixes and keywords."""

    def test_transcription_module_api_prefixes(self):
        from webapp.auth.permissions import MODULES
        mod = MODULES["transcription"]
        assert "/api/transcribe" in mod["api_prefixes"]
        assert "/api/projects/" in mod["api_prefixes"]

    def test_diarization_module_api_prefixes(self):
        from webapp.auth.permissions import MODULES
        mod = MODULES["diarization"]
        assert "/api/diarize" in mod["api_prefixes"]
        assert "/api/projects/" in mod["api_prefixes"]

    def test_transcription_keywords_include_asr(self):
        from webapp.auth.permissions import MODULES
        mod = MODULES["transcription"]
        assert "asr/models_state" in mod["api_keywords"]
        assert "asr/installed" in mod["api_keywords"]

    def test_diarization_keywords_include_asr(self):
        from webapp.auth.permissions import MODULES
        mod = MODULES["diarization"]
        assert "asr/models_state" in mod["api_keywords"]
        assert "asr/installed" in mod["api_keywords"]

    def test_both_modules_share_project_access(self):
        """Both transcription and diarization should include /api/projects/
        prefix for accessing project data."""
        from webapp.auth.permissions import MODULES
        trans = MODULES["transcription"]
        diar = MODULES["diarization"]
        assert "/api/projects/" in trans["api_prefixes"]
        assert "/api/projects/" in diar["api_prefixes"]


# ---------------------------------------------------------------------------
# 5. Auth middleware: route check is binary (allow/deny), no feature limits
# ---------------------------------------------------------------------------

class TestAuthMiddlewareNoFeatureLimits:
    """Verify the auth middleware only does allow/deny per module,
    with no feature-level limits (file size, duration, etc.)."""

    def test_middleware_source_has_no_duration_check(self):
        """The auth middleware should not contain any duration or size checks."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found in server.py"
        assert "duration" not in source.lower(), \
            "Auth middleware should not check audio duration"
        assert "file_size" not in source.lower(), \
            "Auth middleware should not check file size"
        assert "max_length" not in source.lower(), \
            "Auth middleware should not enforce max audio length"

    def test_middleware_uses_binary_route_check(self):
        """Auth middleware should call is_route_allowed for access control."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found in server.py"
        assert "is_route_allowed" in source, \
            "Auth middleware should use is_route_allowed for authorization"

    def test_all_audio_roles_get_identical_modules_for_audio(self):
        """Verify that every role with transcription access gets
        the exact same transcription module definition."""
        from webapp.auth.permissions import get_user_modules, MODULES, ROLE_MODULES

        roles_with_transcription = [
            role for role, mods in ROLE_MODULES.items()
            if "transcription" in mods
        ]

        # Should include at least Transkryptor and Mistrz Sesji
        assert "Transkryptor" in roles_with_transcription
        assert "Mistrz Sesji" in roles_with_transcription

        # Each role gets the same module definition (same prefixes, keywords)
        for role in roles_with_transcription:
            modules = get_user_modules(role, False, [])
            assert "transcription" in modules


# ---------------------------------------------------------------------------
# 6. Full-stack integration: simulated transcription request per role
# ---------------------------------------------------------------------------

class TestTranscriptionIntegration:
    """Integration tests simulating transcription requests from different roles."""

    def test_transkryptor_transcription_route_allowed(self, tmp_path):
        """Simulate route check for Transkryptor accessing /api/transcribe."""
        _init_test_db(tmp_path)
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password

        us = UserStore(tmp_path)
        user = us.create_user(UserRecord(
            username="transkryptor_user",
            password_hash=hash_password("pass123"),
            role="Transkryptor",
        ))
        modules = get_user_modules(user.role, user.is_admin, user.admin_roles, user.is_superadmin)
        assert is_route_allowed("/api/transcribe", modules)
        assert is_route_allowed("/api/diarize", modules)

    def test_mistrz_sesji_transcription_route_allowed(self, tmp_path):
        """Simulate route check for Mistrz Sesji accessing /api/transcribe."""
        _init_test_db(tmp_path)
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password

        us = UserStore(tmp_path)
        user = us.create_user(UserRecord(
            username="mistrz_user",
            password_hash=hash_password("pass123"),
            role="Mistrz Sesji",
        ))
        modules = get_user_modules(user.role, user.is_admin, user.admin_roles, user.is_superadmin)
        assert is_route_allowed("/api/transcribe", modules)
        assert is_route_allowed("/api/diarize", modules)

    def test_superadmin_transcription_route_allowed(self, tmp_path):
        """Simulate route check for superadmin (Główny Opiekun) accessing /api/transcribe."""
        _init_test_db(tmp_path)
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password

        us = UserStore(tmp_path)
        user = us.create_user(UserRecord(
            username="admin_user",
            password_hash=hash_password("pass123"),
            role="Mistrz Sesji",
            is_admin=True,
            is_superadmin=True,
            admin_roles=["Architekt Funkcji", "Strażnik Dostępu"],
        ))
        modules = get_user_modules(user.role, user.is_admin, user.admin_roles, user.is_superadmin)
        assert is_route_allowed("/api/transcribe", modules)
        assert is_route_allowed("/api/diarize", modules)

    def test_identical_access_for_all_audio_roles(self, tmp_path):
        """All roles with audio access should have identical endpoint access."""
        _init_test_db(tmp_path)
        from webapp.auth.permissions import get_user_modules, is_route_allowed
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password

        us = UserStore(tmp_path)
        audio_routes = [
            "/api/transcribe",
            "/api/diarize",
            "/transcription",
            "/diarization",
            "/api/projects/test123/transcript_segments",
            "/api/projects/test123/diarized_segments",
        ]

        users_data = [
            ("transkryptor", "Transkryptor", False, False),
            ("mistrz", "Mistrz Sesji", False, False),
            ("admin", "Mistrz Sesji", True, True),
        ]

        results = {}
        for uname, role, is_admin, is_superadmin in users_data:
            user = us.create_user(UserRecord(
                username=uname,
                password_hash=hash_password("pass"),
                role=role,
                is_admin=is_admin,
                is_superadmin=is_superadmin,
            ))
            modules = get_user_modules(role, is_admin, [], is_superadmin=is_superadmin)
            results[uname] = {
                route: is_route_allowed(route, modules)
                for route in audio_routes
            }

        # All audio routes should be accessible by all audio roles
        for uname, route_access in results.items():
            for route, allowed in route_access.items():
                assert allowed, (
                    f"User '{uname}' should have access to '{route}' but doesn't"
                )
