# Korpus bütünlüğü — kitap ile kazanım dosyası farklı müfredattan (2026-09-11)

**Durum:** `İNSAN İNCELEMESİ BEKLİYOR` · **Kapsam:** `data/lise/10` (elimizdeki tek tam kademe)

## 1. Nasıl bulundu

Öğrenci senaryosunu uçtan uca koşarken, öğrencinin **kendi notundaki** kazanım
("10.1.1.2 Mitozu açıklar") üzerinden sorulan soru `insufficient_data` ile
reddedildi. Önce kendi chunk'lama değişikliğimden (#53) şüphelendim; iki
yapılandırmayı da ölçtüm:

| soru | sayfa hizalı top skor | eski chunk'lama top skor | kapı (0,30) |
|---|---|---|---|
| Mitoz nedir? | 0,0025 | 0,0020 | RED |
| Mayoz bölünme nedir? | 0,0006 | 0,0006 | RED |
| Kalıtım nedir? | 0,0037 | 0,0066 | RED |
| **Ekosistem nedir?** | **0,9845** | **0,9713** | **GEÇER** |

İkisi de aynı → **chunk'lama değil, veri.** Kitabın ham metninde:
`"mitoz"` → **0 kez**, `"mayoz"` → **0 kez**, `"kalıtım"` → **0 kez**;
`"ekosistem"` → **121 kez**, `"fotosentez"` → 67, `"sindirim"` → 49.

## 2. Kök neden

Kitap `1. Tema ENERJİ` / `2. Tema EKOLOJİ` yapısında — **Türkiye Yüzyılı Maarif
Modeli** (tema tabanlı, 2025 baskısı; kapakta "ORTAÖĞRETİM BİYOLOJİ 10. Sınıf").
`kazanimlar.json` ise `ünite: Hücre Bölünmeleri`, `kod: 10.1.1.2` yapısında —
**eski müfredatın** ünite/kazanım kodlaması.

İki dosya EBA'nın farklı uçlarından, **farklı müfredat sürümlerinden** inmiş.

## 3. Ölçüm: kazanım kapsamı

Ölçüt: kazanım metnindeki ayırt edici (≥5 harf, durak-dışı) sözcüklerin
≥%50'si kitap metninde geçiyor mu.

| ders | kazanım | kapsanan | oran | kitapta olmayan (örnek) |
|---|---|---|---|---|
| **biyoloji** | 17 | 12 | **0,71** | Mitozu açıklar · Mayozu açıklar · Eşeysiz üreme |
| **fizik** | 39 | 36 | **0,92** | Mercek çeşitleri · Işık prizmaları |
| kimya | 23 | 22 | 0,96 | Geri dönüşüm (polimer/cam/metal) |
| din-kültürü | 29 | 28 | 0,97 | — |
| İngilizce | 109 | 107 | 0,98 | — |
| coğrafya | 34 | 34 | 1,00 | — |
| felsefe | 18 | 18 | 1,00 | — |

Yalnız 7 derste `kazanimlar.json` var (19 dersin 7'si).

## 4. Neden önemli

1. **Ölçüm zehirlenmesi.** Kapsanmayan bir kazanımdan golden set item'ı ya da
   öğrenci notu üretilirse, ürün doğru davranıp çekimser kalır ama sonuç bir
   **RAG başarısızlığı gibi okunur**. Biyolojide bu, kazanımların %29'udur.
2. **Ürün vaadi.** "Kitabından sorabilirsin" diyoruz; öğrenci mitoz sorarsa
   kitapta yok. Bu bir model hatası değil, **kapsam** sorunudur ve kullanıcıya
   böyle anlatılmalıdır.
3. **Kişiselleştirme.** Kazanım kodları ilerleme takibinin omurgası olacak
   (EduKG / kişisel graf yolu). Kodlar kitapla eşleşmiyorsa ilerleme haritası
   baştan yanlış kurulur.

## 5. Yapılan

`src/backend/senaryo.py` artık **yalnız kapsanan kazanımlardan** not üretiyor
(`kapsanan_kazanimlar`). Kitap okunamazsa eleme yapılmaz — sessizce boş senaryo
üretmek sebebi görünmez kılardı.

## 6. Karara bağlanmamış

- Doğru eşleştirme hangisi: kitabı mı yenilemeli, kazanım dosyasını mı? (Yeni
  müfredatın kazanımları EBA'da ayrı bir uçta olabilir — `eba_dl` yeniden
  koşulacaksa bu da alınmalı.)
- Fizik'te eksik olan optik ünitesi kitabın 2. cildinde olabilir (`kitap.pdf`
  198 sayfa; `calisma-defteri` fasikül yapısında). **Doğrulanmadı.**
- Ortaokul (5–8) ve diğer liseler bu makinede yok (#92) — oranlar yalnız 10.
  sınıf içindir, genele teşmil edilemez.

## 7. Yeniden üretim

```
.venv/bin/python outputs/korpus-butunluk/kazanim_kapsam.py OUT.json   # kazanım düzeyi
.venv/bin/python outputs/korpus-butunluk/korpus_butunluk.py OUT.json  # ünite düzeyi
.venv/bin/python outputs/korpus-butunluk/tani_gate.py                 # kapı skorları
```

---

## 8. DÜZELTME (2026-09-12) — teşhis yanlıştı, kök neden ters yönde

EBA kataloğu indirildikten sonra karşılaştırma yapıldı ve §2'deki teşhis
**yanlış çıktı**. Orada "kazanım dosyası eski müfredattan, kitap yenisinden"
denmişti. Ölçüm bunun tersini gösteriyor:

| karşılaştırma | sonuç |
|---|---|
| katalog `"10"` (güncel etiketi) ↔ `"10. Sınıf (2017-23 Müfredatı)"` | **aynı kazanım kodları** (biyoloji 17/17 ortak, fark 0) |
| katalog güncel ↔ elimizdeki `kazanimlar.json` | **birebir aynı** (17/17, yalnız-dosyada 0, yalnız-katalogda 0) |

Yani:

* `kazanimlar.json` **doğru ve güncel** — EBA'nın 10. sınıf için yayımladığı
  kazanımların aynısı. `(2017-23 Müfredatı)` etiketi **materyal kümesini**
  ayırıyor, kazanım kümesini değil.
* Uyumsuz olan **ders kitabıdır**: `data/lise/10/biyoloji/kitap.pdf` kapağında
  "2025" yazan, **tema tabanlı** (1. Tema ENERJİ / 2. Tema EKOLOJİ) *Türkiye
  Yüzyılı Maarif Modeli* baskısı. EBA'nın OGM Materyal tarafı ise hâlâ eski
  ünite/kazanım yapısını yayımlıyor.

**Karar sorusu değişti.** Artık "hangi kazanım dosyası" değil, **"hangi kitap
baskısı hedef"**:

* Öğrencinin elindeki kitap 2025 baskısıysa **kitap doğru**, kazanım eşlemesi
  yeni müfredata göre yeniden kurulmalı (EBA henüz yayımlamamış).
* Hedef eski müfredatsa **kitap değişmeli** (eski baskı bulunmalı).

Bu, §4'teki "geçici önlem"i geçersiz kılmaz — `covered_objectives()` yine
kitabın kapsamadığı kazanımları eliyor ve ölçüm zehirlenmesini önlüyor. Ama
sebebi artık doğru biliniyor.

**Yan kazanç:** katalogdan 9/11/12. sınıflar için **23 yeni sınıf-ders kazanım
seti** çıkarıldı (`objectives.json`); bu sınıflarda daha önce hiç kazanım
dosyası yoktu.
