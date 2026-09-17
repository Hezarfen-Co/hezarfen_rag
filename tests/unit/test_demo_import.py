"""Modül YÜZEYİ: kiracılık temizliğinden sonra demo koşumu import edilebilmeli.

Ölçülen hata (2026-09-17, b2ba173 sonrası doğrulamada): `src/demo/run_student.py`
kaldırılmış `PUBLIC_SCHOOL` sabitini import ediyordu → **ImportError**. CI'daki
`python -m compileall` bunu GÖRMEZ (derleme geçer, import patlar); yalnız
gerçek import yakalar. `src/` içinde hiçbir test bu modülü import etmediği için
kusur yeşil süitten geçmişti — bu test o boşluğu kapatır.
"""
import unittest


class DemoImportTests(unittest.TestCase):
    def test_run_student_module_imports(self):
        import src.demo.run_student as m
        # Okul ZORUNLUDUR ve paylaşılan/"public" bir boyut yoktur; demo kendi
        # okulunu kurar (bkz. guard/tenant.py + demo/school.py).
        self.assertEqual(m.DEMO_OKUL, "demo")


if __name__ == "__main__":
    unittest.main()
