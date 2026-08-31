"""Curriculum graph — deterministik müfredat omurgası (sınıf→ders→ünite→kazanım).

Kaynak: her dersin `data/.../kazanimlar.json`. Retrieval metadata filtresi ve
(sonra) soru–kazanım eşlemesi için. LLM'in çıkardığı ilişkiler buraya DOĞRUDAN
eklenmez (candidate_edge + öğretmen onayı — bkz. [[mimari]] §GraphRAG)."""
from .graph import Kazanim, CurriculumGraph, parse_kod, load, load_from_vault

__all__ = ["Kazanim", "CurriculumGraph", "parse_kod", "load", "load_from_vault"]
