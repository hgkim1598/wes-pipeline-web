import { Info, OctagonX, TriangleAlert, Wrench } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { cx } from '@/lib/cx'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import type { DiagnosticKind } from '@/registries/diagnostics'

/*
  진단 사건 한 건.

  ── 왜 MessageBlock이 아닌가 ───────────────────────────────────────────

  MessageBlock은 옅은 tint 배경 + 1px 테두리 + 아이콘을 가진 "블록"이고,
  화면에 하나 있을 때 주목을 끄는 것이 목적이다. 진단은 한 실행에 여러 건이
  나오므로 그것을 그대로 쓰면 같은 모양의 tint 상자가 세로로 반복되고,
  결과 화면이 카드 목록처럼 보인다.

  시안은 진단을 상자로 그리지 않는다. results-full.html의 알림은

      border-top:1px + border-bottom:1px solid var(--ink-100)
      [WARN]  mono data w500      code  caption ink-500
      제목    body w500 ink-900
      본문    body ink-700
      IMPACT  eyebrow w600        상세  caption ink-500

  즉 배경 없이 hairline 사이의 텍스트 블록이다. 위계를 배경이 아니라
  글자 크기·굵기·색으로 만든다. 이 component는 그 문법을 따른다.

  MessageBlock은 그대로 남는다 — 페이지 단위 안내(실행 실패, 결과 미준비,
  통신 오류)가 원래 그 component의 역할이고, 그런 메시지는 화면당 한 건이다.

  ── 색은 보조 수단이다 ─────────────────────────────────────────────────

  색을 모두 지워도 아이콘 실루엣과 "자동 복구 / 확인 필요 / 참고 / 실패"
  라벨 텍스트만으로 네 종류가 구분된다. 아이콘은 네 개가 서로 다른 외곽선을
  갖도록 골랐다(팔각형 · 삼각형 · 렌치 · 원). CLAUDE.md 24·27장.

  ── 사용자에게 내부 모델을 가르치지 않는다 ─────────────────────────────

  severity와 resolution이 별개 축이라는 사실은 registry 안에 남고, 여기에는
  이미 합쳐진 kind 하나만 도착한다. 화면에는 PASS/WARN/INFO 같은 파이프라인
  어휘가 나오지 않는다. code는 mono caption으로 조용히 병기해 전문가가
  로그·문서와 대조할 수 있게만 한다.
*/

const KIND_ICON: Record<DiagnosticKind, LucideIcon> = {
  failure: OctagonX,
  attention: TriangleAlert,
  repaired: Wrench,
  note: Info,
}

/**
 * 라벨과 아이콘의 색.
 *
 * note가 중립 회색인 것은 의도다. tokens.css의 info 토큰이 "running(brand
 * blue)과 충돌하지 않도록 별도 파랑을 만들지 않는다"로 정의돼 있고,
 * 참고 사항이 실행 중 단계처럼 파랗게 보이면 안 된다.
 */
const KIND_TEXT_CLASS: Record<DiagnosticKind, string> = {
  failure: 'text-status-failure-fg',
  attention: 'text-status-warning-fg',
  repaired: 'text-status-success-fg',
  note: 'text-text-muted',
}

export interface DiagnosticNoteProps {
  diagnostic: RunDiagnostic
  /**
   * 표 안에 들어가는 축약형. code와 impact를 생략하고 제목까지만 보여준다.
   * 단계 목록의 행처럼 이미 문맥이 있는 자리에서 쓴다.
   */
  compact?: boolean
  className?: string
}

export function DiagnosticNote({
  diagnostic,
  compact = false,
  className,
}: DiagnosticNoteProps) {
  const { view, code, message, impact } = diagnostic
  const Icon = KIND_ICON[view.kind]

  /*
    registry에 없는 code는 제목을 지어내지 않고 backend 원문을 제목 자리에
    쓴다. 그 경우 본문(meaning)은 비어 있으므로 원문을 두 번 보여주지 않는다.
  */
  const known = view.title !== ''
  const heading = known ? view.title : message

  return (
    <div className={cx('flex flex-col gap-1', className)}>
      <div className="flex items-center gap-2">
        <Icon
          size={14}
          strokeWidth={1.5}
          aria-hidden="true"
          className={cx('flex-none', KIND_TEXT_CLASS[view.kind])}
        />
        <span
          className={cx('text-small font-medium', KIND_TEXT_CLASS[view.kind])}
        >
          {view.label}
        </span>
        {!compact && code ? (
          <code className="min-w-0 truncate text-caption text-text-muted">
            {code}
          </code>
        ) : null}
      </div>

      {/*
        max-w-prose로 줄 길이를 제한한다. 단계 목록은 넓은 본문 안에 있어서
        제한이 없으면 한 줄이 100자를 넘어가고, 그 길이는 읽기 어렵다.
        레일(400px)에서는 이 제한이 걸리지 않는다.
      */}
      <p className="max-w-prose text-body font-medium text-text-strong">
        {heading}
      </p>

      {view.meaning ? (
        <p className="max-w-prose text-body text-text">{view.meaning}</p>
      ) : null}

      {/*
        전문가용 Layer 3. backend가 그 자리에 적어 둔 영문 원문이며,
        위의 한국어 설명과 달리 파이프라인이 직접 쓴 문장이다. 둘을 섞지
        않도록 라벨을 붙여 구분한다.
      */}
      {!compact && (impact || (known && message)) ? (
        <dl className="mt-1 flex flex-col gap-1 border-t border-border-subtle pt-2">
          {known && message ? (
            <div className="flex flex-col gap-0.5">
              <dt className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
                Pipeline message
              </dt>
              <dd className="text-caption text-text-muted">{message}</dd>
            </div>
          ) : null}
          {impact ? (
            <div className="flex flex-col gap-0.5">
              <dt className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
                Impact
              </dt>
              <dd className="text-caption text-text-muted">{impact}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  )
}

/**
 * 진단 목록.
 *
 * 항목 사이를 hairline으로 나눈다. 카드를 세로로 쌓는 대신 시안의
 * "구분선 사이 텍스트" 문법을 그대로 쓴다.
 */
export function DiagnosticList({
  diagnostics,
  compact = false,
  className,
}: {
  diagnostics: RunDiagnostic[]
  compact?: boolean
  className?: string
}) {
  if (diagnostics.length === 0) return null

  return (
    <div
      className={cx(
        'flex flex-col border-t border-border-subtle',
        className,
      )}
    >
      {diagnostics.map((diagnostic) => (
        <DiagnosticNote
          key={diagnostic.key}
          diagnostic={diagnostic}
          compact={compact}
          className="border-b border-border-subtle py-3"
        />
      ))}
    </div>
  )
}
