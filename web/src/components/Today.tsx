import type { Article, Day } from '../lib/types'
import { recordClick } from '../lib/likes'
import Card from './Card'
import Empty from './Empty'

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

function korean(date: string): string {
  // "2026-11-12" → "11월 12일 목요일". Date의 월은 0부터 시작한다.
  const [y, m, d] = date.split('-').map(Number)
  const when = new Date(y, m - 1, d)
  return `${m}월 ${d}일 ${WEEKDAYS[when.getDay()]}요일`
}

export default function Today({ day }: { day: Day }) {
  const count = day.articles.length

  function onOpen(article: Article) {
    recordClick(article.id)
  }

  return (
    <main className="mx-auto flex max-w-[1340px] flex-col gap-[26px] px-[22px] pb-8 pt-7">
      <header className="flex flex-col gap-2">
        <div className="font-meta text-[12px] uppercase tracking-[0.06em] text-muted">
          {korean(day.date)}
        </div>
        <h1 className="m-0 text-[25px] font-semibold tracking-[-0.01em]">
          {count === 0 ? '오늘은 보낼 글이 없습니다' : `오늘의 토픽 ${count}건`}
        </h1>
        {count > 0 && (
          <p className="m-0 font-meta text-[12.5px] text-muted">
            후보 {day.considered ?? '?'}건 중 기준을 넘긴 글
          </p>
        )}
      </header>

      <div className="h-px bg-rule" />

      {count === 0 ? (
        <Empty day={day} />
      ) : (
        // 모바일 1열 / 태블릿 이상 2열 (요구사항 O10)
        <div className="grid grid-cols-1 gap-[26px] md:grid-cols-2 md:gap-x-10">
          {/*
            번호는 카톡과 같다. 둘 다 파이프라인이 매긴 순번(articles.position)
            순서이고, fetchDay가 그 순서로 읽는다. 2열에서는 왼→오, 위→아래로
            읽힌다 — 번호가 그 순서를 드러낸다.
          */}
          {day.articles.map((article, index) => (
            <div key={article.id} className="flex flex-col gap-[26px]">
              <Card article={article} number={index + 1} onOpen={onOpen} />
              <div className="h-px bg-rule md:hidden" />
            </div>
          ))}
        </div>
      )}

      <nav className="mt-auto flex items-center justify-end font-meta text-[13px]">
        <a href={import.meta.env.BASE_URL} className="py-3 text-muted">
          전체 브리핑
        </a>
      </nav>
    </main>
  )
}
