"""관련 글 연결 — 임베딩.

새 브리핑 글마다 더 이전 날짜의 비슷한 글을 찾아 페이지에 링크로 단다(RAG의 첫걸음).
설계: design/superpowers/specs/2026-11-23-related-articles-design.md

임베딩은 Voyage AI(`voyage-4`)다. Anthropic은 자체 임베딩 모델이 없고 공식 문서가
Voyage를 소개한다. API 키는 MongoDB Atlas에서 발급하지만 **MongoDB를 데이터베이스로
쓰지 않는다** — 벡터는 Supabase(pgvector)에 저장되고, 유사도 검색도 거기서 한다
(`link_related` SQL 함수).

HTTP는 lib/http.post_json에 맡긴다. 429(요청 한도)는 일시 실패로 분류된다 —
결제 수단 없는 계정은 한 번에 많이 보내면 막힌다(2026-11-23 실측: 35건 일괄 429).
"""

from __future__ import annotations

import json
from typing import Callable

from pipeline.lib.http import post_json
from pipeline.lib.retry import Permanent

EMBED_URL = "https://ai.mongodb.com/v1/embeddings"
EMBED_MODEL = "voyage-4"
# DB 컬럼이 vector(1024)다. 바꾸려면 마이그레이션과 전체 재임베딩이 필요하다.
EMBED_DIM = 1024

# 관련 글 규칙. 2026-11-23 기존 35건 실측으로 정했다 — 0.52 이상 13쌍이 대부분 실제로
# 이어지는 주제였고, 0.50~0.52는 "둘 다 AI 이야기" 수준으로 느슨했다(설계 문서).
LINK_THRESHOLD = 0.52
LINK_LIMIT = 3

# 실패 메시지에 쓰는 이름. 키는 헤더에만 있고 URL은 비밀이 아니지만, 이름이 더 읽기 쉽다.
LABEL = "Voyage embeddings"

EMBED_TIMEOUT = 30.0


def embedding_text(
    *, headline: str, overview: str | None, bullets: list[str], why: str
) -> str:
    """글 하나를 임베딩할 텍스트. 헤드라인 + 본문 요약(예전 글은 요점) + 왜 중요한가.

    원문 본문(article_bodies)은 쓰지 않는다 — 공개 요약만 쓴다. 원문 조각 단위
    임베딩은 챗봇 단계에서 따로 한다.
    """
    body = overview or "\n".join(bullets)
    return f"{headline}\n{body}\n{why}"


def embed(
    texts: list[str],
    *,
    api_key: str,
    post: Callable[..., str] = post_json,
) -> list[list[float]]:
    """텍스트들을 임베딩한다. 입력 순서대로 벡터를 돌려준다.

    개수나 차원이 맞지 않으면 Permanent — 어긋난 채 저장되면 엉뚱한 글끼리 묶인다.
    """
    if not texts:
        return []

    reply = post(
        EMBED_URL,
        payload={"input": texts, "model": EMBED_MODEL, "input_type": "document"},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=EMBED_TIMEOUT,
        label=LABEL,
    )
    try:
        data = json.loads(reply)["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise Permanent(f"{LABEL} 응답이 JSON이 아니다: {reply[:200]!r}") from error

    # 응답의 index를 따른다 — 배열 순서에 기대지 않는다.
    vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
    if len(vectors) != len(texts):
        raise Permanent(f"{LABEL}: 벡터 개수 {len(vectors)} ≠ 입력 {len(texts)}")
    if any(len(vector) != EMBED_DIM for vector in vectors):
        raise Permanent(f"{LABEL}: 차원이 {EMBED_DIM}이 아니다 — 모델이나 차원 설정이 바뀌었다")
    return vectors
