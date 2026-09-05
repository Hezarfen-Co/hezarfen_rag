"""Özet ÇIKARMA mimarisi — soru-cevaptan (src/generate/) AYRI: kapsam-tabanlı,
deterministik (retrieval KULLANMAYAN) kaynak seçimi + DETAYLI, yapılandırılmış,
atıflı ("kanıtlı") özet üretimi. Bkz. scope.py / prompt.py / summarizer.py."""
from .scope import resolve_scope
from .prompt import build_summary_prompt, NO_CONTENT_SENTENCE
from .summarizer import Summarizer, GroundedSummary

__all__ = ["Summarizer", "GroundedSummary", "resolve_scope", "build_summary_prompt",
          "NO_CONTENT_SENTENCE"]
