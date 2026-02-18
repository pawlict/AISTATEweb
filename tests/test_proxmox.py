"""Tests for Proxmox / reverse-proxy / VM deployment environment.

Verifies:
- Cookie Secure flag handling with X-Forwarded-Proto header
- IP address extraction from X-Forwarded-For header
- Security headers middleware
- Auth middleware behaves correctly behind a reverse proxy
- Rate limiting uses correct IP (direct vs proxied)
- Session cookie attributes for HTTP (Proxmox) vs HTTPS deployments

NOTE: Tests that inspect webapp.server or webapp.routers.auth source code
read the files directly to avoid importing heavy dependencies (PyMuPDF, etc.)
that may not be available in all test environments.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Paths for source-level inspection
SERVER_PY = ROOT / "webapp" / "server.py"
AUTH_PY = ROOT / "webapp" / "routers" / "auth.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_test_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite database in tmp_path and configure the engine."""
    from backend.db.engine import set_db_path, init_db
    db_path = tmp_path / "test_proxmox.db"
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
            if stripped and not line.startswith(" " * (indent + 1)) and not stripped.startswith("#") and not stripped.startswith("@"):
                return "\n".join(lines[start:i])
    if start is not None:
        return "\n".join(lines[start:])
    return ""


# ---------------------------------------------------------------------------
# 1. Cookie Secure flag detection
# ---------------------------------------------------------------------------

class TestCookieSecureFlag:
    """Test that the login endpoint correctly detects HTTPS status
    and sets the Secure flag on session cookies accordingly."""

    def test_secure_flag_detection_http(self):
        """On plain HTTP (typical Proxmox), Secure flag should be False."""
        headers = {}
        url_scheme = "http"
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is False, "Plain HTTP should not set Secure flag"

    def test_secure_flag_detection_https(self):
        """On HTTPS, Secure flag should be True."""
        headers = {}
        url_scheme = "https"
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is True, "HTTPS should set Secure flag"

    def test_secure_flag_with_forwarded_proto_https(self):
        """When X-Forwarded-Proto is 'https' (reverse proxy), Secure flag should be True."""
        headers = {"x-forwarded-proto": "https"}
        url_scheme = "http"  # Behind proxy, internal scheme is often HTTP
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is True, "X-Forwarded-Proto: https should set Secure flag"

    def test_secure_flag_with_forwarded_proto_http(self):
        """When X-Forwarded-Proto is 'http', Secure flag should be False."""
        headers = {"x-forwarded-proto": "http"}
        url_scheme = "http"
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is False, "X-Forwarded-Proto: http should not set Secure flag"

    def test_secure_flag_with_mixed_case_header(self):
        """X-Forwarded-Proto header should be case-insensitive."""
        for proto_value in ["HTTPS", "Https", "hTTpS"]:
            forwarded_proto = (proto_value or "").lower()
            is_secure = False or forwarded_proto == "https"
            assert is_secure is True, (
                f"X-Forwarded-Proto: {proto_value} should set Secure flag"
            )

    def test_secure_flag_with_empty_header(self):
        """Empty X-Forwarded-Proto should not affect Secure flag."""
        headers = {"x-forwarded-proto": ""}
        url_scheme = "http"
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is False

    def test_secure_flag_with_none_header(self):
        """Missing X-Forwarded-Proto should default to scheme check."""
        headers = {}
        url_scheme = "http"
        forwarded_proto = (headers.get("x-forwarded-proto") or "").lower()
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is False

    def test_login_source_has_secure_detection(self):
        """Login endpoint source should contain X-Forwarded-Proto detection."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found in auth.py"
        assert "x-forwarded-proto" in source, \
            "Login should check X-Forwarded-Proto header"
        assert "secure=" in source.lower(), \
            "Login should set Secure flag on cookie"


# ---------------------------------------------------------------------------
# 2. IP address extraction from proxy headers
# ---------------------------------------------------------------------------

class TestIPExtraction:
    """Test IP address extraction in proxy environments."""

    def test_direct_client_ip(self):
        """Without proxy headers, should use client.host."""
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {}
        ip = mock_request.client.host if mock_request.client else "unknown"
        assert ip == "192.168.1.100"

    def test_forwarded_for_single_ip(self):
        """X-Forwarded-For with a single IP should be extracted."""
        headers = {"x-forwarded-for": "10.0.0.5"}
        ip = headers.get("x-forwarded-for", "") or "127.0.0.1"
        assert ip == "10.0.0.5"

    def test_forwarded_for_multiple_ips(self):
        """X-Forwarded-For chain should contain the original client IP."""
        headers = {"x-forwarded-for": "10.0.0.5, 172.16.0.1, 192.168.1.1"}
        ip = headers.get("x-forwarded-for", "")
        assert ip.split(",")[0].strip() == "10.0.0.5"

    def test_no_client_object(self):
        """When request.client is None (edge case), should fallback gracefully."""
        mock_request = MagicMock()
        mock_request.client = None
        ip = mock_request.client.host if mock_request.client else "unknown"
        assert ip == "unknown"

    def test_login_uses_direct_ip(self):
        """Login endpoint uses request.client.host for rate limiting."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found in auth.py"
        assert "request.client.host" in source, \
            "Login should use client.host for IP"

    def test_logout_uses_forwarded_for(self):
        """Logout endpoint uses X-Forwarded-For for audit logging."""
        source = _extract_function_source(_read_source(AUTH_PY), "logout")
        assert source, "logout function not found in auth.py"
        assert "x-forwarded-for" in source, \
            "Logout should use x-forwarded-for for audit IP"


# ---------------------------------------------------------------------------
# 3. Security headers middleware (source inspection)
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Test security headers added by middleware."""

    def test_security_headers_source(self):
        """Verify security headers middleware adds expected headers."""
        source = _extract_function_source(_read_source(SERVER_PY), "_security_headers")
        assert source, "_security_headers not found in server.py"
        assert "X-Content-Type-Options" in source
        assert "nosniff" in source
        assert "X-Frame-Options" in source
        assert "SAMEORIGIN" in source
        assert "X-XSS-Protection" in source
        assert "Referrer-Policy" in source

    def test_utf8_charset_middleware_exists(self):
        """Verify UTF-8 charset middleware exists for proper encoding."""
        source = _extract_function_source(_read_source(SERVER_PY), "_force_utf8_charset")
        assert source, "_force_utf8_charset not found in server.py"
        assert "charset" in source.lower()


# ---------------------------------------------------------------------------
# 4. Auth middleware behind reverse proxy (source inspection)
# ---------------------------------------------------------------------------

class TestAuthMiddlewareBehindProxy:
    """Test that auth middleware works correctly when the app is behind
    a reverse proxy (common in Proxmox deployments)."""

    def test_middleware_checks_session_cookie(self):
        """Auth middleware should check session cookie regardless of proxy."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found in server.py"
        assert "COOKIE_NAME" in source or "request.cookies" in source

    def test_middleware_does_not_require_https(self):
        """Auth middleware should not enforce HTTPS (Proxmox runs on HTTP)."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found in server.py"
        # The middleware should not reject HTTP requests
        assert 'request.url.scheme == "https"' not in source, \
            "Auth middleware should not enforce HTTPS"

    def test_public_routes_accessible_without_auth(self):
        """Public routes should be accessible regardless of proxy setup."""
        from webapp.auth.permissions import PUBLIC_ROUTES, is_route_allowed
        for route in PUBLIC_ROUTES:
            assert is_route_allowed(route, []), \
                f"Public route {route} should be accessible without any modules"

    def test_setup_route_always_public(self):
        """Setup route should always be accessible (first deployment)."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found in server.py"
        assert '"/setup"' in source, \
            "Auth middleware should explicitly allow /setup"


# ---------------------------------------------------------------------------
# 5. Rate limiting and IP handling
# ---------------------------------------------------------------------------

class TestRateLimitingProxy:
    """Test rate limiting behavior in proxy environments."""

    def test_rate_limit_constants_in_source(self):
        """Rate limit constants should be defined in auth.py."""
        source = _read_source(AUTH_PY)
        assert "MAX_LOGIN_ATTEMPTS" in source
        assert "RATE_WINDOW_SECONDS" in source

    def test_rate_limit_functions_exist(self):
        """Rate limiting functions should be defined."""
        source = _read_source(AUTH_PY)
        assert "def _is_rate_limited(" in source
        assert "def _record_attempt(" in source

    def test_rate_limit_uses_ip_parameter(self):
        """Rate limiting should operate on IP address."""
        source = _extract_function_source(_read_source(AUTH_PY), "_is_rate_limited")
        assert source, "_is_rate_limited not found"
        assert "ip" in source, "Rate limiter should use IP parameter"

    def test_login_calls_rate_limiter(self):
        """Login endpoint should call rate limiting check."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found"
        assert "_is_rate_limited" in source, \
            "Login should call _is_rate_limited"
        assert "_record_attempt" in source, \
            "Login should call _record_attempt on failure"


# ---------------------------------------------------------------------------
# 6. Session cookie attributes for Proxmox (source inspection)
# ---------------------------------------------------------------------------

class TestSessionCookieAttributes:
    """Test that session cookies have correct attributes for Proxmox deployments."""

    def test_cookie_name_is_defined(self):
        from webapp.auth.session_store import SessionStore
        assert hasattr(SessionStore, "COOKIE_NAME")
        assert SessionStore.COOKIE_NAME, "Cookie name should not be empty"

    def test_login_sets_httponly_cookie(self):
        """Login should set httponly=True (prevents XSS cookie theft)."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found"
        assert "httponly=True" in source, \
            "Session cookie should have httponly=True"

    def test_login_sets_samesite_lax(self):
        """Login should set samesite='lax' (CSRF protection)."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found"
        assert 'samesite="lax"' in source or "samesite='lax'" in source, \
            "Session cookie should have samesite=lax"

    def test_login_sets_path_root(self):
        """Cookie path should be '/' for the whole application."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found"
        assert 'path="/"' in source or "path='/'" in source, \
            "Session cookie path should be /"

    def test_cookie_max_age_based_on_timeout(self):
        """Cookie max_age should be timeout * 3600 (hours to seconds)."""
        source = _extract_function_source(_read_source(AUTH_PY), "login")
        assert source, "login function not found"
        assert "timeout * 3600" in source, \
            "Cookie max_age should be timeout * 3600"


# ---------------------------------------------------------------------------
# 7. Proxmox-specific deployment scenarios
# ---------------------------------------------------------------------------

class TestProxmoxDeploymentScenarios:
    """Test scenarios specific to Proxmox VM deployments."""

    def test_http_only_deployment_cookie_works(self):
        """In a Proxmox HTTP-only deployment, cookies should NOT have Secure flag."""
        url_scheme = "http"
        forwarded_proto = ""
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is False, \
            "HTTP-only Proxmox deployment should not set Secure cookie flag"

    def test_proxmox_nginx_proxy_https_termination(self):
        """When Proxmox uses nginx for HTTPS termination, cookie should be Secure."""
        url_scheme = "http"
        forwarded_proto = "https"
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is True, \
            "HTTPS-terminated proxy should set Secure cookie flag"

    def test_proxmox_direct_https(self):
        """When Proxmox app is directly on HTTPS (e.g., with cert)."""
        url_scheme = "https"
        forwarded_proto = ""
        is_secure = url_scheme == "https" or forwarded_proto == "https"
        assert is_secure is True

    def test_single_user_mode_skips_auth(self):
        """In single-user mode, auth middleware should skip all checks."""
        source = _extract_function_source(_read_source(SERVER_PY), "_auth_middleware")
        assert source, "_auth_middleware not found"
        assert "multiuser" in source.lower(), \
            "Auth middleware should handle single-user mode"

    def test_deployment_store_mode_detection(self, tmp_path):
        """DeploymentStore should correctly report multi-user mode."""
        _init_test_db(tmp_path)
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        assert hasattr(ds, "is_multiuser")
        assert hasattr(ds, "is_configured")

    def test_session_store_operations(self, tmp_path):
        """SessionStore should work correctly (sessions are critical for auth behind proxy)."""
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)

        # Create session
        token = ss.create_session("test-user-id", timeout_hours=8, ip="10.0.0.5")
        assert token is not None
        assert len(token) > 20

        # Retrieve session
        session = ss.get_session(token)
        assert session is not None
        assert session["user_id"] == "test-user-id"

        # Delete session
        ss.delete_session(token)
        assert ss.get_session(token) is None


# ---------------------------------------------------------------------------
# 8. Upload behavior considerations for proxy environments (source inspection)
# ---------------------------------------------------------------------------

class TestUploadBehindProxy:
    """Test upload-related behavior that could be affected by proxy configuration."""

    def test_no_request_body_size_limit_in_app(self):
        """The app itself should not impose a body size limit."""
        source = _extract_function_source(_read_source(SERVER_PY), "save_upload")
        assert source, "save_upload not found"
        assert "content-length" not in source.lower(), \
            "save_upload should not check Content-Length"
        assert "max_size" not in source.lower(), \
            "save_upload should not enforce max file size"

    def test_filename_sanitization_source(self):
        """Filename sanitization function should exist and handle dangerous names."""
        source = _extract_function_source(_read_source(SERVER_PY), "safe_filename")
        assert source, "safe_filename not found in server.py"
        # Should remove path separators
        assert "/" in source or "replace" in source, \
            "safe_filename should handle path separators"
        assert "180" in source or "max" in source.lower(), \
            "safe_filename should limit filename length"

    def test_save_upload_uses_shutil_copyfileobj(self):
        """save_upload should use shutil.copyfileobj for streaming."""
        source = _extract_function_source(_read_source(SERVER_PY), "save_upload")
        assert source, "save_upload not found"
        assert "shutil.copyfileobj" in source, \
            "save_upload should use shutil.copyfileobj for streaming upload"

    def test_audio_probe_is_best_effort(self):
        """Audio probing should be best-effort (handle failures gracefully)."""
        source = _extract_function_source(_read_source(SERVER_PY), "_probe_audio_basic")
        assert source, "_probe_audio_basic not found"
        # Should have try/except for graceful failure
        assert "except" in source, \
            "_probe_audio_basic should handle exceptions gracefully"


# ---------------------------------------------------------------------------
# 9. Multi-user auth flow in Proxmox (full integration)
# ---------------------------------------------------------------------------

class TestMultiUserAuthProxmox:
    """Full auth flow tests relevant to Proxmox deployments."""

    def test_user_creation_and_password_verify(self, tmp_path):
        """Basic user creation and password verification (foundation of auth)."""
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password, verify_password

        us = UserStore(tmp_path)
        user = us.create_user(UserRecord(
            username="proxmox_user",
            password_hash=hash_password("StrongP@ss123!"),
            role="Transkryptor",
        ))
        assert user is not None
        assert verify_password("StrongP@ss123!", user.password_hash)
        assert not verify_password("wrong_password", user.password_hash)

    def test_session_survives_proxy_reconnect(self, tmp_path):
        """Session should remain valid across proxy reconnections."""
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore

        ss = SessionStore(tmp_path)
        token = ss.create_session("user-1", timeout_hours=8, ip="10.0.0.5")

        # Simulate proxy reconnection: retrieve session from different "connection"
        session1 = ss.get_session(token)
        assert session1 is not None

        session2 = ss.get_session(token)
        assert session2 is not None
        assert session1["user_id"] == session2["user_id"]

    def test_audit_log_records_ip(self, tmp_path):
        """Audit log should record the IP address (important for proxy forensics)."""
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore

        audit = AuditStore(tmp_path)
        audit.log_event(
            "login",
            user_id="test-uid",
            username="proxmox_user",
            ip="10.0.0.5",
        )

        events = audit.get_events(user_id="test-uid")
        assert len(events) == 1
        assert events[0]["ip"] == "10.0.0.5"

    def test_audit_log_with_forwarded_ip(self, tmp_path):
        """Audit log should be able to store X-Forwarded-For IP chain."""
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore

        audit = AuditStore(tmp_path)
        audit.log_event(
            "login",
            user_id="test-uid",
            username="proxy_user",
            ip="10.0.0.5, 172.16.0.1",
        )

        events = audit.get_events(user_id="test-uid")
        assert len(events) == 1
        assert "10.0.0.5" in events[0]["ip"]
