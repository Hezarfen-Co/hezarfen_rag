# ORCHESTRATION.md — Agentic sistem + sürekli optimizasyon protokolü

> **Amaç:** Kadir'in her seferinde uzun prompt yazmasına gerek kalmadan; kalite +
> maliyet + ürün amacı üçgeninde **sürekli** çalışan, kendi eksiğini bulup optimize
> eden bir agentic geliştirme sistemi. Bu dosya agentlar + Claude içindir (`docs/`).
> Ölçümler/sonuçlar Kadir için Obsidian `Documents/Hezarfen/rag`'e yazılır.

## 1. Roller (Opus + Sonnet — Fable yok)

| Rol | Model | Ne yapar | Ajan |
|---|---|---|---|
| **Orkestratör** | Opus (ana oturum) | İsteği anlar, işi parçalara böler, ajanlara dağıtır, sonuçları birleştirir, git+issue yönetir, Kadir'e raporlar | (ana) |
| **Mimar** | Opus | Zor/riskli/belirsiz kararlar, kök neden, dosya-bazlı görev tanımı + kabul kriterleri + test listesi. Kod yazmaz. | `architect` |
| **Kodcu** | Sonnet | Onaylı spesifikasyonu uygular, test yazar+çalıştırır, raporlar. | `coder` |
| **Doğrulayıcı** | Sonnet | Temiz bağlamda düşmanca doğrular; PASS/FAIL + kanıt. Kod düzeltmez. | `verifier` |
| **Değerlendirici** | Opus | DeepEval + özel metrik; EKSİK bulur (pass-bias yasak); metrik/test önerir; kalite+maliyet optimizasyonu. | `evaluator` |

Ajan tanımları: `.claude/agents/*.md`. Orkestratör bunları `Agent` tool'uyla çağırır
(hacimli/koşut işi Sonnet'e, zor kararı Opus'a → maliyet tasarrufu buradan gelir).

## 2. Delegasyon akışı (her iş için)

1. **Issue kontrolü** (bkz. §4): ilgili issue var mı?
2. **Belirsiz/mimari/riskli** ise → `architect` (Opus): spec + kabul kriterleri + test listesi.
3. Orkestratör spec'i **sınırları belirli** bir göreve çevirir (architect çıktısını doğrudan koda çevirme; önce net kabul kriteri).
4. **Kod** → yalnız `coder` (Sonnet): uygular + test + çalıştırır + raporlar.
5. **Doğrulama** → `verifier` (Sonnet, temiz bağlam): kabul kriterleri gerçekten karşılanmış mı.
6. Kabul kriteri karşılanmıyorsa → görevi `coder`'a geri yolla.
7. **Ölçüm/kalite** gereken yerde → `evaluator` (Opus): eksik + metrik + optimizasyon.
8. Orkestratör commit + push (yazar = Kadir, AI adı yok) + issue kapat + Kadir'e özet.

Küçük/tek-dosyalık iş orkestratör tarafından doğrudan yapılabilir; ajan overhead'i yalnız işi hızlandırıyor/temizliyorsa kullan.

## 3. Sürekli optimizasyon kriterleri (STANDING — tekrar sorulmaz)

Her iterasyonda şu üçlü gözetilir; **ürün amacına** (ürün-seviyesi, çok kaliteli,
güncel, kaynakla konuşan + kanıtlı özet, öğrenci/öğretmen/veli) varana kadar döngü sürer:

- **Kalite:** faithfulness ↑, atıf doğruluğu ↑, kapsam-dışı/zararlı red ↑, halüsinasyon ↓. Ölçüm: DeepEval + golden set (bkz. `OPTIMIZATION.md`).
- **Maliyet:** DeepSeek token/$ **canlı ölçülür** (usage okunur), cache ile düşürülür; her run `costlog` ile `Maliyet.md`'ye. Ucuz-ama-yanlış kabul edilmez.
- **Eksik-görme (pass-bias YASAK):** amaç geçmek değil, **nerede yanlış/eksik olduğunu bulmak**. Metrik eksiği göremiyorsa yeni metrik/test önerilir. Ajan kendini "başarılı" ilan edemez (SHARED_RULES 9; nihai kabul Kadir).

## 4. GitHub issue iş akışı (Hezarfen-Co/hezarfen_rag)

- **Önce bak:** işe başlamadan `gh issue list` ile ilgili issue var mı kontrol et.
- **Varsa:** o issue üzerinde çalış; bitince commit referansıyla **kapat** (`gh issue close N --comment "..."`).
- **Yoksa:** issue **aç** (`gh issue create`), problemi çöz, **kapat**.
- **Optimizasyon:** kapalı bir işi yeniden optimize edeceksen ilgili issue'yu **reopen** et, iyileştir, tekrar kapat.
- Issue başlıkları mevcut şema ile uyumlu: `[RAG][pipeline|quality|ops|...] ...`.
- Commit mesajında `Refs #N` / `Closes #N` kullan (izlenebilirlik).

## 5. Git disiplini

- **Tek branch `main`**, feature-branch YOK. Adım adım, geri-alınabilir commit.
- Commit'te **AI/Claude adı/izi yok** (yazar = Kadir Yönak).
- Her mantıksal değişiklik ayrı commit; mesaj Türkçe, ne+neden. Bitince push.
- Kod dosya adları **İngilizce** (içerik/yorum Türkçe olabilir).

## 6. Raporlama ayrımı

- **`docs/` (repo, git) → agentlar + Claude için:** protokol, orkestrasyon, süreç, kabul kriterleri, deney kapatma, backlog. (Bu dosya, `OPTIMIZATION.md`, `reports/`.)
- **Obsidian `Documents/Hezarfen/rag` → Kadir için:** ölçümler (`deney-sonuclari.md`), maliyet (`Maliyet.md`), bulgular, mimari, plan. Kilitli dosyalara (mimari/benchmark/bulgular/Notes) SHARED_RULES kuralları geçerli.

## 7. Döngü (loop)

Orkestratör kendini periyodik uyandırır (ScheduleWakeup) ve `OPTIMIZATION.md`'deki
sıradaki en yüksek-değerli optimizasyon adımını alır → §2 akışıyla yürütür → ölçer →
raporlar → issue günceller. Her tik: ya somut ilerleme (kod/ölçüm/bulgu) ya da "engel:
X bekliyor" (ör. DEEPSEEK_API_KEY, golden set onayı). Kadir istediğinde durdurur.
