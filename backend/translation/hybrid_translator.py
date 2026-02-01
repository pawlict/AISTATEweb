"""
Hybrid Translation Engine
Combines NLLB-200 (fast) with Ollama/LLaMA (context-aware)
"""

import torch
import logging
import requests
from typing import Optional, Dict, List
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

logger = logging.getLogger(__name__)


class HybridTranslator:
    """
    Hybrid translator combining NLLB and Ollama
    
    NLLB: Fast, sentence-by-sentence translation
    Ollama: Context-aware, preserves style and terminology
    """
    
    # Language codes for NLLB
    LANG_CODES_NLLB = {
        'polish': 'pol_Latn',
        'english': 'eng_Latn',
        'russian': 'rus_Cyrl',
        'belarusian': 'bel_Cyrl',
        'ukrainian': 'ukr_Cyrl',
        'chinese': 'zho_Hans'
    }
    
    # Language names for Ollama prompts
    LANG_NAMES = {
        'polish': 'Polish',
        'english': 'English',
        'russian': 'Russian',
        'belarusian': 'Belarusian',
        'ukrainian': 'Ukrainian',
        'chinese': 'Chinese'
    }
    
    def __init__(
        self,
        nllb_model: str = "facebook/nllb-200-1.3B",
        ollama_model: str = "llama3.1:8b",
        ollama_url: str = "http://localhost:11434",
        device: str = "auto"
    ):
        """
        Initialize hybrid translator
        
        Args:
            nllb_model: NLLB model name
                - facebook/nllb-200-distilled-600M (2.4GB, fastest)
                - facebook/nllb-200-1.3B (5GB, recommended)
                - facebook/nllb-200-3.3B (13GB, best quality)
            ollama_model: Ollama model name
            ollama_url: Ollama API URL
            device: 'cuda', 'cpu', or 'auto'
        """
        self.nllb_model_name = nllb_model
        self.ollama_model = ollama_model
        self.ollama_url = f"{ollama_url}/api/generate"
        
        # Detect device — respect CUDA_VISIBLE_DEVICES set by GPU RM.
        # Use "cuda" (no index) so PyTorch targets whichever GPU is visible.
        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        elif device == "cuda":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        elif device == "cpu":
            self.device = "cpu"
        else:
            # Allow explicit "cuda:1" etc.
            self.device = device

        logger.info(f"Loading NLLB model: {nllb_model}")
        logger.info(f"Device: {self.device}")
        
        # Load NLLB
        try:
            # Prefer the "slow" tokenizer for NLLB because some Transformers versions
            # do not expose `lang_code_to_id` on the Fast tokenizer wrapper.
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(nllb_model, use_fast=False)
            except Exception:
                logger.warning("Falling back to fast tokenizer for NLLB")
                self.tokenizer = AutoTokenizer.from_pretrained(nllb_model)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(nllb_model)
            
            if self.device != "cpu":
                self.model = self.model.to(self.device)
            
            logger.info("NLLB model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load NLLB model: {e}")
            raise
        
        # Translation memory (cache)
        self.translation_memory: Dict[str, str] = {}
        
        # Glossary
        self.glossary: Dict[str, str] = {}
    
    def _nllb_lang_id(self, lang_code: str) -> int:
        """Resolve NLLB language token id across different tokenizer implementations."""
        tok = self.tokenizer
        mapping = getattr(tok, "lang_code_to_id", None)
        if isinstance(mapping, dict) and lang_code in mapping:
            return int(mapping[lang_code])
    
        get_lang_id = getattr(tok, "get_lang_id", None)
        if callable(get_lang_id):
            try:
                return int(get_lang_id(lang_code))
            except Exception:
                pass
    
        # Fallback: try to resolve via token forms
        candidates = [lang_code, f"__{lang_code}__", f"<2{lang_code}>"]
        try:
            for t in (getattr(tok, "additional_special_tokens", None) or []):
                if isinstance(t, str) and (lang_code in t) and (t not in candidates):
                    candidates.append(t)
        except Exception:
            pass
    
        unk = getattr(tok, "unk_token_id", None)
        for cand in candidates:
            try:
                tid = tok.convert_tokens_to_ids(cand)
            except Exception:
                tid = None
            if tid is not None and tid != unk:
                return int(tid)
    
        raise ValueError(f"Cannot resolve NLLB language id for {lang_code!r} using tokenizer {tok.__class__.__name__}")
    
    def translate_nllb(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        max_length: int = 512,
        use_glossary: bool = False,
        glossary: Optional[Dict] = None,
        preserve_formatting: bool = True,
    ) -> str:
        """
        Fast translation using NLLB
        
        Args:
            text: Text to translate
            source_lang: Source language (polish, english, etc.)
            target_lang: Target language
            max_length: Max sequence length
            
        Returns:
            Translated text
        """
        if not text.strip():
            return text
        
        src_code = self.LANG_CODES_NLLB.get(source_lang)
        tgt_code = self.LANG_CODES_NLLB.get(target_lang)
        
        if not src_code or not tgt_code:
            raise ValueError(f"Unsupported language pair: {source_lang} -> {target_lang}")
        
        # Optional glossary protection (term dictionary)
        gloss = glossary if isinstance(glossary, dict) else None
        protected_text = text
        placeholders: Dict[str, str] = {}
        if use_glossary and gloss:
            protected_text, placeholders = self._protect_terms(protected_text, gloss, target_lang)

        # Check cache
        try:
            import json as _json
            gloss_sig = _json.dumps(gloss or {}, ensure_ascii=False, sort_keys=True)
        except Exception:
            gloss_sig = str(gloss or {})
        cache_key = f"{src_code}_{tgt_code}_{hash(protected_text)}_{int(preserve_formatting)}_{int(use_glossary)}_{hash(gloss_sig)}"
        if cache_key in self.translation_memory:
            logger.debug("Using cached translation")
            out_cached = self.translation_memory[cache_key]
            return self._restore_terms(out_cached, placeholders) if placeholders else out_cached
        
        try:
            if preserve_formatting:
                result = self._translate_preserve_formatting(
                    protected_text, src_code, tgt_code, max_length=max_length
                )
            else:
                result = self._translate_plain(protected_text, src_code, tgt_code, max_length=max_length)
            
            # Cache result
            self.translation_memory[cache_key] = result
            return self._restore_terms(result, placeholders) if placeholders else result
            
        except Exception as e:
            logger.error(f"NLLB translation failed: {e}")
            raise
    
    def _translate_chunk_nllb(
        self,
        text: str,
        src_code: str,
        tgt_code: str,
        max_length: int
    ) -> str:
        """Translate single chunk with NLLB"""
        if hasattr(self.tokenizer, "src_lang"):
            self.tokenizer.src_lang = src_code
        # Tokenize
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length
        )
        
        if self.device != "cpu":
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        # Generate translation
        translated_tokens = self.model.generate(
            **inputs,
            forced_bos_token_id=self._nllb_lang_id(tgt_code),
            max_length=max_length,
            num_beams=5,
            early_stopping=True
        )
        
        # Decode
        translated_text = self.tokenizer.decode(
            translated_tokens[0],
            skip_special_tokens=True
        )
        
        return translated_text

    def _translate_plain(self, text: str, src_code: str, tgt_code: str, max_length: int = 512) -> str:
        """Translate text with basic chunking (may lose some formatting)."""
        if not text.strip():
            return text

        # Split into chunks if too long
        if len(text.split()) > 400:
            chunks = self._split_text(text, max_words=400)
            translated_chunks = []
            for chunk in chunks:
                translated_chunks.append(self._translate_chunk_nllb(chunk, src_code, tgt_code, max_length))
            return ' '.join(translated_chunks)

        return self._translate_chunk_nllb(text, src_code, tgt_code, max_length)

    def _translate_preserve_formatting(self, text: str, src_code: str, tgt_code: str, max_length: int = 512) -> str:
        """Translate while preserving newlines / list prefixes as much as possible."""
        if not text:
            return text

        import re

        # Split by blank lines but keep separators
        parts = re.split(r'(\n\s*\n+)', text)
        out_parts: List[str] = []

        bullet_re = re.compile(r'^(\s*)([-*•]+|\d+[\.)]|[A-Za-z][\.)])\s+(.*)$')

        for part in parts:
            if not part:
                continue
            if re.fullmatch(r'\n\s*\n+', part):
                out_parts.append(part)
                continue

            # Process line-by-line, preserving newline characters
            lines = part.splitlines(True)
            out_lines: List[str] = []
            for line in lines:
                if line.strip() == '':
                    out_lines.append(line)
                    continue

                # Preserve trailing newline
                nl = '\n' if line.endswith('\n') else ''
                base = line[:-1] if nl else line

                m = bullet_re.match(base)
                if m:
                    indent, marker, content = m.group(1), m.group(2), m.group(3)
                    translated = self._translate_plain(content, src_code, tgt_code, max_length=max_length)
                    out_lines.append(f"{indent}{marker} {translated}{nl}")
                else:
                    # Preserve leading/trailing whitespace
                    m2 = re.match(r'^(\s*)(.*?)(\s*)$', base)
                    if m2:
                        lead, content, trail = m2.group(1), m2.group(2), m2.group(3)
                        translated = self._translate_plain(content, src_code, tgt_code, max_length=max_length)
                        out_lines.append(f"{lead}{translated}{trail}{nl}")
                    else:
                        translated = self._translate_plain(base, src_code, tgt_code, max_length=max_length)
                        out_lines.append(f"{translated}{nl}")

            out_parts.append(''.join(out_lines))

        return ''.join(out_parts)

    def _protect_terms(self, text: str, glossary: Dict, target_lang: str) -> tuple[str, Dict[str, str]]:
        """Replace glossary terms with stable placeholders."""
        if not glossary:
            return text, {}

        protected = text
        placeholders: Dict[str, str] = {}

        # Deterministic order for stable placeholders
        items = list(glossary.items())
        try:
            items.sort(key=lambda kv: str(kv[0]))
        except Exception:
            pass

        for i, (term, val) in enumerate(items):
            term = str(term)
            if not term:
                continue

            repl: Optional[str] = None
            if isinstance(val, dict):
                repl = val.get(target_lang) or val.get('default') or val.get('all') or val.get('any')
            elif isinstance(val, str):
                repl = val
            elif val is None:
                repl = term
            else:
                repl = str(val)

            if repl is None:
                repl = term

            if term in protected:
                ph = f"[[GLOSS{i}]]"
                protected = protected.replace(term, ph)
                placeholders[ph] = str(repl)

        return protected, placeholders

    def _restore_terms(self, text: str, placeholders: Dict[str, str]) -> str:
        """Restore glossary placeholders to desired output terms."""
        if not placeholders:
            return text
        out = text
        for ph, repl in placeholders.items():
            out = out.replace(ph, repl)
        return out
    
    def translate_ollama(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        use_glossary: bool = True
    ) -> str:
        """
        Context-aware translation using Ollama
        
        Args:
            text: Text to translate
            source_lang: Source language
            target_lang: Target language
            use_glossary: Whether to use custom glossary
            
        Returns:
            Translated text
        """
        if not text.strip():
            return text
        
        src_name = self.LANG_NAMES.get(source_lang, source_lang)
        tgt_name = self.LANG_NAMES.get(target_lang, target_lang)
        
        # Build prompt
        system_prompt = f"""You are a professional translator. Translate the following text from {src_name} to {tgt_name}.

Rules:
1. Preserve the original meaning, style, and tone
2. Maintain formatting (paragraphs, line breaks)
3. Use appropriate terminology for the subject matter
4. Consider the full context when translating"""
        
        if use_glossary and self.glossary:
            terms_list = ', '.join(self.glossary.keys())
            system_prompt += f"\n5. Do NOT translate these terms: {terms_list}"
        
        prompt = f"{system_prompt}\n\nText to translate:\n{text}\n\nTranslation:"
        
        try:
            logger.info(f"Translating with Ollama ({source_lang} -> {target_lang})")
            
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,  # Lower for more consistent translation
                        "top_p": 0.9,
                    }
                },
                timeout=300  # 5 minutes max
            )
            
            if response.status_code == 200:
                result = response.json()
                translated = result.get("response", "").strip()
                
                if translated:
                    logger.info(f"Ollama translation completed ({len(translated)} chars)")
                    return translated
                else:
                    logger.error("Empty response from Ollama")
                    raise RuntimeError("Empty translation from Ollama")
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                raise RuntimeError(f"Ollama API error: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out")
            raise RuntimeError("Translation timeout")
        except Exception as e:
            logger.error(f"Ollama translation failed: {e}")
            raise
    
    def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        mode: str = "accurate"
    ) -> str:
        """
        Translate text using specified mode
        
        Args:
            text: Text to translate
            source_lang: Source language
            target_lang: Target language
            mode: 'fast' (NLLB) or 'accurate' (Ollama)
            
        Returns:
            Translated text
        """
        if mode == "fast":
            return self.translate_nllb(text, source_lang, target_lang)
        else:
            return self.translate_ollama(text, source_lang, target_lang)
    
    def set_glossary(self, glossary: Dict[str, str]):
        """Set custom glossary for term protection"""
        self.glossary = glossary
        logger.info(f"Glossary updated with {len(glossary)} terms")
    
    def clear_memory(self):
        """Clear translation memory cache"""
        self.translation_memory.clear()
        logger.info("Translation memory cleared")
    
    def _split_text(self, text: str, max_words: int = 400) -> List[str]:
        """Split text into chunks by sentences"""
        import re
        
        # Split by sentence endings
        sentences = re.split(r'([.!?]+\s+)', text)
        
        chunks = []
        current_chunk = ""
        current_words = 0
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            separator = sentences[i+1] if i+1 < len(sentences) else ""
            
            sentence_words = len(sentence.split())
            
            if current_words + sentence_words > max_words and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sentence + separator
                current_words = sentence_words
            else:
                current_chunk += sentence + separator
                current_words += sentence_words
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        logger.debug(f"Split text into {len(chunks)} chunks")
        return chunks
