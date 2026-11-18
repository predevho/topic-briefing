# 토픽 컬럼 자동화

매일 아침 IT 토픽을 수집·선별·요약해서 카카오톡으로 받는다.

- 설계: [`design/superpowers/specs/2026-11-10-it-column-automation-design.md`](design/superpowers/specs/2026-11-10-it-column-automation-design.md)
- ERD: [`design/superpowers/specs/2026-11-11-erd.md`](design/superpowers/specs/2026-11-11-erd.md)
- 요구사항 추적표: [`design/superpowers/specs/2026-11-11-requirements.md`](design/superpowers/specs/2026-11-11-requirements.md)
- 구현 계획과 실측 기록: [계획 1](design/superpowers/plans/2026-11-10-briefing-pipeline.md) · [계획 2](design/superpowers/plans/2026-11-12-briefing-page.md) · [계획 3](design/superpowers/plans/2026-11-17-delivery-automation.md)
- **공개 전 점검**: [`design/공개-전-점검.md`](design/공개-전-점검.md) — 이 리포지토리는 **공개**다. 이 점검을 거쳐 공개로 바꿨다

| | 범위 | 상태 |
|---|---|---|
| 계획 1 | 파이프라인 — 수집·선별·본문·요약, 결과는 터미널 | **완료** |
| 계획 2 | 웹페이지 + 좋아요·클릭 | **완료** |
| 계획 3 | 카카오톡 전송 + 슬랙 경고 + 경고 장치 + GitHub Actions | **완료** |

## 준비

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # 값을 채운다
```

`.env`에 필요한 키와 각각의 뜻은 `.env.example`에 있다(Anthropic·Supabase·카카오·
슬랙·페이지 주소·월 예산). GitHub Actions에는 같은 값이 Secrets로 들어간다 —
목록은 `.github/workflows/daily.yml`의 `env`다. Supabase 키 이름 주의: 대시보드의 **Connect** 대화상자에서
URL과 publishable 키를, **Settings → API Keys**에서 secret 키를 받는다
(`Settings → API` 페이지는 없다). `eyJ...`로 시작하는 긴 키는 2026년 말
폐기되는 레거시 키다.

## 매일 실행

**자동으로 돈다.** GitHub Actions가 월~금 07:20 KST에 실행한다
(`.github/workflows/daily.yml`). 아래는 손으로 돌릴 때의 절차다 — 운영은
아래 "운영" 절을 본다.

```bash
python -m pipeline.collect      # 수집  → data/<날짜>/raw.json
python -m pipeline.rank         # 선별  → ranked.json
python -m pipeline.enrich       # 본문  → articles.json
python -m pipeline.summarize    # 요약  → briefing.json
python -m pipeline.notify       # 카톡 발송 + 터미널 출력 + 발행 이력 + 슬랙 경고
```

> **`notify`는 이제 실제 카톡을 보낸다.** 결과만 터미널에서 보려면 `summarize`
> 까지만 돌린다(`briefing.json`). 같은 날 Actions가 이미 보냈으면 `notify`는
> `AlreadySent`로 멈춘다.

**페이지는 아무것도 하지 않아도 갱신된다.** `notify`가 Supabase에 쓰면
페이지가 열릴 때 직접 조회한다 — 빌드도 커밋도 필요 없다(스펙 6.4의 분리).

> <https://topic-briefing.vercel.app/>

프론트엔드 **코드**를 바꿨을 때만 배포한다.

```bash
cd web && npm run build && cd ..
bash scripts/verify_bundle.sh     # secret 키가 안 섞였는지 (배포 전 필수)
git push                          # Vercel이 푸시를 받고 직접 빌드한다
```

빌드 산출물은 커밋하지 않는다. 로컬 빌드는 **검사를 돌리기 위한** 것이다 —
Vercel이 빌드한 것을 나중에 보는 것보다 올리기 전에 보는 쪽이 낫다.

각 단계는 **단독 재실행이 가능하다.** 요약 프롬프트를 고쳤으면
`python -m pipeline.summarize`만 다시 돌린다 — 수집과 선별 비용이 들지 않는다.
단계 사이의 JSON이 그래서 있다.

**실측 소요 시간** (2026-11-12, 소스 45개):

| 단계 | 시간 | 비고 |
|---|---|---|
| collect | 33초 | 96시간 윈도우에서 240건 |
| rank | 65초 | 240건 일괄 채점, 스트리밍 |
| enrich | 21초 | 상위 10건, 요청 간격 1.5초 포함 |
| summarize | 27초 | 10건 → 7건 |
| notify | 2초 | |

## 품질 튜닝

```bash
python -m pipeline.evaluate --limit 40            # 시드로 (소스 넓이)
python -m pipeline.evaluate --date 2026-11-12     # 실제 하루로 (물량)
```

선별을 돌려 점수 분포와 상·하위를 표로 본다. 입력 표본이 고정이라
`config/interests.md` 변경 효과만 비교된다.

- 상위권에 보도자료·홍보 글이 있으면 → `interests.md`의 "낮게 평가"에 패턴 추가
- 하위권에 읽고 싶은 글이 있으면 → "높게 평가"에 특징 추가
- 점수가 한 구간에 몰리면 → 기준이 모호하다는 뜻. 구체적인 예시를 늘린다

**두 모드의 분포가 다른 것은 정상이다.** 시드 표본은 소스별 상한(3건)을 걸어
**소스 넓이**를 대표하고(중앙값 55), 실제 수집은 **물량**을 대표한다(중앙값 30).
`SCORE_THRESHOLD`는 실제 수집 쪽으로 판단한다.

## 점검

```bash
bash scripts/verify_anon_access.sh   # anon 권한 (14개 항목)
bash scripts/verify_bundle.sh        # 번들에 비밀이 섞였는지 (5개 항목)
```

`verify_bundle.sh`는 `grep sb_secret_`으로 보지 않는다 — supabase-js 자신이
키 형식을 판별하려고 그 리터럴을 들고 있어서 **항상 걸린다.** `.env`의 실제
키 값으로 대조한다.

```bash
pytest                              # 전체 테스트 (525개)
python scripts/check_feeds.py       # 소스 피드 생존 확인
python scripts/verify_anon_access.sh # anon 키로 본문이 막히는지
python scripts/smoke_supabase.py    # DB 연결·권한 확인
python scripts/smoke_llm.py         # Claude API 확인
python -m pipeline.prune --dry-run  # 정리 대상 확인
```

`check_feeds.py`는 **피드가 살아 있는지만** 본다. 내용이 관심사에 맞는지와
글이 실제로 올라오는지는 각각 다른 방법으로만 확인된다 — 수집을 한 번
돌려 제목을 읽고, 시드의 소스별 최신 발행일을 본다. 실제로 이 셋이
전부 달랐다(계획 문서의 Task 11·14 참조).

## 알아둘 것

- **수집 윈도우는 "마지막 발송 이후"**다 (상한 96시간). 주말을 쉬면 월요일이
  자동으로 72시간이 되어 주말 해외 콘텐츠가 들어온다.
- **건수는 고정이 아니다.** 점수 임계값(60)을 넘는 것만 보내므로 2건인 날도
  0건인 날도 정상이다. 0건이면 "조용한 날입니다 — 시스템은 정상입니다"가
  출력된다.
- **`notify`를 건너뛰면 안 된다.** 여기서 `runs`를 기록하고, 그게 다음 실행의
  수집 윈도우 시작점이 된다. 안 돌리면 같은 구간을 계속 다시 수집한다.
- **같은 윈도우는 두 번 보내지 않는다.** 다시 보내려면 `--force`.
- **본문은 Supabase의 `article_bodies`에만 있다.** 리포지토리에 커밋하지 않고
  공개 페이지에서도 읽히지 않는다. Phase 3의 RAG 재료다.
- **`data/_seed/raw.json`은 지우지 않는다.** RSS는 과거를 제공하지 않으므로
  다시 만들 수 없다. `~/briefing-seed-backup/`에 백업이 있고 `prune`이
  보호한다.
- **발췌로 요약한 건이 품질 저하라는 뜻은 아니다.** 크롤링이 막히거나 JS로
  그리는 소스가 피드에 본문을 길게 담는 경우가 많다(실측: Netflix 15,633자).
  경고에 본문 길이가 함께 나오므로 그걸 보고 판단한다. 39자면 얕고,
  8,000자면 전문이다.

## 설계에서 반복되는 규칙

실제로 돌려 보며 세 번 이상 쓰인 것들이다. 코드를 고칠 때 참고한다.

1. **분류가 행동을 바꾸는 곳에서만 분류한다.** `Transient`(기다리면 됨) 대
   `Permanent`(고쳐야 함)의 구분은 재시도 여부를 바꾸므로 `lib/http.py` 한곳에
   둔다. 반면 센더는 "어떤 이유로든 하나가 죽어도 나머지는 보낸다"라서
   `except Exception`으로 묶는다.
2. **재시도를 겹치지 않는다.** 전송 계층은 anthropic SDK가(`max_retries`),
   스키마 실패는 `lib/llm`이 1회. 겹치면 한 번의 논리적 호출이 여러 배가 된다.
3. **LLM 초안은 느슨하게, 우리 계약은 엄격하게, 경계에서 정규화.**
   구조화된 출력의 스키마 제약은 대체로 지켜지지만 **보장이 아니다**
   (실측: `maxLength: 30`인 헤드라인이 34자로 와서 요약 7건이 한꺼번에 날아갔다).
   한 건이 어겨도 나머지를 잃지 않게 `rank.clamp_score`·`summarize.shorten`이
   고친다.
4. **조용히 틀리는 것이 터지는 것보다 비싸다.** 07:20에 무인으로 도는
   작업이라, "며칠째 0건"으로 나타나는 실패가 가장 늦게 발견된다. 설정 오류는
   로딩에서, 잘림은 전송 전에, 소스 침묵은 `runs.source_counts`로 잡는다.
5. **되돌릴 수 없는 작업은 두 번 막는다.** 시드는 덮어쓰기를 거부하고
   (`--force` 필요), `prune`은 날짜 형식을 왕복 비교해 우리가 만들지 않은
   디렉터리를 건드리지 않는다.

## 운영

**경고는 슬랙으로만 온다.** 카톡은 브리핑 전용이다(`SlackSender`에는 `send`가
없다). 슬랙에 오는 것:

| 경고 | 뜻 | 할 일 |
|---|---|---|
| 소스 침묵: X — N일째 (기준 M일) | 그 소스에서 M일 넘게 글을 못 봤다 | `check_feeds.py`로 본다. 멈춘 블로그면 `sources.yaml`에서 `quiet_tier: none` |
| 카카오 토큰 만료 N일 남음/지남 | 회전 저장이 실패했거나 오래 멈췄다 | `python scripts/kakao_auth.py` |
| 카카오 토큰 갱신 실패 — 카톡 없이 보냈다 | 오늘 카톡이 안 갔다(페이지는 갱신됨) | 같다 |
| 크레딧: 이번 달 $X / 예산 $Y | 정가 기준 사용액이 예산의 80%를 넘었다 | Console에서 잔액 확인. 예산은 워크플로의 `MONTHLY_BUDGET_USD` |
| 입력 토큰 급증 | 오늘 입력이 평소(중앙값)의 3배를 넘었다 | 피드 하나가 쏟아냈는지 로그를 본다 |
| 전송 실패 / 페이지 저장 실패 | 카톡 또는 DB 저장이 실패했다 | 로그를 본다 |
| 브리핑 실패 — 죽은 단계 | 단계가 죽었다. **다시 돌려야 하는지 계산해서** 같이 온다 | 보고가 말하는 대로 |

**경고가 없으면 아무것도 오지 않는다** — 매일 "이상 없음"을 보내면 정작 중요한
경고를 안 읽게 된다. 대신 **0건인 날에도 카톡은 간다.** 그래서 "아침에 카톡이
없다"가 시스템이 멈췄다는 신호다.

**60일 동안 저장소 활동이 없으면 예약 실행이 꺼진다**(공개 리포의 GitHub 규칙).
커밋 없이 몇 달 돌아가면 실제로 일어난다. 카톡이 안 오면 먼저 Actions 탭에서
`daily briefing`이 켜져 있는지 본다.

**훈련.** 경고는 울려 봐야 동작을 안다. 둘 다 발송·기록 없이 실제 경로를 탄다.

```bash
gh workflow run "daily briefing" -f drill_failure=true   # 실패 보고 — 수집 전에 일부러 실패한다
```

가드 셋(침묵·토큰·크레딧)은 조건을 바꿔 `notify.guard_warnings`를 부르고 슬랙으로
보내 본다 — 계획 3 문서의 Task 15에 절차가 있다.

**비용.** 첫 실측(2026-11-18) 1회 정가 $0.56(입력 78,637 · 출력 12,182 토큰),
평일 월 22회면 약 $12. 예산 $30의 80%에서 경고한다.

**의존성.** CI는 `constraints.txt`로 고정해 설치한다. 올릴 때는 로컬에서 테스트를
통과시킨 뒤 `pip freeze --exclude-editable`로 다시 만든다(머리말은 손으로).
