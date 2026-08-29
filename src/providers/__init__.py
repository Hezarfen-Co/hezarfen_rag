"""LLM sağlayıcıları. Şu an: DeepSeek. Arayüz: .chat(prompt) -> ChatResult(text, usage)."""
from .deepseek import DeepSeek, ChatResult

__all__ = ["DeepSeek", "ChatResult"]
