"""Embedding (Faz 1.2) — BGE-M3 (dense + sparse), çok dilli.

BGE-M3 mimari kararında **ADAY**tır (Türkçe kanıtı B); Türkçe benchmark'ta
baseline'larla (e5-large, TurkEmbed) yarışıp kazanınca sabitlenir (mimari §0.1).
`Embedder` arayüzü sağlayıcı-değiştirilebilir → baseline'lar sonra eklenir.
"""
from .embedder import Embedder, BGEM3Embedder, cosine_sim, cosine_matrix

__all__ = ["Embedder", "BGEM3Embedder", "cosine_sim", "cosine_matrix"]
