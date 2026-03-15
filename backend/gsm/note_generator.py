"""
GSM Note DOCX Generator — fills the professional note template with data.

Uses docxtpl (Jinja2 in DOCX) to populate the template placeholders
and optionally embeds chart screenshots as inline images.
"""
from __future__ import annotations

import io
import logging
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.gsm.note_gen")


def generate_note_docx(
    template_path: Path,
    placeholders: Dict[str, Any],
    output_path: Path,
    *,
    chart_images: Optional[Dict[str, bytes]] = None,
    llm_overrides: Optional[Dict[str, str]] = None,
) -> Path:
    """Generate a professional analytical note DOCX from the template.

    Args:
        template_path: Path to the DOCX template (gsm_note_template.docx).
        placeholders: Dict from note_builder.build_note_placeholders().
        output_path: Where to save the generated DOCX.
        chart_images: Optional dict of chart_name → PNG bytes to embed.
            Keys: "activity", "top_contacts", "night_activity",
                  "weekend_activity", "map_bts"
        llm_overrides: Optional dict from note_llm.generate_note_sections_llm().
            Contains override text for sections 4-9.

    Returns:
        Path to the generated DOCX file.
    """
    from docxtpl import DocxTemplate, InlineImage
    from docx.shared import Mm

    # Merge LLM overrides into placeholders
    if llm_overrides:
        _apply_llm_overrides(placeholders, llm_overrides)

    # Open template
    tpl = DocxTemplate(str(template_path))

    # Prepare inline images
    images = {}
    if chart_images:
        for name, img_bytes in chart_images.items():
            if img_bytes:
                try:
                    img_stream = io.BytesIO(img_bytes)
                    images[f"chart_{name}"] = InlineImage(
                        tpl, img_stream, width=Mm(150)
                    )
                except Exception as e:
                    log.warning("Failed to create InlineImage for %s: %s", name, e)

    # Build context — flatten nested dicts for docxtpl
    context = _flatten_for_template(placeholders)
    context.update(images)

    # Render
    tpl.render(context)

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(output_path))

    log.info("Generated GSM note: %s (%d bytes)", output_path.name, output_path.stat().st_size)
    return output_path


def _flatten_for_template(placeholders: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested dicts into dot-notation keys for docxtpl.

    docxtpl supports both {{ key }} and {{ obj.key }} syntax.
    We keep both formats for compatibility.
    """
    context: Dict[str, Any] = {}

    for key, value in placeholders.items():
        if isinstance(value, dict):
            # Keep the nested dict (for {{ obj.key }} syntax)
            context[key] = value
            # Also flatten (for {{ obj_key }} syntax — fallback)
            for sub_key, sub_value in value.items():
                context[f"{key}_{sub_key}"] = sub_value
        else:
            context[key] = value

    return context


def _apply_llm_overrides(placeholders: Dict[str, Any], overrides: Dict[str, str]) -> None:
    """Apply LLM-generated text overrides to placeholders dict.

    LLM overrides use dot-notation keys like "assessment.main_characteristics".
    """
    for key, value in overrides.items():
        if key.startswith("_"):
            # Internal keys (full section texts) — skip for now
            # These could be used for a different template approach
            continue

        parts = key.split(".", 1)
        if len(parts) == 2:
            parent, child = parts
            if parent in placeholders and isinstance(placeholders[parent], dict):
                placeholders[parent][child] = value
            else:
                placeholders[parent] = {child: value}
        else:
            placeholders[key] = value


def get_default_template_path() -> Path:
    """Return path to the bundled GSM note template."""
    # Look relative to this file's package
    pkg_dir = Path(__file__).resolve().parent.parent.parent  # → project root
    template = pkg_dir / "templates" / "gsm_note_template.docx"
    if template.exists():
        return template

    # Fallback: look in data_www
    import os
    data_dir = Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))
    alt = data_dir / "templates" / "gsm_note_template.docx"
    if alt.exists():
        return alt

    raise FileNotFoundError(
        f"GSM note template not found. Expected at {template} or {alt}"
    )
