"""중간 산출물 정리: data/의 오래된 날짜 디렉터리를 지운다.

스펙 7.5의 "`data/` 90일 경과분 삭제" 항목이다. 날짜 디렉터리가 무한
증식하는 것을 막는다.

**되돌릴 수 없는 작업이다.** 그래서 지우는 판단(`expired_dirs`)과 지우는
행위(`prune`)를 분리해 양쪽을 테스트한다. `main()`은 배선과 출력만 맡는다.

지우지 않는 것:
- `_seed` — RSS에서 다시 얻을 수 없다(Task 14).
- 날짜 형식이 아닌 이름 — 우리가 만든 것이 아니다.
- 파일 — 날짜 이름이어도 디렉터리가 아니면 건드리지 않는다.
- Supabase — 영구 보관이다(스펙 7.5). 페이지는 거기서 직접 읽는다.

실행:
  python -m pipeline.prune --dry-run   # 지울 목록만 본다
  python -m pipeline.prune             # 실제로 지운다
"""

import argparse
import shutil
from datetime import date
from pathlib import Path

from pipeline.lib.store import DEFAULT_ROOT
from pipeline.seed import SEED_DIR

RETENTION_DAYS = 90


def expired_dirs(names: list[str], *, today: date) -> list[str]:
    """보존 기간을 넘긴 날짜 디렉터리 이름을 **정렬해** 돌려준다.

    정렬하는 이유: `Path.iterdir()`의 순서는 파일시스템에 달려 있다.
    출력이 그 순서를 따르면 같은 상태에서 다른 목록이 나와 로그를 비교할 수 없다.
    """
    cutoff = today.toordinal() - RETENTION_DAYS
    expired: list[str] = []

    for name in names:
        # 시드는 RSS에서 다시 얻을 수 없다. 어떤 경우에도 지우지 않는다.
        # (날짜 형식이 아니라 아래에서도 걸리지만, 의도를 코드에 남긴다.)
        if name == SEED_DIR:
            continue
        try:
            when = date.fromisoformat(name)
        except ValueError:
            # 날짜 형식이 아닌 디렉터리는 건드리지 않는다.
            continue
        # **왕복 비교가 필요하다.** Python 3.11부터 `fromisoformat`이 대시 없는
        # 기본 ISO 형식도 받는다 — `"20260101"`이 2026-01-01로 파싱된다.
        # 우리는 항상 `YYYY-MM-DD`로 만들므로, 그 형태가 아닌 이름은 우리가
        # 만든 것이 아니다. 되돌릴 수 없는 삭제라 좁게 잡는다.
        if when.isoformat() != name:
            continue
        if when.toordinal() < cutoff:
            expired.append(name)

    return sorted(expired)


def prune(root: Path, *, today: date, dry_run: bool) -> list[str]:
    """`root` 아래의 만료된 날짜 디렉터리를 지운다.

    지운(또는 dry_run이면 지울) 이름을 돌려준다. `root`가 없으면 빈 목록이다.
    """
    if not root.exists():
        return []

    # 디렉터리만 본다. 날짜 이름의 파일이 있어도 건드리지 않는다.
    names = [entry.name for entry in root.iterdir() if entry.is_dir()]
    targets = expired_dirs(names, today=today)

    if not dry_run:
        for name in targets:
            # shutil.rmtree는 디렉터리와 그 안의 모든 것을 지운다.
            shutil.rmtree(root / name)

    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="오래된 중간 산출물 정리")
    parser.add_argument("--dry-run", action="store_true", help="지울 목록만 출력")
    args = parser.parse_args()

    root = DEFAULT_ROOT
    if not root.exists():
        print(f"{root}가 없다. 정리할 것이 없다.")
        return

    targets = prune(root, today=date.today(), dry_run=args.dry_run)

    if not targets:
        print(f"보존 기간({RETENTION_DAYS}일)을 넘긴 디렉터리가 없다.")
        return

    표시 = "지울 대상" if args.dry_run else "삭제"
    for name in targets:
        print(f"[{표시}] {root / name}")

    if args.dry_run:
        print()
        print(f"{len(targets)}개가 대상이다. --dry-run 없이 실행하면 삭제된다.")
    else:
        print()
        print(f"{len(targets)}개를 삭제했다. (`{SEED_DIR}`는 보호된다)")


if __name__ == "__main__":
    main()
