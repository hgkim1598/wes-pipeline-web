import { CircleCheck, OctagonX, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'

import { HelpTerm } from '@/components/ui/HelpTerm'
import type { ExplanationFailure } from '@/features/run-detail/api'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { describeFailureCode } from '@/registries/failures'

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
}

export function AttentionSection({
  failures,
  rawError,
  diagnostics,
  isPrecheck,
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
    맨 아래 "기술 정보"에 그대로 남는다.
  */
  const warnings = diagnostics.filter((item) => item.view.kind !== 'failure')
  const repaired = warnings.filter((item) => item.view.kind === 'repaired')
  const needsAttention = warnings.filter(
    (item) => item.view.kind !== 'repaired',
  )

  const hasFailure = failures.length > 0 || Boolean(rawError)
  if (!hasFailure && needsAttention.length === 0 && repaired.length === 0) {
    return null
  }

  const helpPaths = [
    ...new Set(
      failures
        .map((failure) => describeFailureCode(failure.code).helpPath)
        .filter((path): path is string => Boolean(path)),
    ),
  ]

  const tone = hasFailure
    ? 'border-status-failure-bd bg-status-failure-bg'
    : 'border-border bg-surface'

  return (
    <section
      className={`flex flex-col gap-4 rounded-md border p-4 ${tone}`}
      aria-labelledby="run-attention-heading"
    >
      <div className="flex items-start gap-2">
        {hasFailure ? (
          <OctagonX
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="mt-0.5 flex-none text-status-failure-fg"
          />
        ) : (
          <TriangleAlert
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="mt-0.5 flex-none text-status-warning-fg"
          />
        )}
        <div className="flex min-w-0 flex-col gap-1">
          <h2
            id="run-attention-heading"
            className="text-h3 font-semibold text-text-strong"
          >
            {hasFailure
              ? isPrecheck
                ? '분석을 시작하기 전 확인에서 멈췄습니다'
                : '분석이 완료되지 못했습니다'
              : '확인이 필요한 사항이 있습니다'}
          </h2>
          {hasFailure ? (
            <p className="max-w-prose text-body text-text">
              {isPrecheck ? (
                <>
                  <HelpTerm termId="precheck">사전 점검</HelpTerm>에서 문제가
                  확인되어 분석을 시작하지 않았습니다. 아래 항목을 준비한 뒤 다시
                  실행하면 됩니다.
                </>
              ) : (
                '아래 항목에서 실행이 중단되었습니다.'
              )}
            </p>
          ) : null}
        </div>
      </div>

      {/* --- 실패 ------------------------------------------------------- */}
      {failures.length > 0 ? (
        <ul className="flex flex-col gap-3 border-t border-status-failure-bd pt-3">
          {failures.map((failure, index) => {
            const view = describeFailureCode(failure.code)
            return (
              <li key={`${failure.code}-${index}`} className="flex flex-col gap-1">
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
                    할지 흐려진다. 아래 "기술 정보"에서 확인할 수 있다.
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
              </li>
            )
          })}
        </ul>
      ) : null}

      {helpPaths.length > 0 ? (
        <div className="flex flex-wrap gap-3">
          {helpPaths.map((path) => (
            <Link
              key={path}
              to={path}
              className="inline-flex min-h-8 items-center rounded-sm border border-border-strong bg-surface px-4 text-body font-medium text-text-strong no-underline hover:bg-sunken hover:no-underline"
            >
              {path.endsWith('#tools')
                ? '프로그램 준비 방법 보기'
                : '참조 데이터 준비 방법 보기'}
            </Link>
          ))}
        </div>
      ) : null}

      {/* --- 확인이 필요한 진단 ------------------------------------------ */}
      {needsAttention.length > 0 ? (
        <ul
          className={`flex flex-col gap-4 ${
            hasFailure ? 'border-t border-status-failure-bd pt-3' : ''
          }`}
        >
          {needsAttention.map((item) => (
            <DiagnosticItem key={item.key} item={item} />
          ))}
        </ul>
      ) : null}

      {/* --- 자동 해결 ---------------------------------------------------- */}
      {repaired.length > 0 ? (
        <details className="border-t border-border pt-3">
          <summary className="inline-flex min-h-6 cursor-pointer items-center gap-2 text-small font-medium text-text-muted">
            <CircleCheck size={14} strokeWidth={1.5} aria-hidden="true" />
            자동으로 해결된 항목 {repaired.length}건
          </summary>
          <ul className="mt-3 flex flex-col gap-4">
            {repaired.map((item) => (
              <DiagnosticItem key={item.key} item={item} />
            ))}
          </ul>
        </details>
      ) : null}

      {/* --- 실패 원문 ---------------------------------------------------- */}
      {hasFailure ? (
        <details className="border-t border-status-failure-bd pt-3">
          <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
            기술 정보
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
              구조화된 failure가 없을 때만 원문 error가 유일한 단서다.
              둘 다 있으면 같은 내용이 두 번 나오므로 그리지 않는다.
            */}
            {failures.length === 0 && rawError ? (
              <div className="flex flex-col gap-1">
                <dt className="font-mono text-caption text-text-muted">
                  pipeline error
                </dt>
                <dd className="text-caption break-words whitespace-pre-wrap text-text">
                  {rawError}
                </dd>
              </div>
            ) : null}
          </dl>
        </details>
      ) : null}
    </section>
  )
}

/**
 * 하나의 진단.
 *
 * 제목 → 의미 → 기술 정보(원문·code·impact) 순으로 깊어진다. 쉬운 화면과
 * 전문가 화면을 따로 만들지 않고 같은 항목 안에서 내려간다.
 */
function DiagnosticItem({ item }: { item: RunDiagnostic }) {
  const { view } = item
  return (
    <li className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-body font-medium text-text-strong">
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
      {view.meaning ? (
        <p className="max-w-prose text-small text-text">{view.meaning}</p>
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
            {item.impact ? (
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
    </li>
  )
}
