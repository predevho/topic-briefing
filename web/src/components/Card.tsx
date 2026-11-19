import type { Article } from '../lib/types'
import LikeButton from './LikeButton'
import Note from './Note'

type Props = {
  article: Article
  // 1부터. 카톡의 "1. 2. 3."과 같은 번호다.
  number: number
  onOpen: (article: Article) => void
}

export default function Card({ article, number, onOpen }: Props) {
  return (
    <article className="flex flex-col gap-2.5">
      <a
        href={article.url}
        target="_blank"
        rel="noreferrer noopener"
        onClick={() => onOpen(article)}
      >
        <h2 className="m-0 text-[19px] font-semibold leading-[1.45] tracking-[-0.01em]">
          {/* 카톡과 같은 "1." 형식. 헤드라인보다 한 단계 흐리게 둔다. */}
          <span className="mr-1.5 text-muted tabular-nums">{number}.</span>
          {article.headline}
        </h2>
      </a>

      {/*
        2026-11-19부터 원문을 간추린 2~3문단(overview)이 요점을 대신한다.
        문단은 빈 줄로 나뉘어 온다. 그 전 글은 overview가 없으니 요점을 그린다.
      */}
      {article.overview ? (
        <div className="flex flex-col gap-3 text-[14.5px] leading-[1.75] text-ink-2">
          {article.overview
            .split(/\n\s*\n/)
            .map((paragraph) => paragraph.trim())
            .filter(Boolean)
            .map((paragraph, i) => (
              <p key={i} className="m-0">
                {paragraph}
              </p>
            ))}
        </div>
      ) : (
        <ul className="m-0 flex list-disc flex-col gap-1.5 pl-[15px] text-[14.5px] leading-[1.7] text-ink-2">
          {article.bullets.map((bullet, i) => (
            <li key={i}>{bullet}</li>
          ))}
        </ul>
      )}

      {/*
        한글에 이탤릭을 쓰지 않는다 — Noto Serif KR에 이탤릭이 없어서 브라우저가
        합성하고, 한글에서는 어긋나 보인다. 목업처럼 왼쪽 2px 선으로 강조한다.
      */}
      <p className="m-0 border-l-2 border-quote pl-[11px] text-[13.5px] leading-[1.6] text-muted">
        {article.why_it_matters}
      </p>

      <div className="mt-0.5 flex items-center gap-2.5 font-meta text-[11.5px] text-muted">
        <span>{article.source}</span>
        <span aria-hidden="true">·</span>
        <span className="font-medium text-ink-2">{article.score}</span>
        <LikeButton articleId={article.id} className="ml-auto -mr-2.5" />
      </div>

      {/*
        메모는 펼쳐지면 카드 아래로 자란다. 위 메타 줄(flex items-center)
        **안**에 넣으면 레이아웃이 깨지므로 형제로 둔다.
      */}
      <Note articleId={article.id} />
    </article>
  )
}
