# Konteyner dağıtımı — gerçekten koşuldu (2026-09-12)

**Durum:** `İNSAN İNCELEMESİ BEKLİYOR` · **Ortam:** Podman 5.8.4 (host),
imge `localhost/hezarfen-rag:local`, CPU torch 2.14.0+cpu

## 1. Kabul kriteri: SAĞLANDI

> *"Temiz bir makinede tek komutla ayağa kalkar ve `/health` 200 döner."*

| adım | sonuç |
|---|---|
| `podman build` | ✅ başarılı |
| `podman run` | ✅ kap ayakta |
| **`/health`** | ✅ **8. saniyede 200** |
| `/ready` (ısınırken) | ✅ 503 |
| `/ready` (hazır) | ✅ 200 |
| `/rag/chat` gerçek soru | ✅ 2 atıflı doğru cevap, $0,000394 |

Önceki hâlde `CMD` bir metin yazdırıp çıkıyordu; kap hiç servis etmiyordu.

## 2. KOŞARAK BULUNAN İKİ HATA

### 2.1 `/ready` YALAN SÖYLÜYORDU (düzeltildi)

İlk koşumda `/ready` 492. saniyede 200 dedi — ve ondan **sonra** gelen ilk
gerçek soru `reason="timeout"` ile düştü.

Sebep: `build_service` embedder'ı chunk'ları gömerek **dolaylı olarak**
yüklüyor, ama **reranker tembel kalıyordu**. Isınma bitince `/ready` "hazır"
diyor; ilk soru gelince reranker ~2 GB indirmeye kalkıyor ve istek son tarihini
(60 s) aşıyor.

Bu, orkestratörün kabı "trafik alabilir" diye işaretleyip **ilk isteği
düşürmesi** demekti. `/health` ≠ `/ready` ayrımı ancak `/ready` **doğru
söylerse** işe yarar.

> `warmup()` kancasını #80'de eklemiştim ama **çağırmayı unutmuşum**. Birim
> testleri yeşildi; hata yalnızca **gerçek konteyner koşumunda** göründü.

**Düzeltildi:** `build_service` reranker'ı `Generator`'a vermeden önce
ısıtıyor; test hem çağrının varlığını hem **sırasını** bağlıyor.

### 2.2 CPU'da servis interaktif olarak KULLANILAMAZ (açık)

Düzeltmeden sonra kap uçtan uca çalıştı ama **bir soru 96 saniye** sürdü.
Konteyner içinde ölçüldü:

| işlem | CPU | GPU (aynı makine) |
|---|---|---|
| sorgu embed (dense) | 0,12 s | — |
| sorgu embed (sparse) | 0,11 s | — |
| **40 aday rerank** | **65,2 s** | **1,9 s** |
| 10 aday rerank | 15,6 s | — |
| uçtan uca soru | **96 s** | **5,6 s** |

Darboğaz tek bir yerde: **cross-encoder rerank, CPU'da 34 kat yavaş.**
`candidate_n`'i 10'a düşürmek bile 15,6 s demek — hâlâ interaktif değil.

**Sonuç:** `Containerfile` bilinçli olarak CPU torch kuruyor; bu imge
**öğrenciye hizmet edemez**. Seçenekler (hiçbiri ölçülmedi):
GPU passthrough · daha küçük/kuantize reranker · rerank'ı yalnız ilk N adaya
uygulamak · rerank'ı isteğe bağlı yapmak.

**Ayrıca:** varsayılan `RAG_REQUEST_TIMEOUT_S=60` (#78) CPU'da **her isteği
düşürür**. Testte 300'e çekildi. Varsayılanın donanıma göre belirlenmesi
gerekiyor.

## 3. İlk koşum maliyeti

| | |
|---|---|
| Model indirme | **~3,2 GB** (BGE-M3 ~2,2 + reranker ~1,0) |
| İndirme süresi | 9 dk 26 sn + 9 dk 40 sn (HF token'sız, hız sınırlı) |
| Toplam hazırlık | **1452,6 s (~24 dk)** |
| RAM | ~2,4 GB |

Bu yüzden compose'da `rag-models` **kalıcı volume** var: ikinci açılışta
indirme tekrarlanmaz. `HF_TOKEN` verilirse indirme belirgin hızlanır (log
bunu açıkça uyarıyor).

## 4. Yeniden üretim

```
podman build -f Containerfile -t localhost/hezarfen-rag:local .
podman run -d --name rag -p 127.0.0.1:8000:8000 \
  -v "$PWD/data:/app/data:ro,z" -v hezarfen-models:/models \
  -e BOOK_PATH=/app/data/lise/10/biyoloji/kitap.pdf -e SINIF=10 -e DERS=biyoloji \
  -e RAG_REQUEST_TIMEOUT_S=300 -e DEEPSEEK_API_KEY=... \
  localhost/hezarfen-rag:local
curl -fsS http://127.0.0.1:8000/health     # 200, saniyeler içinde
```

`podman compose` bu makinede sağlayıcı eksikliğinden koşulamadı
(`docker-compose`/`podman-compose` kurulu değil); `compose.yaml` **doğrudan
denenmedi**, yalnız sözleşme testleriyle sabitlendi.
