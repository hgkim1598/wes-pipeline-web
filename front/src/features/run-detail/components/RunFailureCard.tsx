import { OctagonX } from 'lucide-react'
import { Link } from 'react-router'

import { HelpTerm } from '@/components/ui/HelpTerm'
import type { ExplanationFailure } from '@/features/run-detail/api'
import { describeFailureCode } from '@/registries/failures'

/*
  실패한 실행의 단일 surface.

  ── 왜 카드 하나인가 ────────────────────────────────────────────────────

  이전에는 같은 실패가 세 곳에 흩어져 있었다 — 상단 job.error 문자열,
  RunLimitations의 "산출물 없음", 단계 표의 진단. 사용자는 전체 상황을
  조립해야 했고, 어느 것이 원인이고 어느 것이 결과인지 알 수 없었다.

  쉬운 설명 카드와 기술 설명 카드를 나란히 두는 것도 답이 아니다. 같은
  사실을 두 번 읽게 된다. 대신 **하나의 표면 안에서 점진적으로 깊어진다.**

    Level 1  무슨 일이 있었나          제목 + 검사가 확인한 것
    Level 2  무엇이 걸렸나             실패 항목 목록 (구조화된 code)
    Level 3  원문과 식별자             기본 접힘

  ── 원인을 만들지 않는다 ────────────────────────────────────────────────

  두 검사가 함께 실패해도 인과관계를 쓰지 않는다. 파이프라인은 "A 때문에 B"를
  기록하지 않았고, 화면이 그것을 지어내면 사용자가 엉뚱한 곳을 고치게 된다.
  각 항목이 **무엇을 확인하는 검사였는지**까지만 말한다.

  ── backend 문자열을 파싱하지 않는다 ────────────────────────────────────

  `missing from PATH: bwa samtools gatk ...` 같은 message에서 도구 이름을
  뽑아내 목록을 만들지 않는다. 그 문장은 계약이 아니라 사람이 읽으라고 쓴
  로그 문구이고, 형식이 바뀌면 조용히 잘못된 목록이 나온다. 원문은 Level 3에
  **원문 그대로** 두고, 도구 준비 방법은 안내 페이지가 설명한다.
*/

export interface RunFailureCardProps {
  failures: ExplanationFailure[]
  /**
   * `GET /api/jobs/{id}`의 error. backend가 실패 message들을 이어 붙인
   * 문자열이며 code가 없다. 구조화된 failures가 있으면 그쪽이 우선이고,
   * 이 값은 Level 3에만 남는다.
   */
  rawError: string | null
  /** 사전 점검 실행인가. 문구를 그 사실에 맞춘다. */
  isPrecheck: boolean
}

export function RunFailureCard({
  failures,
  rawError,
  isPrecheck,
}: RunFailureCardProps) {
  if (failures.length === 0 && !rawError) return null

  const helpPaths = [
    ...new Set(
      failures
        .map((failure) => describeFailureCode(failure.code).helpPath)
        .filter((path): path is string => Boolean(path)),
    ),
  ]

  return (
    <section
      className="flex flex-col gap-4 rounded-md border border-status-failure-bd bg-status-failure-bg p-4"
      aria-labelledby="run-failure-heading"
    >
      {/* Level 1 — 무슨 일이 있었나 */}
      <div className="flex items-start gap-2">
        <OctagonX
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="mt-0.5 flex-none text-status-failure-fg"
        />
        <div className="flex min-w-0 flex-col gap-1">
          <h2
            id="run-failure-heading"
            className="text-h3 font-semibold text-text-strong"
          >
            {isPrecheck
              ? '분석을 시작하기 전 확인에서 멈췄습니다'
              : '분석이 완료되지 못했습니다'}
          </h2>
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
        </div>
      </div>

      {/* Level 2 — 무엇이 걸렸나. 구조화된 failure만 쓴다. */}
      {failures.length > 0 ? (
        <ul className="flex flex-col gap-3 border-t border-status-failure-bd pt-3">
          {failures.map((failure, index) => {
            const view = describeFailureCode(failure.code)
            return (
              <li
                key={`${failure.code}-${index}`}
                className="flex flex-col gap-1"
              >
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-body font-medium text-text-strong">
                    {/* 미등록 code면 backend 원문이 제목이 된다. */}
                    {view.known ? view.title : failure.message}
                  </span>
                  {/*
                    code는 보조 식별자다. 로그·문서와 대조할 때 필요하고,
                    제목을 읽는 데 방해되지 않도록 뒤에 작게 둔다.
                  */}
                  <code className="text-caption text-text-muted">
                    {failure.code}
                  </code>
                  {failure.actualStepLabel ? (
                    <span className="text-caption text-text-muted">
                      · {failure.actualStepLabel}
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

      {/* 다음 행동. 확실히 연결되는 것만 그린다. */}
      {helpPaths.length > 0 ? (
        <div className="flex flex-wrap gap-3 border-t border-status-failure-bd pt-3">
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

      {/* Level 3 — 원문. 기본 접힘. 위 설명의 복제본이 아니라 서버가 쓴 그대로다. */}
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
    </section>
  )
}
