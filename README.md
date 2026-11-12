# 토픽 컬럼 자동화

매일 아침 IT 토픽을 수집·선별·요약해서 카카오톡으로 받는다.

- 설계: [`docs/superpowers/specs/2026-11-10-it-column-automation-design.md`](docs/superpowers/specs/2026-11-10-it-column-automation-design.md)
- ERD: [`docs/superpowers/specs/2026-11-11-erd.md`](docs/superpowers/specs/2026-11-11-erd.md)
- 요구사항 추적표: [`docs/superpowers/specs/2026-11-11-requirements.md`](docs/superpowers/specs/2026-11-11-requirements.md)
- 구현 계획과 실측 기록: [`docs/superpowers/plans/2026-11-10-briefing-pipeline.md`](docs/superpowers/plans/2026-11-10-briefing-pipeline.md)

| | 범위 | 상태 |
|---|---|---|
| 계획 1 | 파이프라인 — 수집·선별·본문·요약, 결과는 터미널 | **완료** |
| 계획 2 | 웹페이지 + 좋아요·클릭 | 예정 |
| 계획 3 | 카카오톡 전송 + 슬랙 경고 + 경고 장치 + GitHub Actions | 예정 |

## 준비

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # 값을 채운다
```

`.env`에 필요한 것은 셋이다 — `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
`ANTHROPIC_API_KEY`. Supabase 키 이름 주의: 대시보드의 **Connect** 대화상자에서
URL과 publishable 키를, **Settings → API Keys**에서 secret 키를 받는다
(`Settings → API` 페이지는 없다). `eyJ...`로 시작하는 긴 키는 2026년 말
폐기되는 레거시 키다.

## 매일 실행

```bash
python -m pipeline.collect      # 수집  → data/<날짜>/raw.json
python -m pipeline.rank         # 선별  → ranked.json
python -m pipeline.enrich       # 본문  → articles.json
python -m pipeline.summarize    # 요약  → briefing.json
python -m pipeline.notify       # 터미널 출력 + 발행 이력 기록
```

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
pytest                              # 전체 테스트 (396개)
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

## 계획 3에서 메워야 할 구멍

**`runs.input_tokens`가 항상 `NULL`이다.** `notify`가 `input_tokens=None`을
넣는다. `AnthropicLLM.parse`는 입력 토큰 수를 돌려주지만 `rank`와 `summarize`가
그 값을 버린다. 지금은 쓰는 곳이 없어서 배선하지 않았다. 계획 3의 크레딧
소진 가드가 이 값을 쓴다. 스키마 컬럼은 이미 있다.

**소스 침묵 경고의 임계값.** spec 8.4를 "소스별 `quiet_days`"로 고쳤다 —
"3일 연속 0건"이면 느리지만 살아 있는 소스 5개가 영구히 경고를 띄운다
(실측: Lil'Log는 400일에 2편이 평소 속도다). 측정값은 `sources.yaml`
주석에 있다.
