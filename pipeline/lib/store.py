"""저장소.

- LocalStore: 단계 간 중간 산출물 (날짜별 JSON 파일)
- RemoteStore: 실행 이력·발행 이력·본문 (Supabase) — Task 10에서 추가
"""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

# TypeVar는 "어떤 타입이 들어와도 같은 타입으로 나간다"를 타입 검사기에
# 알려준다. read("raw", RawBundle)의 반환형이 RawBundle로 추론된다.
TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_ROOT = Path("data")


class LocalStore:
    """날짜별 디렉터리에 단계 산출물을 JSON으로 읽고 쓴다."""

    def __init__(self, *, date: str, root: Path | None = None) -> None:
        self._dir = (root or DEFAULT_ROOT) / date

    def write(self, name: str, model: BaseModel) -> Path:
        # parents=True: 중간 디렉터리까지 만든다
        # exist_ok=True: 이미 있어도 에러 내지 않는다
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{name}.json"

        # ensure_ascii=False여야 한글이 그대로 저장된다. 기본값(True)이면
        # "제목"처럼 바뀌어 파일을 눈으로 디버깅할 수 없다.
        path.write_text(
            json.dumps(model.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def read(self, name: str, model_type: type[TModel]) -> TModel:
        path = self._dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path}가 없다. '{name}'을 만드는 앞 단계를 먼저 실행한다."
            )
        return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def exists(self, name: str) -> bool:
        return (self._dir / f"{name}.json").exists()
