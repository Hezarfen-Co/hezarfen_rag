"""Maliyet defteri — her deneyin adım adım, profesyonel kaydı.

METOT (kafa karışıklığı olmasın diye tek kural):
  * TEK DOĞRULUK KAYNAĞI = `runs.jsonl` (append-only, Obsidian klasöründe).
  * `Maliyet.md` = insan görünümü; runs.jsonl'dan OTOMATİK üretilir.
    Maliyet.md'de yalnız `<!-- AUTO:* -->` blokları makine tarafından yazılır;
    geri kalan (ilkeler, fiyat tablosu, tanımlar) ELLE yazılır ve korunur.
  * Her LLM işi bir "run": modül (özet/soru/chat...), model, token, MALİYET,
    BİRİM MALİYET (maliyet/adet), ve "NE DEĞİŞTİ → maliyet etkisi" notu.

Kullanım (koddan):
    from src.costlog import record
    record(module="ozet", model="deepseek-chat", usage=r.usage, items=10,
           note="chunk 800→500 → maliyet %18 arttı, faithfulness +0.04")

CLI:
    python -m src.costlog render     # Maliyet.md'yi runs.jsonl'dan yeniden üret
    python -m src.costlog demo       # örnek satırlar ekle (sonra sil)
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

from .pricing import (Usage, cost_usd, price_table_rows,
                      PRICING_UPDATED, PRICING_SOURCE, OFFPEAK_FACTOR)

VAULT = r"C:/Users/w/Documents/Hezarfen/rag"
LEDGER = os.path.join(VAULT, "runs.jsonl")
MALIYET = os.path.join(VAULT, "Maliyet.md")

# Modül = ürünün bir yeteneği (birim maliyeti ayrı izlenir).
MODULES = {
    "chat":         "Kaynakla konuşma (RAG cevap)",
    "ozet":         "Özet üretimi",
    "soru-uret":    "Kaynaktan soru üretimi",
    "benzer-soru":  "Benzer soru üretimi",
    "embedding":    "Embedding (indeksleme)",
    "retrieval":    "Retrieval/rerank",
    "diger":        "Diğer",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(ledger: str = LEDGER) -> list[dict]:
    if not os.path.exists(ledger):
        return []
    out = []
    with open(ledger, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # AUDIT EXP-007: TEK bozuk/yarım satır (ör. eşzamanlı append artığı)
                # tüm defteri okunamaz kılmasın — o satırı atla+uyar, gerisini oku.
                import warnings
                warnings.warn(f"costlog: bozuk satır atlandı: {line[:80]!r}", stacklevel=2)
    return out


def _next_id(runs: list[dict]) -> str:
    n = 0
    for r in runs:
        rid = r.get("run_id", "")
        if rid.startswith("R") and rid[1:].isdigit():
            n = max(n, int(rid[1:]))
    return f"R{n + 1:04d}"


def record(module: str, model: str, usage: Usage, items: int = 1, *,
           tier: str = "peak", config: dict | None = None,
           quality: dict | None = None, note: str = "",
           ts: str | None = None, ledger: str = LEDGER,
           maliyet: str = MALIYET) -> dict:
    """Bir run'ı kaydet: maliyet+birim maliyet hesapla, JSONL'e ekle, Maliyet.md render et."""
    runs = _load(ledger)
    usd = cost_usd(model, usage, tier)
    rec = {
        "run_id": _next_id(runs),
        "ts": ts or _now_iso(),
        "module": module,
        "model": model,
        "tier": tier,
        "items": items,
        "config": config or {},
        "usage": {"in_hit": usage.input_cache_hit, "in_miss": usage.input_cache_miss,
                  "out": usage.output, "reasoning": usage.reasoning},
        "cost_usd": round(usd, 6),
        "unit_cost_usd": round(usd / items, 6) if items else round(usd, 6),
        "quality": quality or {},
        "note": note,
    }
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    render(ledger, maliyet)
    return rec


# ----------------------------- render (AUTO bloklar) -----------------------------

def _usd(x: float) -> str:
    return f"${x:,.6f}"


def _fmt_int(x) -> str:
    return f"{int(x):,}"


def _module_table(runs: list[dict]) -> str:
    by = {}
    for r in runs:
        by.setdefault(r["module"], []).append(r)
    lines = ["| Modül | Run | Son birim maliyet | En iyi (min) | 1000 adet ~ | Son not |",
             "|---|---|---|---|---|---|"]
    for m in MODULES:
        rs = by.get(m)
        if not rs:
            continue
        rs_sorted = sorted(rs, key=lambda r: r["run_id"])
        last = rs_sorted[-1]
        best = min(r["unit_cost_usd"] for r in rs)
        proj = last["unit_cost_usd"] * 1000
        note = (last.get("note") or "").replace("|", "/")[:60]
        lines.append(f"| **{MODULES[m]}** | {len(rs)} | {_usd(last['unit_cost_usd'])} "
                     f"| {_usd(best)} | {_usd(proj)} | {note} |")
    if len(lines) == 2:
        lines.append("| _(henüz run yok)_ | | | | | |")
    return "\n".join(lines)


def _ledger_table(runs: list[dict]) -> str:
    lines = ["| Run | Tarih | Modül | Model | Tier | Adet | Giriş(hit/miss) | Çıkış | Maliyet | Birim | Ne değişti → maliyet etkisi |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(runs, key=lambda r: r["run_id"]):
        u = r["usage"]
        note = (r.get("note") or "").replace("|", "/")
        lines.append(
            f"| {r['run_id']} | {r['ts'][:10]} | {r['module']} | {r['model']} | {r['tier']} "
            f"| {r['items']} | {_fmt_int(u['in_hit'])}/{_fmt_int(u['in_miss'])} | {_fmt_int(u['out'])} "
            f"| {_usd(r['cost_usd'])} | {_usd(r['unit_cost_usd'])} | {note} |")
    if len(lines) == 2:
        lines.append("| _(henüz run yok — ilk deneyde otomatik dolar)_ | | | | | | | | | | |")
    return "\n".join(lines)


def _models_table(runs: list[dict]) -> str:
    by = {}
    for r in runs:
        b = by.setdefault(r["model"], {"runs": 0, "cost": 0.0, "in": 0, "out": 0})
        b["runs"] += 1
        b["cost"] += r["cost_usd"]
        b["in"] += r["usage"]["in_hit"] + r["usage"]["in_miss"]
        b["out"] += r["usage"]["out"]
    lines = ["| Model | Run | Toplam token (giriş/çıkış) | Toplam maliyet |",
             "|---|---|---|---|"]
    for m, b in sorted(by.items()):
        lines.append(f"| {m} | {b['runs']} | {_fmt_int(b['in'])}/{_fmt_int(b['out'])} | {_usd(b['cost'])} |")
    if len(lines) == 2:
        lines.append("| _(henüz run yok)_ | | | |")
    return "\n".join(lines)


def _price_table() -> str:
    lines = [f"> Kaynak: {PRICING_SOURCE} · alındı: **{PRICING_UPDATED}** · "
             f"off-peak = peak × {OFFPEAK_FACTOR} · **güncelle: `src/pricing.py`**",
             "",
             "| Model | Giriş cache-hit | Giriş cache-miss | Çıkış | (off-peak) hit/miss/çıkış |",
             "|---|---|---|---|---|"]
    for r in price_table_rows():
        lines.append(
            f"| {r['model']} | ${r['in_hit']:.3f} | ${r['in_miss']:.3f} | ${r['out']:.3f} "
            f"| ${r['in_hit_off']:.3f} / ${r['in_miss_off']:.3f} / ${r['out_off']:.3f} |")
    lines.append("")
    lines.append("_USD / 1M token. Peak = standart; off-peak = indirimli pencere (UTC saatini doğrula)._")
    return "\n".join(lines)


def _replace_block(text: str, name: str, body: str) -> str:
    start, end = f"<!-- AUTO:{name}:START -->", f"<!-- AUTO:{name}:END -->"
    if start not in text or end not in text:
        return text  # marker yoksa dokunma
    pre = text.split(start)[0]
    post = text.split(end, 1)[1]
    return f"{pre}{start}\n{body}\n{end}{post}"


def render(ledger: str = LEDGER, maliyet: str = MALIYET) -> None:
    """runs.jsonl'dan Maliyet.md'nin AUTO bloklarını yeniden üret."""
    if not os.path.exists(maliyet) or os.path.getsize(maliyet) == 0:
        _init_maliyet(maliyet)
    runs = _load(ledger)
    with open(maliyet, encoding="utf-8") as f:
        text = f.read()
    text = _replace_block(text, "PRICING", _price_table())
    text = _replace_block(text, "MODULE", _module_table(runs))
    text = _replace_block(text, "LEDGER", _ledger_table(runs))
    text = _replace_block(text, "MODELS", _models_table(runs))
    text = _replace_block(text, "STAMP",
                          f"_Son güncelleme: {_now_iso()} · toplam run: {len(runs)} · "
                          f"bu görünüm `runs.jsonl`'dan otomatik üretildi._")
    with open(maliyet, "w", encoding="utf-8") as f:
        f.write(text)


def _init_maliyet(path: str) -> None:
    """Boş Maliyet.md'ye profesyonel iskeleti yaz (AUTO marker'larıyla)."""
    from ._cost_template import TEMPLATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)


# ----------------------------- CLI -----------------------------

def _demo():
    """Örnek satırlar (metodu görmek için — sonra runs.jsonl'dan sil)."""
    record(module="ozet", model="deepseek-chat",
           usage=Usage(input_cache_hit=2000, input_cache_miss=18000, output=3200, reasoning=0),
           items=10, config={"chunk": 800, "top_k": 5, "rerank": None, "prompt": "v1"},
           quality={"faithfulness": 0.88}, note="(ÖRNEK) baseline: 10 özet, rerank yok")
    record(module="ozet", model="deepseek-chat",
           usage=Usage(input_cache_hit=6000, input_cache_miss=14000, output=3000, reasoning=0),
           items=10, config={"chunk": 500, "top_k": 5, "rerank": "bge", "prompt": "v1"},
           quality={"faithfulness": 0.92},
           note="(ÖRNEK) chunk 800→500 + rerank açıldı → maliyet düştü (cache↑), faithfulness +0.04")
    print("2 örnek run eklendi + Maliyet.md render edildi. (runs.jsonl'dan silerek temizleyebilirsin.)")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "render":
        render(); print(f"Maliyet.md render edildi ({len(_load())} run).")
    elif cmd == "demo":
        _demo()
    else:
        print(f"bilinmeyen komut: {cmd} (render | demo)")
