"""Curated LLM catalog for AISTATEweb (Ollama).

The Settings UI consumes:
- MODELS_GROUPS: which model ids show up in each dropdown
- DEFAULT_MODELS: default selection when global settings don't exist
- MODELS_INFO: rich metadata shown in the inline info panels

Notes:
- Figures are approximate (quantization/context/backend dependent).
- A model may appear in multiple groups, but MODELS_INFO keys must be unique.
"""

from __future__ import annotations

from typing import Any, Dict, List


# Models shown in each selector.
MODELS_GROUPS: Dict[str, List[str]] = {
    # === QUICK ANALYSIS (4) ===
    "quick": [
        "mistral:7b-instruct",
        "gemma2:9b",
        "llama3.2:3b",
        "qwen2.5:7b",
    ],
    # === DEEP ANALYSIS (6) ===
    "deep": [
        "qwen2.5:14b",
        "qwen2.5:32b",
        "gemma2:27b",
        "llama3.3:70b",
        "qwen2.5:72b",
        "llama3.1:405b",
        "mistral-nemo:12b",
        "aya:8b",
        "aya:35b",
        "command-r:35b",
        "deepseek-r1:70b",
    ],
    # === VISION / OCR (4) ===
    "vision": [
        "llama3.2-vision:11b",
        "granite3.2-vision",
        "llava:13b",
        "minicpm-v",
    ],
    # === TRANSLATION (3) ===
    "translation": [
        "qwen2.5:14b",
        "aya:8b",
        "aya:35b",
    ],
    # === FINANCIAL / STRUCTURED (3) ===
    "financial": [
        "qwen2.5:32b",
        "llama3.3:70b",
        "mistral-nemo:12b",
    ],
    # === SPECIALIZED (2) ===
    "specialized": [
        "command-r:35b",
        "deepseek-r1:70b",
    ],
}


# Default selections (used when global settings file does not exist).
DEFAULT_MODELS: Dict[str, str] = {
    "quick": "mistral:7b-instruct",
    "deep": "qwen2.5:32b",
    "vision": "llama3.2-vision:11b",
    "translation": "qwen2.5:14b",
    "financial": "qwen2.5:32b",
    "specialized": "command-r:35b",
}


# Model metadata indexed by Ollama model id.
# IMPORTANT: Keys must be unique (a model can appear in multiple groups).
MODELS_INFO: Dict[str, Dict[str, Any]] = {
    # ==========================================================
    # QUICK ANALYSIS (4)
    # ==========================================================
    "mistral:7b-instruct": {
        "display_name": "Mistral 7B Instruct",
        "category": "quick",
        "hardware": {
            "vram": "5GB",
            "min_gpu": "RTX 2060 6GB",
            "optimal_gpu": "RTX 3070 8GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 60,
            "analysis_time": {
                "quick": "3-5 sekund",
                "summary": "5-8 sekund",
            },
            "quality_stars": 4,
            "polish_quality_stars": 4,
        },
        "use_cases": [
            "Szybkie podsumowania transkrypcji spotkań",
            "Ekstrakcja kluczowych tematów (bullet points)",
            "Quick insights z nagrań audio",
            "Automatyczna analiza w tle (3-5s)",
            "Preview dokumentów przed deep analysis",
        ],
        "recommendation": "Doskonały wybór dla szybkiej analizy. Najlepszy balans szybkość/jakość dla polskiego. Idealny jako pierwszy krok w pipeline.",
        "defaults": {"quick": True},
        "capabilities": ["quick_summary", "bullet_points", "auto_analysis", "polish"],
    },
    "gemma2:9b": {
        "display_name": "Gemma 2 9B",
        "category": "quick",
        "hardware": {
            "vram": "7GB",
            "min_gpu": "RTX 3060 12GB",
            "optimal_gpu": "RTX 4070 12GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 45,
            "analysis_time": {
                "quick": "5-7 sekund",
                "summary": "8-12 sekund",
            },
            "quality_stars": 4,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Balans jakość/szybkość dla języka polskiego",
            "Formalne podsumowania biznesowe",
            "Mniej halucynacji niż inne modele (Google safety)",
            "Analiza spotkań z naciskiem na precyzję",
            "Dokumenty techniczne (precyzyjne streszczenia)",
        ],
        "recommendation": "Wybierz gdy jakość dla polskiego jest priorytetem. Nieco wolniejszy od Mistral, ale bardziej precyzyjny i mniej halucynuje.",
        "defaults": {"quick": False},
        "capabilities": ["precision", "polish_expert", "business_formal", "low_hallucination"],
    },
    "llama3.2:3b": {
        "display_name": "Llama 3.2 3B",
        "category": "quick",
        "hardware": {
            "vram": "3GB",
            "min_gpu": "GTX 1060 6GB",
            "optimal_gpu": "RTX 3060 12GB",
            "ram": "8GB",
        },
        "performance": {
            "speed_tokens_sec": 100,
            "analysis_time": {
                "quick": "2-3 sekundy",
                "instant": "1-2 sekundy",
            },
            "quality_stars": 3,
            "polish_quality_stars": 3,
        },
        "use_cases": [
            "Ultra szybka analiza (instant preview)",
            "Real-time analysis podczas nagrywania",
            "Mobile/edge computing (słabszy sprzęt)",
            "Batch processing setek plików (szybkość priorytet)",
            "Preview przed pełną analizą",
        ],
        "recommendation": "Najszybszy model. Użyj gdy potrzebujesz natychmiastowych wyników i masz słabsze GPU. Jakość niższa ale wystarczająca dla quick insights.",
        "defaults": {"quick": False},
        "capabilities": ["ultra_fast", "instant", "mobile", "edge", "batch"],
    },
    "qwen2.5:7b": {
        "display_name": "Qwen 2.5 7B",
        "category": "quick",
        "hardware": {
            "vram": "5GB",
            "min_gpu": "RTX 2060 6GB",
            "optimal_gpu": "RTX 3070 8GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 50,
            "analysis_time": {
                "quick": "4-6 sekund",
                "multilingual": "6-10 sekund",
            },
            "quality_stars": 4,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Quick multilingual (30+ języków w tym cyrylica)",
            "Szybka analiza dokumentów rosyjskich/ukraińskich",
            "Preview dokumentów przed tłumaczeniem",
            "Multi-language meetings (PL/EN/RU mix)",
            "Quick classification dokumentów cyrylica",
        ],
        "recommendation": "Świetny dla quick multilingual. Obsługuje cyrylicę bez problemu. Idealny pierwszy krok przed deep translation.",
        "defaults": {"quick": False},
        "capabilities": ["multilingual_30+", "cyrillic", "quick_classification", "polish_expert"],
    },

    # ==========================================================
    # DEEP ANALYSIS (4 + existing 405B)
    # ==========================================================
    "qwen2.5:32b": {
        "display_name": "Qwen 2.5 32B",
        "category": "deep",
        "hardware": {
            "vram": "19GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "32GB",
        },
        "performance": {
            "speed_tokens_sec": 18,
            "analysis_time": {
                "deep": "70-100 sekund",
                "protocol": "90-120 sekund",
                "financial": "60-90 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Szczegółowe protokoły spotkań (formalne, biznesowe)",
            "Deep analysis transkrypcji (co kto powiedział, decyzje)",
            "Analiza finansowa (balance check, scoring)",
            "Długie dokumenty (context 32K = ~24K słów)",
            "Multilingual deep analysis (30+ języków)",
            "Structured data extraction (complex JSON schemas)",
        ],
        "recommendation": "Optymalny wybór dla single GPU (RTX 4090). Doskonały balans jakość/wymagania. Najlepszy dla języka polskiego. TOP model dla deep analysis.",
        "defaults": {"deep": True, "financial": True},
        "capabilities": [
            "deep_reasoning",
            "long_context_32k",
            "polish_expert",
            "multilingual",
            "financial_analysis",
            "structured_json",
        ],
    },
    "llama3.3:70b": {
        "display_name": "Llama 3.3 70B",
        "category": "deep",
        "hardware": {
            "vram": "40GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 12,
            "analysis_time": {
                "deep": "120-180 sekund",
                "complex": "150-200 sekund",
                "structured": "100-150 sekund",
                "financial": "100-150 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Top tier reasoning (najbardziej inteligentny)",
            "Kompleksowe analizy wieloetapowe",
            "Structured output (perfect JSON schema adherence)",
            "Bardzo długie konteksty (128K = ~96K słów)",
            "Complex financial reasoning (anomaly detection)",
            "Legal document analysis (umowy - ryzykowne klauzule)",
        ],
        "recommendation": "Najlepszy ogólny model dostępny lokalnie. Wymaga workstation z dual-GPU. Używaj gdy jakość jest krytyczna i masz sprzęt.",
        "requires_multi_gpu": True,
        "warning": "Wymaga dużej ilości VRAM (często multi-GPU) lub bardzo agresywnej kwantyzacji. Jeśli masz pojedyncze GPU 24GB, rozważ Qwen 32B.",
        "capabilities": [
            "top_reasoning",
            "long_context_128k",
            "perfect_json",
            "anomaly_detection",
            "legal_expert",
        ],
    },
    "gemma2:27b": {
        "display_name": "Gemma 2 27B",
        "category": "deep",
        "hardware": {
            "vram": "16GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "32GB",
        },
        "performance": {
            "speed_tokens_sec": 20,
            "analysis_time": {
                "deep": "60-90 sekund",
                "fast_deep": "50-80 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Szybsza alternatywa dla Qwen 32B",
            "Mniej halucynacji (Google safety features)",
            "Formalne dokumenty medyczne/prawne/finansowe",
            "Precyzyjne analizy gdzie halucynacje = problem",
            "Gdy priorytet to precyzja + szybkość",
        ],
        "recommendation": "Wybierz gdy potrzebujesz szybszego modelu niż Qwen 32B, ale z topową jakością. Świetny dla dokumentów gdzie błędy są niedopuszczalne.",
        "capabilities": ["fast_deep", "low_hallucination", "medical", "legal", "financial"],
    },
    "qwen2.5:72b": {
        "display_name": "Qwen 2.5 72B",
        "category": "deep",
        "hardware": {
            "vram": "41GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 10,
            "analysis_time": {
                "deep": "140-200 sekund",
                "multilingual": "150-220 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Workstation - topowy dla języka polskiego",
            "Konkurent dla Llama 70B z lepszym PL",
            "Multilingual excellence (30+ języków)",
            "Research-grade analizy",
            "Bardzo długie konteksty multilingual (128K)",
            "Complex reasoning w języku polskim",
        ],
        "recommendation": "Najlepszy wybór dla języka polskiego na workstation. Nieco wolniejszy od Llama, ale lepszy dla polskiego i multilingual.",
        "requires_multi_gpu": True,
        "warning": "Wymaga workstation (często multi-GPU) lub bardzo agresywnej kwantyzacji. Dla 1x GPU 24GB wybierz Qwen 32B.",
        "capabilities": ["polish_best", "multilingual_30+", "long_context_128k", "research_grade"],
    },

    # ==========================================================
    # VISION / OCR (4)
    # ==========================================================
    "llama3.2-vision:11b": {
        "display_name": "Llama 3.2 Vision 11B",
        "category": "vision",
        "hardware": {
            "vram": "11GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 15,
            "analysis_time": {
                "vision": "OCR 5-10s • Dokument 10-20s",
                "ocr": "5-10 sekund",
                "document": "10-20 sekund",
                "invoice": "15-25 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "OCR faktur VAT i rachunków (polski + angielski + cyrylica)",
            "Ekstrakcja danych z wyciągów bankowych",
            "Analiza dokumentów BIK (zdolność kredytowa)",
            "OCR oświadczeń majątkowych",
            "Dokumenty techniczne z diagramami",
            "Rozpoznawanie tabel i wykresów",
            "Wysokorozdzielcze obrazy (do 1.8M px = 1344x1344)",
        ],
        "recommendation": "Najlepszy model vision dla dokumentów finansowych. Doskonały OCR dla polskiego tekstu i cyrylicy. Obsługuje złożone layouty z tabelami. PIERWSZY WYBÓR dla OCR.",
        "defaults": {"vision": True},
        "supports_images": True,
        "max_resolution": "1344x1344",
        "capabilities": [
            "ocr_expert",
            "tables",
            "charts",
            "multilingual",
            "cyrillic",
            "structured_data",
            "financial_docs",
        ],
    },
    "granite3.2-vision": {
        "display_name": "Granite 3.2 Vision",
        "category": "vision",
        "hardware": {
            "vram": "8GB",
            "min_gpu": "RTX 3070 8GB",
            "optimal_gpu": "RTX 4070 12GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 18,
            "analysis_time": {
                "vision": "OCR 4-8s • Tabele 8-15s",
                "ocr": "4-8 sekund",
                "tables": "8-15 sekund",
                "complex_tables": "12-20 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 4,
        },
        "use_cases": [
            "NAJLEPSZY dla tabel i wykresów (specjalista)",
            "Billingi telefoniczne (złożone tabele)",
            "Zestawienia finansowe (wielokolumnowe)",
            "Raporty z wykresami słupkowymi/kołowymi",
            "Infografiki, diagramy, schematy techniczne",
            "Faktury z >10 pozycjami w tabeli",
            "Wyciągi bankowe (dziesiątki transakcji)",
        ],
        "recommendation": "Specjalista od tabel i strukturalnych dokumentów. Wybierz gdy dokument ma >10 pozycji w tabeli lub złożone wykresy. Lepszy od Llama dla tabel.",
        "defaults": {"vision": False},
        "supports_images": True,
        "capabilities": ["tables_expert", "charts_expert", "infographics", "diagrams", "multi_column"],
    },
    "llava:13b": {
        "display_name": "LLaVA 13B",
        "category": "vision",
        "hardware": {
            "vram": "13GB",
            "min_gpu": "RTX 3090 24GB",
            "optimal_gpu": "RTX 4090 24GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 20,
            "analysis_time": {
                "vision": "OCR 3-6s • Dokument 8-12s",
                "ocr": "3-6 sekund",
                "document": "8-12 sekund",
            },
            "quality_stars": 3,
            "polish_quality_stars": 2,
        },
        "use_cases": [
            "Szybkie proste skanowanie",
            "Preview dokumentów (quick check)",
            "Nieformalne notatki (bez krytycznych danych)",
            "Backup OCR gdy inne modele niedostępne",
        ],
        "recommendation": "Szybki ale może generować błędy OCR. Używaj TYLKO dla prostych dokumentów bez krytycznych danych. NIE dla faktur/umów/bilingów.",
        "defaults": {"vision": False},
        "supports_images": True,
        "warning": "Może generować błędy OCR - nie używać dla faktur/umów/dokumentów finansowych",
    },
    "minicpm-v": {
        "display_name": "MiniCPM-V",
        "category": "vision",
        "hardware": {
            "vram": "4GB",
            "min_gpu": "GTX 1060 6GB",
            "optimal_gpu": "RTX 3060 12GB",
            "ram": "8GB",
        },
        "performance": {
            "speed_tokens_sec": 30,
            "analysis_time": {
                "vision": "OCR 2-4s • Dokument 5-8s",
                "ocr": "2-4 sekundy",
                "document": "5-8 sekund",
            },
            "quality_stars": 3,
            "polish_quality_stars": 3,
        },
        "use_cases": [
            "Mobilne skanowanie (telefon, tablet)",
            "Edge computing (Raspberry Pi, NUC)",
            "Środowiska z ograniczonymi zasobami",
            "Szybki preview dokumentów",
            "Batch processing gdy sprzęt słaby",
        ],
        "recommendation": "Najlżejszy model vision. Idealny dla mobile/edge gdy sprzęt ograniczony. Jakość niższa ale wystarczająca dla preview.",
        "defaults": {"vision": False},
        "supports_images": True,
        "capabilities": ["edge", "mobile", "low_resource", "ultra_light"],
    },

    # ==========================================================
    # TRANSLATION (qwen + aya)
    # ==========================================================
    "qwen2.5:14b": {
        "display_name": "Qwen 2.5 14B (30+ languages)",
        "category": "translation",
        "hardware": {
            "vram": "9GB",
            "min_gpu": "RTX 3060 12GB",
            "optimal_gpu": "RTX 4060 Ti 16GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 30,
            "analysis_time": {
                "deep": "30-60 sekund",
                "translation": "7-12 sekund (1000 słów)",
                "cyrillic": "10-15 sekund",
            },
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "languages": [
            "English",
            "German",
            "French",
            "Italian",
            "Portuguese",
            "Hindi",
            "Spanish",
            "Thai",
            "Polish",
            "Chinese",
            "Croatian",
            "Czech",
            "Danish",
            "Dutch",
            "Estonian",
            "Finnish",
            "Greek",
            "Hungarian",
            "Indonesian",
            "Japanese",
            "Khmer",
            "Korean",
            "Latvian",
            "Lithuanian",
            "Norwegian",
            "Russian",
            "Swedish",
            "Ukrainian",
            "+more",
        ],
        "use_cases": [
            "NAJLEPSZY dla tłumaczeń polskich (PL↔EN)",
            "Tłumaczenie dokumentów rosyjskich/ukraińskich (RU/UK→PL)",
            "Długie dokumenty (context 32K = ~24K słów)",
            "Tłumaczenie techniczne (zachowuje terminologię)",
            "Multi-step translations (RU→EN→PL)",
            "Obsługa cyrylicy (rozpoznawanie + tłumaczenie)",
        ],
        "recommendation": "TOP wybór dla języka polskiego i cyrylicy. Długi context (32K) idealny dla dokumentów. Najlepszy balans jakość/wymagania dla desktop.",
        "defaults": {"translation": True},
        "capabilities": ["30+_languages", "long_context_32k", "polish_expert", "cyrillic_expert", "technical"],
    },
    "aya:35b": {
        "display_name": "Aya 35B (23 languages)",
        "category": "translation",
        "hardware": {
            "vram": "35GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 8,
            "analysis_time": {"translation": "20-40 sekund (1000 słów)", "premium": "30-50 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "languages": [
            "Arabic",
            "Chinese (simplified & traditional)",
            "Czech",
            "Dutch",
            "English",
            "French",
            "German",
            "Greek",
            "Hebrew",
            "Hindi",
            "Indonesian",
            "Italian",
            "Japanese",
            "Korean",
            "Persian",
            "Polish",
            "Portuguese",
            "Romanian",
            "Russian",
            "Spanish",
            "Turkish",
            "Ukrainian",
            "Vietnamese",
        ],
        "use_cases": [
            "Premium translation (jakość GPT-4 level)",
            "Tłumaczenie umów i kontraktów (precyzja krytyczna)",
            "Lokalizacja dokumentacji technicznej",
            "Multi-lingual chatboty (23 języki)",
            "Tłumaczenie treści wrażliwych (mniej cenzury)",
            "Dokumenty prawne cyrylica→polski",
        ],
        "recommendation": "Król tłumaczeń. Jakość na poziomie topowych modeli chmurowych. Wymaga workstation 2x GPU.",
        "requires_multi_gpu": True,
        "defaults": {"translation": False},
        "capabilities": ["23_languages", "premium_quality", "legal"],
    },
    "aya:8b": {
        "display_name": "Aya 8B (23 languages)",
        "category": "translation",
        "hardware": {
            "vram": "8GB",
            "min_gpu": "RTX 3070 8GB",
            "optimal_gpu": "RTX 4070 12GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 25,
            "analysis_time": {"translation": "8-15 sekund (1000 słów)"},
            "quality_stars": 4,
            "polish_quality_stars": 4,
        },
        "languages": [
            "Arabic",
            "Chinese",
            "Czech",
            "Dutch",
            "English",
            "French",
            "German",
            "Greek",
            "Hebrew",
            "Hindi",
            "Indonesian",
            "Italian",
            "Japanese",
            "Korean",
            "Persian",
            "Polish",
            "Portuguese",
            "Romanian",
            "Russian",
            "Spanish",
            "Turkish",
            "Ukrainian",
            "Vietnamese",
        ],
        "use_cases": [
            "Tłumaczenie na desktop (single GPU)",
            "Batch processing dokumentów multilingual",
            "Real-time translation w chatbotach",
            "Balans jakość/szybkość dla 23 języków",
        ],
        "recommendation": "Dobry balans jakość/wymagania. Najlepszy wybór dla desktop z single GPU. Te same 23 języki co Aya 35B.",
        "defaults": {"translation": False},
        "capabilities": ["23_languages", "fast", "single_gpu", "balanced"],
    },

    # ==========================================================
    # FINANCIAL / STRUCTURED (mistral-nemo)
    # ==========================================================
    "mistral-nemo:12b": {
        "display_name": "Mistral Nemo 12B",
        "category": "financial",
        "hardware": {
            "vram": "9GB",
            "min_gpu": "RTX 3060 12GB",
            "optimal_gpu": "RTX 4070 12GB",
            "ram": "16GB",
        },
        "performance": {
            "speed_tokens_sec": 35,
            "analysis_time": {
                "financial": "15-30 sekund",
                "extraction": "15-25 sekund",
                "scoring": "20-30 sekund",
            },
            "quality_stars": 4,
            "polish_quality_stars": 4,
        },
        "use_cases": [
            "Fast structured extraction (JSON)",
            "Quick scoring (credit scoring fast)",
            "Batch processing transakcji (setki jednocześnie)",
            "Real-time categorization",
            "Długie konteksty (128K = ~96K słów)",
        ],
        "recommendation": "Najszybszy structured extraction. Context 128K = można załadować cały rok transakcji. Idealny do batch processing.",
        "defaults": {"financial": False},
        "capabilities": ["fast_extraction", "long_context_128k", "batch", "scoring"],
    },

    # ==========================================================
    # SPECIALIZED (2)
    # ==========================================================
    "command-r:35b": {
        "display_name": "Command R 35B (Legal Expert)",
        "category": "specialized",
        "hardware": {
            "vram": "35GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 10,
            "analysis_time": {"specialized": "120-200 sekund", "legal": "120-180 sekund", "contract": "150-200 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Legal document analysis (umowy, kontrakty)",
            "Wykrywanie ryzykownych klauzul w umowach",
            "Interpretacja pism urzędowych",
            "Compliance checking",
            "Analiza warunków płatności, kar umownych",
            "Długie dokumenty prawne (RAG-optimized)",
        ],
        "recommendation": "Specjalista od dokumentów prawnych. RAG-optimized = świetny dla długich umów. Wykrywa ukryte ryzyka w klauzulach.",
        "defaults": {"specialized": True},
        "requires_multi_gpu": True,
        "capabilities": ["legal_expert", "contract_analysis", "risk_detection", "compliance", "rag_optimized"],
    },
    "deepseek-r1:70b": {
        "display_name": "DeepSeek R1 70B (Advanced Reasoning)",
        "category": "specialized",
        "hardware": {
            "vram": "40GB",
            "min_gpu": "2x RTX 3090 (48GB total)",
            "optimal_gpu": "2x RTX 4090 (48GB total)",
            "ram": "64GB",
        },
        "performance": {
            "speed_tokens_sec": 8,
            "analysis_time": {"specialized": "180-240 sekund", "reasoning": "180-240 sekund", "complex": "200-280 sekund"},
            "quality_stars": 5,
            "polish_quality_stars": 5,
        },
        "use_cases": [
            "Advanced reasoning (wielostopniowe wnioskowanie)",
            "Complex multi-step analysis",
            "Anomaly detection (subtle patterns)",
            "Research-grade analysis",
            "Multi-document synthesis",
            "Hypothesis generation and testing",
        ],
        "recommendation": "Top tier reasoning model. Używaj gdy zadanie wymaga głębokiego myślenia wieloetapowego. Wolny ale bardzo inteligentny.",
        "defaults": {"specialized": False},
        "requires_multi_gpu": True,
        "capabilities": ["advanced_reasoning", "multi_step", "research", "hypothesis", "synthesis"],
    },

    # ==========================================================
    # DEEP (existing ultra-heavy)
    # ==========================================================
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
            "analysis_time": {"deep": "300-400 sekund"},
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
