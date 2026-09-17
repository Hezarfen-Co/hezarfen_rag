"""Backend köprüsü — `hezarfen_backend` ile konuşan taraf.

Bu paket backend deposundan **hiçbir şey değiştirmez**; yalnız onun ilan ettiği
tel biçimini (wire format) Python tarafında karşılar ve testle sabitler.
Kaynak: `hezarfen_backend/src/ai/protocol.rs` (hab/2), `src/ai/chat.rs`,
`src/ai/rag.rs`, `src/web/{notes,course_notes,classes,courses,auth}.rs`.
"""
from .contract import (AI_CHAT_CAPABILITY, AI_RAG_INDEX_CAPABILITY, ApiRequest,
                       BlobRequest, ChatReplyPayload, ChatRequestPayload, ChatTurn,
                       RagFile, RagIndexPayload)
from .dispatch import Dispatcher
from .student import StudentContext, build_context

__all__ = ["AI_CHAT_CAPABILITY", "AI_RAG_INDEX_CAPABILITY", "ApiRequest",
           "BlobRequest", "ChatReplyPayload", "ChatRequestPayload", "ChatTurn",
           "RagFile", "RagIndexPayload", "StudentContext", "build_context",
           "Dispatcher"]
