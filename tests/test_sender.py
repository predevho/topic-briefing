from pipeline.lib.sender import ConsoleSender, Sender, collect_warnings
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
