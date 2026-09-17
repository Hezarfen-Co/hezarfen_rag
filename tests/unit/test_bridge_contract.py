"""Backend tel biçimi — anahtar adları SABİTLENİR.

Backend'in kendi testi (`hezarfen_backend/src/ai/rag.rs`:
`rag_payload_keys_are_the_documented_wire_names`) şunu diyor:

    "Services in other languages match on these literals — a rename here
     silently breaks every one of them, so pin the encoding."

Biz o "başka dildeki servis"iz. Bu dosya aynı sabitlemeyi bu tarafta yapar:
backend'de bir alan adı değişirse burada KIRILIR, sessizce yanlış çalışmaz.
Backend deposuna DOKUNULMAZ — yalnız okunur.
"""
import unittest

from src.bridge.contract import (AI_CHAT_CAPABILITY, AI_PROTOCOL,
                                  AI_RAG_CHAT_CAPABILITY, AI_RAG_INDEX_CAPABILITY,
                                  ApiError, ApiRequest, ASSIGNABLE_ROLES,
                                  BlobRequest, ChatReplyPayload, ChatRequestPayload,
                                  ChatTurn, RagFile, RagIndexPayload,
                                  RagIndexReply, RagIndexReplyFile,
                                  RagScopePair, decode_api_response)


class YetenekAdlariTests(unittest.TestCase):
    def test_capability_strings(self):
        self.assertEqual(AI_CHAT_CAPABILITY, "chat.reply")
        self.assertEqual(AI_RAG_INDEX_CAPABILITY, "rag.index")
        self.assertEqual(AI_RAG_CHAT_CAPABILITY, "rag.chat")

    def test_protocol_name(self):
        self.assertEqual(AI_PROTOCOL, "hab/2")

    def test_ai_is_not_an_assignable_role(self):
        """`Role::try_from_str` ROLES üzerinde arar ve `Ai` o listede yoktur."""
        self.assertNotIn("ai", ASSIGNABLE_ROLES)
        self.assertEqual(ASSIGNABLE_ROLES,
                         ("parent", "student", "teacher", "manager", "admin"))


class RagIndexTelBicimiTests(unittest.TestCase):
    def test_keys_match_the_rust_test_exactly(self):
        p = RagIndexPayload(course_note="01NOTE", course="01COURSE",
                            author="01AUTHOR", title="Chapter 3",
                            content="quadratics",
                            files=[RagFile("01FILE", "recap.pdf",
                                           "application/pdf", 12)])
        self.assertEqual(p.to_wire(), {
            "course_note": "01NOTE", "course": "01COURSE", "author": "01AUTHOR",
            "title": "Chapter 3", "content": "quadratics",
            "files": [{"id": "01FILE", "name": "recap.pdf",
                       "content_type": "application/pdf", "size": 12}]})

    def test_files_is_optional_on_the_wire(self):
        """"A note with no attachments is the common case — `files` is optional
        on the wire, so a minimal service need not send it back or expect it." """
        p = RagIndexPayload.from_wire({"course_note": "01NOTE", "course": "01C",
                                       "author": "01A", "title": "t", "content": "c"})
        self.assertEqual(p.files, [])

    def test_index_reply_keys_are_id_and_doc_id(self):
        """Backend `course_note_file.rag_doc_id`'yi bu eşleşmeden doldurur —
        `id` (istekteki `RagFile.id` ile AYNI) → `doc_id`. Anahtar adları
        değişirse backend sessizce boş kalır; bu yüzden sabitlenir."""
        r = RagIndexReply(files=[RagIndexReplyFile(id="01FILE", doc_id="5eda1f0a9c32")])
        self.assertEqual(r.to_wire(), {
            "files": [{"id": "01FILE", "doc_id": "5eda1f0a9c32"}]})

    def test_index_reply_round_trips(self):
        w = {"files": [{"id": "01A", "doc_id": "d1"}, {"id": "01B", "doc_id": "d2"}]}
        r = RagIndexReply.from_wire(w)
        self.assertEqual(r.to_wire(), w)
        self.assertEqual(RagIndexReply.from_wire({}).files, [])

    def test_scope_pair_keys_are_sinif_and_ders(self):
        """rag.chat kapsamı bir (sınıf, ders) ÇİFTİDİR; `sinif=None` sınıfsız
        (okul kulübü/etüt) korpusu gösterir. Boş `sinif` anahtardır ve
        `None`'a normalize edilir."""
        self.assertEqual(RagScopePair(sinif="10", ders="biyoloji").to_wire(),
                         {"sinif": "10", "ders": "biyoloji"})
        self.assertEqual(RagScopePair.from_wire({"sinif": "", "ders": "satranc"}).to_wire(),
                         {"sinif": None, "ders": "satranc"})
        self.assertEqual(RagScopePair.from_wire({"ders": "satranc"}).sinif, None)


class ChatTelBicimiTests(unittest.TestCase):
    def test_request_keys(self):
        p = ChatRequestPayload(message="merhaba", asker_role="student",
                               history=[ChatTurn("user", "önceki"),
                                        ChatTurn("assistant", "cevap")])
        self.assertEqual(p.to_wire(), {
            "message": "merhaba", "asker_role": "student",
            "history": [{"role": "user", "content": "önceki"},
                        {"role": "assistant", "content": "cevap"}]})

    def test_history_is_optional(self):
        p = ChatRequestPayload.from_wire({"message": "hi", "asker_role": "student"})
        self.assertEqual(p.history, [])

    def test_history_is_oldest_first(self):
        """"index 0 is the furthest back, the final element is the turn
        immediately before `message`" — sıra ters çevrilirse model yanlış
        bağlamla konuşur."""
        p = ChatRequestPayload.from_wire({
            "message": "3.", "asker_role": "student",
            "history": [{"role": "user", "content": "1."},
                        {"role": "assistant", "content": "2."}]})
        self.assertEqual([t.content for t in p.history], ["1.", "2."])

    def test_reply_carries_text_only(self):
        """ÜRÜN AÇISINDAN KRİTİK: köprüde `citations` için yer YOK.

        Bu test bir hatayı değil, bir SINIRI kaydeder. `docs/API-CONTRACT.md`
        `citations`/`abstained`/`reason` döndürmeyi vaat ediyor; backend
        köprüsü yalnız `text` kabul ediyor. Sözleşme değişene kadar atıflar
        kullanıcıya ancak metnin İÇİNDE ulaşabilir.
        """
        self.assertEqual(ChatReplyPayload(text="cevap").to_wire(), {"text": "cevap"})

    def test_request_has_no_asker_identity(self):
        """İKİNCİ SINIR: hangi öğrencinin sorduğu köprüde YOK.

        Yalnız `asker_role` geliyor. Kişiselleştirme (öğrencinin notlarını
        okuyup ona göre cevap) bu sözleşmeyle MÜMKÜN DEĞİL."""
        alanlar = set(ChatRequestPayload(message="m", asker_role="student").to_wire())
        self.assertEqual(alanlar, {"message", "asker_role", "history"})
        for yasak in ("user", "user_id", "asker", "student", "class", "course"):
            self.assertNotIn(yasak, alanlar)


class ApiOkumaTests(unittest.TestCase):
    def test_minimal_request_omits_optional_keys(self):
        r = ApiRequest(id="01T", school="demo", path="/users/me")
        self.assertEqual(r.to_wire(), {"id": "01T", "school": "demo",
                                       "path": "/users/me"})

    def test_on_behalf_of_and_query_are_carried(self):
        r = ApiRequest(id="01T", school="demo", path="/notes",
                       query="limit=10&offset=0", on_behalf_of="01USER")
        self.assertEqual(r.to_wire()["query"], "limit=10&offset=0")
        self.assertEqual(r.to_wire()["on_behalf_of"], "01USER")

    def test_blob_request_shape(self):
        b = BlobRequest(id="01T", school="demo", file="01FILE",
                        on_behalf_of="01AUTHOR")
        self.assertEqual(b.to_wire(), {"id": "01T", "school": "demo",
                                       "file": "01FILE", "on_behalf_of": "01AUTHOR"})

    def test_404_is_an_ok_outcome_not_an_error(self):
        """"an API call that ran and answered 404 is an `Ok` carrying that
        status, because the service asked and the API replied." """
        status, body = decode_api_response({"outcome": "ok", "id": "1",
                                         "school": "demo", "status": 404,
                                         "body": None})
        self.assertEqual(status, 404)
        self.assertIsNone(body)

    def test_bridge_refusal_raises(self):
        with self.assertRaises(ApiError):
            decode_api_response({"outcome": "err", "id": "1", "school": "demo",
                              "code": "forbidden_path", "message": "no"})


if __name__ == "__main__":
    unittest.main()
