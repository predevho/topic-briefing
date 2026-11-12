from datetime import date

from pipeline.prune import RETENTION_DAYS, SEED_DIR, expired_dirs, prune

TODAY = date(2026, 11, 10)


def _old(days: int) -> str:
    """오늘로부터 days일 전의 디렉터리 이름."""
    return date.fromordinal(TODAY.toordinal() - days).isoformat()


# --- 대상 선별 ---

def test_보존_기간을_넘긴_디렉터리를_고른다():
    names = ["2026-11-09", "2026-08-01", "2026-01-01"]
    assert expired_dirs(names, today=TODAY) == ["2026-01-01", "2026-08-01"]


def test_결과가_정렬돼_있다():
    """`Path.iterdir()`의 순서는 파일시스템에 달려 있다. 출력이 입력 순서를
    따르면 같은 상태에서 다른 목록이 나와 로그를 비교할 수 없다.
    """
    뒤섞음 = ["2026-01-01", "2026-05-05", "2026-03-03"]
    assert expired_dirs(뒤섞음, today=TODAY) == sorted(뒤섞음)


def test_경계일은_남긴다():
    assert expired_dirs([_old(RETENTION_DAYS)], today=TODAY) == []


def test_경계_하루_전은_지운다():
    assert expired_dirs([_old(RETENTION_DAYS + 1)], today=TODAY) != []


def test_오늘_디렉터리는_남긴다():
    assert expired_dirs([TODAY.isoformat()], today=TODAY) == []


def test_시드_디렉터리는_절대_지우지_않는다():
    """다시 만들 수 없는 데이터다."""
    assert expired_dirs([SEED_DIR], today=date(2030, 1, 1)) == []


def test_날짜가_아닌_이름은_건너뛴다():
    assert expired_dirs(["backup", ".DS_Store"], today=TODAY) == []


def test_날짜처럼_보이지만_아닌_이름도_건너뛴다():
    assert expired_dirs(["2026-13-99", "2026-11", "20260101"], today=TODAY) == []


def test_빈_목록도_처리한다():
    assert expired_dirs([], today=TODAY) == []


# --- 실제 삭제 ---
#
# 계획에는 `main()`만 있어 **삭제 경로가 테스트되지 않았다.** 되돌릴 수 없는
# 작업이라 여기가 가장 중요하다.

def _make(root, name: str, 내용: str = "x") -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "raw.json").write_text(내용, encoding="utf-8")


def test_오래된_디렉터리를_지운다(tmp_path):
    _make(tmp_path, _old(RETENTION_DAYS + 10))
    _make(tmp_path, TODAY.isoformat())

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert 지움 == [_old(RETENTION_DAYS + 10)]
    assert not (tmp_path / _old(RETENTION_DAYS + 10)).exists()
    assert (tmp_path / TODAY.isoformat()).exists()


def test_dry_run은_아무것도_지우지_않는다(tmp_path):
    이름 = _old(RETENTION_DAYS + 10)
    _make(tmp_path, 이름)

    대상 = prune(tmp_path, today=TODAY, dry_run=True)

    assert 대상 == [이름]
    assert (tmp_path / 이름).exists()        # 그대로 있다


def test_시드는_오래돼도_남는다(tmp_path):
    """다시 만들 수 없다. 이 테스트가 깨지면 되돌릴 수 없는 손실이다."""
    _make(tmp_path, SEED_DIR, 내용="시드 1923건")
    _make(tmp_path, _old(RETENTION_DAYS + 10))

    prune(tmp_path, today=date(2030, 1, 1), dry_run=False)

    assert (tmp_path / SEED_DIR / "raw.json").read_text(encoding="utf-8") == "시드 1923건"


def test_날짜가_아닌_디렉터리는_남는다(tmp_path):
    _make(tmp_path, "backup")
    prune(tmp_path, today=date(2030, 1, 1), dry_run=False)

    assert (tmp_path / "backup").exists()


def test_파일은_건드리지_않는다(tmp_path):
    """root 바로 아래의 파일은 날짜 이름이어도 디렉터리가 아니다."""
    (tmp_path / "2026-01-01").write_text("파일이다", encoding="utf-8")

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert 지움 == []
    assert (tmp_path / "2026-01-01").exists()


def test_root가_없으면_조용히_끝난다(tmp_path):
    assert prune(tmp_path / "없는디렉터리", today=TODAY, dry_run=False) == []


def test_지울_것이_없으면_빈_목록이다(tmp_path):
    _make(tmp_path, TODAY.isoformat())
    assert prune(tmp_path, today=TODAY, dry_run=False) == []


def test_여러_개를_한_번에_지운다(tmp_path):
    이름들 = [_old(RETENTION_DAYS + n) for n in (1, 50, 200)]
    for 이름 in 이름들:
        _make(tmp_path, 이름)

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert sorted(지움) == sorted(이름들)
    assert list(tmp_path.iterdir()) == []


def test_보존_기간이_90일이다():
    """스펙 7.5의 값이다. 바꾸려면 스펙도 같이 고친다."""
    assert RETENTION_DAYS == 90
