import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { NotFound, fetchArchive, fetchDay, fetchLatest } from './lib/data'
import type { Archive as ArchiveData, Day } from './lib/types'
import ArchiveView from './components/Archive'
import Today from './components/Today'

const DATE = /^\d{4}-\d{2}-\d{2}$/

/** base를 떼고 남은 첫 조각. Vercel에서는 base가 '/'라 경로 그대로다. */
function route(): string {
  const base = import.meta.env.BASE_URL
  const path = window.location.pathname
  const rest = path.startsWith(base)
    ? path.slice(base.length)
    : path.replace(/^\//, '')
  return rest.replace(/\/$/, '')
}

type State =
  | { kind: 'loading' }
  | { kind: 'day'; day: Day }
  | { kind: 'archive'; archive: ArchiveData }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const slug = route()

    const load = async (): Promise<State> => {
      if (slug === 'archive') {
        return { kind: 'archive', archive: await fetchArchive() }
      }
      if (DATE.test(slug)) {
        return { kind: 'day', day: await fetchDay(slug) }
      }
      return { kind: 'day', day: await fetchLatest() }
    }

    load().then(setState, (error: unknown) => {
      const message =
        error instanceof NotFound
          ? '그 날짜의 브리핑이 없습니다.'
          : '브리핑을 불러오지 못했습니다.'
      setState({ kind: 'error', message })
    })
  }, [])

  if (state.kind === 'loading') {
    return <Shell>불러오는 중…</Shell>
  }
  if (state.kind === 'error') {
    return (
      <Shell>
        {state.message}
        <br />
        <a href={import.meta.env.BASE_URL} className="text-accent underline">
          오늘로 가기
        </a>
      </Shell>
    )
  }
  if (state.kind === 'archive') {
    return <ArchiveView archive={state.archive} />
  }
  return <Today day={state.day} />
}

// React.ReactNode로 쓰면 안 된다 — react-jsx 변환에서는 React가 스코프에
// 없고, verbatimModuleSyntax라 타입은 import type으로 가져와야 한다.
function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto max-w-[1340px] px-[22px] pt-7">
      <p className="m-0 font-meta text-[13px] text-muted">{children}</p>
    </main>
  )
}
