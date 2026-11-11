"""config/sources.yaml의 각 피드가 살아있는지 확인한다.

실행: python scripts/check_feeds.py
"""

import sys
from pathlib import Path

import feedparser
import yaml

from pipeline.lib.http import fetch
from pipeline.lib.retry import Permanent, Transient

# 후보 목록은 수십 개라서 소스당 20초(DEFAULT_TIMEOUT)면 전체가 너무 길어진다.
# 이 스크립트는 "살아있나"만 보므로 짧게 끊고, 끊긴 것은 [일시]로 다시 돌린다.
CHECK_TIMEOUT = 10.0


def main() -> int:
    config = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    must_fix: list[str] = []    # 설정을 고쳐야 하는 소스
    flaky: list[str] = []       # 일시 문제일 수 있는 소스

    for source in config["sources"]:
        if not source.get("enabled", True):
            print(f"[   끔] {source['name']}")
            continue

        name, url = source["name"], source["url"]

        try:
            result = fetch(url, timeout=CHECK_TIMEOUT)
        except Permanent as error:
            # 404/403/주소 오타. 고쳐야 한다.
            print(f"[설정] {name}  {error}")
            must_fix.append(name)
            continue
        except Transient as error:
            # 503/타임아웃. 지금만 그럴 수 있다.
            print(f"[일시] {name}  {error}")
            flaky.append(name)
            continue

        feed = feedparser.parse(result.content)
        count = len(feed.entries)

        if count == 0:
            print(f"[ 0건] {name}  ← 파싱은 되지만 항목이 없다. 주소 확인 필요")
            must_fix.append(name)
        else:
            newest = feed.entries[0].get("title", "(제목 없음)")[:40]
            print(f"[{count:3d}건] {name}  최신: {newest}")

        if result.moved_from is not None:
            print(f"         ↳ 영구 이전됨. yaml을 이 주소로 바꾼다: {result.final_url}")
            must_fix.append(name)

    print()
    if must_fix:
        print(f"고쳐야 할 소스 {len(must_fix)}개: {', '.join(must_fix)}")
        print("주소를 바꾸거나 enabled: false로 끈다.")
    if flaky:
        print(f"일시 문제일 수 있는 소스 {len(flaky)}개: {', '.join(flaky)}")
        print("잠시 후 다시 실행해본다. 계속 실패하면 주소를 확인한다.")

    if not must_fix and not flaky:
        print("모든 피드 정상.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
