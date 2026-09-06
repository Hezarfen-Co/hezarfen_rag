"""Faz 0.8 — OCR fallback (taranmış / görüntü-sayfa metin çıkarımı).

`parse_pdf` (bkz. pdf_parse.py) YALNIZ text-layer okur (`get_text`). Taranmış bir
PDF ya da görüntü-sayfada text-layer ~boştur → o sayfa SESSİZCE indekse/özete
girmez (bkz. EXP-003 tanısı: korpusun ~%1'i, ör. görsel-sanatlar kitabı ağırlıklı
taranmış). Bu modül, böyle sayfaları RENDER edip Tesseract (Türkçe) ile OCR eder.

**Zarif degradasyon (bağlayıcı):** pytesseract / tesseract binary / `tur` dil verisi
yoksa modül ÇÖKMEZ — `ocr_available()` False, `ocr_page()` "" döner (çağıran
text-layer ile devam eder). Türkçe için `tur.traineddata` gerekir; yoksa `eng`'e
düşer (Türkçe karakterler bozulabilir — kalite için `models/tessdata/tur.traineddata`
proje-yerel tutulur, bkz. README/CONSTANTS).

Tasarım: OCR yalnız GEREKTİĞİNDE (text-layer boş + sayfada görüntü var) tetiklenir;
`parse_pdf(ocr=True)` ile açık, varsayılan KAPALI (text-layer'lı %99 kitap için
tesseract bağımlılığı GEREKMEZ).
"""
from __future__ import annotations

import io
import os

import fitz  # PyMuPDF (render)

# Windows'ta tesseract PATH'te olmayabilir; yaygın kurulum yolu + env override.
_DEFAULT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Proje-yerel Türkçe dil verisi (models/tessdata/tur.traineddata; git-ignore).
_LOCAL_TESSDATA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "models", "tessdata"))


def _pt():
    """pytesseract'i içe aktar + tesseract_cmd'i ayarla. Bulunamazsa None (zarif)."""
    try:
        import pytesseract
    except ImportError:
        return None
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd and os.path.exists(cmd):
        pytesseract.pytesseract.tesseract_cmd = cmd
    elif os.path.exists(_DEFAULT_WIN):
        pytesseract.pytesseract.tesseract_cmd = _DEFAULT_WIN
    return pytesseract


def _local_tessdata(lang: str) -> str | None:
    """`lang` için proje-yerel tessdata dizini (o dilin .traineddata'sı varsa)."""
    if os.path.exists(os.path.join(_LOCAL_TESSDATA, f"{lang}.traineddata")):
        return _LOCAL_TESSDATA
    return None


def ocr_available(lang: str = "tur") -> bool:
    """OCR bu ortamda `lang` için kullanılabilir mi (pytesseract + tesseract + dil)."""
    pt = _pt()
    if pt is None:
        return False
    if _local_tessdata(lang):
        return True
    try:
        return lang in pt.get_languages(config="")
    except Exception:
        return False


def _resolve_lang(pt, lang: str) -> tuple[str, str]:
    """(kullanılacak_dil, tessdata_dizini) — yerel `lang` verisi varsa dizinini
    döndürür (çağıran onu `TESSDATA_PREFIX`'e koyar); yoksa kurulu `lang`'ı (dizin
    ""); o da yoksa eng'e düşer. NOT: `--tessdata-dir` config'i KULLANILMAZ —
    pytesseract config'i boşlukla böldüğü için tırnaklı yol bozuluyordu; boşluk
    içeren yollara da dayanıklı olması için TESSDATA_PREFIX env'i tercih edilir."""
    td = _local_tessdata(lang)
    if td:
        return lang, td
    try:
        if lang in pt.get_languages(config=""):
            return lang, ""
    except Exception:
        pass
    return "eng", ""


def ocr_page(page: "fitz.Page", *, lang: str = "tur", dpi: int = 300) -> str:
    """fitz sayfasını `dpi`'de render edip OCR metnini döndürür. HERHANGİ bir hatada
    "" döner (zarif degradasyon — çağıran text-layer ile devam eder)."""
    pt = _pt()
    if pt is None:
        return ""
    _prev_prefix = os.environ.get("TESSDATA_PREFIX")   # kaydet (audit EXP-007: env sızıntısı)
    try:
        from PIL import Image
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        use_lang, tessdata_dir = _resolve_lang(pt, lang)
        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_dir
        return pt.image_to_string(img, lang=use_lang).strip()
    except Exception:
        return ""
    finally:                                            # env'i eski haline getir (thread/global sızıntısı olmasın)
        if _prev_prefix is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = _prev_prefix
