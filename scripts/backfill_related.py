"""관련 글 연결 — 이미 발행한 글을 한 번 채운다.

매일 실행은 그날 글만 임베딩한다(notify). 관련 글 기능을 켜기 전에 발행한 글은
여기서 한 번 임베딩하고 링크를 만든다. 여러 번 돌려도 같다 — 벡터가 없는 글만
임베딩하고, 링크는 전부 다시 계산한다.

요청 한도: 결제 수단 없는 Voyage 계정은 한 번에 많이 보내면 429다(2026-11-23 실측:
35건 일괄 429, 8건씩 25초 간격은 통과). 그래서 나눠 보내고, 429면 기다렸다 다시 보낸다.

실행: .venv/bin/python -u scripts/backfill_related.py
"""

from __future__ import annotations

import time

from pipeline.lib.related import EMBED_MODEL, LINK_LIMIT, LINK_THRESHOLD, embed, embedding_text
from pipeline.lib.retry import Transient
from pipeline.lib.secrets import require
from pipeline.lib.store import SupabaseStore

BATCH = 8
PAUSE = 25.0
RETRY_PAUSE = 40.0


def main() -> None:
    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))
    key = require("VOYAGE_API_KEY")
    db = remote._db

    articles = (
        db.table("articles")
        .select("id, briefing_date, headline, overview, bullets, why_it_matters")
        .order("briefing_date").order("position").execute().data
    )
    done = {
        row["article_id"]
        for row in db.table("article_embeddings").select("article_id").eq("model", EMBED_MODEL).execute().data
    }
    todo = [a for a in articles if a["id"] not in done]
    print(f"글 {len(articles)}건 · 이미 임베딩 {len(done)}건 · 이번에 {len(todo)}건")

    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        texts = [
            embedding_text(headline=a["headline"], overview=a["overview"],
                           bullets=a["bullets"] or [], why=a["why_it_matters"])
            for a in chunk
        ]
        for attempt in range(4):
            try:
                vectors = embed(texts, api_key=key)
                break
            except Transient as error:
                print(f"  {start}~: {error} → {RETRY_PAUSE:.0f}초 대기 ({attempt + 1})")
                time.sleep(RETRY_PAUSE)
        else:
            raise SystemExit("요청 한도에 계속 걸린다. 잠시 뒤 다시 돌린다(이미 한 것은 건너뛴다).")
        remote.save_embeddings([(a["id"], EMBED_MODEL, v) for a, v in zip(chunk, vectors)])
        print(f"  임베딩 {start + len(chunk)}/{len(todo)}")
        if start + BATCH < len(todo):
            time.sleep(PAUSE)

    ids = [a["id"] for a in articles]
    written = remote.link_related(ids, LINK_THRESHOLD, LINK_LIMIT)
    print(f"관련 글 링크 {written}개 (기준 {LINK_THRESHOLD}, 글마다 최대 {LINK_LIMIT}개)")


if __name__ == "__main__":
    main()
