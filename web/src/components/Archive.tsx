import type { Archive as ArchiveData, ArchiveEntry } from '../lib/types'

function monthLabel(date: string): string {
  const [y, m] = date.split('-')
  return `${y}년 ${Number(m)}월`
}

function dayLabel(date: string): string {
  const [, m, d] = date.split('-')
  return `${m}/${d}`
}

/** 월별로 묶는다. dates는 최신순으로 들어오므로 순서가 유지된다. */
function byMonth(dates: ArchiveEntry[]): [string, ArchiveEntry[]][] {
  const groups = new Map<string, ArchiveEntry[]>()
  for (const entry of dates) {
    const key = monthLabel(entry.date)
    const list = groups.get(key)
    if (list) list.push(entry)
    else groups.set(key, [entry])
  }
  return [...groups.entries()]
}

export default function Archive({ archive }: { archive: ArchiveData }) {
  return (
    <main className="mx-auto flex max-w-[1340px] flex-col gap-6 px-[22px] pb-8 pt-7">
      {/*
        이 화면이 루트(/)다. 예전의 "← 오늘로" 링크는 루트를 가리켰으므로
        이제 자기 자신으로 가는 링크가 된다 — 지웠다. 최신 브리핑은 목록의
        첫 줄이다.
      */}
      <header className="flex flex-col gap-2">
        <h1 className="m-0 text-[25px] font-semibold tracking-[-0.01em]">
          전체 브리핑
        </h1>
        <p className="m-0 font-meta text-[12.5px] text-muted">
          발행 {archive.days}일 · 총 {archive.total}건
        </p>
      </header>

      <div className="h-px bg-rule" />

      {byMonth(archive.dates).map(([month, entries]) => (
        <section key={month} className="flex flex-col gap-3">
          <h2 className="m-0 font-meta text-[11.5px] uppercase tracking-[0.08em] text-muted">
            {month}
          </h2>
          <ul className="m-0 flex list-none flex-col p-0">
            {entries.map((entry) => (
              <li key={entry.date} className="border-b border-rule-soft">
                <a
                  href={`${import.meta.env.BASE_URL}${entry.date}`}
                  className="flex items-baseline gap-3 py-[13px]"
                >
                  <span
                    className={`w-[52px] flex-none text-[15px] font-semibold ${
                      entry.count === 0 ? 'text-muted-2' : ''
                    }`}
                  >
                    {dayLabel(entry.date)}
                  </span>
                  <span
                    className={`min-w-0 flex-1 text-[13.5px] leading-[1.55] ${
                      entry.count === 0 ? 'text-muted' : 'text-ink-2'
                    }`}
                  >
                    {entry.count === 0
                      ? '기준을 넘긴 글 없음'
                      : entry.count === 1
                        ? entry.lead
                        : `${entry.lead} 외 ${entry.count - 1}건`}
                  </span>
                  <span
                    className={`flex-none font-meta text-[11.5px] ${
                      entry.count === 0 ? 'text-muted-2' : 'text-ink-2'
                    }`}
                  >
                    {entry.count}건
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  )
}
