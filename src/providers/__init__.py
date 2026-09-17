"""LLM sağlayıcıları. Şu an: LLMClient. Arayüz: .chat(prompt) -> ChatResult(text, usage)."""
from .llm import LLMClient, ChatResult

__all__ = ["LLMClient", "ChatResult"]
