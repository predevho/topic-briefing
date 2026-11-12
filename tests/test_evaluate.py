from collections import Counter

from pipeline.evaluate import (
    DEFAULT_LIMIT,
    PER_SOURCE_CAP,
    display_width,
    format_distribution,
    format_table,
    pad,
    sample_items,
)
from pipeline.models import RankedItem, RawItem, ScoreItem


def _raw(index: int, source: str = "s") -> RawItem:
    return RawItem(
        source=source,
        title=f"t{index}",
        url=f"https://e.com/{index}",
        published="2026-11-10T05:30:00+00:00",
        excerpt="e",
    )


def _ranked(score: int, title: str, source: str = "s") -> RankedItem:
    return RankedItem(
        item=RawItem(
            source=source, title=title, url=f"https://e.com/{score}",
            published="2026-11-10T05:30:00+00:00", excerpt="e",
        ),
        score=score,
        reason="이유",
        topic="AI",
    )


# --- 표본 추출 ---

def test_표본_추출이_요청한_개수를_넘지_않는다():
    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    assert len(sample_items(items, limit=30)) == 30


def test_항목이_요청보다_적으면_전부_돌려준다():
    assert len(sample_items([_raw(1)], limit=30)) == 1


def test_표본_추출이_재현_가능하다():
    """프롬프트 변경 효과만 비교하려면 입력이 고정돼야 한다."""
    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    assert sample_items(items, limit=20) == sample_items(items, limit=20)


def test_전역_난수_상태를_건드리지_않는다():
    """random.sample을 직접 쓰면 다른 코드의 재현성에 영향을 준다."""
    import random

    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    random.seed(1)
    먼저 = random.random()
    random.seed(1)
    sample_items(items, limit=10)
    나중 = random.random()

    assert 먼저 == 나중


def test_한_소스가_표본을_독식하지_못한다():
    """**이 태스크의 핵심.** 2026-11-12 실측: 시드 1923건을 균등 무작위로
    40건 뽑으면 OpenAI_Blog가 18건(45%), Hugging_Face_Blog가 7건(17.5%)으로
    **두 소스가 62.5%**를 차지하고 소스 45개 중 14개만 덮었다.

    시드는 400일치라 발행이 잦은 소스가 누적으로 쌓인다(OpenAI 680건).
    실제 운영에서 OpenAI는 240건 중 11건(4.6%)이다. 쏠린 표본으로
    프로필을 튜닝하면 **OpenAI 공지문에 맞춰 기준을 깎게 된다.**
    """
    items = ([_raw(i, "독식소스") for i in range(500)]
             + [_raw(500 + i, f"소스{i}") for i in range(40)])

    표본 = sample_items(items, limit=40)
    집계 = Counter(i.source for i in 표본)

    assert 집계["독식소스"] <= PER_SOURCE_CAP


def test_소스별_상한이_적용된다():
    items = [_raw(i, "한소스") for i in range(100)]
    표본 = sample_items(items, limit=40)

    # 소스가 하나뿐이면 상한만큼만 나온다 — 40건을 채우려고 상한을 깨지 않는다
    assert len(표본) == PER_SOURCE_CAP


def test_여러_소스를_골고루_덮는다():
    """넓게 보려고 쓰는 도구다. 소스 수가 표본 수에 가까워야 한다."""
    items = [_raw(i, f"소스{i % 45}") for i in range(900)]
    표본 = sample_items(items, limit=40)

    assert len({i.source for i in 표본}) >= 20


def test_상한이_1보다_크다():
    """소스당 1건이면 그 소스의 글 품질 분포를 볼 수 없다."""
    assert PER_SOURCE_CAP >= 2


# --- 한글 폭 정렬 ---
#
# 터미널에서 한글은 두 칸을 차지하는데 len()은 1로 센다. 그대로 두면
# 소스 열이 들쭉날쭉해서 표를 읽는 목적이 깨진다.

def test_한글은_두_칸으로_센다():
    assert display_width("토스") == 4


def test_영문은_한_칸으로_센다():
    assert display_width("toss") == 4


def test_섞여_있어도_합이_맞는다():
    assert display_width("토스tech") == 8


def test_폭을_맞춰_채운다():
    assert display_width(pad("토스", 10)) == 10
    assert display_width(pad("Cloudflare", 10)) == 10


def test_폭을_넘으면_자른다():
    assert display_width(pad("토스_기술블로그입니다", 10)) <= 10


# --- 표 ---

def test_표에_점수와_제목과_소스가_들어간다():
    table = format_table([_ranked(90, "좋은 글", "토스_기술블로그")])

    assert "90" in table
    assert "좋은 글" in table
    assert "토스_기술블로그" in table


def test_표에_판단_이유가_들어간다():
    """'왜 이게 뽑혔나'를 보는 게 이 도구의 목적이다."""
    table = format_table([_ranked(90, "글")])
    assert "이유" in table


def test_빈_목록도_표가_된다():
    assert isinstance(format_table([]), str)


def test_표의_소스_열이_정렬된다():
    """한글 소스와 영문 소스가 섞여도 제목이 같은 칸에서 시작해야 한다."""
    table = format_table([
        _ranked(90, "제목A", "토스_기술블로그"),
        _ranked(80, "제목B", "Cloudflare_Blog"),
    ])
    본문 = [l for l in table.splitlines() if "제목" in l]

    시작 = [display_width(l[:l.index("제목")]) for l in 본문]
    assert len(set(시작)) == 1, f"제목 시작 위치가 어긋났다: {시작}"


# --- 점수 분포 ---
#
# 계획 Step 6이 "점수가 60~80에 몰려 있는가"를 확인하라고 하는데, 분포를
# 출력하지 않으면 매번 손으로 세야 한다. 튜닝의 주요 신호다.

def test_분포에_모든_구간이_나온다():
    scores = [ScoreItem(index=i, score=s, reason="r", topic="AI")
              for i, s in enumerate([5, 15, 95])]
    out = format_distribution(scores)

    assert "0~9" in out and "10~19" in out and "90~99" in out


def test_분포에_건수가_나온다():
    scores = [ScoreItem(index=i, score=50, reason="r", topic="AI") for i in range(7)]
    assert "7" in format_distribution(scores)


def test_분포에_중앙값과_최고가_나온다():
    """쏠림을 한눈에 보려면 요약 수치가 필요하다."""
    scores = [ScoreItem(index=i, score=s, reason="r", topic="AI")
              for i, s in enumerate([10, 50, 92])]
    out = format_distribution(scores)

    assert "92" in out and "50" in out


def test_100점도_구간에_들어간다():
    """(score // 10) * 10이면 100이 별도 구간이 된다."""
    scores = [ScoreItem(index=0, score=100, reason="r", topic="AI")]
    out = format_distribution(scores)

    assert "90~100" in out or "90~99" in out
    assert "100~109" not in out


def test_점수가_없으면_분포도_문자열이다():
    assert isinstance(format_distribution([]), str)


def test_기본_표본_크기가_상한_안에_있다():
    """rank가 363건을 넘으면 거부한다. 기본값이 그 안이어야 한다."""
    from pipeline.rank import max_items_per_call

    assert DEFAULT_LIMIT <= max_items_per_call()
