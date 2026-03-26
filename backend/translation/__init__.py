"""
AISTATEweb Translation Module

Provides hybrid translation capabilities using:
- NLLB-200 for fast translation
- Ollama/LLaMA for context-aware translation
"""

from .hybrid_translator import HybridTranslator
from .document_handlers import get_handler
from .language_detector import detect_language
from .glossary_manager import GlossaryManager
from .summarizer import generate_summary

__all__ = [
    "HybridTranslator",
    "get_handler",
    "detect_language",
    "GlossaryManager",
    "generate_summary",
]
