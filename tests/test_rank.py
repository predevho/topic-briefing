import pytest
from pydantic import ValidationError

from pipeline.lib.llm import TruncatedError
from pipeline.models import RawItem, ScoreItem, ScoreSheet
from pipeline.rank import (
    MAX_OUTPUT_TOKENS,
    OUTPUT_TOKENS_PER_ITEM,
    RANK_EFFORT,
    THINKING_ALLOWANCE,
    TOP_N,
    apply_weight,
    build_prompt,
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


def test_음수_index는_계약_경계에서_막힌다():
    """`rank`의 `0 <= index` 검사보다 먼저, pydantic이 거부한다.

    `ScoreItem.index`에 `ge=0`이 있어 **스키마에도 minimum 0이 들어간다** —
    LLM이 음수를 돌려줄 길이 없고, 돌려줘도 파싱에서 걸린다. 검사가
    없으면 `index=-1`이 `items[-1]`(마지막 항목)을 가리킬 뻔했다.
    """
    with pytest.raises(ValidationError):
        ScoreItem(index=-1, score=90, reason="r", topic="AI")


def test_점수_범위도_계약_경계에서_막힌다():
    """0~100을 벗어난 점수는 가중치 계산과 임계값 판정을 무의미하게 만든다."""
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=101, reason="r", topic="AI")
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=-1, reason="r", topic="AI")


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

def test_topic은_정해진_다섯_값만_받는다():
    """프롬프트에만 적어 두면 LLM 준수에 의존한다. 값이 흔들리면
    (AI / ai / 인공지능) 집계와 화면 분류가 조용히 깨진다.
    """
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=50, reason="r", topic="인공지능")


def test_topic이_스키마의_enum으로_나간다():
    """API가 생성 단계에서 막아 주려면 스키마에 enum이 있어야 한다."""
    schema = ScoreSheet.model_json_schema()
    topic = schema["$defs"]["ScoreItem"]["properties"]["topic"]

    assert set(topic["enum"]) == {"AI", "backend", "infra", "tooling", "other"}
