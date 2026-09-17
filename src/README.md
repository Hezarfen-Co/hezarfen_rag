# src/ — maliyet altyapısı (ilk modül)

RAG boru hattından ÖNCE, her denemenin maliyetini profesyonelce tutmak için
kurulan çekirdek. **Sıfır harici bağımlılık** (yalnız Python stdlib).

## Parçalar
| Dosya | İş |
|---|---|
| `pricing.py` | DeepSeek fiyat tablosu (tek yer) + `cost_usd(model, usage, tier)` |
| `providers/llm.py` | LLM çağrısı — sağlayıcı-nötr, OpenAI-uyumlu; metin + **token usage** döndürür (`LLMClient`) |
| `costlog.py` | run kaydı (`runs.jsonl`) + **Maliyet.md** otomatik render |
| `_cost_template.py` | Maliyet.md profesyonel iskeleti (AUTO marker'lı) |

## Akış
```
LLMClient().chat(prompt) --> ChatResult(text, usage)
                                   │
        cost_usd(model, usage) ────┤
                                   ▼
   costlog.record(module, model, usage, items, note)
        │  runs.jsonl'e ekler (tek doğruluk kaynağı)
        └► Maliyet.md AUTO bloklarını yeniden üretir (Obsidian)
```

## Kullanım
```python
import os; os.environ["LLM_API_KEY"] = "..."   # tek ad (eski adlar kaldırıldı)
from src.providers import LLMClient
from src.costlog import record

r = LLMClient(model="deepseek-chat").chat("Şu metni 3 cümlede özetle:\n...")
record(module="ozet", model="deepseek-chat", usage=r.usage, items=1,
       quality={"faithfulness": 0.92},
       note="prompt v2: madde-madde iste → çıkış token %10 arttı")
print(r.text)
```
Maliyet defterini elle yenile: `python -m src.costlog render`
Metodu boş görmek için örnek: `python -m src.costlog demo` (satırları sonra sil)

## Fiyat güncelleme
Fiyat değişince **yalnız** `pricing.py` → `PRICING` tablosu + `PRICING_UPDATED`
tarihi güncellenir; Maliyet.md sonraki render'da otomatik yansıtır.

## Not
- Maliyet defteri Obsidian'da: `C:/Users/w/Documents/Hezarfen/rag/Maliyet.md`
  (+ makine kaydı `runs.jsonl`). Kalite defteri ayrı: `deney-sonuclari.md`.
- RAG boru hattı (chunk/embed/retrieve/generate) henüz YOK — bkz. `src/gorevler`.
