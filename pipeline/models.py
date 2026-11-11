"""단계 간 데이터 계약.

각 단계는 자기 번들을 JSON으로 쓰고, 다음 단계가 그것을 읽는다. 여기서
모양을 한 번만 정의해 "오타난 키가 조용히 통과하는" 사고를 막는다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 카톡 텍스트 템플릿이 200자이고, 머리글 약 20자 + 건당 번호 3자를 빼면
# 헤드라인에 쓸 수 있는 길이가 30자다. 모델이 직접 강제한다.
HEADLINE_MAX = 30

# 본문 추출 경로. 폴백이 일어났는지 기록해 품질 저하를 추적한다.
BodySource = Literal["trafilatura", "rss_excerpt"]

# 수집 실패의 성격. 계획 3의 소스 침묵 경고가 "주소가 죽은 소스"와
# "일시적으로 불안정한 소스"를 구분하는 근거가 된다.
#   config    — 설정을 고쳐야 한다 (404/403/주소 오타)
#   transient — 기다리면 된다 (429/5xx/타임아웃). 재시도 후에도 실패한 경우
#   moved     — 301/308로 이전됐다. 실패는 아니지만 sources.yaml을 고쳐야 한다
ErrorKind = Literal["config", "transient", "moved"]

# 선별이 붙이는 분류. 프롬프트에만 적어 두면 LLM 준수에 의존하게 되고,
# 값이 흔들리면(AI / ai / 인공지능) 집계와 화면 분류가 조용히 깨진다.
# Literal로 두면 JSON 스키마에 enum이 들어가 API가 생성 단계에서 막는다.
# 2026-11-12 실측에서는 240건 모두 아래 다섯 값 안이었다.
Topic = Literal["AI", "backend", "infra", "tooling", "other"]


class Contract(BaseModel):
    """모든 계약 모델의 공통 설정."""

    # frozen: 생성 후 변경 금지. 단계 간 데이터는 흘러가며 바뀌면 안 된다.
    # extra="forbid": 정의하지 않은 키가 들어오면 즉시 에러.
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- 01 수집 ---

class RawItem(Contract):
    source: str
    title: str
    url: str                # 정규화된 URL
    published: str          # UTC ISO 8601
    excerpt: str


class SourceError(Contract):
    source: str
    kind: ErrorKind
    message: str


class RawBundle(Contract):
    window_start: str
    window_end: str
    items: list[RawItem]
    source_counts: dict[str, int]   # 소스 침묵 감지에 쓴다
    errors: list[SourceError]


# --- 02 선별 ---

class ScoreItem(Contract):
    """LLM이 돌려주는 채점 결과 한 건. 입력을 되돌려받지 않고 index로 참조한다."""

    index: int = Field(ge=0)
    score: int = Field(ge=0, le=100)
    reason: str             # 탈락 이유를 나중에 조회하기 위해 항상 남긴다
    topic: Topic


class ScoreSheet(Contract):
    """LLM 구조화된 출력의 최상위 모양."""

    scores: list[ScoreItem]


class RankedItem(Contract):
    item: RawItem
    score: int = Field(ge=0, le=100)
    reason: str
    topic: Topic


class RankedBundle(Contract):
    window_start: str
    window_end: str
    selected: list[RankedItem]      # 상위 N건
    all_scores: list[ScoreItem]     # 전체 — 탈락 이유 조회용
    # 가중치 적용 후 최고 점수. 0건인 날 화면이 "최고 54점 / 기준 60점"을
    # 보여주는 데 쓴다 — 0건이면 articles가 비어서 다른 데서 알 수 없다.
    max_score: int | None = None


# --- 03 본문 ---

class Article(Contract):
    ranked: RankedItem
    body: str
    body_source: BodySource
    # 폴백이 일어난 이유. 경고를 "2건 발췌"가 아니라
    # "403 봇 차단 2건"으로 쓸 수 있게 한다. 폴백이 없으면 None.
    fallback_reason: str | None = None


class ArticlesBundle(Contract):
    window_start: str
    window_end: str
    articles: list[Article]


# --- 04 요약 ---

class SummaryDraft(Contract):
    """LLM이 돌려주는 요약 한 건."""

    index: int = Field(ge=0)
    headline: str = Field(min_length=1, max_length=HEADLINE_MAX)
    bullets: list[str] = Field(min_length=1, max_length=3)
    why_it_matters: str


class SummarySheet(Contract):
    """LLM 구조화된 출력의 최상위 모양. 임계값 미달은 LLM이 아예 빼고 돌려준다."""

    summaries: list[SummaryDraft]


class Summary(Contract):
    article: Article
    headline: str = Field(min_length=1, max_length=HEADLINE_MAX)
    bullets: list[str] = Field(min_length=1, max_length=3)
    why_it_matters: str


class Briefing(Contract):
    window_start: str
    window_end: str
    summaries: list[Summary]    # 0건이 정상 상태다
    considered: int             # 요약 후보로 올린 건수 (적중률 추적용)
