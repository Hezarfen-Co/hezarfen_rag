"""#74 / EXP-010 #M3-11 — KIRILMA SENARYOSU KATALOĞU ve test kapsamı.

Kaynak: Obsidian `rag/benchmark.md §8.4` ("edge case sicili"). Kadir'in şartı:
*"her senaryoyu her kırılmayı düşünmemiz gerek"*. O tablo **testlerin
kaynağıdır** — her satır ya bir teste ya bir kapıya bağlanır. Kapı **T-06**
MVP'de ≥%80 kapsam istiyor.

SORUN: katalog bir Markdown tablosuydu. Kimse hangi satırın test edildiğini
bilmiyordu; "kapsam %80" iddiası ölçülemiyordu ve bir test silinse katalog
sessizce yalan söylemeye devam ederdi.

BU DOSYA senaryoları veri hâline getirir ve her birini KAPSAYAN testlerin tam
adlarını tutar. `tests/unit/test_breakage_coverage.py` bu adların GERÇEKTEN
var olduğunu doğrular — harita çürürse test kırılır.

DÜRÜSTLÜK KURALI: `covered_by` yalnız o senaryoyu GERÇEKTEN sınayan testleri
içerir. Boş liste = kapsanmıyor; `note` neyin eksik olduğunu yazar. Listeyi
ilgisiz testlerle doldurmak kapsam sayısını şişirir ve kapıyı anlamsızlaştırır
— bu, ölçmemekten daha kötüdür.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    area: str
    title: str
    expected: str
    covered_by: tuple = ()
    note: str = ""

    @property
    def covered(self) -> bool:
        """En az bir test bu senaryoya bağlı mı."""
        return bool(self.covered_by)

    @property
    def partial(self) -> bool:
        """Kapsanıyor AMA `note` bir boşluk yazıyor.

        "Kapsanıyor" ile "yeterince kapsanıyor" aynı şey değildir. E-03 (2000
        sayfalık PDF) 60 sayfaya kadar sınandı; sayıya 1 olarak girer ama
        senaryo tam karşılanmadı. Tek bir yüzdeye bakan, olduğundan iyi bir
        tablo görür.
        """
        return self.covered and bool(self.note)


def _s(sid, area, title, expected, covered_by=(), note=""):
    return Scenario(sid, area, title, expected, tuple(covered_by), note)


# --- 4.1 Veri / ingest kırılmaları ---------------------------------------
INGEST = [
    _s("E-01", "ingest", "Taranmış (görüntü) PDF, metin katmanı yok",
       "OCR devreye girer; girmezse açıkça 'okunamadı' + indekslenmez",
       ["unit/test_ocr.py::PageNeedsOcrTests::test_empty_text_with_image_needs_ocr",
        "unit/test_ocr.py::PageNeedsOcrTests::test_empty_text_no_image_skips",
        "unit/test_ocr.py::PageNeedsOcrTests::test_only_label_noise_still_needs_ocr"]),
    _s("E-02", "ingest", "Bozuk/şifreli/parola korumalı PDF",
       "Hata yakalanır, anlaşılır mesaj, servis çökmez",
       ["unit/test_pdf_edge_cases.py::UnreadableSourceTests::test_corrupt_bytes",
        "unit/test_pdf_edge_cases.py::UnreadableSourceTests::test_encrypted_pdf",
        "unit/test_pdf_edge_cases.py::UnreadableSourceTests::test_zero_byte_file",
        "unit/test_pdf_edge_cases.py::UnreadableSourceTests::test_reason_is_machine_readable"]),
    _s("E-03", "ingest", "1 sayfalık PDF · 2000 sayfalık PDF",
       "İkisi de çalışır; büyükte ilerleme + zaman aşımı yönetimi",
       ["unit/test_pdf_edge_cases.py::DegenerateButValidTests::test_blank_page_yields_no_units",
        "unit/test_pdf_edge_cases.py::DegenerateButValidTests::test_real_content_survives_at_scale"],
       "2000 sayfa ölçülmedi; 60 sayfaya kadar sınandı. İlerleme/zaman aşımı YOK."),
    _s("E-04", "ingest", "İki sütun düzeni yanlış sıralanıyor",
       "Okuma sırası testi; bozulursa chunk sınırı kayar → atıf kayar",
       ["unit/test_pdf_classify.py::OrderTests::test_two_column_left_before_right",
        "unit/test_pdf_classify.py::OrderTests::test_single_column_y_order"]),
    _s("E-05", "ingest", "Aynı kaynak iki kez yüklenir",
       "Tekilleştirme (içerik hash'i); çift atıf oluşmaz",
       ["unit/test_pdf_edge_cases.py::DegenerateButValidTests::test_doc_id_follows_bytes_not_path",
        "unit/test_distill.py::DistillTests::test_exact_duplicate_dropped_first_kept",
        "unit/test_distill.py::DistillTests::test_near_duplicate_dropped"],
       "doc_id BAYT kimliği: aynı içerik yeniden üretilirse farklı doc_id "
       "(bkz. test_regenerating_the_same_content_changes_the_doc_id)."),
    _s("E-06", "ingest", "Kaynakta cevap anahtarı/soru sayfası var",
       "Retrieval'dan izole; özet/soru yolunda da izole",
       ["unit/test_isolate.py::AssessmentTests::test_assessment_markers",
        "integration/test_isolate.py::Isolation12BioTests::test_scattered_question_blocks_flagged",
        "integration/test_isolate.py::Isolation12BioTests::test_teaching_pages_are_retained"]),
    _s("E-07", "ingest", "Kaynak metninde gömülü talimat (dolaylı injection)",
       "Uyulmaz; özet/soru yollarında da",
       ["unit/test_indirect_injection.py"]),
    _s("E-08", "ingest", "Yüklenen dosya PDF değil (docx/pptx/xlsx/jpg)",
       "Ya desteklenir ya NET reddedilir",
       ["unit/test_pdf_edge_cases.py::UnreadableSourceTests::test_not_a_pdf_at_all"],
       "Yalnız 'net reddedilir' yolu var; başka format DESTEKLENMİYOR."),
    _s("E-09", "ingest", "Zip-bomb / 500 MB dosya / kötücül dosya",
       "Boyut+tip limiti, sandbox parser",
       [],
       "KAPSANMIYOR. İngest'te dosya boyutu/tip sınırı YOK. HTTP gövde sınırı "
       "var ama ingest bir HTTP ucu değil (çevrimdışı/CLI)."),
    _s("E-10", "ingest", "Türkçe karakter bozulması (yumuşak tire, NFC, İ/ı)",
       "tr_normalize; indeks ve guard AYNI normalizasyonu kullanır",
       ["unit/test_tr_normalize.py",
        "unit/test_audit_fixes.py::TrNormalizeRobustTests::test_non_str_returns_empty",
        "unit/test_canonical.py::UnitsFromParsedTests::test_text_normalized",
        "unit/test_pdf_edge_cases.py::TurkishTextTests::test_turkish_characters_survive_extraction"]),
    _s("E-11", "ingest", "Tablo yanlış sütuna hizalanıyor",
       "Tablo kalite filtresi; hatalı tablo LLM'e verilmez",
       ["unit/test_tables.py",
        "integration/test_tables.py::TableExtractionTests::test_decorative_boxes_stay_filtered"]),
    _s("E-12", "ingest", "Şekil-caption eşleşmesi kayıyor",
       "Görsel birim atıfı yanlış sayfa göstermez",
       ["unit/test_visuals.py", "unit/test_vlm.py",
        "unit/test_pdf_classify.py::ClassifyTests::test_caption_gorsel"]),
]

# --- 4.2 Sorgu / kullanıcı kırılmaları -----------------------------------
QUERY = [
    _s("E-20", "sorgu", "Boş / tek karakter / 100.000 karakter sorgu",
       "Sınır kontrolü, anlamlı hata",
       ["unit/test_guard.py::EdgeCaseTests::test_empty_query_allowed",
        "unit/test_cache.py::ResponseCacheKeyTests::test_empty_query_produces_stable_non_crashing_key",
        "unit/test_http_hardening.py",
        "unit/test_guard.py::EdgeCaseTests::test_harmful_phrase_buried_in_long_query_still_caught"]),
    _s("E-21", "sorgu", "Sorgu içinde sahte kaynak bloğu / fence",
       "Sanitize; uydurma içerik atıflanamaz",
       ["unit/test_query_sanitization.py"]),
    _s("E-22", "sorgu", "Türkçe olmayan sorgu (EN/AR/karışık)",
       "Ya Türkçe cevap ya net yönlendirme; guard dilden bağımsız çalışır",
       [],
       "KAPSANMIYOR. Dil kapısı yok; guard'ın İngilizce zararlı isteği "
       "yakalayıp yakalamadığı ölçülmedi."),
    _s("E-23", "sorgu", "Argo / yazım hatası yoğun sorgu",
       "Retrieval bozulmaz; guard argoyu da yakalar",
       ["unit/test_guard_selfharm_redteam.py::InputGuardRedTeamTests::test_additional_variants_refused",
        "e2e/test_demo_scenarios.py::GuvenlikTests::test_accent_free_turkish_is_also_caught"]),
    _s("E-24", "sorgu", "Zamir yığını ('bunun onunla ilişkisi ne?')",
       "Rewrite bağımsız sorgu üretir; üretemezse clarify",
       ["unit/test_memory.py::HistoryRewriteTests::test_rewrites_followup_with_history",
        "unit/test_multiturn_deep.py::RewriterDepthTests::test_seven_turn_history_is_truncated"],
       "`clarify` (açıklama isteme) yolu YOK — üretemezse orijinal sorgu kullanılır."),
    _s("E-25", "sorgu", "20+ turlu konuşma",
       "Bağlam penceresi + durum yönetimi; eski/yanlış kanıt büyütülmez",
       ["unit/test_multiturn_deep.py::WindowTruncationTests::test_seventh_turn_keeps_the_newest",
        "unit/test_multiturn_deep.py::RewriterDepthTests::test_long_history_does_not_grow_the_prompt",
        "unit/test_multiturn_deep.py::CostTests::test_one_rewrite_call_per_turn"]),
    _s("E-26", "sorgu", "Konu değişimi ortada",
       "Yeni turda retrieval yeniden değerlendirilir",
       ["unit/test_multiturn_deep.py::TopicSwitchAndReturnTests"
        "::test_old_context_is_gone_once_it_falls_out_of_the_window",
        "unit/test_multiturn_deep.py::TopicSwitchAndReturnTests::test_turn_order_is_preserved"]),
    _s("E-27", "sorgu", "Aynı soru 100 kez (spam)",
       "Cache + oran sınırı; maliyet tavanı",
       ["unit/test_budget.py", "unit/test_http_hardening.py",
        "e2e/test_demo_scenarios.py::DayaniklilikTests::test_repeated_identical_question_is_stable",
        "unit/test_concurrency_multitenant.py::BudgetCounterTests"
        "::test_no_thread_passes_once_the_cap_is_exceeded"]),
    _s("E-28", "sorgu", "Cevabı kaynakta OLMAYAN ama makul görünen soru",
       "Çekimser",
       ["e2e/test_demo_scenarios.py"],
       "Golden set'te 22 alan-içi `unanswerable` item var ama ÇEKİMSERLİK EŞİĞİ "
       "kalibre edilmedi (#60) — oran ölçülmedi."),
    _s("E-29", "sorgu", "Çelişkili kaynaklar (iki sayfa farklı şey diyor)",
       "Çelişki bildirilir, biri sessizce seçilmez",
       [],
       "KAPSANMIYOR. Çelişki tespiti YOK."),
    _s("E-30", "sorgu", "Ölçü birimi/sayı içeren soru ('kaç kromozom?')",
       "Sayı doğruluğu; dedup riski",
       ["unit/test_distill.py::DistillTests::test_near_duplicate_dropped"],
       "Sayı doğruluğu ölçülmedi; yalnız dedup'ın sayı farkını koruduğu sınandı."),
    _s("E-31", "sorgu", "Öğrenci ödevini/sınavını yaptırmaya çalışıyor",
       "Politika kararı gerekiyor (Kadir)",
       [],
       "KAPSANMIYOR — POLİTİKA KARARI BEKLİYOR (#90)."),
    _s("E-32", "sorgu", "Öğrenci duygusal destek arıyor ('çok kötüyüm')",
       "Kriz protokolü + insan yönlendirme",
       ["unit/test_guard_selfharm_redteam.py"],
       "Guard yakalıyor ama KRİZ HATTI METNİ yok (#45, Kadir onayı bekliyor)."),
]

# --- 4.3 Yetki / kimlik kırılmaları --------------------------------------
AUTHZ = [
    _s("E-40", "yetki", "Rol alanı hiç gönderilmez", "Fail-closed red",
       ["unit/test_audit_fixes.py::GuardHardeningTests::test_strict_role_required_fails_closed",
        "unit/test_service_authz_adversarial.py",
        "unit/test_llm_failure_paths.py::SummaryAndQuestionPathTests"
        "::test_missing_role_is_a_different_reason_than_a_failure"]),
    _s("E-41", "yetki", "Tanınmayan rol (`manager`, `Öğrenci`, `STUDENT `)",
       "Fail-closed red",
       ["unit/test_role_change_midsession.py::SummaryAndQuestionPathTests"
        "::test_unknown_role_is_not_fail_open",
        "unit/test_service_authz_adversarial.py"]),
    _s("E-42", "yetki", "İstemci scope'u kendi yetkisi gibi bildirir",
       "Sunucu gerçeğiyle karşılaştırılır, red",
       ["unit/test_service_authz_adversarial.py",
        "unit/test_registry.py::RoutingTests::test_routing_is_not_authorization"]),
    _s("E-43", "yetki", "Öğrencinin rolü oturum ortasında değişir",
       "Sonraki istekte yeni rol; atıfa tıklayınca ACL yeniden kontrol",
       ["unit/test_role_change_midsession.py::RoleIsDerivedPerRequestTests",
        "unit/test_role_change_midsession.py::CacheKeyCarriesRoleTests",
        "unit/test_role_change_midsession.py::NarrowedAuthorizationTakesEffectTests"],
       "'Atıfa tıklayınca yeniden kontrol' BACKEND'in işi — burada sözleşme "
       "tarafı sınandı, uçtan uca değil."),
    _s("E-44", "yetki", "Chunk meta'sında `sinif`/`ders` eksik", "Deny",
       ["unit/test_kasa_izolasyon.py", "unit/test_service_authz_adversarial.py"]),
    _s("E-45", "yetki", "İki okul aynı ders adını kullanıyor",
       "Kiracı ayrımı anahtarda; cache paylaşmaz",
       ["unit/test_concurrency_multitenant.py::CrossTenantLeakTests",
        "unit/test_cache_invalidation.py::RoleAndScopeStillSeparateTests"],
       "Anahtar `sinif`+`ders`+rol taşıyor ama AYRI BİR `tenant` alanı YOK: "
       "iki okulun 10/biyolojisi aynı korpussa aynı anahtarı paylaşır."),
    _s("E-46", "yetki", "Veli öğrencinin sorusunu görmek istiyor",
       "Politika: veli yalnız rapor görür",
       [],
       "KAPSANMIYOR — POLİTİKA KARARI BEKLİYOR (BL-011)."),
    _s("E-47", "yetki", "Öğretmen başka sınıfın kaynağını yüklüyor",
       "Backend sorumluluğu; sözleşme testi gerekli",
       ["unit/test_bridge_contract.py"],
       "Sözleşme tarafı sınandı; gerçek backend ile uçtan uca DEĞİL (#95)."),
]

# --- 4.4 Model / LLM kırılmaları -----------------------------------------
LLM = [
    _s("E-60", "llm", "LLM boş içerik döndürür (reasoning bütçesi)",
       "Yakalanır, çekimser/retry — EXP-009'da GERÇEKLEŞTİ",
       ["unit/test_generate.py", "unit/test_memory.py::HistoryRewriteTests"
        "::test_error_fail_safe_returns_original",
        "unit/test_multiturn_deep.py::MalformedHistoryTests"
        "::test_empty_rewrite_keeps_the_original"]),
    _s("E-61", "llm", "LLM bozuk JSON döndürür (guard)",
       "Kritik kategoride fail-closed",
       ["unit/test_guard_llm.py::LLMSafetyClassifierTests::test_parse_error_fail_safe_allow",
        "unit/test_guard_llm.py::LLMSafetyClassifierTests::test_unknown_category_falls_back",
        "unit/test_eval_judge.py::JudgeModelTests::test_unparsable_output_raises_instead_of_lying"]),
    _s("E-62", "llm", "LLM 429 / timeout / 5xx",
       "Retry + devre kesici + anlamlı mesaj",
       ["unit/test_llm_resilience.py",
        "unit/test_llm_failure_paths.py::ChatPathTests",
        "unit/test_llm_failure_paths.py::BreakerProductEffectTests"]),
    _s("E-63", "llm", "LLM sağlayıcısı model kimliğini değiştirir",
       "Fiyat/alias tablosu uyarır, servis çökmez",
       ["unit/test_pricing.py", "unit/test_provider_config.py"]),
    _s("E-64", "llm", "LLM dil karıştırır (Çince/Korece sızma)",
       "Dil kontrolü kapısı — EXP-009'da GERÇEKLEŞTİ",
       [],
       "KAPSANMIYOR. Çıktı dili kapısı YOK. EXP-009'da nemotron-lightning'de "
       "gerçekleşti; şu anki üretici modelde görülmedi ama korunmuyor."),
    _s("E-65", "llm", "LLM kaynak metnini birebir kopyalar",
       "Kopyalama kapısı (P-01)",
       [],
       "KAPSANMIYOR. Kopyalama oranı ölçülmüyor."),
    _s("E-66", "llm", "LLM atıf yerine 'Kaynak 3'e göre' yazar",
       "Atıfsız sayılır → çekimser",
       ["unit/test_sentences.py", "unit/test_generate.py::GeneratorCitationTests"]),
    _s("E-67", "llm", "LLM red mesajını taklit eder",
       "⚠️ şüphe, doğrulanmadı",
       [],
       "KAPSANMIYOR. Modelin kendi 'çekimserim' metnini üretip gerçek red gibi "
       "görünmesi ölçülmedi."),
    _s("E-68", "llm", "Sağlayıcı kotası dolar (ücretsiz uç)",
       "Yedek sağlayıcıya düşme + alarm — EXP-009'da GERÇEKLEŞTİ",
       ["unit/test_llm_resilience.py::CircuitBreakerTests",
        "unit/test_llm_failure_paths.py::ChatPathTests::test_student_sees_turkish_non_technical_text"],
       "Devre kesici var; YEDEK SAĞLAYICIYA DÜŞME yok."),
]

# --- 4.5 Operasyon kırılmaları -------------------------------------------
OPS = [
    _s("E-80", "ops", "Servis yeniden başlar", "İndeks kalıcı",
       [],
       "KAPSANMIYOR. İndeks in-memory; yeniden başlatmada her şey kayıp (#75)."),
    _s("E-81", "ops", "Disk dolu / SQLite kilitli", "Anlamlı hata, veri kaybı yok",
       ["unit/test_cache_ops.py::EvictionTests::test_concurrent_writes_do_not_corrupt",
        "unit/test_cache.py::SQLiteCacheEdgeCaseTests::test_corrupted_record_graceful_miss",
        "unit/test_costlog.py::CostlogTests::test_corrupt_line_skipped"],
       "Kilit/bozulma sınandı; DİSK DOLU senaryosu sınanmadı."),
    _s("E-82", "ops", "Embedding modeli indirilemez (ağ yok)",
       "Açık hata; sessiz düşük kalite YOK",
       ["unit/test_model_lifecycle.py", "unit/test_cold_start.py"]),
    _s("E-83", "ops", "İki süreç aynı cache/costlog'a yazar",
       "Kilit + atomik yazım",
       ["unit/test_costlog_hotpath.py", "unit/test_cache_ops.py",
        "unit/test_concurrency_multitenant.py::BudgetCounterTests"]),
    _s("E-84", "ops", "Model sürümü değişir (embedding)",
       "Tam reindex tetiklenir; karışık vektör uzayı YOK",
       ["unit/test_cache_invalidation.py::ReingestInvalidatesTests",
        "unit/test_index_delete_reindex.py::ReindexCycleTests"],
       "Korpus sürümü cache'i geçersiz kılıyor; EMBEDDING MODEL sürümü "
       "anahtarda ayrı bir alan DEĞİL."),
    _s("E-85", "ops", "Öğretmen kaynağı silerken sorgu geliyor",
       "Tutarlı durum; yarım silinmiş kaynak dönmez",
       ["unit/test_index_delete_reindex.py::CascadePropagationTests",
        "integration/test_source_deletion.py::CascadeTests"],
       "Kısmi başarısızlık RAPORLANIYOR ama silme sırasında gelen eşzamanlı "
       "sorgu ölçülmedi (atomik değil)."),
    _s("E-86", "ops", "Aynı anda 100 öğrenci", "Kuyruk + adil paylaşım",
       ["unit/test_concurrency_multitenant.py::ConcurrentServiceTests"],
       "20 eşzamanlı istek hermetik olarak sınandı; 100 öğrenci GERÇEK yükle "
       "ölçülmedi (#M4-6) ve CPU'da rerank 65 s (#96)."),
]

SCENARIOS = INGEST + QUERY + AUTHZ + LLM + OPS
BY_ID = {s.id: s for s in SCENARIOS}

# Kapı T-06'nın MVP eşiği. Karar aracın değil, kapının/insanın.
T06_MVP_THRESHOLD = 0.80


def coverage() -> dict:
    """Alan bazlı ve toplam kapsam. Karar VERMEZ, ölçer."""
    out: dict = {}
    for s in SCENARIOS:
        d = out.setdefault(s.area, {"total": 0, "covered": 0, "missing": []})
        d["total"] += 1
        if s.covered:
            d["covered"] += 1
        else:
            d["missing"].append(s.id)
        if s.partial:
            d.setdefault("partial", []).append(s.id)
    toplam = len(SCENARIOS)
    kapsanan = sum(1 for s in SCENARIOS if s.covered)
    kismi = sum(1 for s in SCENARIOS if s.partial)
    out["_toplam"] = {
        "total": toplam, "covered": kapsanan,
        "ratio": round(kapsanan / toplam, 4) if toplam else None,
        "partial": kismi,
        # TAM kapsam: bağlı testi var VE bilinen bir boşluğu yok. Kapı
        # tartışılırken bakılması gereken sayı budur.
        "full": kapsanan - kismi,
        "full_ratio": round((kapsanan - kismi) / toplam, 4) if toplam else None,
        "missing": [s.id for s in SCENARIOS if not s.covered],
        "partial_ids": [s.id for s in SCENARIOS if s.partial],
    }
    return out
