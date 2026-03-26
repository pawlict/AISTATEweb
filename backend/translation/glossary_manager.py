"""
Glossary Manager - manages custom terminology dictionaries
"""

import json
import logging
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class GlossaryManager:
    """Manages custom glossaries for translation"""
    
    def __init__(self, storage_path: Path = None):
        """
        Initialize glossary manager
        
        Args:
            storage_path: Path to store glossaries (default: ./glossaries/)
        """
        self.storage_path = storage_path or Path("./glossaries")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.current_glossary: Dict[str, str] = {}
    
    def set_glossary(self, glossary: Dict[str, str]):
        """
        Set current glossary
        
        Args:
            glossary: Dictionary mapping original terms to translations
        """
        self.current_glossary = glossary
        logger.info(f"Glossary set with {len(glossary)} terms")
    
    def get_glossary(self) -> Dict[str, str]:
        """Get current glossary"""
        return self.current_glossary.copy()
    
    def clear_glossary(self):
        """Clear current glossary"""
        self.current_glossary = {}
        logger.info("Glossary cleared")
    
    def save_glossary(self, name: str):
        """
        Save current glossary to file
        
        Args:
            name: Name for the glossary file
        """
        filepath = self.storage_path / f"{name}.json"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.current_glossary, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Glossary saved to {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to save glossary: {e}")
            raise
    
    def load_glossary(self, name: str):
        """
        Load glossary from file
        
        Args:
            name: Name of the glossary file (without .json)
        """
        filepath = self.storage_path / f"{name}.json"
        
        if not filepath.exists():
            raise FileNotFoundError(f"Glossary file not found: {filepath}")
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.current_glossary = json.load(f)
            
            logger.info(f"Glossary loaded from {filepath} ({len(self.current_glossary)} terms)")
            
        except Exception as e:
            logger.error(f"Failed to load glossary: {e}")
            raise
    
    def protect_terms(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Replace glossary terms with placeholders
        
        Args:
            text: Original text
            
        Returns:
            Tuple of (protected_text, placeholder_mapping)
        """
        if not self.current_glossary:
            return text, {}
        
        protected_text = text
        placeholders = {}
        
        for i, (term, translation) in enumerate(self.current_glossary.items()):
            if term in protected_text:
                placeholder = f"__GLOSS_{i}__"
                protected_text = protected_text.replace(term, placeholder)
                placeholders[placeholder] = translation
        
        logger.debug(f"Protected {len(placeholders)} terms")
        return protected_text, placeholders
    
    def restore_terms(self, text: str, placeholders: Dict[str, str]) -> str:
        """
        Restore protected terms from placeholders
        
        Args:
            text: Text with placeholders
            placeholders: Placeholder mapping
            
        Returns:
            Text with restored terms
        """
        restored_text = text
        
        for placeholder, term in placeholders.items():
            restored_text = restored_text.replace(placeholder, term)
        
        return restored_text
    
    def list_saved_glossaries(self) -> list:
        """
        List all saved glossary files
        
        Returns:
            List of glossary names (without .json extension)
        """
        files = list(self.storage_path.glob("*.json"))
        return [f.stem for f in files]
