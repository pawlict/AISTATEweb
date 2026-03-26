"""
Feature gating decorator for API endpoints.

Usage:
    from backend.licensing.feature_gate import require_feature

    @app.post("/api/tts/kokoro/generate")
    @require_feature("tts_kokoro")
    async def generate_kokoro(...):
        ...

When LICENSING_ENABLED is False, the decorator is a no-op.
When LICENSING_ENABLED is True, it checks the cached license for the feature.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from fastapi.responses import JSONResponse

from backend.licensing import LICENSING_ENABLED


def require_feature(feature: str) -> Callable:
    """Decorator that gates an endpoint behind a licensed feature.

    If licensing is disabled or the current license includes the feature,
    the endpoint runs normally.  Otherwise returns 403.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not LICENSING_ENABLED:
                return await func(*args, **kwargs)

            from backend.licensing.validator import get_cached_license

            lic = get_cached_license()

            if lic.is_expired:
                return JSONResponse(
                    {
                        "status": "error",
                        "code": "LICENSE_EXPIRED",
                        "message": "Licencja wygas\u0142a. Skontaktuj si\u0119 z dostawc\u0105 w celu odnowienia.",
                        "plan": lic.plan,
                    },
                    status_code=403,
                )

            if not lic.has_feature(feature):
                return JSONResponse(
                    {
                        "status": "error",
                        "code": "FEATURE_LOCKED",
                        "message": f"Funkcja wymaga planu Pro lub wy\u017cszego.",
                        "feature": feature,
                        "plan": lic.plan,
                    },
                    status_code=403,
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
