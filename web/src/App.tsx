import { useEffect, useState } from 'react'
import { signOut, useSession } from './lib/auth'
import { fetchLatest } from './lib/data'
import { recordClick } from './lib/likes'
import type { Day } from './lib/types'
import Card from './components/Card'
import SignIn from './components/SignIn'

/**
 * 플레이스홀더다. Task 9(라우팅)가 `/`, `/:date`, `/archive`를 읽어
 * Today·Archive를 띄우는 실제 App으로 교체하고, Task 7이 0건 분기와
 * 2열 레이아웃을 가진 제대로 된 오늘 화면을 만든다.
 *
 * 지금은 Task 11·12·6(좋아요·메모·카드)을 실제 데이터로 확인하는
 * 역할만 한다.
 */
export default function App() {
  const { session, loading } = useSession()
  const [asking, setAsking] = useState(false)
  const [day, setDay] = useState<Day | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchLatest()
      .then((found) => {
        if (alive) setDay(found)
      })
      .catch((problem: unknown) => {
        if (alive) {
          setError(problem instanceof Error ? problem.message : String(problem))
        }
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <main className="mx-auto max-w-[680px] px-[22px] py-10">
      <header className="border-b border-rule pb-4">
        <h1 className="font-serif text-[22px] font-semibold leading-[1.4]">
          브리핑
        </h1>

        <p className="mt-1.5 font-meta text-[12.5px] text-muted">
          {loading
            ? '세션 확인 중…'
            : session
              ? '로그인됨 — 좋아요와 메모를 쓸 수 있습니다'
              : '로그인하지 않음 — 읽기는 이 상태로도 됩니다'}
        </p>

        {!loading && !session && !asking && (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="mt-1.5 font-meta text-[12.5px] font-medium text-accent"
          >
            로그인
          </button>
        )}

        {!loading && session && (
          <button
            type="button"
            onClick={() => void signOut()}
            className="mt-1.5 font-meta text-[12.5px] text-muted underline"
          >
            로그아웃
          </button>
        )}

        {asking && (
          <SignIn
            onDone={() => setAsking(false)}
            onCancel={() => setAsking(false)}
          />
        )}
      </header>

      {error && (
        <p className="mt-6 font-meta text-[13px] text-warn">{error}</p>
      )}

      {day && (
        <>
          <p className="mt-6 font-meta text-[12px] text-muted-2">
            {day.date} · 후보 {day.considered ?? '?'}건 중 {day.articles.length}건
          </p>

          <div className="mt-4 flex flex-col">
            {day.articles.map((article) => (
              <div
                key={article.id}
                className="border-t border-rule py-[26px] first:border-t-0 first:pt-0"
              >
                <Card article={article} onOpen={(a) => recordClick(a.id)} />
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  )
}
