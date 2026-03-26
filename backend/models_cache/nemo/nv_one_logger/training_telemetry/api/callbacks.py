"""Stub callbacks used by NeMo's OneLogger integration.

NeMo may import:
    from nv_one_logger.training_telemetry.api.callbacks import on_app_start

For inference-only usage in AISTATEweb we provide no-op callbacks.
"""

def on_app_start(*args, **kwargs):  # pragma: no cover
    return None

def on_app_end(*args, **kwargs):  # pragma: no cover
    return None

# Some stacks may look for additional lifecycle hooks; keep them as no-ops.

def on_train_start(*args, **kwargs):  # pragma: no cover
    return None

def on_train_end(*args, **kwargs):  # pragma: no cover
    return None
