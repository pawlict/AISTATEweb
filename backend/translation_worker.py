"""Translation worker (NLLB)

This worker is used by the /translation page.

Input is passed as a JSON file.

It prints progress markers to STDERR in the format:
  PROGRESS: <0-100>
and prints a single JSON dict to STDOUT when finished.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]

# Ensure repo root is on sys.path so `import backend...` works when running as a script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def eprint(msg: str) -> None:
    sys.stderr.write(str(msg).rstrip("\n") + "\n")
    sys.stderr.flush()


def progress(pct: int) -> None:
    pct = max(0, min(100, int(pct)))
    eprint(f"PROGRESS: {pct}")


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(v)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to JSON payload")
    args = ap.parse_args()

    payload_path = Path(args.input).expanduser().resolve()
    if not payload_path.exists():
        raise SystemExit(f"Missing input file: {payload_path}")

    payload: Dict[str, Any] = json.loads(payload_path.read_text(encoding="utf-8"))

    text = str(payload.get("text") or "").strip()
    if not text:
        raise SystemExit("Empty text")

    mode = str(payload.get("mode") or "fast").lower().strip()
    if mode not in ("fast", "accurate"):
        mode = "fast"

    nllb_model = str(payload.get("nllb_model") or "").strip()
    if not nllb_model:
        raise SystemExit("Missing nllb_model")

    source_lang = str(payload.get("source_lang") or "auto").lower().strip()
    target_langs = _as_list(payload.get("target_langs"))
    if not target_langs:
        raise SystemExit("No target languages")

    generate_summary = bool(payload.get("generate_summary") in (True, 1, "1", "true", "True", "yes"))
    use_glossary = bool(payload.get("use_glossary") in (True, 1, "1", "true", "True", "yes", "on"))
    preserve_formatting = bool(payload.get("preserve_formatting") in (True, 1, "1", "true", "True", "yes", "on"))
    try:
        summary_detail = int(payload.get("summary_detail") or 5)
    except Exception:
        summary_detail = 5
    summary_detail = max(1, min(10, summary_detail))

    # Make transformers fully offline by default for this worker.
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    progress(2)

    # Lazy imports (so the error shows clearly in logs)
    from backend.translation.hybrid_translator import HybridTranslator  # type: ignore
    from backend.translation.language_detector import detect_language  # type: ignore
    from backend.translation.summarizer import generate_summary as make_summary  # type: ignore

    # Normalize & validate language keys (frontend bugs should not crash the worker)
    supported_langs = set(getattr(HybridTranslator, "LANG_CODES_NLLB", {}).keys())

    # Detect language if needed
    detected = None
    if source_lang == "auto":
        try:
            detected = detect_language(text)
        except Exception:
            detected = None
        source_lang = detected or "english"

    source_lang = str(source_lang).lower().strip()
    if supported_langs and source_lang not in supported_langs:
        eprint(f"translate: unsupported source_lang='{source_lang}', fallback to 'english'")
        source_lang = "english"

    cleaned_targets: List[str] = []
    for t in target_langs:
        t2 = str(t).lower().strip()
        if not t2:
            continue
        if supported_langs and t2 not in supported_langs:
            eprint(f"translate: skipping unsupported target '{t2}'")
            continue
        cleaned_targets.append(t2)
    target_langs = cleaned_targets

    if not target_langs:
        raise SystemExit("No valid target languages")

    progress(5)
    eprint(f"translate: init NLLB model='{nllb_model}' mode={mode}")

    # Load translator
    tr = HybridTranslator(nllb_model=nllb_model)

    # Optional glossary (term dictionary)
    glossary: Dict[str, Any] = {}
    if use_glossary:
        try:
            gloss_path = ROOT / "backend" / "translation" / "glossaries" / "default.json"
            if gloss_path.exists():
                glossary = json.loads(gloss_path.read_text(encoding="utf-8"))
                if not isinstance(glossary, dict):
                    glossary = {}
        except Exception as e:
            eprint(f"glossary load failed: {e}")
            glossary = {}
    progress(20)

    results: Dict[str, str] = {}
    n = max(1, len(target_langs))

    for i, tgt in enumerate(target_langs):
        tgt = str(tgt).lower().strip()
        if not tgt:
            continue
        eprint(f"translate: {source_lang} -> {tgt}")
        # HybridTranslator.translate_nllb does chunking for long text.
        out = tr.translate_nllb(
            text,
            source_lang,
            tgt,
            use_glossary=use_glossary,
            glossary=glossary,
            preserve_formatting=preserve_formatting,
        )
        results[tgt] = out
        pct = 20 + int(((i + 1) / n) * 70)
        progress(pct)

    summ = None
    if generate_summary:
        # Prefer summary in Polish if it is one of the targets; otherwise first target; otherwise source.
        summary_lang = "polish" if "polish" in results else (target_langs[0] if target_langs else source_lang)
        base_text = results.get(summary_lang) or text
        progress(92)
        try:
            summ = make_summary(base_text, language=summary_lang, detail_level=summary_detail)
        except Exception as e:
            eprint(f"summary failed: {e}")
            summ = None

    progress(100)

    print(
        json.dumps(
            {
                "ok": True,
                "mode": mode,
                "nllb_model": nllb_model,
                "source_lang": source_lang,
                "detected_source_lang": detected,
                "targets": target_langs,
                "results": results,
                "summary": summ,
                "use_glossary": use_glossary,
                "preserve_formatting": preserve_formatting,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
