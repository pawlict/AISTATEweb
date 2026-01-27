"""
Language detection for translation module
"""

import logging
from typing import Optional

try:
    from langdetect import detect, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

logger = logging.getLogger(__name__)

# Mapping from langdetect codes to our language names
LANG_CODE_MAP = {
    'pl': 'polish',
    'en': 'english',
    'ru': 'russian',
    'be': 'belarusian',
    'uk': 'ukrainian',
    'zh-cn': 'chinese',
    'zh-tw': 'chinese',
}


def detect_language(text: str) -> Optional[str]:
    """
    Detect language of given text
    
    Args:
        text: Text to analyze
        
    Returns:
        Language name (polish, english, etc.) or None if detection fails
    """
    if not LANGDETECT_AVAILABLE:
        logger.warning("langdetect not available, cannot detect language")
        return None
    
    if not text or len(text.strip()) < 10:
        logger.warning("Text too short for reliable detection")
        return None
    
    try:
        detected_code = detect(text)
        language = LANG_CODE_MAP.get(detected_code)
        
        if language:
            logger.info(f"Detected language: {language} (code: {detected_code})")
            return language
        else:
            logger.warning(f"Detected code '{detected_code}' not in supported languages")
            return None
            
    except LangDetectException as e:
        logger.error(f"Language detection failed: {e}")
        return None
