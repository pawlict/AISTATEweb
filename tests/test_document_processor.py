"""Tests for backend.document_processor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_supported_exts():
    """SUPPORTED_EXTS should contain expected formats."""
    from backend.document_processor import SUPPORTED_EXTS

    assert ".txt" in SUPPORTED_EXTS
    assert ".pdf" in SUPPORTED_EXTS
    assert ".docx" in SUPPORTED_EXTS
    assert ".json" in SUPPORTED_EXTS
    assert ".csv" in SUPPORTED_EXTS
    assert ".png" in SUPPORTED_EXTS


def test_extract_text_txt(sample_txt_file: Path):
    """extract_text should read plain text files."""
    from backend.document_processor import extract_text

    result = extract_text(sample_txt_file)
    assert "Hello world" in result.text
    assert "Second line" in result.text


def test_extract_text_json(sample_json_file: Path):
    """extract_text should pretty-print JSON files."""
    from backend.document_processor import extract_text

    result = extract_text(sample_json_file)
    assert "key" in result.text
    assert "value" in result.text
    # Should be valid JSON when re-parsed
    parsed = json.loads(result.text)
    assert parsed["key"] == "value"


def test_extract_text_csv(sample_csv_file: Path):
    """extract_text should convert CSV to markdown table."""
    from backend.document_processor import extract_text

    result = extract_text(sample_csv_file)
    assert "name" in result.text
    assert "Alice" in result.text
    assert "Bob" in result.text
    # Should contain markdown table separators
    assert "---" in result.text


def test_extract_text_unsupported(tmp_path: Path):
    """extract_text should raise error for unsupported file types."""
    from backend.document_processor import extract_text, DocumentProcessingError

    unsupported = tmp_path / "file.xyz"
    unsupported.write_text("data", encoding="utf-8")
    with pytest.raises(DocumentProcessingError):
        extract_text(unsupported)


def test_extract_text_missing_file(tmp_path: Path):
    """extract_text should raise error for non-existent files."""
    from backend.document_processor import extract_text

    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(Exception):
        extract_text(missing)


def test_extracted_document_to_dict(sample_txt_file: Path):
    """ExtractedDocument.to_dict() should produce a serializable dict."""
    from backend.document_processor import extract_text

    result = extract_text(sample_txt_file)
    d = result.to_dict()
    assert isinstance(d, dict)
    assert "text" in d
    assert "tables" in d
    assert "metadata" in d
    # Should be JSON-serializable
    json.dumps(d)


def test_extract_text_empty_file(tmp_path: Path):
    """extract_text should handle empty text files."""
    from backend.document_processor import extract_text

    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    result = extract_text(empty)
    assert result.text == ""


def test_extract_text_unicode(tmp_path: Path):
    """extract_text should handle unicode content."""
    from backend.document_processor import extract_text

    uni = tmp_path / "unicode.txt"
    uni.write_text("Cześć świecie! 日本語テスト", encoding="utf-8")
    result = extract_text(uni)
    assert "Cześć" in result.text
    assert "日本語" in result.text


def test_extract_json_invalid(tmp_path: Path):
    """extract_text should raise for invalid JSON."""
    from backend.document_processor import extract_text, DocumentProcessingError

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(DocumentProcessingError):
        extract_text(bad)
