import pytest

from pipeline.lib.secrets import optional, require


def test_값이_있으면_돌려준다(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "값")
    assert require("TEST_KEY") == "값"


def test_없으면_즉시_죽는다(monkeypatch):
    """파이프라인 중간에 터지는 것보다 시작할 때 죽는 게 낫다."""
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISSING_KEY"):
        require("MISSING_KEY")


def test_빈_문자열도_없는_것으로_취급한다(monkeypatch):
    """Actions에서 Secret 이름을 틀리면 빈 문자열이 주입된다."""
    monkeypatch.setenv("EMPTY_KEY", "")
    with pytest.raises(RuntimeError, match="EMPTY_KEY"):
        require("EMPTY_KEY")


def test_에러_메시지가_해결_방법을_알려준다(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"\.env"):
        require("SOME_KEY")


def test_optional은_없으면_기본값을_돌려준다(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    assert optional("NOPE") is None
    assert optional("NOPE", "기본값") == "기본값"
