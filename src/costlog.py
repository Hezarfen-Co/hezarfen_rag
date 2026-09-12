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
import contextlib
import json
import os
import warnings
import tempfile
import time
from datetime import datetime, timezone

try:                       # POSIX
    import fcntl
except ImportError:
    fcntl = None
try:                       # Windows
    import msvcrt
except ImportError:
    msvcrt = None

from .pricing import (Usage, cost_usd, price_table_rows,
                      PRICING_UPDATED, PRICING_SOURCE, OFFPEAK_FACTOR)

# #49 (EXP-010/SEC-10 + OPS-04): bu yol SABIT bir WINDOWS yoluydu ve env
# override'i yoktu. Linux'ta goreceli cozuluyor ve calisma dizininde gercekten
# `./C:/Users/w/...` klasoru olusuyordu (olculdu) -- `.gitignore`da karsiligi
# olmadigi icin maliyet defteri (ve icindeki her sey) REPOYA SIZABILIYORDU.
# Konteynerde ise imaj katmanina yazip restart'ta kayboluyordu.
# Defterin GERCEK yeri Obsidian kasasidir ve ORADA KALIR (Kadir, 2026-09-11).
# Env ile ezilebilir olmasi sart: konteynerde/CI'da kasa yoktur ve #49'un asil
# sebebi buydu -- yol SABIT oldugu icin yazilamayan yere yaziliyordu.
# TESTLER bu degeri EZMEK ZORUNDA (bkz. tests/__init__.py): aksi halde birim
# testleri gercek maliyet defterine stub kayitlari yaziyor (olculdu: 27 satir).
OBSIDIAN_VAULT = os.path.join(
    os.path.expanduser("~"), "Masaüstü", "Obsidian Vault", "Hezarfen-Vault",
    "Hezarfen", "rag")
VAULT = os.environ.get("HEZARFEN_COST_VAULT") or OBSIDIAN_VAULT
LEDGER = os.path.join(VAULT, "runs.jsonl")
# #84: varsayilan KAPALI -- render istek yolundan cikti.
# Eski davranisi isteyen (ornek/tek kullanicili kosum) 1 yapar.
RENDER_ON_RECORD = os.environ.get("HEZARFEN_COST_RENDER", "0") not in (
    "0", "", "false", "False")
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


@contextlib.contextmanager
def _file_lock(target: str):
    """Süreçler-arası eksklüzif kilit (AUDIT EXP-007 #28): id-atama + append kritik
    bölümünü serileştirir → duplicate run_id + iç-içe append (bozuk satır) önlenir.
    fcntl (POSIX) / msvcrt (Windows); ikisi de yoksa no-op (yalnız tek-süreç güvence)."""
    lockpath = target + ".lock"
    d = os.path.dirname(lockpath)
    if d:
        os.makedirs(d, exist_ok=True)
    f = open(lockpath, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            f.seek(0)
            for _ in range(200):                    # ~10s dene (LK_LOCK zaten bloklar; NBLCK ile döngü)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                f.seek(0)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            f.close()


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


def _tail_lines(path: str, n_bytes: int = 65536) -> list[str]:
    """Dosyanın SONUNDAN en çok `n_bytes` okuyup satırlara böler.

    #84: id atamak için bütün defteri okumak O(n)'dir ve kilit ALTINDA olur —
    yani her cevap, defter büyüdükçe daha uzun süre kuyrukta bekler. Ölçüldü:
    50.000 satırda `record()` **745 ms**. id'ler artan olduğu için son satır
    yeterlidir.
    """
    if not os.path.exists(path):
        return []
    boyut = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, boyut - n_bytes))
        ham = f.read()
    if boyut > n_bytes:
        ham = ham.split(b"\n", 1)[-1]        # ilk (yarım) satırı at
    return [x for x in ham.decode("utf-8", "replace").splitlines() if x.strip()]


def _next_id_fast(ledger: str) -> str:
    """Son satırdan sıradaki id — bütün defteri okumadan.

    Bozuk/eksik son satırlara dayanıklı: geriye doğru ilk okunabilir satır
    kullanılır. Hiçbiri okunamazsa dosya tam taranır (nadir, güvenli yol).
    """
    satirlar = _tail_lines(ledger)
    for satir in reversed(satirlar):
        try:
            rid = json.loads(satir).get("run_id", "")
        except json.JSONDecodeError:
            continue
        if isinstance(rid, str) and rid.startswith("R") and rid[1:].isdigit():
            return f"R{int(rid[1:]) + 1:04d}"
    return _next_id(_load(ledger))


def record(module: str, model: str, usage: Usage, items: int = 1, *,
           tier: str = "peak", config: dict | None = None,
           quality: dict | None = None, note: str = "",
           ts: str | None = None, ledger: str = LEDGER,
           maliyet: str = MALIYET) -> dict:
    """Bir run'ı kaydet: maliyet+birim maliyet hesapla, JSONL'e ekle, Maliyet.md render et."""
    usd = cost_usd(model, usage, tier)             # saf hesap — kilidin DIŞINDA
    rec = {
        "run_id": None,                            # kilit içinde atanır (yarış önleme #28)
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
    # #84 (EXP-010/OPS-04): `os.path.dirname(path)` dizinsiz yolda "" döner ve
    # `makedirs("")` FileNotFoundError fırlatır — bu `record()` içinden gelince
    # CEVAP ÜRETİLDİKTEN SONRA 500 oluyordu (para harcanmış, cevap kaybolmuş).
    d = os.path.dirname(ledger) or "."
    os.makedirs(d, exist_ok=True)
    # KRİTİK BÖLÜM: id-atama + append tek kilit altında → eşzamanlı iki süreç
    # aynı id'yi almaz, satırlar iç-içe girmez (#28). id artık SON SATIRDAN
    # okunuyor; eskiden bütün defter kilit altında taranıyordu.
    with _file_lock(ledger):
        rec["run_id"] = _next_id_fast(ledger)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # #84: `render()` BURADAN KALDIRILDI. Her `record()` çağrısında tüm
    # `runs.jsonl` okunup `Maliyet.md` baştan yazılıyordu — her LLM cevabında,
    # her guard çağrısında, her özet parçasında. ÖLÇÜLDÜ:
    #   1.000 satır → 12,7 ms · 10.000 → 145 ms · 50.000 → **745 ms**
    # ve `flock` bunu süreçler arasında SERİLEŞTİRİYOR. 500 öğrenci × 5 soru/gün
    # = 20 günde 50.000 satır → her cevaba +0,75 s.
    # Render artık ayrı: `python -m src.costlog` (cron/CLI).
    if RENDER_ON_RECORD:
        render(ledger, maliyet)
    return rec


def record_safe(**kwargs):
    """`record()`'un ASLA fırlatmayan sarmalayıcısı — varsayılan kaydedici budur.

    #84 (EXP-010/OPS-04): telemetri hatası **cevabı düşürmemeli**. Ölçülen
    somut örnek: `os.path.dirname(path)` dizinsiz yolda `""` döndürüyor,
    `makedirs("")` `FileNotFoundError` fırlatıyor ve bu `record()` içinden
    geldiği için **cevap üretildikten SONRA HTTP 500** oluyordu — yani para
    harcanmış, LLM çağrılmış, cevap hazır ve kullanıcıya hata gidiyor.

    Guard katmanında bu sarmalama zaten vardı; üretici yollarında YOKTU.
    Aynı ilke `guard/audit.py` için de geçerli.
    """
    try:
        return record(**kwargs)
    except Exception as e:                       # noqa: BLE001
        warnings.warn(f"costlog: kayit basarisiz ({type(e).__name__}: {e}) — "
                      "cevap etkilenmedi", RuntimeWarning, stacklevel=2)
        return None


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
    # Savunmacı (AUDIT #28/#29): tablolar hard-key erişir; eksik-alanlı (geçerli-JSON
    # ama kısmi/elle-düzenlenmiş) satır tüm render'ı çökertmesin → böyle satırları
    # tablolardan ATLA (yine de _next_id bunları _load ile görür, id çakışmaz).
    _need = {"run_id", "ts", "module", "model", "tier", "items", "usage",
             "cost_usd", "unit_cost_usd"}
    runs = [r for r in _load(ledger) if isinstance(r, dict) and _need <= r.keys()]
    with open(maliyet, encoding="utf-8") as f:
        text = f.read()
    text = _replace_block(text, "PRICING", _price_table())
    text = _replace_block(text, "MODULE", _module_table(runs))
    text = _replace_block(text, "LEDGER", _ledger_table(runs))
    text = _replace_block(text, "MODELS", _models_table(runs))
    text = _replace_block(text, "STAMP",
                          f"_Son güncelleme: {_now_iso()} · toplam run: {len(runs)} · "
                          f"bu görünüm `runs.jsonl`'dan otomatik üretildi._")
    # ATOMİK yaz (AUDIT #28): temp'e yaz + os.replace → eşzamanlı render yarım/bozuk
    # Maliyet.md bırakmaz (os.replace atomiktir).
    d = os.path.dirname(maliyet) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, maliyet)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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


def main(argv=None) -> int:
    """Render CLI — #84 ile istek yolundan ÇIKARILDI, buraya taşındı.

    Eskiden `render()` her `record()` içinde koşuyordu (50.000 satırda 745 ms,
    lineer). Artık cron/elle çağrılır. Argümanlar test edilebilsin diye
    `main(argv)` biçiminde; eski `python -m src.costlog render|demo` kullanımı
    korunur.
    """
    import argparse
    ap = argparse.ArgumentParser(description="Maliyet defteri araçları")
    ap.add_argument("komut", nargs="?", default="render",
                    choices=("render", "demo"))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.komut == "demo":
        _demo()
        return 0
    ledger = a.ledger or LEDGER
    out = a.out or MALIYET
    render(ledger, out)
    print(f"Maliyet.md render edildi ({len(_load(ledger))} run) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
