import type { Day } from '../lib/types'

export default function Empty({ day }: { day: Day }) {
  const silent = Object.entries(day.source_counts)
    .filter(([, n]) => n === 0)
    .map(([name]) => name)

  return (
    <div className="flex flex-col gap-6">
      <p className="m-0 text-[15px] leading-[1.75] text-ink-2">
        후보 {day.considered ?? 0}건을 봤지만 기준을 넘긴 글이 없었습니다.
        <br />
        조용한 날입니다 —{' '}
        <strong className="font-semibold">시스템은 정상입니다.</strong>
      </p>

      <section className="flex flex-col gap-3 bg-panel px-[18px] py-4 font-meta">
        <h2 className="m-0 font-serif text-[14px] font-semibold">왜 비었는지</h2>
        <dl className="m-0 flex flex-col gap-2 text-[12.5px]">
          <Row label="수집" value={`${day.collected ?? 0}건`} />
          <Row
            label="최고 점수"
            value={day.max_score === null ? '없음' : `${day.max_score}점`}
          />
          <Row label="기준" value={`${day.threshold}점`} strong />
        </dl>
        {day.max_score !== null && (
          <p className="m-0 font-serif text-[12.5px] leading-[1.65] text-muted">
            최고 점수가 기준에 {day.threshold - day.max_score}점 못 미쳤습니다.
            이런 날이 한 주에 세 번 넘으면 기준을 내리거나 소스를 늘릴 때입니다.
          </p>
        )}
      </section>

      {silent.length > 0 && (
        <section className="flex flex-col gap-2.5 font-meta">
          <h2 className="m-0 font-serif text-[14px] font-semibold">0건인 소스</h2>
          <ul className="m-0 flex list-none flex-col gap-[7px] p-0 text-[12.5px]">
            {silent.map((name) => (
              <li key={name} className="flex justify-between gap-3">
                <span className="text-ink-2">{name}</span>
                <span className="text-muted">0건</span>
              </li>
            ))}
          </ul>
          {/*
            목업은 "3일 연속"까지 보여주지만, 그건 여러 날의 runs를 봐야 안다.
            계획 3의 lib/guard가 그 판정을 하므로 여기서는 그날의 0건만 보여준다.
          */}
        </section>
      )}
    </div>
  )
}

function Row({
  label,
  value,
  strong,
}: {
  label: string
  value: string
  strong?: boolean
}) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className={`m-0 ${strong ? 'font-medium text-ink-2' : 'text-ink'}`}>
        {value}
      </dd>
    </div>
  )
}
