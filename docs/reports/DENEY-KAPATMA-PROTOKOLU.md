# Deney Kapatma Protokolü (HER deneyden sonra uygulanır)

> Kadir'in standart talimatı (2026-08-31). Her deney bittiğinde **birebir** bu adımlar
> izlenir. Bağlayıcı kurallar: [[AGENTS]] / [[CLAUDE]] ortak kural #8-#9.
> Çalışma dizini: `C:/Users/w/Documents/Hezarfen/rag`.

## Ön okuma (başlamadan)
Önce `AGENTS.md`, ajan Claude ise ayrıca `CLAUDE.md`, ardından `reports/README.md`,
`benchmark.md` ve deneyle ilgili diğer Markdown dosyaları okunur.

## 19 adım
1. Deney için benzersiz `EXP-XXX` kimliği belirle.
2. Ayrıntılı deney raporunu `reports/EXP-XXX-<slug>.md` olarak oluştur.
3. Ayarlar + model sürümü + prompt sürümü + veri kümesi sürümü + commit kimliği + çalışma ortamını kaydet.
4. Başlangıç sistemi sonuçları ile yeni sonuçları **aynı koşullarda** karşılaştır.
5. Otomatik metrikleri ve LLM-hakem sonuçlarını **ayrı** göster.
6. Başarılı / başarısız / sınırda / rastgele seçilmiş örnekleri Kadir'in inceleyebileceği biçimde sun.
7. Ham çıktı ve log yollarını kaydet.
8. Gecikme + token + donanım kullanımı + maliyeti kaydet.
9. Sonucu `deney-sonuclari.md`'ye özet olarak ekle.
10. Tekrarlanabilir hata varsa `buglar.md` güncelle.
11. Maliyet oluştuysa `Maliyet.md` güncelle (AUTO — kod/costlog ile).
12. Yeni görev doğduysa `gorevler.md` ekle.
13. İş yarım kaldıysa `Backlog.md`'ye devralma bağlamıyla kaydet.
14. Mimari etkileniyorsa yalnız **öneri** oluştur; Kadir onayı olmadan `mimari.md` kabul edilmiş mimariyi değiştirme.
15. Doğrulanmamış sonucu `bulgular.md`'ye **kesin bulgu** olarak ekleme.
16. Kadir onayı tamamlanmadan işi `COMPLETED.md`'ye taşıma.
17. `Notes.md` içindeki Kadir'e ait bölümleri değiştirme.
18. Gerekirse **"Ajanın onay bekleyen önerileri"** bölümüne öneri ekle.
19. `AGENTS.md` ve `CLAUDE.md` ortak kurallarının eşleştiğini kontrol et.

**Nihai deney durumu → `İNSAN İNCELEMESİ BEKLİYOR`.**

## Değerlendirme paketi (kapanışta Kadir'e sunulur)
Deney amacı · değiştirilen unsur · başlangıç sonucu · yeni sonuç · otomatik metrikler ·
en iyi örnekler · başarısız örnekler · sınırda kalan örnekler · kontrol edilecek kritik
noktalar · doldurulacak insan değerlendirme alanları · onaylanırsa güncellenecek dosyalar.

## Değişmez ilkeler (ihlal edilemez)
- Kadir açıkça **"onaylandı"** ya da **"reddedildi"** demeden **nihai karar verilmez.**
- Ajan **kendi çıktısını tek başına "başarılı" sayamaz**; LLM-hakem yalnız yardımcı, nihai doğruluk kaynağı Kadir.
- **Uydurma yasak:** olmayan deney/sonuç kapatılmaz; model çalışmadıysa ilgili alanlar `N/A` yazılır.
- Başarısız denemeler silinmez; cherry-pick yapılmaz; baseline↔yeni aynı veri+koşul.
- `benchmark.md` çekirdeği (set/eşik/insan-ölçütü) Kadir onayı olmadan değişmez; değişirse **yeni benchmark sürümü**.
