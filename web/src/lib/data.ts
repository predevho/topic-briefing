import { supabase } from './supabase'
import type { Archive, ArchiveEntry, Article, Day, RelatedLink } from './types'

// pipeline/summarize.py의 SCORE_THRESHOLD와 같은 값이다. **두 곳에 있다** —
// 파이프라인에서 바꾸면 여기도 바꾼다. 화면의 "기준 60점" 표시에만 쓰이므로
// 어긋나도 선별 동작은 바뀌지 않지만, 표시가 거짓이 된다.
export const THRESHOLD = 60

// articles에서 읽는 컬럼. reason을 넣으면 컬럼 단위 grant 때문에 질의가 실패한다.
const ARTICLE_COLUMNS =
  'id, url, source, published_at, headline, overview, bullets, why_it_matters, topic, score, position'

// runs에서 읽는 컬럼. errors·input_tokens·window_*는 grant가 없다.
// published_count는 화면에 쓰지 않고 **정렬에만** 쓴다 — 아래 RUN_ORDER 참조.
const RUN_COLUMNS =
  'briefing_date, collected_count, considered_count, max_score, published_count, source_counts'

/**
 * 같은 날짜에 runs 행이 여러 개일 수 있다. 2026-11-17 실측: 2026-11-12에
 * 3행이 있었고 수치가 서로 달랐다 — 실제 발송 1건(collected=240, published=7)과
 * 빈 행 2건(collected=0, published=0). 계획 1 개발 중 `--force`로 여러 번
 * 돌린 흔적이다.
 *
 * 정렬 없이 집으면 **실제로 240건 수집해 7건 발행한 날에 "수집 0건"이 뜬다.**
 * runs.briefing_date를 넣어서 막으려던 바로 그 거짓말이다.
 *
 * `sent_at` 순은 틀린다 — 실측에서 실제 발송이 **가장 먼저**였고 빈 행들이
 * 뒤에 왔다. `published_count` 내림차순이 "실제로 발행한 실행"을 집는다.
 * 같은 값이면 어느 쪽이든 같은 글을 발행한 것이므로 무해하다.
 */
const RUN_ORDER = { column: 'published_count', ascending: false } as const

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
      // **순번이 먼저다.** 카톡이 매긴 "1. 2. 3."과 같은 순서여야 한다.
      // 점수만으로 정렬하면 동점 사이가 어긋난다(2026-11-12: 100점 3건).
      // 순번이 없는 행(null)은 뒤로 보내고 점수순으로 물러선다.
      .order('position', { ascending: true, nullsFirst: false })
      .order('score', { ascending: false }),
    // maybeSingle()을 쓰지 않는다 — 같은 날짜에 행이 둘이면 **던진다.**
    // 실측으로 그런 날이 실제로 있었다(RUN_ORDER 주석 참조).
    supabase
      .from('runs')
      .select(RUN_COLUMNS)
      .eq('briefing_date', date)
      .order(RUN_ORDER.column, { ascending: RUN_ORDER.ascending })
      .limit(1),
  ])

  if (articles.error) fail(`${date}의 글을 읽지 못했다`, articles.error)
  if (runs.error) fail(`${date}의 실행 기록을 읽지 못했다`, runs.error)

  const run = runs.data?.[0] ?? null
  const rows = (articles.data ?? []) as unknown as Omit<Article, 'related'>[]
  const related = await fetchRelated(rows.map((row) => row.id))

  // **이 줄이 "0건인 날"과 "없는 날짜"를 구별한다.**
  // 실행 기록이 있으면 파이프라인이 돌았고 기준을 넘긴 글이 없었던 것이다.
  // 둘 다 없으면 그 날짜는 존재하지 않는다.
  if (rows.length === 0 && run === null) throw new NotFound(date)

  return {
    date,
    articles: rows.map((row) => ({ ...row, related: related.get(row.id) ?? [] })),
    collected: run?.collected_count ?? null,
    considered: run?.considered_count ?? null,
    max_score: run?.max_score ?? null,
    threshold: THRESHOLD,
    source_counts: run?.source_counts ?? {},
  }
}

/**
 * 글마다 이전에 다룬 비슷한 글(2026-11-23). article_links에서 관련 글의 날짜와
 * 헤드라인을 FK로 함께 읽는다.
 *
 * **실패해도 페이지를 깨지 않는다.** 관련 글은 부가 정보다 — 조회가 실패하면
 * (테이블이 아직 없거나 권한 문제) 관련 글만 빠지고 브리핑은 보인다.
 */
async function fetchRelated(ids: number[]): Promise<Map<number, RelatedLink[]>> {
  const byArticle = new Map<number, RelatedLink[]>()
  if (ids.length === 0) return byArticle

  const { data, error } = await supabase
    .from('article_links')
    .select('article_id, similarity, related:articles!article_links_related_id_fkey(id, briefing_date, headline)')
    .in('article_id', ids)
    .order('similarity', { ascending: false })

  if (error) {
    console.warn('관련 글을 읽지 못했다(브리핑은 그대로 보인다):', error.message)
    return byArticle
  }

  for (const row of (data ?? []) as unknown as {
    article_id: number
    similarity: number
    related: { id: number; briefing_date: string; headline: string } | null
  }[]) {
    if (!row.related) continue
    const list = byArticle.get(row.article_id) ?? []
    list.push({
      id: row.related.id,
      date: row.related.briefing_date,
      headline: row.related.headline,
      similarity: row.similarity,
    })
    byArticle.set(row.article_id, list)
  }
  return byArticle
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
    // 주의: 이 질의는 날짜당 여러 행을 돌려줄 수 있다. 아래에서 중복을 뺀다.
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
  //
  // **중복을 빼야 한다.** runs는 날짜당 여러 행일 수 있다(RUN_ORDER 주석).
  // 그대로 매핑하면 2026-11-17 실측처럼 같은 날짜가 3번 나오고,
  // days가 3, total이 21(실제 7)이 된다.
  const seen = new Set<string>()
  const dates: ArchiveEntry[] = []
  for (const row of runs.data ?? []) {
    const date = row.briefing_date as string
    if (seen.has(date)) continue
    seen.add(date)
    const hit = byDate.get(date)
    dates.push({ date, count: hit?.count ?? 0, lead: hit?.lead ?? null })
  }

  return {
    dates,
    days: dates.length,
    total: dates.reduce((sum, entry) => sum + entry.count, 0),
  }
}
