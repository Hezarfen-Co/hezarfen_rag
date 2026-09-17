"""hezarfen_rag — RAG servisi (yapım aşamasında).

Şu an yalnız maliyet altyapısı hazır:
  - pricing.py         DeepSeek fiyat tablosu + maliyet hesabı
  - providers/llm.py  DeepSeek LLM sağlayıcı (token usage döndürür)
  - costlog.py         run kaydı + Maliyet.md otomatik render (Obsidian)
RAG boru hattı (chunk/embed/retrieve/generate) henüz yazılmadı — bkz. gorevler.md.
"""
