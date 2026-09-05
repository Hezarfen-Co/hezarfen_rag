"""Faz 1.7a — kaynak-sınırlı üretim + atıf (kaynak yer bulma)."""
from src.generate.prompt import ABSTAIN_SENTENCE, build_grounded_prompt
from src.generate.generator import Generator, GroundedAnswer, build_span_meta

__all__ = ["Generator", "GroundedAnswer", "build_grounded_prompt", "build_span_meta",
          "ABSTAIN_SENTENCE"]
