"""#8 Veri damıtma (dedup) testleri — hermetik."""
import unittest

from src.ingest.distill import distill_units, _signature


class _U:
    def __init__(self, text): self.text = text


class DistillTests(unittest.TestCase):
    def test_exact_duplicate_dropped_first_kept(self):
        a = _U("Mitokondri hücrenin enerji santralidir ve ATP üretir.")
        b = _U("Mitokondri hücrenin enerji santralidir ve ATP üretir.")   # birebir tekrar
        c = _U("Ribozomlar protein sentezinin yapıldığı organellerdir.")
        kept, rep = distill_units([a, b, c])
        self.assertEqual(kept, [a, c])            # ilk kopya (a) kalır, b düşer
        self.assertEqual(rep.dropped_exact, 1)
        self.assertEqual(rep.kept, 2)

    def test_boilerplate_repeated_collapses_to_one(self):
        boiler = "Bu etkinliği yaparken laboratuvar güvenlik kurallarına mutlaka uyunuz."
        units = [_U(boiler), _U("Özgün içerik biri."), _U(boiler), _U(boiler),
                 _U("Özgün içerik iki.")]
        kept, rep = distill_units(units)
        texts = [u.text for u in kept]
        self.assertEqual(texts.count(boiler), 1)  # 3 kopya → 1
        self.assertEqual(rep.dropped_exact, 2)

    def test_near_duplicate_dropped(self):
        a = _U("Hücre zarı seçici geçirgen bir yapıdır ve madde giriş çıkışını düzenler burada.")
        b = _U("Hücre zarı seçici geçirgen bir yapıdır ve madde giriş çıkışını düzenler orada.")  # 1 kelime farkı
        kept, rep = distill_units([a, b], near_threshold=0.9)
        self.assertEqual(kept, [a])
        self.assertEqual(rep.dropped_near, 1)

    def test_unique_kept(self):
        units = [_U("Konu A hakkında uzun ve özgün bir açıklama metni burada yer alır."),
                 _U("Tamamen farklı konu B için bambaşka özgün bir paragraf yazılmıştır.")]
        kept, rep = distill_units(units)
        self.assertEqual(len(kept), 2)
        self.assertEqual(rep.dropped_exact + rep.dropped_near, 0)

    def test_short_text_never_dropped(self):
        units = [_U("H2O"), _U("H2O"), _U("ATP")]   # <3 sözcük → dedup dışı
        kept, _ = distill_units(units)
        self.assertEqual(len(kept), 3)

    def test_order_preserved(self):
        u = [_U(f"Özgün paragraf numara {i} burada uzunca yer almaktadır.") for i in range(5)]
        kept, _ = distill_units(u)
        self.assertEqual(kept, u)

    def test_signature_prefix(self):
        self.assertEqual(_signature("bir iki üç dört beş altı yedi sekiz dokuz on"),
                         ("bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz"))


if __name__ == "__main__":
    unittest.main()
