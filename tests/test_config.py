import pytest
from pydantic import ValidationError

from pipeline.lib.config import Source, load_interests, load_sources

YAML_OK = """
sources:
  - name: 토스_기술블로그
    url: https://toss.tech/rss.xml
    kind: rss
    weight: 1.3
    lang: ko
    enabled: true
  - name: 꺼진_소스
    url: https://example.com/rss
    kind: rss
    weight: 1.0
    lang: ko
    enabled: false
"""


def test_켜진_소스만_돌려준다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(YAML_OK, encoding="utf-8")

    sources = load_sources(path)

    assert [s.name for s in sources] == ["토스_기술블로그"]


def test_enabled가_없으면_켜진_것으로_본다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n  - name: s\n    url: https://e.com/r\n"
        "    kind: rss\n    weight: 1.0\n    lang: ko\n",
        encoding="utf-8",
    )
    assert len(load_sources(path)) == 1


def test_lang은_ko_또는_en만_받는다():
    with pytest.raises(ValidationError):
        Source(name="s", url="https://e.com", kind="rss", weight=1.0, lang="jp")


def test_weight는_0보다_커야_한다():
    with pytest.raises(ValidationError):
        Source(name="s", url="https://e.com", kind="rss", weight=0, lang="ko")


def test_url이_http로_시작하지_않으면_거부한다():
    """스킴 오타는 수집 때 Permanent가 되어 그 소스만 조용히 죽는다.
    증상이 "며칠째 0건"이라 알아차리기까지 오래 걸리므로 로딩에서 막는다.
    """
    with pytest.raises(ValidationError):
        Source(name="s", url="htp://e.com/r", kind="rss", weight=1.0, lang="ko")


def test_소스_이름이_중복되면_거부한다(tmp_path):
    """source_counts의 키가 되므로 중복되면 집계가 조용히 틀린다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 같은이름, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 같은이름, url: 'https://b.com/r', kind: rss, weight: 1.0, lang: ko}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_소스_주소가_중복되면_거부한다(tmp_path):
    """같은 피드를 두 번 등록하면 같은 글을 두 번 받는다. 중복 제거가
    걸러주더라도 어느 소스에서 왔는지가 임의로 정해져 집계가 흔들린다.
    """
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 이름하나, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 이름둘, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_꺼진_소스도_중복_검사에_들어간다(tmp_path):
    """끈 소스를 켤 때 이름이 겹치는 걸 그때 발견하면 늦다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 같은이름, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 같은이름, url: 'https://b.com/r', kind: rss, weight: 1.0, lang: ko,"
        " enabled: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_소스가_하나도_없으면_거부한다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="비어"):
        load_sources(path)


def test_전부_꺼져_있으면_거부한다(tmp_path):
    """sources는 차 있지만 켜진 게 없으면 수집할 게 없다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: s, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko,"
        " enabled: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="비어"):
        load_sources(path)


def test_관심사_프로필을_그대로_읽는다(tmp_path):
    path = tmp_path / "interests.md"
    path.write_text("# 관심사\n\n백엔드와 AI.\n", encoding="utf-8")

    assert load_interests(path) == "# 관심사\n\n백엔드와 AI."


def test_관심사_프로필이_비어_있으면_거부한다(tmp_path):
    """빈 프로필로 채점하면 LLM이 제 기준으로 점수를 주고, 그 사실이
    출력에 드러나지 않는다. 조용히 틀리는 쪽이라 로딩에서 막는다.
    """
    path = tmp_path / "interests.md"
    path.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="비어"):
        load_interests(path)


# --- 침묵 등급 ---

def test_모르는_침묵_등급을_거부한다():
    """오타가 조용히 기본값으로 떨어지면 그 소스는 엉뚱한 기준으로 감시된다."""
    with pytest.raises(ValidationError):
        Source(
            name="s", url="https://e.com/r", kind="rss",
            weight=1.0, lang="ko", quiet_tier="weekley",   # 오타
        )


def test_등급을_안_적으면_fast다():
    source = Source(name="s", url="https://e.com/r", kind="rss", weight=1.0, lang="ko")

    assert source.quiet_tier == "fast"


def test_실제_소스_목록의_등급_배정():
    """config/sources.yaml의 배정을 고정한다(계획 3 Task 9, 시드 실측).

    계획 원안은 monthly 5 / none 5였다. 하이퍼커넥트를 none으로 옮겼다 —
    2026-04-22 이후 멈춰 2026-11-17 기준 209일이고, monthly(200일)로 두면
    매일 같은 경고가 뜬다.
    """
    from collections import Counter

    sources = load_sources()
    tiers = Counter(s.quiet_tier for s in sources)

    # 우아한형제들(fast)은 2026-11-19에 껐다 — Actions 러너에서만 403(sources.yaml 주석).
    assert tiers == {"fast": 24, "weekly": 10, "monthly": 4, "none": 6}
    by_name = {s.name: s.quiet_tier for s in sources}
    assert by_name["하이퍼커넥트_기술블로그"] == "none"
    # 피드가 최근 20건만 보여 날짜가 적어 보이지만 하루 20건씩 쓰는 곳이다.
    assert by_name["GeekNews"] == "fast"
