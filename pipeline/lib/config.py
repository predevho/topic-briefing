"""소스 설정 로딩.

수집(collect)·선별(rank)·요약(summarize)이 모두 이 모듈로 설정을 읽는다.
설정이 틀렸으면 **파이프라인이 시작하기 전에** 터뜨린다. 07:20에 무인으로
도는 작업이라, 설정 오류가 "그 소스만 며칠째 0건"으로 나타나면 알아차리기까지
오래 걸린다.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_INTERESTS_PATH = Path("config/interests.md")


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    url: str
    kind: Literal["rss"]            # 지금은 rss만. 다른 방식이 생기면 여기 추가한다
    weight: float = Field(gt=0)     # LLM 점수에 곱한다
    lang: Literal["ko", "en"]
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _http로_시작해야_한다(cls, value: str) -> str:
        # pydantic의 HttpUrl을 쓰지 않는 이유: 주소를 정규화해서 되돌려준다
        # (끝에 / 를 붙이는 등). sources.yaml의 주소는 check_feeds.py로 하나하나
        # 확인한 것이라, 로더가 조용히 바꾸면 확인한 의미가 없어진다.
        # 여기서는 형식만 보고 글자는 그대로 넘긴다.
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"url이 http(s)로 시작하지 않는다: {value!r}")
        return value


def _중복(값들: list[str]) -> list[str]:
    보인것: set[str] = set()
    겹친것: set[str] = set()
    for 값 in 값들:
        if 값 in 보인것:
            겹친것.add(값)
        보인것.add(값)
    return sorted(겹친것)


def load_sources(path: Path | None = None) -> list[Source]:
    """켜진 소스만 돌려준다."""
    path = path or DEFAULT_SOURCES_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    all_sources = [Source.model_validate(row) for row in data.get("sources") or []]

    # 중복 검사는 꺼진 소스까지 포함한다. 끈 소스를 다시 켤 때 이름이
    # 겹치는 걸 그때 발견하면 늦다.
    if 겹친이름 := _중복([s.name for s in all_sources]):
        raise ValueError(
            f"소스 이름이 중복됐다: {', '.join(겹친이름)}. "
            f"이름은 집계 키(runs.source_counts)로 쓰이므로 유일해야 한다."
        )

    if 겹친주소 := _중복([s.url for s in all_sources]):
        raise ValueError(
            f"소스 주소가 중복됐다: {', '.join(겹친주소)}. "
            f"같은 피드를 두 번 받으면 어느 소스에서 왔는지가 임의로 정해진다."
        )

    enabled = [s for s in all_sources if s.enabled]
    if not enabled:
        raise ValueError(f"{path}에 켜진 소스가 비어 있다.")

    return enabled


def load_interests(path: Path | None = None) -> str:
    """관심사 프로필 전문. 선별 프롬프트에 그대로 들어간다."""
    path = path or DEFAULT_INTERESTS_PATH
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}가 비어 있다. 선별 기준이 없으면 채점이 무의미하다.")
    return text
