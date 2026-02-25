"""
Document handlers for various file formats
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx not available - DOCX support disabled")

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("pdfplumber not available - PDF support disabled")

try:
    import fitz as pymupdf  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available - PDF text overlay disabled")

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False
    logger.warning("python-pptx not available - PPTX support disabled")


class DocumentHandler:
    """Base class for document handlers"""
    
    def extract_text(self, file_path: Path) -> str:
        """Extract text from document"""
        raise NotImplementedError
    
    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        **kwargs
    ):
        """Save translated text to document"""
        raise NotImplementedError


class TXTHandler(DocumentHandler):
    """Plain text file handler"""
    
    def extract_text(self, file_path: Path) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            logger.info(f"Extracted {len(text)} characters from {file_path.name}")
            return text
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                text = f.read()
            logger.warning(f"Fallback to latin-1 encoding for {file_path.name}")
            return text
    
    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        **kwargs
    ):
        """Save translated text to TXT file"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_text)
        logger.info(f"Saved translation to {output_path}")


class DOCXHandler(DocumentHandler):
    """Microsoft Word document handler"""
    
    def extract_text(self, file_path: Path) -> str:
        """Extract text from DOCX file"""
        if not DOCX_AVAILABLE:
            raise RuntimeError("python-docx not available")
        
        try:
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = '\n\n'.join(paragraphs)
            logger.info(f"Extracted {len(text)} characters from {file_path.name}")
            return text
        except Exception as e:
            logger.error(f"Failed to extract text from DOCX: {e}")
            raise
    
    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        translator=None,
        source_lang: str = None,
        target_lang: str = None,
        **kwargs
    ):
        """
        Save translated text to DOCX file
        
        If translator is provided, translates paragraph by paragraph
        to preserve formatting better
        """
        if not DOCX_AVAILABLE:
            raise RuntimeError("python-docx not available")
        
        try:
            if translator and source_lang and target_lang:
                # Paragraph-by-paragraph translation (better formatting preservation)
                doc = Document(original_path)
                
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        original_text = paragraph.text
                        translated = translator.translate_text(
                            original_text,
                            source_lang,
                            target_lang
                        )
                        
                        # Clear paragraph and add translated text
                        paragraph.clear()
                        paragraph.add_run(translated)
                
                doc.save(output_path)
            else:
                # Simple approach: create new document with translated text
                doc = Document()
                
                for paragraph_text in translated_text.split('\n\n'):
                    if paragraph_text.strip():
                        doc.add_paragraph(paragraph_text)
                
                doc.save(output_path)
            
            logger.info(f"Saved DOCX translation to {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save DOCX: {e}")
            raise


class PDFHandler(DocumentHandler):
    """PDF document handler — extract text with page markers, re-inject via PyMuPDF overlay."""

    # Unicode font embedded with PyMuPDF for non-Latin scripts
    _FALLBACK_FONTNAME = "helv"

    def extract_text(self, file_path: Path) -> str:
        """Extract text from PDF file, page by page with markers (like PPTX slides)."""
        if not PDF_AVAILABLE:
            raise RuntimeError("pdfplumber not available")

        try:
            parts: list[str] = []

            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        parts.append(f"--- Strona {i} ---\n{page_text}")
                        logger.debug(f"Extracted page {i}/{len(pdf.pages)}")

            text = "\n\n".join(parts)
            logger.info(
                f"Extracted {len(text)} chars from PDF "
                f"({len(parts)} pages, {file_path.name})"
            )
            return text

        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {e}")
            raise

    # ------------------------------------------------------------------
    # PDF → PDF  text overlay (used by export-to-original endpoint)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_color(color) -> tuple:
        """Convert PyMuPDF color (int or tuple) → (r, g, b) floats."""
        if isinstance(color, (list, tuple)):
            return tuple(color[:3])
        if isinstance(color, int):
            r = ((color >> 16) & 0xFF) / 255.0
            g = ((color >> 8) & 0xFF) / 255.0
            b = (color & 0xFF) / 255.0
            return (r, g, b)
        return (0, 0, 0)

    @staticmethod
    def _dominant_font(dict_block: dict) -> dict:
        """Return {'size': float, 'color': tuple} for the most common font in a dict block."""
        sizes: list[float] = []
        colors: list = []
        for ln in dict_block.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip():
                    sizes.append(sp["size"])
                    colors.append(sp.get("color", 0))
        if not sizes:
            return {"size": 11, "color": (0, 0, 0)}
        dominant = max(set(sizes), key=sizes.count)
        idx = sizes.index(dominant)
        return {
            "size": dominant,
            "color": PDFHandler._normalize_color(colors[idx]),
        }

    @staticmethod
    def _fit_fontsize(rect, text: str, start_size: float, min_size: float = 5.0) -> float:
        """Estimate largest font size that makes *text* fit inside *rect*."""
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            return min_size
        for fs in (start_size, start_size * 0.85, start_size * 0.7,
                   start_size * 0.55, start_size * 0.4, min_size):
            fs = max(fs, min_size)
            cpl = w / (fs * 0.52) if fs > 0 else 1          # chars per line (approx)
            cpl = max(cpl, 1)
            est_lines = sum(max(1, len(line) / cpl) for line in text.split("\n"))
            if est_lines * fs * 1.2 <= h:
                return fs
        return min_size

    @staticmethod
    def inject_translated_text(original_path: Path, translated_text: str) -> bytes:
        """Replace text in original PDF with *translated_text* and return PDF bytes.

        Works at **text-block** level (not individual spans) so that each
        paragraph gets a full-width rectangle with proper word-wrapping.
        Uses ``--- Strona N ---`` markers to split text across pages.
        """
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PyMuPDF (fitz) not available — cannot write PDF")

        import re as _re

        doc = pymupdf.open(str(original_path))

        # --- 1. Parse translated text into pages via markers ---------------
        marker_re = _re.compile(
            r"^-{2,}\s*(?:Strona|Page)\s*(\d+)\s*-{2,}\s*$",
            _re.IGNORECASE | _re.MULTILINE,
        )
        pages_text: dict[int, str] = {}
        parts = marker_re.split(translated_text)
        # parts = [preamble, "1", text_page1, "2", text_page2, …]
        idx = 1
        while idx + 1 < len(parts):
            page_num = int(parts[idx]) - 1          # 0-indexed
            pages_text[page_num] = parts[idx + 1].strip()
            idx += 2

        # --- 2. Process each page ------------------------------------------
        for page_idx, page in enumerate(doc):
            if page_idx not in pages_text:
                continue
            page_translated = pages_text[page_idx]
            if not page_translated:
                continue

            # 2a. Collect original text blocks (block-level bounding rects)
            raw_blocks = page.get_text("blocks")
            orig_blocks: list[dict] = []
            for item in raw_blocks:
                x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
                btype = item[6] if len(item) > 6 else 0
                if btype != 0 or not str(text).strip():
                    continue
                orig_blocks.append({
                    "rect": pymupdf.Rect(x0, y0, x1, y1),
                    "text": str(text).strip(),
                })
            if not orig_blocks:
                continue

            # 2b. Get dominant font info per block from dict representation
            dict_blocks = [
                b for b in page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                if b.get("type", -1) == 0
            ]
            block_fonts: list[dict] = []
            for i, ob in enumerate(orig_blocks):
                # Match dict_block by index (same order) or fall back
                if i < len(dict_blocks):
                    block_fonts.append(PDFHandler._dominant_font(dict_blocks[i]))
                else:
                    block_fonts.append({"size": 11, "color": (0, 0, 0)})

            # 2c. Distribute translated text across blocks
            #     Try double-newline split first (natural paragraph breaks)
            paras = [p.strip() for p in _re.split(r"\n\s*\n", page_translated) if p.strip()]

            if len(paras) == len(orig_blocks):
                chunks = paras
            else:
                # Proportional line distribution by original char count
                all_lines = [ln for ln in page_translated.split("\n") if ln.strip()]
                total_chars = sum(len(ob["text"]) for ob in orig_blocks) or 1
                chunks: list[str] = []
                lptr = 0
                for i, ob in enumerate(orig_blocks):
                    if i == len(orig_blocks) - 1:
                        chunks.append("\n".join(all_lines[lptr:]))
                    else:
                        prop = len(ob["text"]) / total_chars
                        n = max(1, round(prop * len(all_lines)))
                        chunks.append("\n".join(all_lines[lptr:lptr + n]))
                        lptr += n

            # 2d. Redact all original text blocks (white-out)
            for ob in orig_blocks:
                page.add_redact_annot(ob["rect"], fill=(1, 1, 1))
            page.apply_redactions()

            # 2e. Insert translated text into block rectangles
            for i, ob in enumerate(orig_blocks):
                chunk = chunks[i].strip() if i < len(chunks) else ""
                if not chunk:
                    continue

                rect = ob["rect"]
                fi = block_fonts[i] if i < len(block_fonts) else {"size": 11, "color": (0, 0, 0)}
                fontsize = PDFHandler._fit_fontsize(rect, chunk, fi["size"])

                page.insert_textbox(
                    rect,
                    chunk,
                    fontsize=fontsize,
                    color=fi["color"],
                    align=pymupdf.TEXT_ALIGN_LEFT,
                )

        pdf_bytes = doc.tobytes()
        doc.close()
        return pdf_bytes

    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        **kwargs,
    ):
        """Save translated PDF — overlay text on original preserving layout."""
        if PYMUPDF_AVAILABLE:
            try:
                pdf_bytes = self.inject_translated_text(original_path, translated_text)
                output_path = output_path.with_suffix(".pdf")
                output_path.write_bytes(pdf_bytes)
                logger.info(f"Saved PDF translation to {output_path}")
                return
            except Exception as e:
                logger.error(f"PyMuPDF overlay failed, falling back to TXT: {e}")

        # Fallback: save as TXT
        txt_output = output_path.with_suffix(".txt")
        with open(txt_output, "w", encoding="utf-8") as f:
            f.write(translated_text)
        logger.info(f"Saved PDF translation as TXT: {txt_output}")
        logger.warning("PDF → PDF translation requires PyMuPDF library")


class SRTHandler(DocumentHandler):
    """Subtitle file handler (preserves timestamps)"""
    
    def extract_text(self, file_path: Path) -> str:
        """Extract text from SRT file (returns full content with timestamps)"""
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        logger.info(f"Extracted {len(text)} characters from SRT")
        return text
    
    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        translator=None,
        source_lang: str = None,
        target_lang: str = None,
        **kwargs
    ):
        """
        Save translated SRT file (preserving structure)
        
        If translator is provided, translates subtitle-by-subtitle
        """
        import re
        
        try:
            with open(original_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse SRT blocks
            blocks = re.split(r'\n\n+', content.strip())
            translated_blocks = []
            
            for block in blocks:
                lines = block.split('\n')
                
                if len(lines) >= 3:
                    # lines[0] = number
                    # lines[1] = timestamp
                    # lines[2:] = subtitle text
                    
                    number = lines[0]
                    timestamp = lines[1]
                    subtitle_text = ' '.join(lines[2:])
                    
                    # Translate subtitle
                    if translator and source_lang and target_lang:
                        translated = translator.translate_text(
                            subtitle_text,
                            source_lang,
                            target_lang
                        )
                    else:
                        translated = subtitle_text
                    
                    translated_block = f"{number}\n{timestamp}\n{translated}"
                    translated_blocks.append(translated_block)
            
            # Save
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(translated_blocks))
            
            logger.info(f"Saved SRT translation to {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save SRT: {e}")
            raise


class PPTXHandler(DocumentHandler):
    """Microsoft PowerPoint handler — extracts text from all slides."""

    def extract_text(self, file_path: Path) -> str:
        """Extract text from PPTX file, slide by slide."""
        if not PPTX_AVAILABLE:
            raise RuntimeError("python-pptx not available")

        try:
            prs = Presentation(file_path)
            parts: list[str] = []

            for idx, slide in enumerate(prs.slides, 1):
                slide_texts: list[str] = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            txt = para.text.strip()
                            if txt:
                                slide_texts.append(txt)
                    # Also extract text from tables
                    if shape.has_table:
                        for row in shape.table.rows:
                            for cell in row.cells:
                                txt = cell.text.strip()
                                if txt:
                                    slide_texts.append(txt)
                if slide_texts:
                    parts.append(f"--- Slajd {idx} ---\n" + "\n".join(slide_texts))

            text = "\n\n".join(parts)
            logger.info(
                f"Extracted {len(text)} chars from PPTX "
                f"({len(prs.slides)} slides, {file_path.name})"
            )
            return text

        except Exception as e:
            logger.error(f"Failed to extract text from PPTX: {e}")
            raise

    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        translator=None,
        source_lang: str = None,
        target_lang: str = None,
        **kwargs,
    ):
        """
        Save translated PPTX — clones the original presentation and replaces
        text in every shape while preserving slide layout, images, formatting.
        """
        if not PPTX_AVAILABLE:
            raise RuntimeError("python-pptx not available")

        try:
            prs = Presentation(original_path)

            if translator and source_lang and target_lang:
                # Translate shape-by-shape preserving formatting
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for para in shape.text_frame.paragraphs:
                                full = para.text.strip()
                                if not full:
                                    continue
                                translated = translator.translate_text(
                                    full, source_lang, target_lang
                                )
                                # Overwrite first run, clear the rest
                                if para.runs:
                                    para.runs[0].text = translated
                                    for run in para.runs[1:]:
                                        run.text = ""
                        if shape.has_table:
                            for row in shape.table.rows:
                                for cell in row.cells:
                                    txt = cell.text.strip()
                                    if txt:
                                        translated = translator.translate_text(
                                            txt, source_lang, target_lang
                                        )
                                        cell.text = translated
                prs.save(output_path)
            else:
                # Fallback: save plain text as DOCX
                if DOCX_AVAILABLE:
                    from docx import Document as DocxDoc

                    doc = DocxDoc()
                    for para_text in translated_text.split("\n\n"):
                        if para_text.strip():
                            doc.add_paragraph(para_text)
                    doc.save(output_path.with_suffix(".docx"))
                else:
                    with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
                        f.write(translated_text)

            logger.info(f"Saved PPTX translation to {output_path}")

        except Exception as e:
            logger.error(f"Failed to save PPTX translation: {e}")
            raise


# Factory function
def get_handler(file_extension: str) -> Optional[DocumentHandler]:
    """
    Get appropriate handler for file type
    
    Args:
        file_extension: File extension (e.g., '.txt', '.docx')
        
    Returns:
        DocumentHandler instance or None if unsupported
    """
    handlers = {
        '.txt': TXTHandler,
        '.docx': DOCXHandler,
        '.pdf': PDFHandler,
        '.srt': SRTHandler,
        '.pptx': PPTXHandler,
    }

    ext = file_extension.lower()
    handler_class = handlers.get(ext)

    if handler_class:
        # Check if dependencies are available
        if ext == '.docx' and not DOCX_AVAILABLE:
            logger.error("DOCX handler requested but python-docx not available")
            return None
        if ext == '.pdf' and not PDF_AVAILABLE:
            logger.error("PDF handler requested but pdfplumber not available")
            return None
        if ext == '.pptx' and not PPTX_AVAILABLE:
            logger.error("PPTX handler requested but python-pptx not available")
            return None
        
        return handler_class()
    
    logger.warning(f"No handler available for extension: {ext}")
    return None


# Convenience function
def extract_text_from_file(file_path: Path) -> str:
    """
    Extract text from any supported file format
    
    Args:
        file_path: Path to file
        
    Returns:
        Extracted text
        
    Raises:
        ValueError: If file type not supported
        RuntimeError: If extraction fails
    """
    handler = get_handler(file_path.suffix)
    
    if not handler:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")
    
    return handler.extract_text(file_path)
