"""Chunking (Faz 1.1) — CanonicalDoc birimlerinden çok-temsilli chunk.

çocuk (150-300 tok, normal QA) + üst (700-1500 tok, bağlam genişletme). Her chunk
kaynak birimlerin **span-id**'lerini taşır (atıf/provenance korunur). Atomik önerme
temsili LLM gerektirir → Faz 1 sonrası (API gelince). Bkz. mimari §2.
"""
from .chunker import Chunk, chunk_document, approx_tokens

__all__ = ["Chunk", "chunk_document", "approx_tokens"]
