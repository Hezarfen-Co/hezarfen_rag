# CLAUDE.md — Hezarfen RAG proje kuralları (Claude)

> Bu klasör (`C:/Users/w/Documents/Hezarfen/rag`) projenin **kalıcı hafızası**dır.
> Kod deposu ayrı: `hezarfen_rag` (git). Aşağıdaki **ortak kurallar** `AGENTS.md`
> ve `CLAUDE.md`'de BİREBİR AYNI tutulur.

<!-- SHARED_RULES_START -->
<!-- shared_rules_version: 3 -->
## Ortak Kurallar (AGENTS.md ve CLAUDE.md'de kelimesi kelimesine AYNI)

1. **Önce oku:** Göreve başlamadan `Notes.md` (varsa) + ilgili Markdown belgelerini oku. Yalnız sohbet geçmişine güvenme; proje dosyaları kalıcı hafızadır.
2. **Araştırma → `reports/`:** Literatür/teknik araştırma sonuçları sohbette bırakılmaz; `reports/` altına yazılır.
3. **Yarım iş → `Backlog.md`:** Başlanıp bitmeyen işler devralma bağlamıyla `Backlog.md`'ye yazılır.
4. **Biten iş → `COMPLETED.md`:** Yalnız **Kadir onayından** sonra `Backlog.md`'den çıkarılıp `COMPLETED.md`'ye taşınır.
5. **Değişmez bilgi → `CONSTANTS.md`:** Doğrulanmış, değişmeyecek değerler orada tutulur.
6. **Oturum sonu:** Kalıcı proje bilgisi ilgili Markdown dosyalarına yazılmadan oturum kapatılmaz.
7. **Kodlamadan önce:** Araştırma, kapsam, mimari, ölçüm yöntemi ve kabul ölçütleri netleştirilir.
8. **Deney kapatma protokolü:** Her deney benzersiz `EXP-XXX` kimliği alır; ayrıntılı rapor `reports/EXP-XXX-<slug>.md`'ye yazılır (ayarlar, model/prompt/veri sürümü, commit, ortam, ham çıktı yolları, gecikme/token/maliyet). Başlangıç ↔ yeni sistem **aynı veri + aynı koşulda** karşılaştırılır. **Her deneyden sonra `reports/DENEY-KAPATMA-PROTOKOLU.md`'deki 19-adım kontrol listesi + değerlendirme paketi BİREBİR uygulanır (bağlayıcı).**
9. **İnsan denetimi (AI testleri):** Otomatik metrik · LLM-hakem · insan değerlendirmesi **ayrı** gösterilir. LLM-hakem yalnız yardımcıdır, nihai doğruluk kaynağı değildir. **Ajan kendi çıktısını tek başına "başarılı" işaretleyemez.** Nihai kabul **Kadir**'dedir; o incelemeden durum **`İNSAN İNCELEMESİ BEKLİYOR`** kalır. Başarısız denemeler silinmez; cherry-pick yapılmaz.
10. **`benchmark.md` kilidi:** Çekirdek test kümesi, eşikler ve insan değerlendirme ölçütleri **Kadir onayı** olmadan değiştirilmez. Bunlardan biri değişirse **yeni benchmark sürümü** oluşturulur (eskisi korunur).
11. **`mimari.md` kilidi:** Kabul edilmiş mimari Kadir onayı olmadan değiştirilmez; etki varsa yalnız **öneri** sunulur (Notes.md onay kuyruğu).
12. **`bulgular.md` kilidi:** Doğrulanmamış sonuç **kesin bulgu** olarak eklenmez (`[DENEYSEL SONUÇ]` yalnız kod/veri ile doğrulanana).
13. **`Notes.md` kuralı:** Kadir'e ait bölümler değiştirilemez/özetlenemez/silinemez. Ajan yalnız **"Ajanın onay bekleyen önerileri"** bölümüne **tarihli** öneri ekler; onaysız öneriyi kesin karar sayamaz.
14. **`Maliyet.md`:** AUTO blokları yalnız kod (`costlog`) yazar; elle düzenlenmez.
15. **Git (kod deposu):** Tek branch (`main`), adım adım commit; feature-branch açılmaz. **Commit'lerde AI/Claude adı/izi bulunmaz** (yazar = Kadir).
16. **Uydurma yasak:** Bilinmeyen bilgi etiketlenir: `[DOĞRULANDI]` `[VARSAYIM]` `[DENEYSEL SONUÇ]` `[KADİR ONAYI BEKLİYOR]` `[ARAŞTIRILACAK]` `[ÇELİŞKİ VAR]`.
17. **AGENTS/CLAUDE senkronu:** Ortak kural değişirse **aynı işlemde** her iki dosya güncellenir ve `shared_rules_version` artırılır. Oturum başında iki blok karşılaştırılır; **çelişki varsa ajan sessizce seçmez, Kadir'e bildirir.**
18. **Agentic orkestrasyon:** Roller Opus (orkestratör + mimar) + Sonnet (kodcu + doğrulayıcı) + Opus (değerlendirici); ajan tanımları `.claude/agents/`, protokol `docs/ORCHESTRATION.md`. Kod değişikliği yalnız `coder`; doğrulama ayrı `verifier` (temiz bağlam, düşmanca); kabul kriteri karşılanmazsa iş geri gönderilir. Zor/riskli karar `architect`; ölçüm/eksik-analizi `evaluator`.
19. **GitHub issue akışı:** İşe başlamadan ilgili issue kontrol edilir; **varsa** üstünde çalışılıp commit referansıyla **kapatılır**, **yoksa açılır → çözülür → kapatılır**; kapalı işi yeniden optimize ederken **reopen** edilir. Commit mesajında `Refs #N`/`Closes #N`.
20. **Sürekli optimizasyon (pass-bias YASAK):** Kalite + maliyet + eksik-görme üçlüsü ürün amacına varana dek gözetilir; amaç geçmek değil **eksiği bulmak**; metrik yetersizse yeni metrik/test önerilir; canlı token/$ ölçülür. Standing kararlar `docs/OPTIMIZATION.md`'de gömülü — Kadir tekrar prompt yazmaz.
<!-- SHARED_RULES_END -->

## Claude'a özel notlar (ortak-dışı)
- Geçici dosya/analiz betikleri için scratchpad kullan; kalıcı olmayanları repoya koyma (kod deposunda `eba_dl/`, `data/` git-ignore).
- Gerçek testi BİZZAT çalıştır, "test ettim" deyip geçme; somut kanıt (gerçek sayılar/çıktı) sun.
- Türkçe cevap; kullanıcı = Kadir.
