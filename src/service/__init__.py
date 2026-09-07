"""Faz — Servis katmanı (#2): transport-BAĞIMSIZ RAG isteği işleyici (handler).
QUIC-köprü VEYA HTTP bunu sarar (D3 kararı transport'a kalır; iş mantığı burada)."""
from .handler import RagService

__all__ = ["RagService"]
