"""관련 글 연결 — 임베딩 클라이언트 테스트.

실제 Voyage를 부르지 않는다. `post`를 주입해 요청 모양과 응답 검증만 본다.
설계: design/superpowers/specs/2026-11-23-related-articles-design.md
"""

import json

import pytest

from pipeline.lib.related import (
    EMBED_DIM,
    EMBED_MODEL,
    LINK_LIMIT,
    LINK_THRESHOLD,
    embed,
    embedding_text,
)
from pipeline.lib.retry import Permanent


def _reply(vectors, *, shuffle=False):
    data = [{"object": "embedding", "embedding": v, "index": i} for i, v in enumerate(vectors)]
    if shuffle:
        data.reverse()
    return json.dumps({"object": "list", "data": data, "model": EMBED_MODEL,
                       "usage": {"total_tokens": 10}})


def _vec(x: float) -> list[float]:
    return [x] * EMBED_DIM


def test_기준선은_실측으로_정한_값이다():
    """2026-11-23 실측: 0.52 이상 13쌍, 대부분 실제로 이어지는 주제(설계 문서)."""
    assert LINK_THRESHOLD == 0.52
    assert LINK_LIMIT == 3
    assert EMBED_MODEL == "voyage-4" and EMBED_DIM == 1024


def test_본문_요약이_있으면_그걸_쓴다():
    text = embedding_text(headline="H", overview="본문 요약", bullets=["요점"], why="왜")

    assert text == "H\n본문 요약\n왜"


def test_예전_글은_요점을_쓴다():
    text = embedding_text(headline="H", overview=None, bullets=["가", "나"], why="왜")

    assert text == "H\n가\n나\n왜"


def test_요청에_모델과_키와_문서용_표시를_싣는다():
    seen = {}

    def fake(url, *, payload, headers, timeout, label):
        seen.update(url=url, payload=payload, headers=headers, label=label)
        return _reply([_vec(0.1)])

    embed(["글"], api_key="K", post=fake)

    assert seen["payload"] == {"input": ["글"], "model": EMBED_MODEL, "input_type": "document"}
    assert seen["headers"] == {"Authorization": "Bearer K"}
    # 실패 메시지에 키가 실리지 않게 이름으로 쓴다
    assert "K" not in seen["label"]


def test_응답을_입력_순서대로_돌려준다():
    """응답의 index를 따른다 — 배열 순서에 기대지 않는다."""
    vectors = embed(["a", "b"], api_key="K",
                    post=lambda *a, **k: _reply([_vec(0.1), _vec(0.2)], shuffle=True))

    assert [v[0] for v in vectors] == [0.1, 0.2]


def test_입력이_없으면_부르지_않는다():
    calls = []
    assert embed([], api_key="K", post=lambda *a, **k: calls.append(1)) == []
    assert calls == []


def test_개수가_안_맞으면_영구_실패다():
    """글과 벡터가 어긋난 채 저장되면 엉뚱한 글끼리 묶인다."""
    with pytest.raises(Permanent, match="개수"):
        embed(["a", "b"], api_key="K", post=lambda *a, **k: _reply([_vec(0.1)]))


def test_차원이_안_맞으면_영구_실패다():
    """DB 컬럼이 vector(1024)다. 모델이나 차원 설정이 바뀌면 저장에서 터진다."""
    with pytest.raises(Permanent, match="차원"):
        embed(["a"], api_key="K", post=lambda *a, **k: _reply([[0.1] * 512]))


def test_JSON이_아니면_영구_실패다():
    with pytest.raises(Permanent, match="JSON"):
        embed(["a"], api_key="K", post=lambda *a, **k: "<html>maintenance</html>")
