"""Stub module expected by NeMo.

NeMo imports:
    from nv_one_logger.training_telemetry.integration.pytorch_lightning import TimeEventCallback

For inference we provide a no-op callback.
"""

class TimeEventCallback:  # pragma: no cover
    def __init__(self, *args, **kwargs):
        pass
