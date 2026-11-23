import type { ReactNode } from 'react'
import { ArrowRight, BookOpenCheck, CircleCheck, Info, ListChecks, OctagonX, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'

import { WithheldLine } from '@/components/ui/DiagnosticNote'
import { HelpTerm } from '@/components/ui/HelpTerm'
import type { ExplanationFailure } from '@/features/run-detail/api'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { attentionHeading, failureLead, failureLeadText } from '@/features/run-detail/emptyStateCopy'
import { nextActions } from '@/features/run-detail/nextActions'
import { describeFailureCode } from '@/registries/failures'
import { describeStep } from '@/registries/steps'
import { cx } from '@/lib/cx'

/*
  이 실행에서 일어난 일의 **유일한 본문**.

  ── 무엇을 통합했나 ─────────────────────────────────────────────────────

  이전에는 같은 warning 하나가 최대 네 곳에 나타났다.

    파이프라인 탭 StepTable 행 · StepDetailRail · 결과 탭 "확인할 사항" · AI 패널

  결과 탭의 목록과 이 카드가 **같은 `results.warnings` 배열**을 각각 렌더링하고
  있었다. 사용자는 그것이 네 개의 문제인지 하나인지 스스로 판단해야 했다.

  이제 사건의 본문은 여기 하나다. StepTable은 "이 단계에서 사건이 있었다"는
  **위치 표시**만 유지한다 — 그것은 중복이 아니라 다른 정보다(무엇 vs 어디).

  ── 세 종류를 한 표면에서 구분한다 ──────────────────────────────────────

    실패        실행을 멈춘 것. 준비할 항목이 있으면 안내 링크가 붙는다
    확인 필요    끝났지만 결과 해석에 영향을 주는 것
    자동 해결    파이프라인이 이미 처리한 것 — 접어 둔다

  자동 해결된 항목을 확인 필요와 같은 무게로 펼치면, 할 일이 없는 항목이
  할 일 목록에 섞인다. 지우지도 않는다 — 무슨 일이 있었는지는 사실이다.

  ── 원인을 만들지 않는다 ────────────────────────────────────────────────

  여러 항목이 함께 있어도 인과관계를 쓰지 않는다. 파이프라인은 그렇게 기록하지
  않았고, 화면이 지어내면 사용자가 엉뚱한 곳을 고친다.
*/

export interface AttentionSectionProps {
  /** 구조화된 실패. explanation이 없으면 빈 배열이고 rawError가 대신한다. */
  failures: ExplanationFailure[]
  /** `GET /api/jobs/{id}`의 error. code가 없는 이어붙인 문자열이다. */
  rawError: string | null
  /** 이번 실행의 진단 전체. kind로 나눈다. */
  diagnostics: RunDiagnostic[]
  /** 사전 점검 실행인가. 제목 문구를 그 사실에 맞춘다. */
  isPrecheck: boolean
  /**
   * "파이프라인에서 보기"를 눌렀을 때. 해당 단계를 선택하고 탭을 옮긴다.
   *
   * 주지 않으면 이동 링크를 그리지 않는다 — 갈 곳이 없는 버튼을 만들지 않는다.
   */
  onGoToStep?: (stepId: string) => void
  /**
   * 항목 옆에 둘 AI 해설. code를 받아 그 항목의 해설을 돌려준다(없으면 null).
   *
   * 주지 않으면 지금과 똑같이 그린다. 어느 code에 무엇이 붙는지는
   * synthesisPlacement.ts가 근거 id로만 정한다 — 이 component는 받은 것을
   * 그 자리에 둘 뿐이다.
   */
  renderAiNote?: (kind: 'failure' | 'diagnostic', code: string) => ReactNode
}

export function AttentionSection({
  failures,
  rawError,
  diagnostics,
  isPrecheck,
  onGoToStep,
  renderAiNote,
}: AttentionSectionProps) {
  /*
    실패는 이 목록에서 제외한다 `[코드근거]`

    `collectDiagnostics`는 `results.failures`와 `results.warnings`를 함께
    담는다. 그런데 실패는 진단 knowledge를 거치지 않으므로
    `describeFailure()`가 title·meaning을 **빈 문자열**로 돌려주고,
    아래 DiagnosticItem의 `{view.title || item.message}` fallback이 걸려
    **backend raw message가 제목 자리에 올라온다.**

    실제로 그렇게 보였다.

        missing from PATH: bwa samtools gatk ... 준비 방법은 docs/MAIN_SH_...
        실패
        required_tools

    초보자가 가장 먼저 읽는 문장이 `missing from PATH`가 되어, "폴더를 잘못
    잡았나"로 읽힐 수 있었다. 게다가 위쪽 `failures` 블록이 같은 실패를
    curated title로 이미 보여주고 있어서 **같은 실패가 두 번** 나왔다.

    실패의 표현은 `failures` prop 하나가 맡는다 — 그쪽은
    `wes_failures.json`의 title·meaning을 쓴다. raw message는 사라지지 않고
    맨 아래 "멈춘 이유의 원문"에 그대로 남는다.
  */
  const warnings = diagnostics.filter((item) => item.view.kind !== 'failure')
  const repaired = warnings.filter((item) => item.view.kind === 'repaired')
  const needsAttention = warnings.filter(
    (item) => item.view.kind !== 'repaired',
  )

  // items: 아래에 실패 항목이 있다. rawOnly: 원문 error뿐이다 — "아래 항목"이라고
  // 말하지 않고 원문을 펼쳐 보인다(emptyStateCopy.ts).
  const lead = failureLead(failures.length, rawError)
  const hasFailure = lead !== 'none'
  if (!hasFailure && needsAttention.length === 0 && repaired.length === 0) {
    return null
  }

  /*
    다음 행동: 준비 안내(helpPath) + 실패 단계의 근거 보기. 기록에서만 만든다
    (nextActions.ts). 단계 이동은 onGoToStep이 있을 때만 — 갈 곳 없는 버튼 금지.
  */
  const actions = nextActions(failures, (code) => describeFailureCode(code).helpPath).filter(
    (action) => action.kind === 'help' || onGoToStep,
  )

  const heading = attentionHeading(
    hasFailure,
    isPrecheck,
    needsAttention.filter((item) => item.view.kind === 'attention').length,
  )

  /*
    카드 전체를 빨갛게 칠하지 않는다(2026-11-23 발표용 정리, ref 다크 시안의
    "Analysis Stopped" 띠). 카드는 중립 면이고 상태 tint는 맨 위 제목 띠에만
    둔다 — 아래 구획(멈춘 이유·다음 행동·함께 기록된 항목)이 같은 무게로 읽힌다.

    2026-11-23 UI 정리(개발판단기록 63장): 제목 띠를 카드 안의 또 다른 상자로
    두지 않고 카드 머리(가장자리까지 닿는 띠)로 만든다. 그 아래 목록도 테두리
    상자 대신 위아래 hairline으로 나눈다 — 카드 속 카드 속 목록의 3중 중첩을 없앤다.
  */
  const banner =
    heading.tone === 'failure'
      ? 'border-b border-status-failure-bd bg-status-failure-bg'
      : heading.tone === 'warning'
        ? 'border-b border-status-warning-bd bg-status-warning-bg'
        : 'border-b border-border-subtle'

  return (
    <section
      className="flex flex-col gap-5 overflow-hidden rounded-lg border border-border bg-surface pb-5 shadow-card [&>*:not(:first-child)]:mx-5"
      aria-labelledby="run-attention-heading"
    >
      <div className={cx('flex items-start gap-3 px-5 py-4', banner)}>
        {heading.tone === 'failure' ? (
          <OctagonX size={20} strokeWidth={1.75} aria-hidden="true" className="mt-0.5 flex-none text-status-failure-fg" />
        ) : heading.tone === 'warning' ? (
          <TriangleAlert size={20} strokeWidth={1.75} aria-hidden="true" className="mt-0.5 flex-none text-status-warning-fg" />
        ) : (
          <Info
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="mt-0.5 flex-none text-text-muted"
          />
        )}
        <div className="flex min-w-0 flex-col gap-1">
          <h2
            id="run-attention-heading"
            className="text-h3 font-semibold text-text-strong"
          >
            {heading.title}
          </h2>
          {hasFailure ? (
            <p className="max-w-prose text-body text-text">
              {lead === 'items' && isPrecheck ? (
                <>
                  <HelpTerm termId="precheck">사전 점검</HelpTerm>에서 문제가
                  확인되어 분석을 시작하지 않았습니다. 아래 항목을 준비한 뒤 다시
                  실행하면 됩니다.
                </>
              ) : (
                failureLeadText(lead, isPrecheck)
              )}
            </p>
          ) : null}
        </div>
      </div>

      {/* --- 원문만 있는 실패: 접지 않는다. 이것이 유일한 단서다 ----------- */}
      {lead === 'rawOnly' && rawError ? (
        <div className="flex flex-col gap-1">
          <p className="text-caption font-medium text-text-muted">
            실행이 남긴 오류 원문
          </p>
          {/* 스크롤되는 영역이라 키보드로도 들어갈 수 있게 tabIndex를 준다(2026-11-23 리뷰). */}
          <pre
            tabIndex={0}
            aria-label="실행이 남긴 오류 원문"
            className="max-h-48 overflow-auto rounded-sm border border-border bg-surface p-3 font-mono text-caption break-words whitespace-pre-wrap text-text">
            {rawError}
          </pre>
        </div>
      ) : null}

      {/* --- 실패 ------------------------------------------------------- */}
      {/*
        세 구획(2026-11-23, ref 1의 위계): 멈춘 이유 → 다음 행동 → 함께 기록된
        항목. 구획 제목이 있어서 경고가 중단 원인처럼 읽히지 않는다 — 원인을
        잇는 문장은 여전히 쓰지 않는다.
      */}
      {failures.length > 0 ? (
        <div className="flex flex-col gap-2">
          <SubHeading>멈춘 이유 {failures.length}건</SubHeading>
          <ul className="flex flex-col divide-y divide-border-subtle border-y border-border-subtle">
            {failures.map((failure, index) => {
              const view = describeFailureCode(failure.code)
              return (
                <li key={`${failure.code}-${index}`} className="flex items-start gap-3 py-3">
                  <RowIcon tone="failure" />
                  <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-body font-medium text-text-strong">
                      {/*
                        미등록 code면 backend 원문이 제목이 된다. 지어낸 문장보다
                        낫고, 등록된 두 code는 이 경로를 타지 않는다.
                      */}
                      {view.known ? view.title : failure.message}
                    </span>
                    {/*
                      code는 제목 옆에 두지 않는다. `required_tools`는 사용자
                      어휘가 아니라 식별자이고, 제목 옆에 있으면 무엇을 읽어야
                      할지 흐려진다. 아래 "멈춘 이유의 원문"에서 확인할 수 있다.
                    */}
                    {failure.actualStepLabel ? (
                      <span className="text-caption text-text-muted">
                        {failure.actualStepLabel}
                      </span>
                    ) : null}
                  </div>
                  {view.known ? (
                    <p className="max-w-prose text-small text-text">
                      {view.meaning}
                    </p>
                  ) : null}
                  {renderAiNote ? renderAiNote('failure', failure.code) : null}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}

      {actions.length > 0 ? (
        <div className="flex flex-col gap-2">
          <SubHeading>다음 행동</SubHeading>
          <ul className="flex flex-wrap gap-2">
            {actions.map((action) =>
              action.kind === 'help' ? (
                <li key={action.path}>
                  <Link
                    to={action.path}
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-sm border border-border-strong bg-surface px-3 text-body font-medium text-text-strong no-underline hover:bg-sunken hover:no-underline"
                  >
                    <BookOpenCheck size={15} strokeWidth={1.5} aria-hidden="true" />
                    {action.label}
                  </Link>
                </li>
              ) : (
                <li key={action.stepId}>
                  <button
                    type="button"
                    onClick={() => onGoToStep?.(action.stepId)}
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-sm border border-border bg-surface px-3 text-body text-text hover:bg-sunken"
                  >
                    <ListChecks size={15} strokeWidth={1.5} aria-hidden="true" />
                    {describeStep(action.stepId).label} 단계 기록 보기
                  </button>
                </li>
              ),
            )}
          </ul>
        </div>
      ) : null}

      {/* --- 확인이 필요한 진단 ------------------------------------------ */}
      {needsAttention.length > 0 ? (
        <div className="flex flex-col gap-2">
          {hasFailure ? (
            <SubHeading>함께 기록된 항목 {needsAttention.length}건</SubHeading>
          ) : null}
          <ul className={cx('flex flex-col divide-y divide-border-subtle border-b border-border-subtle', hasFailure && 'border-t')}>
            {needsAttention.map((item) => (
              <DiagnosticItem
                key={item.key}
                item={item}
                onGoToStep={onGoToStep}
                renderAiNote={renderAiNote}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {/* --- 자동 해결 ---------------------------------------------------- */}
      {repaired.length > 0 ? (
        <details className="border-t border-border-subtle pt-3">
          <summary className="inline-flex min-h-6 cursor-pointer items-center gap-2 text-small font-medium text-text-muted">
            <CircleCheck
              size={14}
              strokeWidth={1.5}
              aria-hidden="true"
              className="text-status-success-fg"
            />
            {/*
              접힌 상태에서 읽히는 유일한 문장이다. "무엇이 있었는지"보다
              "지금 할 일이 없다"가 먼저 오게 쓴다 — 이 그룹의 요점은
              사용자가 여기서 멈추지 않아도 된다는 것이다.
            */}
            파이프라인이 처리해 조치가 필요 없는 항목 {repaired.length}건
          </summary>
          <ul className="mt-3 flex flex-col divide-y divide-border-subtle border-y border-border-subtle">
            {repaired.map((item) => (
              <DiagnosticItem
                key={item.key}
                item={item}
                onGoToStep={onGoToStep}
                renderAiNote={renderAiNote}
                muted
              />
            ))}
          </ul>
        </details>
      ) : null}

      {/* --- 실패 원문 (구조화된 실패의 code·원문) ---------------------------- */}
      {lead === 'items' ? (
        <details className="border-t border-border-subtle pt-3">
          <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
            {/*
              항목마다 있는 "기술 정보"와 이름이 같아 두 개가 나란히 보였다
              (2026-11-23 화면 점검). 무엇의 원문인지 이름에 쓴다.
            */}
            멈춘 이유의 원문 (code · message)
          </summary>
          <dl className="mt-3 flex flex-col gap-3">
            {failures.map((failure, index) => (
              <div key={`raw-${failure.code}-${index}`} className="flex flex-col gap-1">
                <dt className="font-mono text-caption text-text-muted">
                  {failure.code}
                </dt>
                <dd className="text-caption break-words text-text">
                  {failure.message}
                </dd>
              </div>
            ))}
            {/*
              구조화된 failure가 없을 때의 원문 error는 위에서 펼쳐 보인다
              (rawOnly). 둘 다 있으면 같은 내용이 두 번 나오므로 그리지 않는다.
            */}
          </dl>
        </details>
      ) : null}
    </section>
  )
}

/** 카드 안 구획 제목. 시각은 작게, 구조는 h3로 — 화면 낭독기가 구획을 건너뛸 수 있다. */
function SubHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-caption font-semibold tracking-wide-kr text-text-muted">{children}</h3>
  )
}

/**
 * 하나의 진단.
 *
 * 제목 → 의미 → 기술 정보(원문·code·impact) 순으로 깊어진다. 쉬운 화면과
 * 전문가 화면을 따로 만들지 않고 같은 항목 안에서 내려간다.
 */
function DiagnosticItem({
  item,
  onGoToStep,
  renderAiNote,
  muted = false,
}: {
  item: RunDiagnostic
  onGoToStep?: (stepId: string) => void
  renderAiNote?: AttentionSectionProps['renderAiNote']
  /**
   * 자동 해결 그룹에서 쓴다.
   *
   * 색을 따로 만들지 않고 **제목의 굵기와 색만 한 단계 낮춘다.** 확인 필요
   * 항목과 나란히 놓였을 때 시선이 먼저 가지 않게 하는 것이 목적이고,
   * 새로운 severity 축을 만드는 것이 아니다 — kind는 그대로다.
   */
  muted?: boolean
}) {
  const { view } = item
  return (
    <li className="flex items-start gap-3 py-3">
      <RowIcon
        tone={view.kind === 'attention' ? 'warning' : view.kind === 'repaired' ? 'success' : 'note'}
      />
      <div className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span
          className={
            muted
              ? 'text-body text-text'
              : 'text-body font-medium text-text-strong'
          }
        >
          {/* 등록되지 않은 code면 backend 원문이 제목 자리에 온다. */}
          {view.title || item.message}
        </span>
        {/*
          `label`은 남긴다 — "확인 필요"·"자동 복구"·"참고"는 사용자가 바로
          행동을 판단하는 단서이고, 색에만 의존하지 않는 유일한 표시다.

          반면 `item.code`(UNCOVERED_TARGETS 같은)는 제목 옆에서 뺐다.
          사용자 어휘가 아니라 식별자여서, 제목 옆에 있으면 무엇을 먼저
          읽어야 하는지 흐려진다. 아래 기술 정보에 그대로 있다.
        */}
        <span className="text-caption text-text-muted">{view.label}</span>
      </div>
      {/*
        이 실행의 기록이 뒷받침하지 않는 일반 설명은 보이지 않고 이유만 남긴다
        (2026-11-21, factApplicability.ts). 영향 문구도 아래 기술 정보에서 같다.
      */}
      {view.meaning && !item.withheld?.meaning ? (
        <p className="max-w-prose text-small text-text">{view.meaning}</p>
      ) : null}
      {item.withheld?.meaning ? (
        <WithheldLine what="일반 설명을" reason={item.withheld.meaning} />
      ) : null}

      {/* 결정론 설명 바로 아래. 주지 않으면 아무것도 그리지 않는다. */}
      {renderAiNote ? renderAiNote('diagnostic', item.code) : null}

      {/*
        Attention("무엇이 있었나") -> Pipeline("어디서 일어났나") 이동.

        한 방향만 만든다. 반대 방향(단계 -> 항목)은 StepTable이 이미 건수를
        보여주고 행을 누르면 레일이 열리므로, 링크를 하나 더 두면 같은 화면에
        이동 경로가 두 개가 된다.

        `navigate`가 아니라 콜백이다 — 탭 이동과 단계 선택은 페이지가 가진
        상태이고, 이 component가 router와 selection을 둘 다 알 필요는 없다.
        state를 URL에 새로 얹지 않으므로 뒤로가기도 그대로 동작한다.
      */}
      {item.stepId && onGoToStep ? (
        <button
          type="button"
          onClick={() => onGoToStep(item.stepId as string)}
          className="inline-flex min-h-6 w-fit items-center gap-1 text-caption text-text-muted underline underline-offset-2 hover:text-brand"
        >
          {describeStep(item.stepId).label} 단계에서 발생
          <ArrowRight size={12} strokeWidth={1.5} aria-hidden="true" />
        </button>
      ) : null}
      {item.code || item.message ? (
        <details>
          <summary className="inline-flex min-h-6 cursor-pointer items-center text-caption font-medium text-text-muted">
            기술 정보
          </summary>
          <dl className="mt-2 flex flex-col gap-1">
            <div className="flex flex-col">
              <dt className="font-mono text-caption text-text-muted">code</dt>
              <dd className="font-mono text-caption break-words text-text">
                {item.code}
              </dd>
            </div>
            {item.stepId ? (
              <div className="flex flex-col">
                <dt className="font-mono text-caption text-text-muted">step</dt>
                <dd className="font-mono text-caption text-text">{item.stepId}</dd>
              </div>
            ) : null}
            <div className="flex flex-col">
              <dt className="font-mono text-caption text-text-muted">message</dt>
              <dd className="text-caption break-words text-text">
                {item.message}
              </dd>
            </div>
            {item.impact && item.withheld?.impact ? (
              <div className="flex flex-col">
                <dt className="font-mono text-caption text-text-muted">impact</dt>
                <dd>
                  <WithheldLine what="파이프라인 영향 문구를" reason={item.withheld.impact} />
                </dd>
              </div>
            ) : item.impact ? (
              <div className="flex flex-col">
                <dt className="font-mono text-caption text-text-muted">impact</dt>
                <dd className="text-caption break-words text-text">
                  {item.impact}
                </dd>
              </div>
            ) : null}
          </dl>
        </details>
      ) : null}
      </div>
    </li>
  )
}

/** 목록 행 머리의 상태 아이콘 타일. 글자 라벨이 함께 있어 색만으로 말하지 않는다. */
function RowIcon({ tone }: { tone: 'failure' | 'warning' | 'success' | 'note' }) {
  const Icon =
    tone === 'failure'
      ? OctagonX
      : tone === 'warning'
        ? TriangleAlert
        : tone === 'success'
          ? CircleCheck
          : Info
  const color =
    tone === 'failure'
      ? 'bg-status-failure-bg text-status-failure-fg'
      : tone === 'warning'
        ? 'bg-status-warning-bg text-status-warning-fg'
        : tone === 'success'
          ? 'bg-status-success-bg text-status-success-fg'
          : 'bg-status-info-bg text-status-info-fg'
  return (
    <span
      aria-hidden="true"
      className={cx('mt-0.5 flex size-7 flex-none items-center justify-center rounded-md', color)}
    >
      <Icon size={15} strokeWidth={1.5} />
    </span>
  )
}
