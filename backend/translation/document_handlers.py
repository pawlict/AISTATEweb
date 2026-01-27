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
    """PDF document handler"""
    
    def extract_text(self, file_path: Path) -> str:
        """Extract text from PDF file using pdfplumber"""
        if not PDF_AVAILABLE:
            raise RuntimeError("pdfplumber not available")
        
        try:
            text_parts = []
            
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                        logger.debug(f"Extracted page {i}/{len(pdf.pages)}")
            
            text = '\n\n'.join(text_parts)
            logger.info(f"Extracted {len(text)} characters from PDF ({len(text_parts)} pages)")
            return text
            
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {e}")
            raise
    
    def save_translated(
        self,
        original_path: Path,
        translated_text: str,
        output_path: Path,
        **kwargs
    ):
        """
        Save translated text to TXT file (PDF generation is complex)
        
        Note: For production, consider using reportlab for PDF generation
        """
        # Simple approach: save as TXT
        txt_output = output_path.with_suffix('.txt')
        with open(txt_output, 'w', encoding='utf-8') as f:
            f.write(translated_text)
        
        logger.info(f"Saved PDF translation as TXT: {txt_output}")
        logger.warning("PDF → PDF translation requires reportlab library")


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
