"""
Text summarizer using Ollama/LLaMA
"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.1:8b"


def generate_summary(
    text: str,
    language: str = "english",
    detail_level: int = 5,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_URL
) -> Optional[str]:
    """
    Generate summary of translated text using Ollama
    
    Args:
        text: Text to summarize
        language: Target language for summary
        detail_level: 1-10, where 1 is very brief, 10 is very detailed
        model: Ollama model to use
        ollama_url: Ollama API URL
        
    Returns:
        Generated summary or None if failed
    """
    if not text or len(text.strip()) < 50:
        logger.warning("Text too short to summarize")
        return None
    
    # Adjust prompt based on detail level
    if detail_level <= 3:
        length_instruction = "very brief (1-2 sentences)"
    elif detail_level <= 6:
        length_instruction = "moderate (3-5 sentences)"
    else:
        length_instruction = "detailed (1-2 paragraphs)"
    
    # Language-specific instruction
    lang_names = {
        'polish': 'Polish',
        'english': 'English',
        'russian': 'Russian',
        'belarusian': 'Belarusian',
        'ukrainian': 'Ukrainian',
        'chinese': 'Chinese'
    }
    
    target_lang = lang_names.get(language, 'English')
    
    prompt = f"""Analyze the following text and provide a {length_instruction} summary in {target_lang}.

Focus on:
- Main topic and key points
- Important findings or conclusions
- Actionable information

Text to summarize:
{text}

Summary:"""
    
    try:
        logger.info(f"Generating summary (detail level: {detail_level}, language: {language})")
        
        response = requests.post(
            ollama_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            },
            timeout=120  # 2 minutes max
        )
        
        if response.status_code == 200:
            result = response.json()
            summary = result.get("response", "").strip()
            
            if summary:
                logger.info(f"Summary generated successfully ({len(summary)} chars)")
                return summary
            else:
                logger.error("Empty summary received from Ollama")
                return None
        else:
            logger.error(f"Ollama API error: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out")
        return None
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return None


def generate_bullet_summary(
    text: str,
    language: str = "english",
    num_points: int = 5,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_URL
) -> Optional[str]:
    """
    Generate bullet-point summary
    
    Args:
        text: Text to summarize
        language: Target language
        num_points: Number of bullet points (3-10)
        model: Ollama model
        ollama_url: Ollama API URL
        
    Returns:
        Bullet-point summary or None
    """
    lang_names = {
        'polish': 'Polish',
        'english': 'English',
        'russian': 'Russian',
        'belarusian': 'Belarusian',
        'ukrainian': 'Ukrainian',
        'chinese': 'Chinese'
    }
    
    target_lang = lang_names.get(language, 'English')
    
    prompt = f"""Create exactly {num_points} bullet points summarizing the key information from this text in {target_lang}.

Format each point as:
• Point 1
• Point 2
etc.

Text:
{text}

Summary:"""
    
    try:
        response = requests.post(
            ollama_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            summary = result.get("response", "").strip()
            return summary if summary else None
        else:
            return None
            
    except Exception as e:
        logger.error(f"Bullet summary generation failed: {e}")
        return None
