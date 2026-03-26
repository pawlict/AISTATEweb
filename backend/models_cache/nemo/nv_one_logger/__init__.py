"""Local stub for NVIDIA nv_one_logger.

NeMo sometimes imports nv_one_logger for training telemetry/callback wiring.
AISTATEweb uses NeMo for inference (ASR/diarization), so nv_one_logger is optional.

On some version combinations (notably newer Python / PyTorch Lightning), the upstream
nv_one_logger package can fail at import time due to strict signature checks.
This stub prevents hard crashes and is safe for inference.
"""
