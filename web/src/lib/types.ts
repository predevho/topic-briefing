// Supabase articles 테이블의 **페이지가 읽는 컬럼**과 1:1.
//
// reason은 없다 — 마이그레이션이 컬럼 단위 grant로 막았고, 질의에 넣으면
// permission denied(42501)가 난다. 화면에 안 그리는 것과 API가 막힌 것은
// 다른 층이고, 둘 다 필요하다.
export type Article = {
  id: number
  headline: string
  bullets: string[]
  why_it_matters: string
  source: string
  url: string
  published_at: string
  topic: string
  score: number
}

export type Day = {
  date: string
  articles: Article[]
  // runs 행에서 온다. 0건인 날에도 실행 기록은 있으므로 수치가 채워진다.
  // 그 행조차 없으면 그 날짜는 존재하지 않는 것이고 fetchDay가 NotFound를 던진다.
  collected: number | null
  considered: number | null
  max_score: number | null
  threshold: number
  source_counts: Record<string, number>
}

export type ArchiveEntry = {
  date: string
  count: number
  // count > 0이면 **반드시 문자열이다.** 아카이브 화면이 `${lead} 외 N건`으로
  // 그대로 그리므로, null이 들어오면 화면에 "null"이 보인다.
  lead: string | null
}

export type Archive = {
  dates: ArchiveEntry[]
  days: number
  total: number
}
