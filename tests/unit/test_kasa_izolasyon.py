"""Faz 1.6 birim testleri — KASA İZOLASYONU: role_ctx retrieval filtresi (0 sızıntı)."""
import unittest

from src.retrieve import HybridRetriever
from src.guard import RoleContext, Role


class _Emb:
    def embed(self, texts): return [[0.0]]
    def embed_sparse(self, texts): return [{}]


class _Idx:
    """search(q, k) -> sabit (chunk_id, skor) listesi (3 farklı kasa)."""
    def __init__(self, hits): self._hits = hits
    def search(self, q, k=20, school=None): return self._hits[:k]


def _retriever(meta):
    hits = [("c_12bio", 3.0), ("c_9bio", 2.0), ("c_12fizik", 1.0), ("c_bilinmeyen", 0.5)]
    return HybridRetriever(_Emb(), _Idx(hits), _Idx(hits), sparse=None, meta=meta)


_META = {
    "c_12bio": {"school": "okul-a", "sinif": "12", "ders": "biyoloji"},
    "c_9bio": {"school": "okul-a", "sinif": "9", "ders": "biyoloji"},
    "c_12fizik": {"school": "okul-a", "sinif": "12", "ders": "fizik"},
    # c_bilinmeyen meta'da YOK -> no-leak deny
}


class KasaIzolasyonTests(unittest.TestCase):
    def test_student_sees_only_own_class_and_course(self):
        r = _retriever(_META)
        rc = RoleContext(role=Role.STUDENT, sinif="12", ders_list=["biyoloji"])
        got = [cid for cid, _ in r.retrieve("soru", top_k=10, role_ctx=rc, school="okul-a")]
        self.assertEqual(got, ["c_12bio"])                 # yalnız 12-biyoloji
        self.assertNotIn("c_9bio", got)                    # farklı sınıf sızmadı
        self.assertNotIn("c_12fizik", got)                 # farklı ders sızmadı
        self.assertNotIn("c_bilinmeyen", got)              # meta'sız -> no-leak deny

    def test_no_role_ctx_returns_every_chunk_of_the_school(self):
        r = _retriever(_META)
        got = [cid for cid, _ in r.retrieve("soru", top_k=10, school="okul-a")]  # rol yok
        self.assertEqual(len(got), 3)       # okulun TÜM damgalı chunk'ları (rol filtresi yok)

    def test_admin_sees_all(self):
        r = _retriever(_META)
        rc = RoleContext(role=Role.ADMIN)
        got = [cid for cid, _ in r.retrieve("soru", top_k=10, role_ctx=rc, school="okul-a")]
        # admin tüm meta'lı chunk'ları görür; meta'sız yine deny (bilinmeyen kaynak)
        self.assertIn("c_12bio", got)
        self.assertIn("c_9bio", got)
        self.assertIn("c_12fizik", got)

    def test_role_without_meta_fails_closed(self):
        # AUDIT EXP-007 (core #1): role_ctx verildi AMA meta yok → FAIL-CLOSED (boş).
        # Eskiden filtre sessizce atlanıp TÜM chunk'lar dönüyordu (kasa sızıntısı /
        # fail-open); artık rol-filtresi istenip uygulanamıyorsa sızıntıdansa boş döner.
        r = _retriever(meta=None)
        rc = RoleContext(role=Role.STUDENT, sinif="12", ders_list=["biyoloji"])
        got = [cid for cid, _ in r.retrieve("soru", top_k=10, role_ctx=rc, school="okul-a")]
        self.assertEqual(got, [])                          # fail-closed: 0 sızıntı

    def test_teacher_other_class_zero_leak(self):
        r = _retriever(_META)
        rc = RoleContext(role=Role.TEACHER, sinif="9", ders_list=["biyoloji"])
        got = [cid for cid, _ in r.retrieve("soru", top_k=10, role_ctx=rc, school="okul-a")]
        self.assertEqual(got, ["c_9bio"])                  # 9-biyoloji öğretmeni yalnız onu görür


if __name__ == "__main__":
    unittest.main()
