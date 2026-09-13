"""Faz 1.8 / OPTIMIZATION.md §A — DeepSeek-hakem (LLM-judge) metrikleri.

pip install deepeval BAŞARIYLA kuruldu ve bu ortamda test edildi (gerçek
DeepSeek çağrısıyla FaithfulnessMetric/AnswerRelevancyMetric/GEval ölçüldü,
skorlar döndü) — bu yüzden CUSTOM fallback YOK, DeepEval doğrudan kullanılır
(bkz. src/eval/runner.py raporunda "DeepEval kullanıldı" notu).

DeepEval'in DeepSeek'i hakem model olarak kullanabilmesi için `DeepEvalBaseLLM`
arayüzü sarmalanır (`DeepSeekJudgeModel`) — her gerçek `.chat()` çağrısının
token kullanımı (`Usage`) yan-kanal olarak biriktirilir (`self.usages`) çünkü
DeepEval'in `generate()` sözleşmesi yalnız `str` döner, usage taşımaz; bu
yan-kanal olmadan gerçek maliyet costlog'a yazılamaz.

Metrikler (methodoloji DeepEval'in kendi — RagArt/DeepEval usulü):
  - Faithfulness: cevap, getirilen bağlama (retrieval_context) sadık mı
    (iddiaları context'ten çıkarılabiliyor mu / halüsinasyon var mı).
  - AnswerRelevancy: cevap soruyu (input) karşılıyor mu (alakasız cümle var mı).
  - AnswerCorrectness: G-Eval (chain-of-thought + skor) ile cevap, gold_cevap'a
    (expected_output) kıyasla olgusal doğru mu. DeepEval'de hazır
    "AnswerCorrectnessMetric" YOK — G-Eval, DeepEval'in kendi önerdiği yöntemdir
    (bkz. DeepEval dokümantasyonu: custom criteria + G-Eval).

Maliyet: LLM-hakem PAHALIDIR (Faithfulness+Relevancy+Correctness ~ 8-9 gerçek
DeepSeek çağrısı/item) — bu yüzden yalnız `critical` item'larda + birkaç
örnekte çağrılır (bkz. runner.py `_select_judge_ids`), TÜMÜNDE DEĞİL.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# DeepEval telemetriyi (anonim kullanım istatistiği) devre dışı bırak — bu bir
# kalite/güvenlik testi ortamı, dışarıya sessiz arka-plan çağrısı YAPILMAMALI.
# (import'tan ÖNCE ayarlanmalı.)
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from deepeval.models.base_model import DeepEvalBaseLLM          # noqa: E402
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric, GEval  # noqa: E402
from deepeval.test_case import LLMTestCase, LLMTestCaseParams    # noqa: E402

from ..pricing import Usage, cost_usd as pricing_cost_usd       # noqa: E402
from ..providers.deepseek import DeepSeek                       # noqa: E402

DEEPEVAL_AVAILABLE = True   # bu modül import edilebildiyse kurulum başarılı demektir
JUDGE_METHOD = "deepeval"



def _parse_schema(text: str, schema):
    """Model çıktısını `schema` (pydantic) nesnesine çevirir.

    JSON modu istense de model bazen çıktıyı kod bloğuyla sarıyor ya da
    önüne/arkasına açıklama ekliyor; ham `json.loads` bunda patlar. İlk ve
    son süslü paraneze kadar kırpmak DeepEval'in kendi `trimAndLoadJson`
    davranışıyla aynı yaklaşımdır.
    """
    import json as _json
    ham = (text or "").strip()
    if ham.startswith("```"):
        ham = ham.split("```")[1] if "```" in ham[3:] else ham[3:]
        if ham.lstrip().startswith("json"):
            ham = ham.lstrip()[4:]
    bas, son = ham.find("{"), ham.rfind("}")
    if bas != -1 and son > bas:
        ham = ham[bas:son + 1]
    veri = _json.loads(ham)
    return schema(**veri)


class DeepSeekJudgeModel(DeepEvalBaseLLM):
    """DeepEval `DeepEvalBaseLLM` sarmalayıcısı — hakem = gerçek DeepSeek API.

    `generate()` DeepEval sözleşmesi gereği `schema` verilmediğinde `str`,
    verildiğinde O ŞEMANIN NESNESİNİ döndürür; GERÇEK token
    kullanımı (maliyet için) `self.usages` listesine yan-kanal olarak eklenir.
    `async_mode=False` ile metriklere verildiği için `a_generate` fiilen
    kullanılmaz ama arayüz (abstract method) gereği tanımlanmalı."""

    def __init__(self, model_name: str = "deepseek-chat", temperature: float = 0.0):
        self.temperature = temperature
        self.usages: list[Usage] = []
        self._ds = DeepSeek(model=model_name)
        super().__init__(model_name)

    def load_model(self) -> "DeepSeek":
        return self._ds

    def generate(self, prompt: str, schema=None) -> str:
        # DeepEval `schema` verdiginde (structured-output adimlari: truths/claims/
        # verdicts/reason) DeepSeek'in JSON-mode'unu ZORLA (`response_format:
        # json_object`) -- BULGU: bu olmadan DeepSeek bazen serbest metin/kod-
        # bloguyla sarili JSON dondurup DeepEval'in `trimAndLoadJson`'ini
        # patlatiyordu ("Evaluation LLM outputted an invalid JSON"; ilk kosuda
        # TUM Faithfulness olcumleri boyle basarisiz oldu -- bkz. eval raporu).
        # DeepSeek'in json_object modu, mesajlarda 'json' kelimesi gectiginde
        # calisir; DeepEval'in kendi sablonlari zaten JSON istedigini yaziyor.
        extra = {"response_format": {"type": "json_object"}} if schema is not None else None
        try:
            result = self._ds.chat(prompt, temperature=self.temperature, max_tokens=4096, extra=extra)
        except Exception:
            if extra is None:
                raise
            # fallback: API 'json' kelimesi gecmiyor diye reddederse duz istekle dene
            result = self._ds.chat(prompt, temperature=self.temperature, max_tokens=4096)
        self.usages.append(result.usage)
        if schema is None:
            return result.text
        # KONTROL KOSUMUYLA BULUNDU (#72): burasi her kosulda `str`
        # donduruyordu. deepeval 2.9.3'te `schema` verilen cagri O SEMANIN
        # NESNESINI bekliyor; metin donunce HER metrik `AttributeError:
        # 'str' object has no attribute 'truths'/'statements'/'steps'` ile
        # patliyordu. Yani hakem HIC CALISMIYORDU ve bu hiçbir yerde
        # gorunmuyordu -- `evaluate()` istisnayi `errors`'a yazip None skor
        # donduruyor, rapor da None'lari atliyordu. Kalibrasyon kosumunun
        # ilk ciktisi bu oldu: once hakemin kendisi tamir edilmeli.
        return _parse_schema(result.text, schema)

    async def a_generate(self, prompt: str, schema=None) -> str:
        return self.generate(prompt, schema=schema)

    def get_model_name(self) -> str:
        return self._ds.model

    def usage_since(self, checkpoint: int) -> Usage:
        """`checkpoint` (önceki `len(self.usages)`) SONRASI biriken tüm
        çağrıların toplam kullanımı (bir `evaluate()` çağrısının GERÇEK
        maliyetini hesaplamak için — bir tek metrik ölçümü birden çok LLM
        çağrısı üretir: truth-extraction, claim-extraction, verdict, vb.)."""
        total = Usage()
        for u in self.usages[checkpoint:]:
            total = Usage(input_cache_hit=total.input_cache_hit + u.input_cache_hit,
                          input_cache_miss=total.input_cache_miss + u.input_cache_miss,
                          output=total.output + u.output,
                          reasoning=total.reasoning + u.reasoning)
        return total


_CORRECTNESS_CRITERIA = (
    "Actual output (üretilen cevap), Expected output (referans/gold cevap) ile "
    "karşılaştırıldığında olgusal olarak DOĞRU mu? Gold'da olmayan ama context'le "
    "çelişmeyen ek detay cezalandırılmaz; gold ile ÇELİŞEN ya da UYDURMA (gold'da "
    "karşılığı olmayan iddia) bilgi düşük puan almalı. Eksik ama yanlış olmayan "
    "cevap kısmi puan alır. Köşeli parantez atıf işaretleri [1][2] göz ardı edilir. "
    # KALIBRASYONLA BULUNDU (#72): gold'daki bir iddia TERSİNE çevrildiğinde
    # ("artar" -> "azalır") hakem 0,9 veriyordu. Öğrenciye yanlış öğretilen bir
    # olgu, eksik öğretilenden daha zararlıdır; ölçü bunu yansıtmalı.
    "ÖNEMLİ: gold'daki bir iddianın YÖNÜ tersine çevrilmişse (artar/azalır, "
    "vardır/yoktur, üretir/tüketir gibi) bu ciddi bir olgusal hatadır ve cevap "
    "0,2'nin altında puan almalıdır — cevabın geri kalanı doğru olsa bile."
)


_GROUNDEDNESS_CRITERIA = (
    "Actual output'taki HER iddia, Retrieval context'te AÇIKÇA yer alıyor mu? "
    "Bağlamda karşılığı bulunmayan her ek iddia (tarih, sayı, kişi adı, yer, "
    "sayfa numarası, örnek) puanı ciddi biçimde düşürür — bağlamla çelişmese "
    "bile. Bağlamdan çıkarılamayan tek bir cümle varsa puan 0,5'in altında "
    "olmalıdır. Köşeli parantez atıf işaretleri [1][2] göz ardı edilir."
)


@dataclass
class JudgeResult:
    faithfulness: float | None = None
    faithfulness_reason: str = ""
    answer_relevancy: float | None = None
    answer_relevancy_reason: str = ""
    answer_correctness: float | None = None
    answer_correctness_reason: str = ""
    groundedness: float | None = None
    groundedness_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    model: str = ""
    method: str = JUDGE_METHOD
    errors: list[str] = field(default_factory=list)


class LlmJudge:
    """Golden-set item başına faithfulness/answer_relevancy/answer_correctness
    ölçer. Metrik nesneleri BİR KEZ kurulur (GEval'in evaluation_steps'i ilk
    ölçümde üretilip yeniden kullanılır — item başına tekrar tekrar
    ürettirmemek maliyet tasarrufu sağlar)."""

    def __init__(self, model_name: str = "deepseek-chat", threshold: float = 0.5):
        self.judge_model = DeepSeekJudgeModel(model_name)
        self.faithfulness_metric = FaithfulnessMetric(
            threshold=threshold, model=self.judge_model, include_reason=True,
            async_mode=False,
            # BULGU: gercek (uzun, parent-genisletmeli) bagsam metniyle "truths"
            # cikarma adiminin JSON ciktisi max_tokens'i asip kesiliyordu ("invalid
            # JSON" hatasi HER judge item'inda tekrarlandi) -- sinir koyarak
            # (+ generate()'te max_tokens=4096) kesilmeyi onler.
            truths_extraction_limit=20)
        self.relevancy_metric = AnswerRelevancyMetric(
            threshold=threshold, model=self.judge_model, include_reason=True,
            async_mode=False)
        # KALIBRASYONLA BULUNDU (#72): DeepEval'in `FaithfulnessMetric`'i
        # yalnız bağlamla ÇELİŞEN iddiaları cezalandırıyor. Gold cevabın
        # içine uydurma bir cümle eklendiğinde ("Bu konu 1923'te Ankara'da
        # kanıtlanmıştır") faithfulness **1,000** verdi; 20 vakalık kontrol
        # koşumunda ayırt etme gücü **0,020** çıktı, yani metrik bu ürünün
        # en kritik hata türüne (uydurma) KÖR. Bizim tanımımızda "uydurma",
        # çelişmek değil DESTEKSİZ olmaktır; onu ayrı ölçüyoruz.
        self.groundedness_metric = GEval(
            name="Groundedness", criteria=_GROUNDEDNESS_CRITERIA,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT,
                               LLMTestCaseParams.RETRIEVAL_CONTEXT],
            model=self.judge_model, async_mode=False, threshold=threshold)
        self.correctness_metric = GEval(
            name="AnswerCorrectness", criteria=_CORRECTNESS_CRITERIA,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT,
                              LLMTestCaseParams.EXPECTED_OUTPUT],
            model=self.judge_model, async_mode=False, threshold=threshold)

    def evaluate(self, *, question: str, answer_text: str,
                retrieved_contexts: list[str], gold_answer: str | None) -> JudgeResult:
        checkpoint = len(self.judge_model.usages)
        errors: list[str] = []
        # KALIBRASYONLA BULUNDU (#72): BOŞ cevap faithfulness=1 ve
        # answer_relevancy=1 alıyordu — hiçbir şey söylemeyen bir cevap üç
        # metriğin ikisinde TAM PUAN. Boş cevabın kalitesi ölçülmez, sıfırdır;
        # ayrıca LLM'e sormak bedava değil.
        if not (answer_text or "").strip():
            return JudgeResult(
                faithfulness=0.0, faithfulness_reason="cevap bos",
                answer_relevancy=0.0, answer_relevancy_reason="cevap bos",
                answer_correctness=0.0, answer_correctness_reason="cevap bos",
                groundedness=0.0, groundedness_reason="cevap bos",
                model=self.judge_model.get_model_name())
        contexts = retrieved_contexts or ["(bağlam getirilmedi)"]
        tc = LLMTestCase(input=question, actual_output=answer_text or "",
                         retrieval_context=contexts, expected_output=gold_answer or "")

        f_score = f_reason = None
        try:
            self.faithfulness_metric.measure(tc)
            f_score = self.faithfulness_metric.score
            f_reason = self.faithfulness_metric.reason
        except Exception as e:                                  # pass-bias YASAK: yut(ma)ma, kaydet
            errors.append(f"faithfulness: {type(e).__name__}: {e}")

        r_score = r_reason = None
        try:
            self.relevancy_metric.measure(tc)
            r_score = self.relevancy_metric.score
            r_reason = self.relevancy_metric.reason
        except Exception as e:
            errors.append(f"answer_relevancy: {type(e).__name__}: {e}")

        g_score = g_reason = None
        try:
            self.groundedness_metric.measure(tc)
            g_score = self.groundedness_metric.score
            g_reason = self.groundedness_metric.reason
        except Exception as e:
            errors.append(f"groundedness: {type(e).__name__}: {e}")

        c_score = c_reason = None
        if gold_answer:
            try:
                self.correctness_metric.measure(tc)
                c_score = self.correctness_metric.score
                c_reason = self.correctness_metric.reason
            except Exception as e:
                errors.append(f"answer_correctness: {type(e).__name__}: {e}")
        else:
            c_reason = "gold_cevap yok (edge case) — correctness ölçülemez"

        usage = self.judge_model.usage_since(checkpoint)
        usd = pricing_cost_usd(self.judge_model.get_model_name(), usage) if usage.total else 0.0

        return JudgeResult(faithfulness=f_score, faithfulness_reason=f_reason or "",
                           answer_relevancy=r_score, answer_relevancy_reason=r_reason or "",
                           answer_correctness=c_score, answer_correctness_reason=c_reason or "",
                           groundedness=g_score, groundedness_reason=g_reason or "",
                           usage=usage, cost_usd=usd,
                           model=self.judge_model.get_model_name(), errors=errors)
