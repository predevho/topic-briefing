import json

from pipeline.lib.sender import (
    ConsoleSender,
    KakaoSender,
    Sender,
    build_kakao_text,
    kakao_len,
    collect_warnings,
)
from pipeline.models import (
    Article,
    Briefing,
    RankedItem,
    RawBundle,
    RawItem,
    SourceError,
    Summary,
)

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _summary(index: int = 0, fallback: bool = False) -> Summary:
    return Summary(
        article=Article(
            ranked=RankedItem(
                item=RawItem(
                    source="토스_기술블로그", title=f"원제 {index}",
                    url=f"https://toss.tech/a/{index}",
                    published="2026-11-10T05:30:00+00:00", excerpt="발췌",
                ),
                score=92, reason="이유", topic="backend",
            ),
            body="본문",
            body_source="rss_excerpt" if fallback else "trafilatura",
            fallback_reason="접근 불가 — HTTP 403" if fallback else None,
        ),
        headline=f"헤드라인 {index}",
        bullets=["첫 요점", "둘째 요점"],
        why_it_matters="중요한 이유",
    )


def _briefing(summaries, considered: int = 10) -> Briefing:
    return Briefing(
        window_start=WINDOW[0], window_end=WINDOW[1],
        summaries=summaries, considered=considered,
    )


def _raw(errors=None) -> RawBundle:
    return RawBundle(
        window_start=WINDOW[0], window_end=WINDOW[1], items=[],
        source_counts={"토스_기술블로그": 3},
        errors=errors or [],
    )


# --- 경고 수집 ---

def test_경고가_없으면_빈_목록이다():
    assert collect_warnings(briefing=_briefing([_summary()]), raw=_raw()) == []


def test_발췌_폴백을_경고로_모은다():
    warnings = collect_warnings(
        briefing=_briefing([_summary(0, fallback=True), _summary(1)]),
        raw=_raw(),
    )
    joined = "\n".join(warnings)

    assert "발췌" in joined
    assert "403" in joined


def test_설정_문제_소스를_경고로_모은다():
    """내가 sources.yaml을 고쳐야 하는 것."""
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="죽은소스", kind="config",
                              message="https://x.com/r HTTP 404")]),
    )
    joined = "\n".join(warnings)

    assert "죽은소스" in joined
    assert "404" in joined


def test_주소_이전을_경고로_모은다():
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="이전된소스", kind="moved",
                              message="old → new (sources.yaml 갱신)")]),
    )
    assert "이전된소스" in "\n".join(warnings)


def test_일시_실패는_경고로_모으지_않는다():
    """내가 할 일이 없다. 매번 알리면 알림 피로가 생긴다."""
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="불안정소스", kind="transient",
                              message="HTTP 503")]),
    )
    assert warnings == []


def test_발췌가_길면_품질_저하로_부르지_않는다():
    """2026-11-12 실측: 크롤링이 막힌 소스가 피드에 전문을 담는다
    (Netflix 15,633자). "품질 저하"라고 쓰면 멀쩡한 날에 경고가 뜬다.
    """
    긴발췌 = _summary(0, fallback=True)
    긴발췌 = Summary(
        article=Article(
            ranked=긴발췌.article.ranked,
            body="가" * 5000,
            body_source="rss_excerpt",
            fallback_reason="접근 불가 — HTTP 403",
        ),
        headline=긴발췌.headline,
        bullets=긴발췌.bullets,
        why_it_matters=긴발췌.why_it_matters,
    )
    warnings = collect_warnings(briefing=_briefing([긴발췌]), raw=_raw())

    assert warnings != []                    # 알리기는 한다
    assert "품질 저하" not in "\n".join(warnings)


# --- 터미널 출력 ---

def test_ConsoleSender가_인터페이스를_만족한다():
    sender = ConsoleSender()

    # Sender가 runtime_checkable이라 실제로 확인된다. 타입 주석만 달면
    # 런타임에는 아무것도 검사되지 않는다.
    assert isinstance(sender, Sender)
    assert sender.name == "console"


def test_헤드라인과_요점과_링크를_출력한다(capsys):
    ConsoleSender().send(briefing=_briefing([_summary()]), raw=_raw())
    out = capsys.readouterr().out

    assert "헤드라인 0" in out
    assert "첫 요점" in out
    assert "중요한 이유" in out
    assert "https://toss.tech/a/0" in out


def test_점수와_출처를_출력한다(capsys):
    """튜닝 중에 '왜 이게 뽑혔나'를 보려면 둘 다 필요하다."""
    ConsoleSender().send(briefing=_briefing([_summary()]), raw=_raw())
    out = capsys.readouterr().out

    assert "92" in out
    assert "토스_기술블로그" in out


def test_건수와_후보_수를_출력한다(capsys):
    ConsoleSender().send(briefing=_briefing([_summary(0), _summary(1)]), raw=_raw())
    out = capsys.readouterr().out

    assert "2건" in out
    assert "10" in out


def test_0건이면_그렇게_출력한다(capsys):
    """조용히 끝나면 시스템이 죽은 것과 구분되지 않는다."""
    ConsoleSender().send(briefing=_briefing([], considered=8), raw=_raw())
    out = capsys.readouterr().out

    assert "없" in out
    assert "8" in out


def test_경고를_하단에_출력한다(capsys):
    ConsoleSender().send(
        briefing=_briefing([_summary(0, fallback=True)]),
        raw=_raw([SourceError(source="죽은소스", kind="config", message="HTTP 404")]),
    )
    out = capsys.readouterr().out

    assert "죽은소스" in out
    assert "403" in out


def test_발췌로_온_건을_표시한다(capsys):
    """요약이 얕을 수 있다는 걸 읽는 사람이 알아야 한다."""
    ConsoleSender().send(briefing=_briefing([_summary(0, fallback=True)]), raw=_raw())
    out = capsys.readouterr().out

    assert "발췌" in out


# --- KakaoSender ---
#
# 200자가 상한이다(스펙 6.1). 넘으면 발송이 거부된다 — 즉 **그날 브리핑이
# 안 간다.** 그래서 조립은 "맞으면 좋겠다"가 아니라 반드시 맞아야 한다.

MAX_TEXT = 200


def test_다섯_건까지는_그대로_싣는다():
    text = build_kakao_text("2026-11-17", ["가" * 10] * 5, total=5)

    assert "1. " in text and "5. " in text
    assert "외" not in text
    assert kakao_len(text) <= MAX_TEXT


def test_여섯_건부터는_외_N건으로_접는다():
    text = build_kakao_text("2026-11-17", ["가" * 10] * 5, total=7)

    assert "외 2건" in text
    assert kakao_len(text) <= MAX_TEXT


def test_DB_상한인_30자_다섯_건은_들어간다():
    """계획서는 "30자 5건이 200자를 넘을 수 있다"고 했지만 **틀렸다.**

    2026-11-17 실측: 198자 / UTF-16 199단위로 들어간다. 여유 1~2자다.
    이 테스트는 그 여유를 고정한다 — 머리글을 한 글자라도 늘리면 여기서
    먼저 깨진다. 실제 발송에서 깨지는 것보다 낫다.
    """
    text = build_kakao_text("2026-11-17", ["가" * 30] * 5, total=7)

    assert kakao_len(text) <= MAX_TEXT
    assert "5. " in text            # 다섯 건 다 실렸다


def test_발행_건수가_두_자리여도_다섯_건이_들어간다():
    """여유가 가장 적은 실제 경우다. "외 7건"이 "외 2건"보다 한 자 길다.
    UTF-16으로 정확히 200단위다 — 1단위만 더 늘면 못 보낸다.
    """
    text = build_kakao_text("2026-11-17", ["가" * 30] * 5, total=12)

    assert kakao_len(text) <= MAX_TEXT
    assert "외 7건" in text


def test_헤드라인이_상한보다_길면_건수를_줄인다():
    """`shorten()`이 30자로 막지만 그게 뚫리는 날을 대비한 가드다
    (HEADLINE_MAX를 올리거나, 스키마만 고치고 조립을 잊는 경우).

    30자로는 이 분기를 밟지 못한다 — 실측으로 36자가 필요하다.
    조용히 잘리는 대신 건수를 줄인다. 잘린 헤드라인은 읽는 사람에게 아무
    뜻이 없지만, 건수가 줄어든 것은 "외 N건"이 알려준다.
    """
    text = build_kakao_text("2026-11-17", ["가" * 36] * 5, total=7)

    assert kakao_len(text) <= MAX_TEXT
    assert "5. " not in text        # 다 싣지 못했다
    assert "외" in text


def test_이모지를_두_단위로_세어_상한을_지킨다():
    """머리글의 📡는 len()으로 1이지만 UTF-16으로는 2다.
    작은 쪽을 믿으면 상한을 넘긴 본문을 내보낼 수 있다.
    """
    text = build_kakao_text("2026-11-17", ["가" * 30] * 5, total=12)

    assert len(text) == 199          # 코드 포인트
    assert kakao_len(text) == 200    # UTF-16 코드 단위 — 상한에 딱 붙는다


def test_한_건도_못_넣으면_건수만_알린다():
    """비정상적으로 긴 헤드라인. 조용히 끝나지 않는 것이 핵심이다."""
    text = build_kakao_text("2026-11-17", ["가" * 400], total=3)

    assert kakao_len(text) <= MAX_TEXT
    assert "외 3건" in text


def test_0건이어도_보낸다():
    """조용히 끝나면 시스템이 죽은 것과 구분되지 않는다 (요구사항 O2)."""
    text = build_kakao_text("2026-11-17", [], total=0)

    assert "0건" in text
    assert kakao_len(text) <= MAX_TEXT


def test_날짜를_월일로_줄인다():
    """200자 안에서 네 글자가 아깝다."""
    text = build_kakao_text("2026-11-17", ["가"], total=1)

    assert "11/17" in text
    assert "2026" not in text


def test_카톡_날짜를_KST로_읽는다():
    """**window_end는 UTC다.** 그대로 [:10]을 자르면 전날이 된다.

    cron이 `20 22 * * 0-4`(22:20 UTC)라서 이건 예외가 아니라 **매 실행**이
    그렇다. 픽스처의 window_end가 바로 그 시각이다:
    2026-11-10T22:20:00+00:00 → KST로는 2026-11-11.

    카톡에 전날 날짜가 찍히면 페이지의 날짜와 어긋난다.
    """
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(data=data)
        return {"result_code": 0}

    KakaoSender(
        access_token="AT", page_url="https://x.test/", post=fake_post
    ).send(briefing=_briefing([_summary()]), raw=_raw())

    text = json.loads(sent["data"]["template_object"])["text"]
    assert "11/11" in text, f"KST 날짜가 아니다: {text!r}"
    assert "11/10" not in text


def test_KakaoSender가_인터페이스를_만족한다():
    sender = KakaoSender(access_token="AT", page_url="https://x.test/")

    assert isinstance(sender, Sender)
    assert sender.name == "kakao"


def test_발송_본문이_form으로_나간다():
    """카카오 토큰 엔드포인트와 발송 엔드포인트 둘 다 JSON 본문을 받지 않는다.
    template_object를 JSON **문자열**로 폼 필드에 넣어야 한다.
    """
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(url=url, data=data, headers=headers)
        return {"result_code": 0}

    KakaoSender(
        access_token="AT", page_url="https://x.test/", post=fake_post
    ).send(briefing=_briefing([_summary()]), raw=_raw())

    assert "template_object" in sent["data"]
    template = json.loads(sent["data"]["template_object"])
    assert template["object_type"] == "text"
    assert template["link"]["web_url"] == "https://x.test/2026-11-11"
    assert sent["headers"]["Authorization"] == "Bearer AT"


def test_버튼은_그날짜_고정주소를_가리킨다():
    """메시지에 링크가 둘인데 우리가 정할 수 있는 것은 버튼뿐이다.

    하단 "IT 브리핑 >" 행은 카카오 콘솔의 등록 웹 도메인이 정하고 콘솔은
    경로를 무시한다(2026-11-17 실측) — 항상 호스트 루트, 즉 전체 목록이다.
    그러니 버튼까지 루트로 두면 링크 둘이 같은 곳으로 간다.

    버튼에 날짜를 박으면 사흘 뒤에 눌러도 그날 브리핑이 열린다.
    루트면 그때의 최신이 열려 메시지 내용과 어긋난다.
    """
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(data=data)
        return {"result_code": 0}

    KakaoSender(
        access_token="AT", page_url="https://x.test", post=fake_post
    ).send(briefing=_briefing([_summary()]), raw=_raw())

    link = json.loads(sent["data"]["template_object"])["link"]
    # window_end가 2026-11-10T22:20Z이므로 KST로 11일이다.
    assert link["web_url"] == "https://x.test/2026-11-11"
    assert link["mobile_web_url"] == link["web_url"]


def test_PAGE_URL_끝의_슬래시가_겹치지_않는다():
    """.env에 슬래시를 붙여 적는 사람이 있다. //가 되면 라우트가 어긋난다."""
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(data=data)
        return {"result_code": 0}

    KakaoSender(
        access_token="AT", page_url="https://x.test/", post=fake_post
    ).send(briefing=_briefing([_summary()]), raw=_raw())

    link = json.loads(sent["data"]["template_object"])["link"]
    assert link["web_url"] == "https://x.test/2026-11-11"
