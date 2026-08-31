# RAG — Buglar

> Henüz kod yok → kayıtlı bug yok. Servis geliştikçe buglar buraya, chatbot ile
> **aynı formatta** eklenecek.

| ID | Belirti | Kök neden | Önem | Durum | Fix | Issue |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |

**Kural:** fixlenince `Durum` = **FİXLENDİ** + `Fix` = commit/branch.
İzlenecek erken riskler (henüz bug değil):
- course-notes silinince/güncellenince vektör index'in senkron kalması (reindex).
- yetkisiz-kurs chunk'ının retrieval'da sızması (izolasyon) — kesinlikle 0 olmalı.
