"""EXP-009 — sağlayıcı yapılandırması (env ile uç nokta/model/anahtar/extra).

NEDEN: `mimari.md §0.1` üretici LLM'i **ADAY** sayıyor; aday karşılaştırması için
uç noktanın KOD DEĞİŞTİRMEDEN değişebilmesi gerekiyor. Bu testler ağ ÇAĞIRMAZ —
yalnız yapılandırma çözümlemesi (öncelik sırası + gövde birleştirme) sınanır.
"""
import json
import os
import unittest
from unittest import mock

from src.providers.llm import LLMClient, LLMConfigError, DEFAULT_BASE, DEFAULT_MODEL
from src.pricing import Usage, cost_usd, resolve


def _clean_env(**over):
    """LLM_*/anahtar env'lerini SIFIRLA, sonra verilenleri koy (test izolasyonu)."""
    base = {k: "" for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
                            "LLM_EXTRA_JSON", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY")}
    base.update(over)
    return mock.patch.dict(os.environ, base, clear=False)


class DefaultsTests(unittest.TestCase):
    def test_defaults_are_deepseek(self):
        with _clean_env():
            c = LLMClient()
        self.assertEqual(c.base_url, DEFAULT_BASE)
        self.assertEqual(c.model, DEFAULT_MODEL)
        self.assertIsNone(c._api_key)
        self.assertEqual(c.extra, {})

    def test_empty_env_counts_as_unset(self):
        """`.env` boş satır bırakıyor (LLM_MODEL=) — bu 'ayarlanmadı' demektir."""
        with _clean_env(LLM_MODEL="   ", LLM_BASE_URL=""):
            c = LLMClient()
        self.assertEqual(c.model, DEFAULT_MODEL)
        self.assertEqual(c.base_url, DEFAULT_BASE)


class EnvOverrideTests(unittest.TestCase):
    def test_env_base_url_model_and_key_reach_client(self):
        """Temiz kesimden sonra sağlayıcı SEÇİMİ yalnız LLM_* adlarıyla yapılır."""
        with _clean_env(LLM_BASE_URL="https://integrate.api.nvidia.com/v1/",
                        LLM_MODEL="moonshotai/kimi-k3", LLM_API_KEY="nv-key"):
            c = LLMClient()
        self.assertEqual(c.base_url, "https://integrate.api.nvidia.com/v1")  # sondaki / atılır
        self.assertEqual(c.model, "moonshotai/kimi-k3")
        self.assertEqual(c._api_key, "nv-key")

    def test_explicit_args_beat_env(self):
        with _clean_env(LLM_BASE_URL="https://env/v1", LLM_MODEL="env-model",
                        LLM_API_KEY="env-key"):
            c = LLMClient(model="arg-model", base_url="https://arg/v1", api_key="arg-key")
        self.assertEqual((c.model, c.base_url, c._api_key),
                         ("arg-model", "https://arg/v1", "arg-key"))

    def test_retired_key_names_refuse(self):
        """Kaldırılan sağlayıcı adları YOK SAYILMAZ — yapılandırma reddedilir.

        Sessiz bir geri düşüş, adı değişmemiş bir operatörü kendi ayar
        dosyasının artık okunmadığını fark ettirmez (filo ad sözleşmesi)."""
        for eski in ("DEEPSEEK_API_KEY", "NVIDIA_API_KEY"):
            with _clean_env(**{eski: "k"}):
                with self.assertRaises(LLMConfigError) as cm:
                    LLMClient()
                mesaj = str(cm.exception)
                self.assertIn(eski, mesaj)              # suçlu ADI söylenir
                self.assertIn("LLM_API_KEY", mesaj)     # yerine geçen ad söylenir
        # Yeni ad DOLU olsa bile eski ad ortamda duruyorsa reddedilir: yarım
        # kalmış bir kurulum sessizce çalışmaya devam etmemeli.
        with _clean_env(LLM_API_KEY="yeni", DEEPSEEK_API_KEY="eski"):
            with self.assertRaises(LLMConfigError):
                LLMClient()

    def test_missing_key_raises_only_on_chat(self):
        with _clean_env():
            c = LLMClient()                                    # import/ctor patlamaz
            with self.assertRaises(RuntimeError):
                c.chat("merhaba")                             # ağa ÇIKMADAN patlar


class ExtraBodyTests(unittest.TestCase):
    """`LLM_EXTRA_JSON` — reasoning modellerinin boş içerik döndürmesini önler."""

    def test_env_extra_parsed(self):
        with _clean_env(LLM_EXTRA_JSON='{"reasoning_effort": "none"}'):
            c = LLMClient()
        self.assertEqual(c.extra, {"reasoning_effort": "none"})

    def test_nested_extra_parsed(self):
        payload = '{"chat_template_kwargs": {"thinking": false}}'
        with _clean_env(LLM_EXTRA_JSON=payload):
            c = LLMClient()
        self.assertEqual(c.extra, {"chat_template_kwargs": {"thinking": False}})

    def test_broken_json_warns_and_is_ignored(self):
        with _clean_env(LLM_EXTRA_JSON="{bozuk"):
            with self.assertWarns(UserWarning):
                c = LLMClient()
        self.assertEqual(c.extra, {})

    def test_non_object_json_warns_and_is_ignored(self):
        with _clean_env(LLM_EXTRA_JSON='["liste"]'):
            with self.assertWarns(UserWarning):
                c = LLMClient()
        self.assertEqual(c.extra, {})

    def test_ctor_extra_beats_env(self):
        with _clean_env(LLM_EXTRA_JSON='{"a": 1}'):
            c = LLMClient(extra={"b": 2})
        self.assertEqual(c.extra, {"b": 2})

    def test_per_call_extra_wins_over_provider_extra(self):
        """guard'ın response_format'ı env'deki genel parametreyi geçersiz kılabilmeli."""
        sent = {}

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return json.dumps({"choices": [{"message": {"content": "ok"}}],
                                   "usage": {"prompt_tokens": 1,
                                             "completion_tokens": 1}}).encode()

        def _fake_urlopen(req, timeout=None):
            sent.update(json.loads(req.data.decode()))
            return _Resp()

        with _clean_env(LLM_EXTRA_JSON='{"reasoning_effort": "none", "temperature": 9}',
                        LLM_API_KEY="k"):
            c = LLMClient()
            with mock.patch("urllib.request.urlopen", _fake_urlopen):
                r = c.chat("soru", extra={"temperature": 0.0})
        self.assertEqual(r.text, "ok")
        self.assertEqual(sent["reasoning_effort"], "none")    # env parametresi geçti
        self.assertEqual(sent["temperature"], 0.0)            # çağrı-başına ezdi


class PricingAliasTests(unittest.TestCase):
    def test_deepseek_flash_alias_resolves(self):
        """Canlı katalog artık 'deepseek-flash' diyor (2026-09-10) — fiyatı bilinmeli."""
        self.assertEqual(resolve("deepseek-flash"), "deepseek-v4-flash")
        usd = cost_usd("deepseek-flash", Usage(input_cache_miss=1_000_000))
        self.assertAlmostEqual(usd, 0.44, places=6)

    def test_nim_free_models_cost_zero_without_warning(self):
        import warnings
        for m in ("moonshotai/kimi-k3", "meta/muse-glimmer-30b",
                  "nvidia/nemotron-3-super-120b-a12b"):
            with warnings.catch_warnings():
                warnings.simplefilter("error")             # uyarı = hata sayılsın
                self.assertEqual(cost_usd(m, Usage(input_cache_miss=10_000, output=500)), 0.0)

    def test_unknown_model_still_warns(self):
        """Bilinmeyen modelin maliyeti sessizce 0 sayılmasın (denetim EXP-007)."""
        with self.assertWarns(UserWarning):
            self.assertEqual(cost_usd("uydurma/model", Usage(output=10)), 0.0)


if __name__ == "__main__":
    unittest.main()
