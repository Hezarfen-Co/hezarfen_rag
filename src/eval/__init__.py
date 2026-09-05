"""Faz 1.8 / OPTIMIZATION.md sub A -- degerlendirme (eval) harness'i.

  - metrics.py  deterministik metrikler (retrieval recall/precision/MRR,
                citation P/R, guardrail/fail-closed) -- LLM gerektirmez.
  - judge.py    DeepSeek-hakem metrikleri (DeepEval: faithfulness,
                answer_relevancy, answer_correctness/GEval).
  - runner.py   golden set'e karsi TAM pipeline'i kurup kosan orkestrasyon.
"""
from .metrics import (RetrievalMetrics, CitationMetrics, compute_retrieval_metrics,
                      citation_precision_recall, guardrail_pass, is_fail_closed, mean)

__all__ = ["RetrievalMetrics", "CitationMetrics", "compute_retrieval_metrics",
          "citation_precision_recall", "guardrail_pass", "is_fail_closed", "mean"]
