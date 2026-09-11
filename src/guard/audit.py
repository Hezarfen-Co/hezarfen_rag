"""#49 — güvenlik olay kaydı (maliyet defterinden AYRI, erişimi kısıtlı).

NEDEN (EXP-010/SEC-10): `llm_classifier` güvenlik kararını `cat=self_harm` gibi
bir etiketle **maliyet defterine** yazıyordu. O defter (`runs.jsonl` +
`Maliyet.md`) şifresiz, genel erişimli ve raporlama amaçlı bir dosya. Ama
"bu kullanıcı self_harm kategorisinde bir soru sordu" bilgisi, **reşit olmayan
bir kişiye ait özel nitelikli (sağlık) veri çıkarımıdır** (KVKK m.6).

Bu olay kaydı yine de GEREKLİ: güvenlik katmanının çalışıp çalışmadığını
ölçmek, kırmızı-takım sonuçlarını doğrulamak ve bir olay sonrası inceleme
yapmak için lazım. Çözüm kaydı silmek değil, **ayırmak**:

- ayrı dosya, `0600` izinle (yalnız servis kullanıcısı okur)
- **sorgu metni ASLA yazılmaz** — yalnız uzunluk + kısa hash
- kullanıcı kimliği yazılmaz; çağıran isterse kendi ürettiği opak bir
  `oturum_hash` verir (kimliğe geri götürülemez)
- **saklama süresi**: `HEZARFEN_AUDIT_RETENTION_DAYS` (varsayılan 30);
  her yazımda süresi dolmuş satırlar atılır
- varsayılan KAPALI: `HEZARFEN_AUDIT_PATH` verilmezse hiçbir şey yazılmaz
  (veri minimizasyonu — açıkça istenmediyse toplama)

DÜRÜST SINIR: bu dosya-tabanlı basit bir kayıttır, tam bir denetim altyapısı
değil. Üretimde erişim kontrolü + silme SLA'sı + şifreleme operasyon
sorumluluğudur (bkz. #85 trace/sink işi).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone

AUDIT_PATH = os.environ.get("HEZARFEN_AUDIT_PATH")      # None -> kayıt KAPALI
RETENTION_DAYS = int(os.environ.get("HEZARFEN_AUDIT_RETENTION_DAYS", "30"))


def query_fingerprint(query: str | None) -> str:
    """Sorgunun içeriğini ifşa etmeyen, tekrar-tespitine yeten kısa parmak izi."""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:12]


def _prune(rows: list[dict], now: float) -> list[dict]:
    if RETENTION_DAYS <= 0:
        return rows
    cutoff = now - RETENTION_DAYS * 86400
    return [r for r in rows if float(r.get("ts", 0)) >= cutoff]


def record_safety_event(*, category: str, action: str, layer: str,
                        query: str | None = None, oturum_hash: str | None = None,
                        path: str | None = None) -> bool:
    """Bir güvenlik kararını kaydeder. Döner: yazıldı mı.

    `query` YALNIZ uzunluk + hash üretmek için kullanılır; metin yazılmaz.
    `oturum_hash` çağıranın ürettiği opak değerdir (kimlik DEĞİL) — verilmezse
    hiç yazılmaz.

    Hata durumunda sessizce False döner: telemetri hatası ASLA bir cevabı
    düşürmemeli (aynı ilke `costlog` için #M4-10'da da geçerli).
    """
    target = path or AUDIT_PATH
    if not target:
        return False
    now = time.time()
    row = {
        "ts": now,
        "utc": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "layer": layer,               # "regex" | "llm" | "degraded" | "output"
        "action": action,             # "refuse" | "allow"
        "category": category or "",
        "q_len": len(query or ""),
        "q_hash": query_fingerprint(query),
    }
    if oturum_hash:
        row["oturum_hash"] = str(oturum_hash)[:32]
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        rows = []
        if os.path.exists(target):
            with open(target, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            continue        # bozuk satır kaydı düşürmez
        rows = _prune(rows, now)
        rows.append(row)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, target)
        try:
            os.chmod(target, 0o600)          # yalnız sahibi okur
        except OSError:
            pass
        return True
    except Exception:
        return False


def read_events(path: str | None = None) -> list[dict]:
    """Kayıtları okur (ölçüm/inceleme için). Dosya yoksa boş liste."""
    target = path or AUDIT_PATH
    if not target or not os.path.exists(target):
        return []
    out = []
    with open(target, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out
