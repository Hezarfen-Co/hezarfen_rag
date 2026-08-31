"""Faz 0.7 — Curriculum graph (kazanimlar.json → sınıf/ders/ünite/kazanım).

Deterministik omurga; JSON/bellek-içi (harici bağımlılık yok). `kod` biçimi
"12.1.1.1" = sınıf.ünite.konu.kazanım.
"""
from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass, field

_KOD = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Kazanim:
    kazanim_id: int
    kod: str
    metin: str
    unite_id: int
    unite: str
    sinif: str
    ders: str


def parse_kod(kod: str) -> tuple[int, int, int, int] | None:
    """"12.1.1.1" → (12, 1, 1, 1). Uymayan → None."""
    m = _KOD.match(kod or "")
    return tuple(int(g) for g in m.groups()) if m else None


class CurriculumGraph:
    """sınıf→ders→ünite→kazanım. Birden çok ders birleştirilebilir."""

    def __init__(self, kazanimlar: list[Kazanim] | None = None):
        self._items: list[Kazanim] = list(kazanimlar or [])
        self._by_id: dict[int, Kazanim] = {}
        self._by_kod: dict[str, Kazanim] = {}
        for k in self._items:
            self._by_id[k.kazanim_id] = k
            self._by_kod[k.kod] = k

    def add(self, k: Kazanim) -> None:
        self._items.append(k)
        self._by_id[k.kazanim_id] = k
        self._by_kod[k.kod] = k

    def __len__(self) -> int:
        return len(self._items)

    @property
    def kazanimlar(self) -> list[Kazanim]:
        return list(self._items)

    def by_id(self, kazanim_id: int) -> Kazanim | None:
        return self._by_id.get(kazanim_id)

    def by_kod(self, kod: str) -> Kazanim | None:
        return self._by_kod.get(kod)

    def units(self, sinif: str | None = None, ders: str | None = None) -> list[tuple[int, str]]:
        seen: dict[int, str] = {}
        for k in self._items:
            if sinif and k.sinif != sinif:
                continue
            if ders and k.ders != ders:
                continue
            seen.setdefault(k.unite_id, k.unite)
        return sorted(seen.items())

    def kazanimlar_of(self, unite_id: int) -> list[Kazanim]:
        return [k for k in self._items if k.unite_id == unite_id]

    def subjects(self) -> list[tuple[str, str]]:
        return sorted({(k.sinif, k.ders) for k in self._items})


def _kasa(sinif: str) -> str:
    try:
        return "ortaokul" if int(sinif) <= 8 else "lise"
    except ValueError:
        return "lise"


def load(path: str, sinif: str, ders: str) -> CurriculumGraph:
    """Tek kazanimlar.json → CurriculumGraph."""
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    items = [Kazanim(kazanim_id=int(r["kazanim_id"]), kod=str(r["kod"]),
                     metin=r.get("metin", ""), unite_id=int(r["unite_id"]),
                     unite=r.get("unite", ""), sinif=sinif, ders=ders)
             for r in rows]
    return CurriculumGraph(items)


def load_from_vault(data_root: str) -> CurriculumGraph:
    """data/{kasa}/{sınıf}/{ders}/kazanimlar.json hepsini birleştir."""
    g = CurriculumGraph()
    for path in glob.glob(os.path.join(data_root, "*", "*", "*", "kazanimlar.json")):
        parts = path.replace("\\", "/").split("/")
        sinif, ders = parts[-3], parts[-2]
        try:
            sub = load(path, sinif, ders)
        except (json.JSONDecodeError, KeyError):
            continue
        for k in sub.kazanimlar:
            g.add(k)
    return g
