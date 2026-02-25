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
    def inject_translated_text(original_path: Path, translated_text: str) -> bytes:
        """Replace text in original PDF with *translated_text* and return PDF bytes.

        Algorithm (per page):
        1. Extract text blocks with positions from the original via PyMuPDF.
        2. Redact (white-out) original text areas.
        3. Insert translated text into the same rectangles, auto-shrinking
           the font size when the translation is longer than the original.

        Returns raw PDF bytes ready to stream.
        """
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PyMuPDF (fitz) not available — cannot write PDF")

        import re as _re

        doc = pymupdf.open(str(original_path))

        # --- 1. Collect text-block counts per page from original ----------
        page_block_counts: list[int] = []
        for page in doc:
            blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]
            count = 0
            for b in blocks:
                if b["type"] != 0:  # skip image blocks
                    continue
                for line in b["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            count += 1
            page_block_counts.append(count)

        # --- 2. Strip page markers from translated text -------------------
        _marker_re = _re.compile(
            r"^-{2,}\s*(?:Strona|Page|strona|page)\s*\d+\s*-{2,}$",
            _re.IGNORECASE,
        )
        flat_lines: list[str] = []
        for line in translated_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if _marker_re.match(stripped):
                continue
            flat_lines.append(stripped)

        # --- 3. Map translated lines → pages by block count ---------------
        line_ptr = 0
        for page_idx, page in enumerate(doc):
            if page_idx >= len(page_block_counts):
                break
            expected = page_block_counts[page_idx]
            page_lines = flat_lines[line_ptr: line_ptr + expected]
            line_ptr += expected

            # Collect original spans with their rects
            blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]
            original_spans: list[dict] = []
            for b in blocks:
                if b["type"] != 0:
                    continue
                for line in b["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            original_spans.append(span)

            # Redact original text areas
            for span in original_spans:
                rect = pymupdf.Rect(span["bbox"])
                page.add_redact_annot(rect, fill=(1, 1, 1))  # white fill
            page.apply_redactions()

            # Insert translated text
            sp = 0
            for span in original_spans:
                if sp >= len(page_lines):
                    break
                new_text = page_lines[sp]
                sp += 1

                rect = pymupdf.Rect(span["bbox"])
                fontsize = span.get("size", 11)
                color = span.get("color", 0)
                # Normalize color: int → (r, g, b) tuple
                if isinstance(color, int):
                    r = ((color >> 16) & 0xFF) / 255.0
                    g = ((color >> 8) & 0xFF) / 255.0
                    b = (color & 0xFF) / 255.0
                    color = (r, g, b)

                # Auto-shrink font if translated text is longer
                orig_len = len(span["text"].strip())
                if orig_len > 0 and len(new_text) > orig_len:
                    ratio = orig_len / len(new_text)
                    fontsize = max(fontsize * ratio, 5)

                page.insert_textbox(
                    rect,
                    new_text,
                    fontsize=fontsize,
                    color=color,
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
