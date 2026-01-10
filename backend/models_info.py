"""Curated LLM catalog for AISTATEweb (Ollama).

Used by the Settings UI:
- recommended models grouped as "quick" and "deep"
- model info modal (hardware/performance/use-cases)

Figures are approximate and depend on quantization, context length and backend.
"""

from __future__ import annotations

from typing import Any, Dict, List


# Models shown in each selector.
MODELS_GROUPS: Dict[str, List[str]] = {
    "quick": [
        "mistral:7b-instruct",
        "gemma2:9b",
        "llama3.2:3b",
        "qwen2.5:14b",
    ],
    "deep": [
        "qwen2.5:14b",
        "qwen2.5:32b",
        "gemma2:27b",
        "llama3.3:70b",
        "qwen2.5:72b",
        "llama3.1:405b",
    ],
}


# Default selections (used when global settings file does not exist).
DEFAULT_MODELS: Dict[str, str] = {
    "quick": "mistral:7b-instruct",
    "deep": "qwen2.5:32b",
}


# Model metadata indexed by Ollama model id.
# IMPORTANT: Keys must be unique (a model can appear in multiple groups).
MODELS_INFO: Dict[str, Dict[str, Any]] = {
    # ============= QUICK ANALYSIS =============
    "mistral:7b-instruct": {
        "display_name": "Mistral 7B Instruct",
        "hardware": {
            "vram": "5GB",
            "min_gpu": "RTX 2060 6GB",
            "optimal_gpu": "RTX 3070 8GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 60,
            "analysis_time": {"quick": "3-5 sekund", "deep": None},
            "quality_stars": 4,
            "polish_quality_stars": 4,
        },
        "use_cases": [
            "Szybkie podsumowania transkrypcji",
            "Ekstrakcja kluczowych informacji",
            "Automatyczna analiza w tle",
            "Najlepszy balans szybkość/jakość",
        ],
        "recommendation": "Doskonały wybór dla szybkiej analizy. Świetnie radzi sobie z polskim językiem i daje wyniki w kilka sekund.",
        "defaults": {"quick": True},
    },
    "gemma2:9b": {
        "display_name": "Gemma 2 9B",
        "hardware": {
            "vram": "7GB",
            "min_gpu": "RTX 3060 12GB",
            "optimal_gpu": "RTX 4070 12GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 45,
            "analysis_time": {"quick": "5-7 sekund", "deep": None},
            "quality_stars": 4,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Balans szybkość/jakość dla polskiego",
            "Analiza z naciskiem na poprawność",
            "Mniej halucynacji niż część modeli",
            "Dobry dla treści formalnych",
        ],
        "recommendation": "Wybierz jeśli jakość dla polskiego jest priorytetem. Nieco wolniejszy od Mistral, ale bardziej precyzyjny.",
    },
    "llama3.2:3b": {
        "display_name": "Llama 3.2 3B",
        "hardware": {
            "vram": "3GB",
            "min_gpu": "GTX 1060 6GB",
            "optimal_gpu": "RTX 3060 12GB",
            "ram": "8GB",
        },
        "performance": {
            "speed_tokens_sec": 100,
            "analysis_time": {"quick": "2-3 sekundy", "deep": None},
            "quality_stars": 3,
            "polish_quality_stars": 3,
        },
        "use_cases": [
            "Ultra szybka analiza",
            "Instant preview podczas pracy",
            "Słabszy sprzęt / użycie CPU",
            "Gdy liczy się tylko szybkość",
        ],
        "recommendation": "Najszybszy model, ale niższa jakość. Użyj gdy potrzebujesz natychmiastowych wyników i masz słabsze GPU.",
    },
    "qwen2.5:14b": {
        "display_name": "Qwen 2.5 14B",
        "hardware": {
            "vram": "9GB",
            "min_gpu": "RTX 3060 12GB",
            "optimal_gpu": "RTX 4060 Ti 16GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 30,
            "analysis_time": {"quick": "7-10 sekund", "deep": "30-60 sekund"},
            "quality_stars": 4,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Najlepszy dla języka polskiego w tej klasie",
            "Świetny multilingual support",
            "Gdy jakość ważniejsza niż prędkość",
            "Entry point dla głębokiej analizy na jednym GPU",
        ],
        "recommendation": "Top wybór dla polskiego w kategorii szybkiej analizy. Może też pełnić rolę entry-level modelu do głębokich raportów.",
    },

    # ============= DEEP ANALYSIS =============
    "qwen2.5:32b": {
        "display_name": "Qwen 2.5 32B",
        "hardware": {
            "vram": "19GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "32GB",
        },
        "performance": {
            "speed_tokens_sec": 18,
            "analysis_time": {"quick": None, "deep": "70-100 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Single GPU premium - najlepszy wybór",
            "Topowa jakość dla języka polskiego",
            "Skomplikowane raporty z wieloma źródłami",
            "Długie transkrypcje (większy kontekst)",
        ],
        "recommendation": "Optymalny wybór dla RTX 4090. Doskonały balans jakość/wymagania dla profesjonalistów.",
        "defaults": {"deep": True},
    },
    "gemma2:27b": {
        "display_name": "Gemma 2 27B",
        "hardware": {
            "vram": "16GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "32GB",
        },
        "performance": {
            "speed_tokens_sec": 20,
            "analysis_time": {"quick": None, "deep": "60-90 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Szybsza alternatywa dla Qwen 32B",
            "Mniej halucynacji (profil bezpieczeństwa)",
            "Formalne dokumenty medyczne/prawne",
            "Gdy priorytet to precyzja",
        ],
        "recommendation": "Wybierz gdy potrzebujesz szybszego modelu niż Qwen 32B, ale nadal z topową jakością.",
    },
    "llama3.3:70b": {
        "display_name": "Llama 3.3 70B",
        "hardware": {
            "vram": "40GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 12,
            "analysis_time": {"quick": None, "deep": "120-180 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Workstation - flagowy model",
            "Top tier reasoning i analiza",
            "Bardzo długie konteksty (duży context window)",
            "Gdy jakość > szybkość",
        ],
        "recommendation": "Najlepszy ogólny model dostępny lokalnie, ale wymaga workstation (często dual-GPU).",
        "requires_multi_gpu": True,
        "warning": "Wymaga dużej ilości VRAM (często multi-GPU) lub bardzo agresywnej kwantyzacji. Jeśli masz pojedyncze GPU 24GB, rozważ Qwen 32B.",
    },
    "qwen2.5:72b": {
        "display_name": "Qwen 2.5 72B",
        "hardware": {
            "vram": "41GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 10,
            "analysis_time": {"quick": None, "deep": "140-200 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Workstation - topowy dla polskiego",
            "Konkurent dla modeli 70B z lepszym PL",
            "Multilingual excellence",
            "Research-grade analizy",
        ],
        "recommendation": "Najlepszy wybór dla języka polskiego na workstation. Nieco wolniejszy od 70B, ale bardzo mocny dla PL.",
        "requires_multi_gpu": True,
        "warning": "Wymaga workstation (często multi-GPU) lub bardzo agresywnej kwantyzacji. Dla 1x GPU 24GB wybierz Qwen 32B.",
    },
    "llama3.1:405b": {
        "display_name": "Llama 3.1 405B",
        "hardware": {
            "vram": "231GB",
            "min_gpu": "8x A100 40GB (320GB total)",
            "optimal_gpu": "4x H100 80GB (320GB total)",
            "ram": "256GB",
        },
        "performance": {
            "speed_tokens_sec": 5,
            "analysis_time": {"quick": None, "deep": "300-400 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Enterprise only - absolutny top",
            "Research-grade reasoning",
            "Gdy koszty nie mają znaczenia",
            "Overkill dla większości zadań",
        ],
        "recommendation": "Najlepszy model lokalnie, ale wymaga sprzętu klasy enterprise. Niepolecany dla typowego użycia.",
        "requires_multi_gpu": True,
        "warning": "Wymaga sprzętu server-grade (setki GB VRAM). Rozważ cloud computing lub model 32B/27B na pojedynczym GPU.",
    },
}
