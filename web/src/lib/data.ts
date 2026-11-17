import { supabase } from './supabase'
import type { Archive, ArchiveEntry, Article, Day } from './types'

// pipeline/summarize.py의 SCORE_THRESHOLD와 같은 값이다. **두 곳에 있다** —
// 파이프라인에서 바꾸면 여기도 바꾼다. 화면의 "기준 60점" 표시에만 쓰이므로
// 어긋나도 선별 동작은 바뀌지 않지만, 표시가 거짓이 된다.
export const THRESHOLD = 60

// articles에서 읽는 컬럼. reason을 넣으면 컬럼 단위 grant 때문에 질의가 실패한다.
const ARTICLE_COLUMNS =
  'id, url, source, published_at, headline, bullets, why_it_matters, topic, score'

// runs에서 읽는 컬럼. errors·input_tokens·window_*는 grant가 없다.
const RUN_COLUMNS =
  'briefing_date, collected_count, considered_count, max_score, source_counts'

// 아카이브 질의의 상한. 날짜당 한 행이므로 2000이면 5년 넘는다.
// PostgREST의 기본 상한(1000)에 조용히 걸리는 것을 막으려고 명시한다.
const ARCHIVE_LIMIT = 2000

/** 그 날짜에 브리핑이 없다 — 실행 기록조차 없다. */
export class NotFound extends Error {}

function fail(context: string, error: { message: string }): never {
  // Supabase 오류를 그대로 던지면 화면에 "JSON object requested..." 같은
  // 내부 문구가 뜬다. 무엇을 하다 실패했는지를 앞에 붙인다.
  throw new Error(`${context}: ${error.message}`)
}

export async function fetchDay(date: string): Promise<Day> {
  // 두 질의를 동시에 보낸다. 직렬이면 왕복이 두 배다.
  const [articles, runs] = await Promise.all([
    supabase
      .from('articles')
      .select(ARTICLE_COLUMNS)
      .eq('briefing_date', date)
      .order('score', { ascending: false }),
    // maybeSingle()을 쓰지 않는다 — 같은 날짜에 행이 둘이면 **던진다.**
    // notify의 AlreadySent 가드가 그걸 막지만, 화면이 그 가드에
    // 의존할 이유가 없다.
    supabase.from('runs').select(RUN_COLUMNS).eq('briefing_date', date).limit(1),
  ])

  if (articles.error) fail(`${date}의 글을 읽지 못했다`, articles.error)
  if (runs.error) fail(`${date}의 실행 기록을 읽지 못했다`, runs.error)

  const run = runs.data?.[0] ?? null
  const rows = (articles.data ?? []) as unknown as Article[]

  // **이 줄이 "0건인 날"과 "없는 날짜"를 구별한다.**
  // 실행 기록이 있으면 파이프라인이 돌았고 기준을 넘긴 글이 없었던 것이다.
  // 둘 다 없으면 그 날짜는 존재하지 않는다.
  if (rows.length === 0 && run === null) throw new NotFound(date)

  return {
    date,
    articles: rows,
    collected: run?.collected_count ?? null,
    considered: run?.considered_count ?? null,
    max_score: run?.max_score ?? null,
    threshold: THRESHOLD,
    source_counts: run?.source_counts ?? {},
  }
}

export async function fetchArchive(): Promise<Archive> {
  // briefing_index는 날짜당 한 행(건수 + 최고점 헤드라인)을 주는 뷰다.
  // runs는 **0건인 날까지** 포함한 전체 날짜 목록이다. 둘을 합쳐야
  // "조용했던 날"이 아카이브에서 사라지지 않는다.
  const [index, runs] = await Promise.all([
    supabase
      .from('briefing_index')
      .select('briefing_date, count, lead')
      .order('briefing_date', { ascending: false })
      .limit(ARCHIVE_LIMIT),
    supabase
      .from('runs')
      .select('briefing_date')
      .order('briefing_date', { ascending: false })
      .limit(ARCHIVE_LIMIT),
  ])

  if (index.error) fail('아카이브 목록을 읽지 못했다', index.error)
  if (runs.error) fail('실행 날짜를 읽지 못했다', runs.error)

  const byDate = new Map<string, { count: number; lead: string | null }>()
  for (const row of index.data ?? []) {
    byDate.set(row.briefing_date as string, {
      count: row.count as number,
      lead: row.lead as string | null,
    })
  }

  // runs의 날짜가 기준이다. 글이 있는 날은 뷰에서 건수와 헤드라인을
  // 가져오고, 없는 날은 count 0으로 남는다.
  const dates: ArchiveEntry[] = (runs.data ?? []).map((row) => {
    const date = row.briefing_date as string
    const hit = byDate.get(date)
    return { date, count: hit?.count ?? 0, lead: hit?.lead ?? null }
  })

  return {
    dates,
    days: dates.length,
    total: dates.reduce((sum, entry) => sum + entry.count, 0),
  }
}

/** 최신 브리핑. 아카이브 전체를 받지 않고 날짜 하나만 찾는다. */
export async function fetchLatest(): Promise<Day> {
  const { data, error } = await supabase
    .from('runs')
    .select('briefing_date')
    .order('briefing_date', { ascending: false })
    .limit(1)

  if (error) fail('최신 브리핑 날짜를 읽지 못했다', error)

  const latest = data?.[0]?.briefing_date as string | undefined
  if (!latest) throw new NotFound('아직 발행한 브리핑이 없다')

  return fetchDay(latest)
}
