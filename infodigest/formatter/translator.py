"""Formatter translator: translate English entries to Chinese using Google Translate.

No LLM — uses deterministic translation API. Translated text is appended below
original (bilingual display), never replaces original.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# In-memory cache: hash(text) -> translated_text
_cache: dict[str, str] = {}
_translator = None
_cache_file: Path | None = None


def _get_translator(source: str = "en", target: str = "zh-CN"):
    global _translator
    if _translator is None:
        try:
            from deep_translator import GoogleTranslator
            _translator = GoogleTranslator(source=source, target=target)
        except ImportError:
            log.warning("deep-translator not installed; translation disabled")
            return None
    return _translator


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_cache(cache_path: Path | None = None) -> None:
    """Load translation cache from disk."""
    global _cache, _cache_file
    _cache_file = cache_path
    if cache_path and cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cache = {}


def save_cache() -> None:
    """Save translation cache to disk."""
    if _cache_file and _cache:
        _cache_file.parent.mkdir(parents=True, exist_ok=True)
        with _cache_file.open("w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)


def translate_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "zh-CN",
) -> str | None:
    """Translate text. Returns translated text, or None on failure.
    Uses in-memory cache to avoid redundant API calls."""
    if not text or not text.strip():
        return None

    key = _text_hash(text)
    if key in _cache:
        return _cache[key]

    translator = _get_translator(source_lang, target_lang)
    if translator is None:
        return None

    # deep-translator has a 5000 char limit per call; truncate if needed
    max_chars = 4900
    input_text = text[:max_chars] if len(text) > max_chars else text

    try:
        result = translator.translate(input_text)
        if result:
            _cache[key] = result
            return result
    except Exception as exc:
        log.warning("translation failed for %s: %s", text[:50], exc)
    return None


def should_translate(source_lang: str, target_lang: str) -> bool:
    """Should we translate content from this source language?"""
    if not source_lang or not target_lang:
        return False
    # Don't translate if source == target
    src = source_lang.lower().replace("-", "").replace("_", "")
    tgt = target_lang.lower().replace("-", "").replace("_", "")
    # zh -> zh-CN, zh -> zh, etc.
    if src.startswith("zh") and tgt.startswith("zh"):
        return False
    if src == tgt:
        return False
    return True
