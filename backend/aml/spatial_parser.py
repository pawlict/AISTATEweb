"""Spatial (coordinate-based) PDF parser for bank statements.

Instead of relying on pdfplumber's extract_tables() which breaks on
multi-line cells, this module uses extract_words() to get every text
element with its bounding box, then:

1. Detects column header row by keyword matching
2. Derives column boundaries from header word positions
3. Segments transactions by date markers in the first column
4. Collects all words within each column zone for each transaction band

This correctly handles cells that wrap across multiple PDF lines.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("aistate.aml.spatial_parser")

# Header detection keywords (lowercase)
_HEADER_KEYWORDS = [
    "data", "księgowania", "ksiegowania", "transakcji", "kontrahent",
    "kontrahenta", "tytuł", "tytul", "kwota", "saldo", "szczegół",
    "szczegoly", "opis", "operacji", "obciążeni", "obciazeni",
    "uznani", "nadawca", "odbiorca", "walut", "numer",
]

# Date pattern for transaction start detection
_DATE_RE = re.compile(r"\d{2}[.\-/]\d{2}[.\-/]\d{2,4}")

# Amount pattern
_AMOUNT_RE = re.compile(r"^-?\s*\d[\d\s]*[,\.]\d{2}(\s*(PLN|EUR|USD|GBP|CHF))?$")


@dataclass
class WordBox:
    """A text element with its position on the page."""
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int = 0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass
class ColumnZone:
    """A detected column with its horizontal boundaries."""
    label: str           # Original header text
    col_type: str        # Detected type (date, counterparty, amount, etc.)
    x_min: float
    x_max: float
    header_y: float      # Y position of header text

    def contains_x(self, x: float, tolerance: float = 2.0) -> bool:
        return self.x_min - tolerance <= x <= self.x_max + tolerance


@dataclass
class TransactionBand:
    """A horizontal band spanning one transaction (may be multi-line)."""
    y_start: float
    y_end: float
    page: int
    row_index: int = 0


@dataclass
class SpatialParseResult:
    """Result of spatial PDF parsing."""
    pages: List[PageData]
    columns: List[ColumnZone]
    transactions: List[Dict[str, Any]]
    header_region: Optional[Dict[str, Any]]  # bank info above table
    page_count: int
    bank_id: str = ""
    bank_name: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class PageData:
    """Parsed data for a single PDF page."""
    page_num: int
    width: float
    height: float
    words: List[WordBox]
    image_path: Optional[str] = None  # path to rendered PNG


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def spatial_parse_pdf(
    pdf_path: Path,
    max_preview_pages: int = 5,
    render_images: bool = True,
    image_dir: Optional[Path] = None,
) -> SpatialParseResult:
    """Parse a bank statement PDF using spatial/coordinate analysis.

    Args:
        pdf_path: Path to the PDF file
        max_preview_pages: Max pages to process for preview
        render_images: Whether to render page images for UI overlay
        image_dir: Where to save page images (defaults to alongside PDF)

    Returns:
        SpatialParseResult with pages, columns, transactions, etc.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required for spatial parsing")

    if image_dir is None:
        image_dir = pdf_path.parent / ".preview"
    image_dir.mkdir(parents=True, exist_ok=True)

    pages_data: List[PageData] = []
    all_words: List[WordBox] = []
    full_text_parts: List[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)

        for pg_idx, pg in enumerate(pdf.pages[:max_preview_pages]):
            # Extract words with positions
            raw_words = pg.extract_words(
                keep_blank_chars=True,
                extra_attrs=["fontname", "size"],
            ) or []

            words = []
            for w in raw_words:
                wb = WordBox(
                    text=w.get("text", ""),
                    x0=float(w.get("x0", 0)),
                    x1=float(w.get("x1", 0)),
                    top=float(w.get("top", 0)),
                    bottom=float(w.get("bottom", 0)),
                    page=pg_idx,
                )
                words.append(wb)

            # Also grab full text for bank detection
            text = (pg.extract_text() or "").strip()
            if text:
                full_text_parts.append(text)

            # Render page image
            img_path = None
            if render_images:
                try:
                    img = pg.to_image(resolution=120)
                    img_file = image_dir / f"page_{pg_idx}.png"
                    img.save(str(img_file), format="PNG")
                    img_path = str(img_file)
                except Exception as e:
                    log.warning("Failed to render page %d: %s", pg_idx, e)

            page_data = PageData(
                page_num=pg_idx,
                width=float(pg.width),
                height=float(pg.height),
                words=words,
                image_path=img_path,
            )
            pages_data.append(page_data)
            all_words.extend(words)

    full_text = "\n\n".join(full_text_parts)

    # Detect bank
    bank_id, bank_name = _detect_bank(full_text)

    # Find header row and derive columns
    columns, header_y_end = _detect_columns(all_words)

    # Parse header region (above table)
    header_region = _parse_header_region(all_words, columns, header_y_end)

    # Segment into transaction bands
    bands = _segment_transactions(all_words, columns, header_y_end)

    # Extract transaction data from bands
    transactions = _extract_transactions(all_words, columns, bands)

    warnings = []
    if not columns:
        warnings.append("Nie wykryto kolumn — sprawdz czy PDF zawiera tabelaryczne dane")
    if not transactions:
        warnings.append("Nie znaleziono transakcji — sprawdz granice kolumn")

    return SpatialParseResult(
        pages=pages_data,
        columns=columns,
        transactions=transactions,
        header_region=header_region,
        page_count=page_count,
        bank_id=bank_id,
        bank_name=bank_name,
        warnings=warnings,
    )


# ============================================================
# BANK DETECTION
# ============================================================

def _detect_bank(full_text: str) -> Tuple[str, str]:
    """Detect bank from text using existing parser infrastructure."""
    try:
        from ..finance.parsers import get_parser
        parser = get_parser(full_text[:5000])
        return parser.BANK_ID, parser.BANK_NAME
    except Exception:
        return "unknown", "Nieznany bank"


# ============================================================
# COLUMN DETECTION
# ============================================================

def _detect_columns(words: List[WordBox]) -> Tuple[List[ColumnZone], float]:
    """Detect column headers and their horizontal boundaries.

    Scans for a row of words that contains header keywords.
    Returns the detected columns and the Y coordinate where headers end.
    """
    if not words:
        return [], 0.0

    # Group words by approximate Y position (same line)
    y_groups = _group_by_y(words, tolerance=4.0)

    # Score each line for header-likeness
    best_score = 0
    best_y = None
    best_line_words = []

    for y_center, line_words in y_groups:
        line_text = " ".join(w.text for w in line_words).lower()
        score = sum(1 for kw in _HEADER_KEYWORDS if kw in line_text)
        if score > best_score:
            best_score = score
            best_y = y_center
            best_line_words = line_words

    if best_score < 2 or best_y is None:
        # Try multi-line header (some banks split header across 2 lines)
        return _detect_columns_multiline(words, y_groups)

    # Found header line — now detect column boundaries
    header_y_end = max(w.bottom for w in best_line_words) + 5

    # Also check if there's a second header line just below (e.g. "Data księgowania\n/ Data transakcji")
    for y_center, line_words in y_groups:
        if header_y_end - 5 < y_center < header_y_end + 20:
            # This might be a continuation of the header
            line_text = " ".join(w.text for w in line_words).lower()
            sub_score = sum(1 for kw in _HEADER_KEYWORDS if kw in line_text)
            if sub_score >= 1:
                # Merge into header
                best_line_words = best_line_words + line_words
                header_y_end = max(w.bottom for w in best_line_words) + 5

    columns = _words_to_columns(best_line_words)
    return columns, header_y_end


def _detect_columns_multiline(
    words: List[WordBox],
    y_groups: List[Tuple[float, List[WordBox]]],
) -> Tuple[List[ColumnZone], float]:
    """Handle headers that span 2-3 lines (e.g. 'Data księgowania / Data transakcji')."""
    # Look for consecutive lines with at least 1 keyword each
    for i in range(len(y_groups) - 1):
        y1, words1 = y_groups[i]
        y2, words2 = y_groups[i + 1]

        if y2 - y1 > 25:  # Too far apart
            continue

        combined_text = " ".join(w.text for w in words1 + words2).lower()
        score = sum(1 for kw in _HEADER_KEYWORDS if kw in combined_text)

        if score >= 3:
            header_y_end = max(w.bottom for w in words1 + words2) + 5
            columns = _words_to_columns(words1 + words2)
            return columns, header_y_end

    return [], 0.0


def _words_to_columns(header_words: List[WordBox]) -> List[ColumnZone]:
    """Convert header words into column zones by clustering X positions.

    Groups nearby words into column clusters, then assigns types.
    """
    if not header_words:
        return []

    # Sort by X position
    sorted_words = sorted(header_words, key=lambda w: w.x0)

    # Cluster words that are close horizontally
    clusters: List[List[WordBox]] = []
    current_cluster: List[WordBox] = [sorted_words[0]]

    for w in sorted_words[1:]:
        # If this word overlaps or is very close to the last word in cluster
        prev = current_cluster[-1]
        gap = w.x0 - prev.x1

        if gap < 20:  # Close enough to be same column header
            current_cluster.append(w)
        else:
            clusters.append(current_cluster)
            current_cluster = [w]

    clusters.append(current_cluster)

    # Build columns from clusters
    columns = []
    for i, cluster in enumerate(clusters):
        label = " ".join(w.text for w in sorted(cluster, key=lambda w: (w.top, w.x0)))
        x_min = min(w.x0 for w in cluster)
        x_max = max(w.x1 for w in cluster)
        header_y = min(w.top for w in cluster)

        # Expand boundaries to fill gaps between columns
        # Left boundary: halfway between this column's left and previous column's right
        if i > 0:
            prev_x_max = columns[-1].x_max
            boundary = (prev_x_max + x_min) / 2
            columns[-1].x_max = boundary
            x_min = boundary

        col_type = _classify_column(label)
        columns.append(ColumnZone(
            label=label,
            col_type=col_type,
            x_min=x_min,
            x_max=x_max,
            header_y=header_y,
        ))

    # Extend first column to page left edge, last to right edge
    if columns:
        columns[0].x_min = 0
        # Extend last column to a reasonable right boundary
        page_width = max(w.x1 for w in header_words) + 50
        columns[-1].x_max = page_width

    return columns


def _classify_column(label: str) -> str:
    """Classify a column by its header text."""
    from .column_mapper import COLUMN_TYPES

    label_lower = label.strip().lower()
    if not label_lower:
        return "skip"

    best_type = "skip"
    best_score = 0

    for col_type, meta in COLUMN_TYPES.items():
        if col_type == "skip":
            continue
        for pattern in meta["patterns"]:
            if re.search(pattern, label_lower):
                score = len(pattern)
                if score > best_score:
                    best_score = score
                    best_type = col_type

    # Special combined header: "Dane kontrahenta" → counterparty
    if "kontrahent" in label_lower or "dane kontrahent" in label_lower:
        return "counterparty"
    if "szczegó" in label_lower or "szczego" in label_lower:
        return "reference"

    return best_type


# ============================================================
# HEADER REGION (bank info above table)
# ============================================================

def _parse_header_region(
    words: List[WordBox],
    columns: List[ColumnZone],
    header_y_end: float,
) -> Optional[Dict[str, Any]]:
    """Extract bank info from text above the table header.

    Returns dict with field values and 'words' list with positions
    for the frontend overlay, and 'field_boxes' with bounding rects
    for each detected field.
    """
    if not words or header_y_end <= 0:
        return None

    # Get all words above the column headers (first page only)
    header_words = [w for w in words if w.page == 0 and w.bottom < header_y_end - 10]
    if not header_words:
        return None

    sorted_words = sorted(header_words, key=lambda w: (w.top, w.x0))
    header_text = " ".join(w.text for w in sorted_words)

    # Build word list with positions for frontend
    word_items = [
        {"text": w.text, "x0": w.x0, "top": w.top, "x1": w.x1, "bottom": w.bottom}
        for w in sorted_words
    ]

    # Extract known fields via regex (on concatenated text)
    result: Dict[str, Any] = {
        "raw_text": header_text,
        "words": word_items,
        "field_boxes": [],
    }

    # Helper: find bounding box for a text span in header_words
    def _find_box_for_text(text_fragment: str) -> Optional[Dict[str, float]]:
        """Find bounding box of words that contain the text fragment."""
        frag_clean = re.sub(r"\s+", "", text_fragment.lower())
        # Sliding window over words
        for start_i in range(len(sorted_words)):
            accumulated = ""
            for end_i in range(start_i, len(sorted_words)):
                accumulated += sorted_words[end_i].text.lower().replace(" ", "")
                if frag_clean in accumulated:
                    span = sorted_words[start_i:end_i + 1]
                    return {
                        "x0": min(w.x0 for w in span),
                        "top": min(w.top for w in span),
                        "x1": max(w.x1 for w in span),
                        "bottom": max(w.bottom for w in span),
                    }
        return None

    # IBAN
    iban_match = re.search(r"(?:PL\s*)?(\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4})", header_text)
    if iban_match:
        val = re.sub(r"\s", "", iban_match.group(0))
        result["account_number"] = val
        box = _find_box_for_text(iban_match.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "account_number", "value": val, **box,
            })

    # Account holder — look for "Posiadacz:" or "Właściciel:" or "Nazwa:" pattern
    holder_match = re.search(
        r"(?:posiadacz|w[lł]a[sś]ciciel|nazwa\s+klienta|klient)[:\s]+(.+?)(?=\s{2,}|\d{2}[.-]|\n|$)",
        header_text, re.IGNORECASE,
    )
    if holder_match:
        holder_val = holder_match.group(1).strip()
        if holder_val and len(holder_val) > 3:
            result["account_holder"] = holder_val
            box = _find_box_for_text(holder_match.group(0))
            if box:
                result["field_boxes"].append({
                    "field_type": "account_holder", "value": holder_val, **box,
                })

    # Currency
    cur_match = re.search(r"\b(PLN|EUR|USD|GBP|CHF|CZK|SEK|NOK|DKK)\b", header_text)
    if cur_match:
        result["currency"] = cur_match.group(1)
        box = _find_box_for_text(cur_match.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "currency", "value": cur_match.group(1), **box,
            })

    # Saldo końcowe poprzedniego wyciągu (must match before general saldo patterns)
    prev_closing_m = re.search(
        r"saldo\s*(?:końc|ko.c)\w*\s*(?:poprz|pop\.)\w*[^0-9\-]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if prev_closing_m:
        parsed = _parse_amount_str(prev_closing_m.group(1))
        result["previous_closing_balance"] = parsed
        box = _find_box_for_text(prev_closing_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "previous_closing_balance",
                "value": str(parsed) if parsed is not None else "",
                **box,
            })

    # Saldo początkowe / końcowe
    for label, key in [
        (r"saldo\s*(pocz|otwarcia|na\s*pocz)", "opening_balance"),
        (r"saldo\s*(końc|zamkni|na\s*koniec|ko.c)", "closing_balance"),
    ]:
        # Skip if already matched as previous_closing_balance
        m = re.search(label + r"[^0-9\-]*(-?\d[\d\s]*[,\.]\d{2})", header_text, re.IGNORECASE)
        if m:
            # Don't re-match the "saldo końcowe poprzedniego" as regular closing_balance
            if key == "closing_balance" and prev_closing_m and m.start() == prev_closing_m.start():
                continue
            parsed = _parse_amount_str(m.group(len(m.groups())))
            result[key] = parsed
            box = _find_box_for_text(m.group(0))
            if box:
                result["field_boxes"].append({
                    "field_type": key,
                    "value": str(parsed) if parsed is not None else "",
                    **box,
                })

    # Saldo dostępne
    avail_m = re.search(
        r"saldo\s*dost[ęe]pn\w*[^0-9\-]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if avail_m:
        parsed = _parse_amount_str(avail_m.group(1))
        result["available_balance"] = parsed
        box = _find_box_for_text(avail_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "available_balance",
                "value": str(parsed) if parsed is not None else "",
                **box,
            })

    # Suma uznań: "Suma uznań (123) \n 45 678,90"
    credits_m = re.search(
        r"(?:suma\s*uzna[ńn])\s*\(?(\d+)\)?[^0-9\-]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if credits_m:
        count_val = int(credits_m.group(1))
        sum_val = _parse_amount_str(credits_m.group(2))
        result["declared_credits_count"] = count_val
        result["declared_credits_sum"] = sum_val
        box = _find_box_for_text(credits_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "declared_credits_count",
                "value": str(count_val),
                **box,
            })
            result["field_boxes"].append({
                "field_type": "declared_credits_sum",
                "value": str(sum_val) if sum_val is not None else "",
                **box,
            })

    # Suma obciążeń: "Suma obciążeń (45) \n 12 345,67"
    debits_m = re.search(
        r"(?:suma\s*obci[ąa][żz]e[ńn])\s*\(?(\d+)\)?[^0-9\-]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if debits_m:
        count_val = int(debits_m.group(1))
        sum_val = _parse_amount_str(debits_m.group(2))
        result["declared_debits_count"] = count_val
        result["declared_debits_sum"] = sum_val
        box = _find_box_for_text(debits_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "declared_debits_count",
                "value": str(count_val),
                **box,
            })
            result["field_boxes"].append({
                "field_type": "declared_debits_sum",
                "value": str(sum_val) if sum_val is not None else "",
                **box,
            })

    # Limit zadłużenia
    limit_m = re.search(
        r"limit\s*(?:zad[łl]u[żz]enia|kredyt\w*)?[:\s]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if limit_m:
        parsed = _parse_amount_str(limit_m.group(1))
        result["debt_limit"] = parsed
        box = _find_box_for_text(limit_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "debt_limit",
                "value": str(parsed) if parsed is not None else "",
                **box,
            })

    # Kwota prowizji zaległej
    commission_m = re.search(
        r"(?:kwota\s*)?prowizj[iy]\s*(?:za[lł]eg[lł]\w*)?[:\s]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if commission_m:
        parsed = _parse_amount_str(commission_m.group(1))
        result["overdue_commission"] = parsed
        box = _find_box_for_text(commission_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "overdue_commission",
                "value": str(parsed) if parsed is not None else "",
                **box,
            })

    # Kwota zablokowana
    blocked_m = re.search(
        r"(?:kwota\s*)?zablok\w*[:\s]*(-?\d[\d\s]*[,\.]\d{2})",
        header_text, re.IGNORECASE,
    )
    if blocked_m:
        parsed = _parse_amount_str(blocked_m.group(1))
        result["blocked_amount"] = parsed
        box = _find_box_for_text(blocked_m.group(0))
        if box:
            result["field_boxes"].append({
                "field_type": "blocked_amount",
                "value": str(parsed) if parsed is not None else "",
                **box,
            })

    # Period
    dates = _DATE_RE.findall(header_text)
    if len(dates) >= 2:
        result["period_from"] = _normalize_date(dates[0])
        result["period_to"] = _normalize_date(dates[-1])
        box_from = _find_box_for_text(dates[0])
        box_to = _find_box_for_text(dates[-1])
        if box_from:
            result["field_boxes"].append({
                "field_type": "period_from",
                "value": result["period_from"],
                **box_from,
            })
        if box_to:
            result["field_boxes"].append({
                "field_type": "period_to",
                "value": result["period_to"],
                **box_to,
            })

    # Bank name — try to find in first line(s) of header
    # Group words by Y-line, take the first line that has >2 words as bank name
    if sorted_words:
        y_groups: Dict[int, List] = {}
        for w in sorted_words:
            y_key = int(w.top / 5) * 5  # group by ~5pt tolerance
            y_groups.setdefault(y_key, []).append(w)
        for y_key in sorted(y_groups.keys()):
            line_words = y_groups[y_key]
            line_text = " ".join(w.text for w in line_words).strip()
            # Skip lines that are just numbers, dates, or very short
            if len(line_text) > 5 and not re.match(r"^[\d\s.,-/]+$", line_text):
                result["bank_name_detected"] = line_text
                box = {
                    "x0": min(w.x0 for w in line_words),
                    "top": min(w.top for w in line_words),
                    "x1": max(w.x1 for w in line_words),
                    "bottom": max(w.bottom for w in line_words),
                }
                # Only add if no bank_name box yet
                if not any(fb["field_type"] == "bank_name" for fb in result["field_boxes"]):
                    result["field_boxes"].append({
                        "field_type": "bank_name", "value": line_text, **box,
                    })
                break

    return result


# ============================================================
# TRANSACTION SEGMENTATION
# ============================================================

def _segment_transactions(
    words: List[WordBox],
    columns: List[ColumnZone],
    header_y_end: float,
) -> List[TransactionBand]:
    """Segment data area into transaction bands.

    A new transaction starts whenever a date (DD.MM.YYYY) appears
    in the first column zone (date column).

    Handles multi-page PDFs with per-page header detection:
    page 0 uses the detected header_y_end, continuation pages detect
    their own header boundary (repeated column headers may be at
    different Y position since page 0 has bank info above).
    """
    if not columns or header_y_end <= 0:
        return []

    # Find the date column (first column typed as 'date')
    date_col = None
    for col in columns:
        if col.col_type == "date":
            date_col = col
            break

    # Fallback: use the first column
    if date_col is None:
        date_col = columns[0]

    # Build per-page header_y_end to handle continuation pages correctly.
    # Page 0 uses the provided header_y_end. Pages 1+ detect their own
    # header position (repeated column headers at different Y than page 0
    # because page 0 has bank info above the table header).
    page_nums = sorted(set(w.page for w in words))
    page_header_y: Dict[int, float] = {0: header_y_end}

    for pg in page_nums:
        if pg == 0:
            continue
        pg_words = [w for w in words if w.page == pg]
        if not pg_words:
            page_header_y[pg] = 0
            continue

        # Check top portion of the page for repeated column header keywords
        # Use 60% of page-0 header_y_end as the scan zone (headers on
        # continuation pages are typically shorter)
        scan_limit = max(header_y_end * 1.2, 120)
        top_words = [w for w in pg_words if w.top < scan_limit]
        if not top_words:
            page_header_y[pg] = 0
            continue

        # Group top words into lines and check for header keywords
        top_lines = _group_by_y(top_words, tolerance=4.0)
        best_hdr_bottom = 0.0
        for _y, line_words in top_lines:
            line_text = " ".join(w.text for w in line_words).lower()
            hdr_score = sum(1 for kw in _HEADER_KEYWORDS if kw in line_text)
            if hdr_score >= 2:
                line_bottom = max(w.bottom for w in line_words) + 5
                best_hdr_bottom = max(best_hdr_bottom, line_bottom)

        page_header_y[pg] = best_hdr_bottom

    # Filter data words using per-page header boundaries
    data_words = [
        w for w in words
        if w.top >= page_header_y.get(w.page, 0)
    ]
    date_starts: List[Tuple[float, int]] = []  # (y_position, page)

    for w in data_words:
        if date_col.contains_x(w.cx, tolerance=10):
            if _DATE_RE.match(w.text.strip()):
                # Check this isn't a duplicate date on same transaction
                # (e.g. booking date and value date on consecutive lines)
                if date_starts:
                    last_y, last_pg = date_starts[-1]
                    # If very close vertically (< 15 pts) and same page,
                    # it's likely a second date in the same transaction
                    if last_pg == w.page and abs(w.top - last_y) < 15:
                        continue
                date_starts.append((w.top, w.page))

    if not date_starts:
        return []

    # Build bands between consecutive date starts
    bands = []
    for i in range(len(date_starts)):
        y_start = date_starts[i][0] - 2  # Small padding above
        page = date_starts[i][1]

        if i + 1 < len(date_starts):
            next_y, next_pg = date_starts[i + 1]
            if next_pg == page:
                y_end = next_y - 2
            else:
                # Transaction spans to end of this page
                y_end = 9999
        else:
            # Last transaction — extends to bottom of data
            y_end = 9999

        bands.append(TransactionBand(
            y_start=y_start,
            y_end=y_end,
            page=page,
            row_index=i,
        ))

    return bands


# ============================================================
# TRANSACTION EXTRACTION
# ============================================================

def _extract_transactions(
    words: List[WordBox],
    columns: List[ColumnZone],
    bands: List[TransactionBand],
) -> List[Dict[str, Any]]:
    """Extract structured transaction data from word positions.

    For each transaction band, collects all words within each column zone,
    sorts them by Y position, and joins into field text.
    """
    transactions = []

    for band in bands:
        # Get all words in this band
        band_words = [
            w for w in words
            if w.page == band.page
            and w.top >= band.y_start
            and w.top < band.y_end
        ]

        if not band_words:
            continue

        # Assign words to columns
        tx_data: Dict[str, str] = {}
        for col in columns:
            col_words = [
                w for w in band_words
                if col.contains_x(w.cx, tolerance=5)
            ]
            # Sort by Y then X for multi-line content
            col_words.sort(key=lambda w: (w.top, w.x0))
            text = _join_words(col_words)
            tx_data[col.col_type] = text

        # Build transaction dict
        tx = _build_transaction(tx_data, band.row_index)
        if tx:
            transactions.append(tx)

    return transactions


def _join_words(words: List[WordBox]) -> str:
    """Join words into text, preserving line breaks for multi-line content."""
    if not words:
        return ""

    lines: List[List[str]] = [[]]
    prev_bottom = words[0].top

    for w in words:
        # If Y position jumped significantly, start a new line
        if w.top - prev_bottom > 3:
            lines.append([])
        lines[-1].append(w.text)
        prev_bottom = w.bottom

    return " ".join(" ".join(line) for line in lines if line)


def _build_transaction(
    fields: Dict[str, str],
    row_index: int,
) -> Optional[Dict[str, Any]]:
    """Build a clean transaction dict from extracted fields."""
    date_str = fields.get("date", "").strip()

    # Try to split compound date field (booking + value date on same field)
    booking_date = ""
    value_date = ""
    date_matches = _DATE_RE.findall(date_str)
    if len(date_matches) >= 2:
        booking_date = _normalize_date(date_matches[0])
        value_date = _normalize_date(date_matches[1])
    elif len(date_matches) == 1:
        booking_date = _normalize_date(date_matches[0])
    elif fields.get("value_date"):
        vd_matches = _DATE_RE.findall(fields["value_date"])
        if vd_matches:
            value_date = _normalize_date(vd_matches[0])

    if not booking_date:
        return None

    # Parse amount
    amount = None
    amount_str = fields.get("amount", "").strip()
    debit_str = fields.get("debit", "").strip()
    credit_str = fields.get("credit", "").strip()

    if amount_str:
        amount = _parse_amount_str(amount_str)
    elif debit_str:
        val = _parse_amount_str(debit_str)
        if val is not None:
            amount = -abs(val)
    elif credit_str:
        val = _parse_amount_str(credit_str)
        if val is not None:
            amount = abs(val)

    if amount is None:
        return None

    balance = _parse_amount_str(fields.get("balance", ""))

    counterparty = fields.get("counterparty", "").strip()
    title = fields.get("description", "").strip()
    reference = fields.get("reference", "").strip()
    bank_category = fields.get("bank_type", "").strip()

    return {
        "row_index": row_index,
        "date": booking_date,
        "value_date": value_date or booking_date,
        "amount": amount,
        "balance_after": balance,
        "counterparty": counterparty,
        "title": title,
        "reference": reference,
        "bank_category": bank_category,
        "direction": "DEBIT" if amount < 0 else "CREDIT",
        "currency": "PLN",
        "raw_fields": {k: v for k, v in fields.items() if v},
    }


# ============================================================
# HELPERS
# ============================================================

def _group_by_y(
    words: List[WordBox],
    tolerance: float = 4.0,
) -> List[Tuple[float, List[WordBox]]]:
    """Group words into lines by Y position."""
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w.page, w.top, w.x0))
    groups: List[Tuple[float, List[WordBox]]] = []
    current_y = sorted_words[0].top
    current_group: List[WordBox] = [sorted_words[0]]

    for w in sorted_words[1:]:
        if abs(w.top - current_y) <= tolerance and w.page == current_group[0].page:
            current_group.append(w)
        else:
            avg_y = sum(ww.top for ww in current_group) / len(current_group)
            groups.append((avg_y, current_group))
            current_y = w.top
            current_group = [w]

    if current_group:
        avg_y = sum(ww.top for ww in current_group) / len(current_group)
        groups.append((avg_y, current_group))

    return groups


def _normalize_date(s: str) -> Optional[str]:
    """Parse date string to YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{2})[.\-/](\d{2})[.\-/](\d{2})", s)
    if m:
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        return f"{year}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s
    return None


def _parse_amount_str(s: str) -> Optional[float]:
    """Parse Polish-format amount (e.g. '-28,26 PLN') to float."""
    if not s or not s.strip():
        return None
    s = s.strip().replace("\xa0", "").replace(" ", "")
    # Remove currency suffix
    s = re.sub(r"[A-Za-z]+$", "", s).strip()
    if not s:
        return None
    # Polish format: thousands with dot, decimal with comma
    # "1.234,56" → "1234.56"
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ============================================================
# SERIALIZATION FOR API
# ============================================================

def result_to_api_response(
    result: SpatialParseResult,
    base_url: str = "/api/aml/page-image",
) -> Dict[str, Any]:
    """Convert SpatialParseResult to JSON-serializable dict for the API."""
    pages = []
    for pd in result.pages:
        page_info = {
            "page_num": pd.page_num,
            "width": pd.width,
            "height": pd.height,
            "image_url": f"{base_url}/{pd.page_num}" if pd.image_path else None,
            "word_count": len(pd.words),
        }
        pages.append(page_info)

    columns = []
    for col in result.columns:
        columns.append({
            "label": col.label,
            "col_type": col.col_type,
            "x_min": round(col.x_min, 1),
            "x_max": round(col.x_max, 1),
            "header_y": round(col.header_y, 1),
        })

    return {
        "status": "ok",
        "page_count": result.page_count,
        "pages": pages,
        "columns": columns,
        "transactions": result.transactions,
        "transaction_count": len(result.transactions),
        "header_region": result.header_region,
        "bank_id": result.bank_id,
        "bank_name": result.bank_name,
        "warnings": result.warnings,
    }
