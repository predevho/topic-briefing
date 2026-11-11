import pytest

from pipeline.lib.store import LocalStore
from pipeline.models import RawBundle, RawItem


def _bundle() -> RawBundle:
    return RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[RawItem(
            source="s", title="제목", url="https://e.com/a",
            published="2026-11-10T01:00:00+00:00", excerpt="발췌",
        )],
        source_counts={"s": 1},
        errors=[],
    )


def test_쓰고_읽으면_같은_값이_나온다(tmp_path):
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    assert store.read("raw", RawBundle) == _bundle()


def test_날짜별_디렉터리에_저장한다(tmp_path):
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    assert (tmp_path / "2026-11-10" / "raw.json").exists()


def test_한글이_그대로_저장된다(tmp_path):
    """\\uXXXX로 이스케이프되면 파일을 눈으로 볼 수 없다."""
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    text = (tmp_path / "2026-11-10" / "raw.json").read_text(encoding="utf-8")
    assert "제목" in text


def test_없는_파일을_읽으면_친절한_에러가_난다(tmp_path):
    """"앞 단계를 먼저 돌려라"를 알려줘야 한다."""
    store = LocalStore(root=tmp_path, date="2026-11-10")
    with pytest.raises(FileNotFoundError, match="raw"):
        store.read("raw", RawBundle)


def test_다른_날짜는_섞이지_않는다(tmp_path):
    LocalStore(root=tmp_path, date="2026-11-10").write("raw", _bundle())
    other = LocalStore(root=tmp_path, date="2026-11-11")

    with pytest.raises(FileNotFoundError):
        other.read("raw", RawBundle)
