import pytest
from pydantic import ValidationError

from pipeline.lib.llm import TruncatedError
from pipeline.models import RawItem, ScoreItem, ScoreSheet
from pipeline.rank import (
    MAX_OUTPUT_TOKENS,
    TOPICS,
    OUTPUT_TOKENS_PER_ITEM,
    RANK_EFFORT,
    THINKING_ALLOWANCE,
    TOP_N,
    apply_weight,
    build_prompt,
    clamp_score,
    normalize_topic,
    rank,
    rank_max_tokens,
    weighted_score,
)
from tests.fakes import FakeLLM

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _item(index: int, source: str = "토스_기술블로그") -> RawItem:
    return RawItem(
        source=source,
        title=f"제목 {index}",
        url=f"https://e.com/{index}",
        published="2026-11-10T05:30:00+00:00",
        excerpt=f"발췌 {index}",
    )


# --- 가중치 ---

def test_가중치를_점수에_곱한다():
    assert apply_weight(60, 1.3) == 78


def test_가중치_적용_후_100을_넘지_않는다():
    assert apply_weight(90, 1.3) == 100


def test_가중치가_1이면_점수가_그대로다():
    assert apply_weight(73, 1.0) == 73


def test_가중치가_점수를_내릴_수도_있다():
    assert apply_weight(80, 0.9) == 72


# --- 출력 토큰 산정 ---
#
# 2026-11-12 실측: 227건을 한 프롬프트에 넣으면 입력 42,135토큰이고
# 출력은 ScoreItem 한 건당 82토큰이라 18,614토큰이 필요하다. 기본값
# 16,000으로는 잘린다 — 그러면 stop_reason=max_tokens로 와서 재시도해도
# 똑같이 잘린다. 그래서 항목 수에 맞춰 계산한다.

def test_항목_수에_비례해_늘어난다():
    적음 = rank_max_tokens(10)
    많음 = rank_max_tokens(200)
    assert 많음 > 적음


def test_사고_토큰_여유를_더한다():
    """Opus 5.5는 사고가 항상 켜져 있고 사고 토큰도 max_tokens에 든다."""
    assert rank_max_tokens(0) >= THINKING_ALLOWANCE


def test_실측한_227건을_담을_수_있다():
    """출력 18,614토큰 + 사고. 이게 96시간 윈도우의 현실적 상한이다."""
    assert rank_max_tokens(227) >= 18_614 + THINKING_ALLOWANCE


def test_실측값보다_넉넉하게_잡는다():
    """이유 문장이 길어질 수 있다. 실측 82토큰보다 여유를 둔다."""
    assert OUTPUT_TOKENS_PER_ITEM > 82


def test_상한을_넘지_않는다():
    assert rank_max_tokens(100_000) == MAX_OUTPUT_TOKENS


def test_현실적_상한에_여유가_남아_있다():
    """윈도우가 96시간으로 묶여 있어 227건이 현실적 최대였다.
    소스를 늘려도 한동안 버티는지 확인한다 — 이 테스트가 깨지면
    스트리밍을 도입할 때가 된 것이다.
    """
    여유 = (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM
    assert 여유 >= 300, f"항목 {여유}건까지만 담긴다. 227건 실측 대비 여유가 부족하다"


def test_산정한_max_tokens를_LLM에_넘긴다():
    """계산만 하고 넘기지 않으면 아무 의미가 없다."""
    items = [_item(i) for i in range(50)]
    scores = [ScoreItem(index=i, score=70, reason="r", topic="AI") for i in range(50)]
    _, llm = _rank(items, scores)

    assert llm.calls[0]["max_tokens"] == rank_max_tokens(50)


def test_채점은_낮은_effort로_한다():
    """깊은 추론이 필요 없다. 토큰을 아낀다."""
    _, llm = _rank([_item(0)], [ScoreItem(index=0, score=70, reason="r", topic="AI")])
    assert llm.calls[0]["effort"] == RANK_EFFORT == "low"


def test_항목이_너무_많으면_잘리기_전에_거부한다():
    """조용히 잘리는 것보다 이유를 아는 실패가 낫다."""
    한계 = (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM
    items = [_item(i) for i in range(한계 + 1)]
    llm = FakeLLM(responses=[])

    with pytest.raises(TruncatedError, match="항목"):
        rank(
            items=items, interests="i", recent_headlines=[], weights={},
            llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
        )
    assert llm.prompts == []      # 토큰을 쓰지 않고 거부했다


# --- 프롬프트 조립 ---

def test_프롬프트에_관심사_프로필이_들어간다():
    prompt = build_prompt(
        interests="나는 백엔드 개발자다", recent_headlines=[], items=[_item(0)]
    )
    assert "나는 백엔드 개발자다" in prompt


def test_프롬프트에_최근_헤드라인이_들어간다():
    """같은 사건 중복 판정의 입력."""
    prompt = build_prompt(
        interests="i", recent_headlines=["어제 다룬 그 글"], items=[_item(0)]
    )
    assert "어제 다룬 그 글" in prompt


def test_프롬프트에_항목이_번호와_함께_들어간다():
    """LLM이 index로 참조하므로 번호가 정확해야 한다."""
    prompt = build_prompt(interests="i", recent_headlines=[], items=[_item(0), _item(1)])

    assert "[0]" in prompt and "[1]" in prompt
    assert "제목 0" in prompt and "제목 1" in prompt


def test_최근_헤드라인이_없으면_중복_섹션을_생략한다():
    prompt = build_prompt(interests="i", recent_headlines=[], items=[_item(0)])
    assert "최근 발행" not in prompt


def test_프롬프트가_모든_항목에_점수를_요구한다():
    """빠진 항목은 조용히 버려진다. 프롬프트가 전부 채점하라고 말해야 한다."""
    prompt = build_prompt(
        interests="i", recent_headlines=[], items=[_item(i) for i in range(3)]
    )
    assert "3" in prompt and "빠뜨리지" in prompt


def test_발췌를_잘라_토큰을_아낀다():
    긴발췌 = "가" * 2000
    item = RawItem(source="s", title="t", url="https://e.com/1",
                   published="2026-11-10T05:30:00+00:00", excerpt=긴발췌)

    prompt = build_prompt(interests="i", recent_headlines=[], items=[item])
    assert 긴발췌 not in prompt
    assert "가" * 400 in prompt


# --- 선별 ---

def _rank(items, scores, weights=None):
    llm = FakeLLM(responses=[ScoreSheet(scores=scores)])
    return rank(
        items=items,
        interests="i",
        recent_headlines=[],
        weights=weights or {"토스_기술블로그": 1.0},
        llm=llm,
        window_start=WINDOW[0],
        window_end=WINDOW[1],
    ), llm


def test_점수_내림차순으로_정렬한다():
    items = [_item(0), _item(1), _item(2)]
    scores = [
        ScoreItem(index=0, score=50, reason="r", topic="AI"),
        ScoreItem(index=1, score=90, reason="r", topic="AI"),
        ScoreItem(index=2, score=70, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert [r.score for r in bundle.selected] == [90, 70, 50]


def test_상위_N건만_선택한다():
    items = [_item(i) for i in range(TOP_N + 5)]
    scores = [
        ScoreItem(index=i, score=100 - i, reason="r", topic="AI")
        for i in range(TOP_N + 5)
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == TOP_N


def test_전체_점수를_모두_보관한다():
    """탈락 이유를 나중에 조회하려면 전체가 필요하다."""
    items = [_item(i) for i in range(TOP_N + 5)]
    scores = [
        ScoreItem(index=i, score=100 - i, reason=f"이유 {i}", topic="AI")
        for i in range(TOP_N + 5)
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.all_scores) == TOP_N + 5


def test_소스_가중치를_반영한다():
    items = [_item(0, "일반매체"), _item(1, "토스_기술블로그")]
    scores = [
        ScoreItem(index=0, score=70, reason="r", topic="AI"),
        ScoreItem(index=1, score=60, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores, weights={"일반매체": 0.9, "토스_기술블로그": 1.3})

    # 70*0.9=63, 60*1.3=78 → 토스가 앞으로 온다
    assert bundle.selected[0].item.source == "토스_기술블로그"
    assert bundle.selected[0].score == 78


def test_가중치_표에_없는_소스는_1로_본다():
    """설정이 빠져도 죽지 않아야 한다."""
    bundle, _ = _rank([_item(0, "모르는소스")],
                      [ScoreItem(index=0, score=70, reason="r", topic="AI")],
                      weights={})
    assert bundle.selected[0].score == 70


def test_범위를_벗어난_index는_무시한다():
    """LLM이 없는 번호를 돌려줘도 IndexError로 죽지 않아야 한다."""
    items = [_item(0)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=99, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_음수_index는_rank가_막는다():
    """`ScoreItem`에는 제약이 없다(신뢰할 수 없는 입력이므로). `rank`의
    `0 <= index` 검사가 막는다 — 없으면 `index=-1`이 `items[-1]`(마지막
    항목)을 가리킨다.
    """
    items = [_item(0), _item(1)]
    scores = [ScoreItem(index=-1, score=90, reason="r", topic="AI")]
    bundle, _ = _rank(items, scores)

    assert bundle.selected == []


def test_같은_index를_두_번_주면_한_번만_센다():
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=0, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_먼저_나온_점수를_쓴다():
    """중복 index에서 어느 쪽을 쓰는지가 정해져 있어야 한다."""
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=80, reason="먼저", topic="AI"),
        ScoreItem(index=0, score=90, reason="나중", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert bundle.selected[0].reason == "먼저"


def test_채점되지_않은_항목은_빠진다():
    """LLM이 일부를 빼먹으면 그 항목은 순위에 들어올 수 없다.
    all_scores와 수집 건수를 비교하면 누락이 드러난다 —
    main()이 양쪽을 함께 출력한다.
    """
    items = [_item(0), _item(1), _item(2)]
    scores = [ScoreItem(index=0, score=80, reason="r", topic="AI")]
    bundle, _ = _rank(items, scores)

    assert len(bundle.all_scores) == 1
    assert len(bundle.selected) == 1


def test_최고_점수를_기록한다():
    """0건인 날 화면이 "최고 54점 / 기준 60점"을 보여주는 데 쓴다."""
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=50, reason="r", topic="AI"),
        ScoreItem(index=1, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert bundle.max_score == 90


def test_가중치_적용_후의_점수를_최고로_기록한다():
    items = [_item(0, "토스_기술블로그")]
    scores = [ScoreItem(index=0, score=60, reason="r", topic="AI")]
    bundle, _ = _rank(items, scores, weights={"토스_기술블로그": 1.3})

    assert bundle.max_score == 78


def test_수집이_0건이면_최고_점수가_없다():
    llm = FakeLLM(responses=[])
    bundle = rank(
        items=[], interests="i", recent_headlines=[], weights={},
        llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
    )
    assert bundle.max_score is None


def test_채점_결과가_모두_버려져도_최고_점수가_없다():
    """"최고 0점"과 "점수 없음"은 다르다. 0으로 두면 0건인 날 화면이
    "최고 0점"이라고 거짓말한다.
    """
    bundle, _ = _rank([_item(0)], [ScoreItem(index=99, score=90, reason="r", topic="AI")])
    assert bundle.max_score is None


def test_수집_항목이_없으면_LLM을_호출하지_않는다():
    """토큰을 쓰지 않는다."""
    llm = FakeLLM(responses=[])
    bundle = rank(
        items=[], interests="i", recent_headlines=[], weights={},
        llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
    )

    assert bundle.selected == []
    assert llm.prompts == []


def test_윈도우를_그대로_넘긴다():
    bundle, _ = _rank([_item(0)], [ScoreItem(index=0, score=70, reason="r", topic="AI")])
    assert bundle.window_start == WINDOW[0]
    assert bundle.window_end == WINDOW[1]


# --- 상한이 상위 순서를 망치지 않는다 ---
#
# 2026-11-12 실측에서 상위 6건이 전부 100점으로 묶였다. LLM 원점수는 잘
# 퍼져 있었는데(최고 92, 중앙값 30) 우리 가중치 상한이 납작하게 만들었고,
# 하필 상위 10건을 고르는 자리였다.

def test_상한_없는_가중_점수는_100을_넘는다():
    assert weighted_score(90, 1.3) == pytest.approx(117.0)


def test_표시_점수는_여전히_100에서_멈춘다():
    assert apply_weight(90, 1.3) == 100


def test_상한에_묶여도_순서가_유지된다():
    """실측 그대로: 원 90×1.3=117 과 원 85×1.2=102. 둘 다 100으로 표시되지만
    117이 먼저 와야 한다.
    """
    items = [_item(0, "낮은가중"), _item(1, "높은가중")]
    scores = [
        ScoreItem(index=0, score=85, reason="r", topic="AI"),   # ×1.2 = 102.0
        ScoreItem(index=1, score=90, reason="r", topic="AI"),   # ×1.3 = 117.0
    ]
    bundle, _ = _rank(items, scores, weights={"낮은가중": 1.2, "높은가중": 1.3})

    assert [r.score for r in bundle.selected] == [100, 100]     # 둘 다 상한
    assert bundle.selected[0].item.source == "높은가중"           # 순서는 살아 있다


def test_상한_넘는_항목이_TOP_N_경계에서_밀리지_않는다():
    """상한으로 정렬하면 100점 동점자 중 누가 잘리는지가 입력 순서로
    결정된다. 상한 없는 값으로 정렬해야 실제 우열이 반영된다.
    """
    # 11건 모두 가중 후 100을 넘긴다. 진짜 1등은 마지막에 넣는다.
    items = [_item(i, "높은가중") for i in range(TOP_N + 1)]
    scores = [ScoreItem(index=i, score=80, reason="보통", topic="AI")
              for i in range(TOP_N)]
    scores.append(ScoreItem(index=TOP_N, score=95, reason="최고", topic="AI"))

    bundle, _ = _rank(items, scores, weights={"높은가중": 1.3})

    assert len(bundle.selected) == TOP_N
    assert bundle.selected[0].reason == "최고"


def test_최고_점수는_상한_있는_값으로_기록한다():
    """0건인 날 화면이 "최고 117점 / 기준 60점"이면 안 된다."""
    bundle, _ = _rank([_item(0, "높은가중")],
                      [ScoreItem(index=0, score=90, reason="r", topic="AI")],
                      weights={"높은가중": 1.3})
    assert bundle.max_score == 100


# --- topic 계약 ---

def test_초안_topic에는_enum을_걸지_않는다():
    """**규칙: LLM 초안은 느슨하게, 우리 계약은 엄격하게, 경계에서 정규화.**

    enum을 걸면 API가 생성을 제약해 주지만(실측 240/240 준수) **보장은
    아니다** — 같은 종류의 제약인 maxLength가 2026-11-18에 실제로 어겨졌고,
    pydantic이 시트 전체를 거부해 요약 7건이 한꺼번에 날아갔다. 여기서
    같은 일이 생기면 채점 240건이 통째로 날아간다.

    프롬프트가 다섯 값을 명시하고, `normalize_topic`이 모르는 값을 other로
    보내고, `RankedItem`이 계약을 지킨다.
    """
    schema = ScoreSheet.model_json_schema()
    assert "enum" not in schema["$defs"]["ScoreItem"]["properties"]["topic"]

    # 모르는 값도 받아들여야 한다 — 거부하면 전체를 잃는다
    assert ScoreItem(index=0, score=50, reason="r", topic="인공지능").topic == "인공지능"


def test_최종_항목의_topic은_계약을_지킨다():
    from pipeline.models import RankedItem

    with pytest.raises(ValidationError):
        RankedItem(item=_item(0), score=80, reason="r", topic="인공지능")


# --- LLM 출력 정규화 ---
#
# 구조화된 출력의 스키마 제약은 대체로 지켜지지만 **보장이 아니다.**
# 2026-11-18 실측: maxLength 30인 헤드라인이 33자로 왔고 pydantic이 시트
# 전체를 거부해 요약 7건이 한꺼번에 날아갔다. 여기서 같은 일이 생기면
# 채점 240건이 통째로 날아간다.

def test_점수를_0_100으로_자른다():
    assert clamp_score(105) == 100
    assert clamp_score(-5) == 0
    assert clamp_score(80) == 80


def test_모르는_topic은_other로_바꾼다():
    assert normalize_topic("인공지능") == "other"
    assert normalize_topic("AI") == "AI"


def test_TOPICS를_모델에서_끌어온다():
    """손으로 적으면 Topic Literal과 어긋나 멀쩡한 값이 other로 간다."""
    import typing

    from pipeline.models import Topic

    assert TOPICS == frozenset(typing.get_args(Topic))


def test_범위를_넘는_점수가_와도_전체를_잃지_않는다():
    """이게 정규화의 존재 이유다. 한 건 때문에 240건을 잃지 않는다."""
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=105, reason="r", topic="AI"),
        ScoreItem(index=1, score=70, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 2
    assert bundle.selected[0].score == 100


def test_모르는_topic이_와도_전체를_잃지_않는다():
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=90, reason="r", topic="인공지능"),
        ScoreItem(index=1, score=70, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 2
    assert bundle.selected[0].topic == "other"


def test_정규화한_값이_all_scores에_들어간다():
    """원본을 담으면 evaluate의 분포에 105점이 찍히고 DB 적재가 거부한다."""
    scores = [ScoreItem(index=0, score=105, reason="r", topic="인공지능")]
    bundle, _ = _rank([_item(0)], scores)

    assert bundle.all_scores[0].score == 100
    assert bundle.all_scores[0].topic == "other"
