"""Faz 1.7b — guardrail/güvenlik katmanı (girdi + rol + çıktı).

Bkz. input_guard.py / roles.py / output_guard.py docstring'leri için gerekçe
(RES-002 §2) ve dürüst sınırlar (regex/kalıp tabanlı — TEK savunma DEĞİL)."""
from .input_guard import GuardVerdict, check_input
from .output_guard import check_output
from .roles import Role, RoleContext, can_access

__all__ = ["GuardVerdict", "check_input", "check_output",
          "Role", "RoleContext", "can_access"]
