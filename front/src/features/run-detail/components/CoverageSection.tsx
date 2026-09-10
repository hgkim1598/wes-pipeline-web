import { SectionHeader } from '@/components/ui/SectionHeader'
import type { Results } from '@/features/run-detail/api'

/*
  커버리지 — 측정 단위가 이 화면의 전부다.

  ── 무엇이 틀렸었나 `[코드근거]` ────────────────────────────────────────

  이전 라벨은 `완전히 0×인 구간이 차지하는 비율` = 7.2115% 였다.
  "구간이 차지하는 비율"은 **구간의 %**로 읽힌다. 실제로 그 값은
  `basesInFullyUncoveredIntervalsPct` — 완전히 0×인 구간에 **속한 target 염기**가
  전체 target 염기에서 차지하는 비율이다.

  같은 오독을 LLM도 했다(§29-3 ③). 그쪽은 prompt와 concepts로 고쳤는데
  화면은 그대로였다. 여기서 고친다.

  ── 세 가지 측정을 섞지 않는다 ──────────────────────────────────────────

    염기 단위        zeroCoverageBasesPct · breadth
                     분모: 전체 target 염기
    구간 개수        fullyUncoveredIntervals · lowMeanDepthIntervals
                     분모 없음 — 아래 참조
    구간에 속한 염기  basesInFullyUncoveredIntervalsPct · basesInLowMeanDepth…Pct
                     분모: 전체 target 염기 (구간 수가 아니다)

  ── 구간 비율을 계산하지 않는다 `[설계판단]` ────────────────────────────

  "전체 구간의 19.26%"를 쓰고 싶었지만 **전체 구간 수가 계약에 없다.**
  283,942는 파이프라인 로그의 `METRIC coverage_intervals`이고 /results에는
  들어오지 않는다. `targetNonoverlapBases`는 염기 수이지 구간 수가 아니다.

  그래서 구간은 **개수만** 적는다. 분모를 모르면서 %를 만들면 그 순간
  이 파일이 고치려는 오류를 다시 만드는 것이다.

  ── 판정하지 않는다 ─────────────────────────────────────────────────────

  좋다/나쁘다/충분을 쓰지 않는다. 이 프로젝트는 커버리지에 합격 기준을
  두지 않았고(§27-4), 화면이 기준을 발명할 수는 없다.
*/

export interface CoverageSectionProps {
  coverage: NonNullable<Results['coverage']>
}

export function CoverageSection({ coverage }: CoverageSectionProps) {
  const totalBases = coverage.targetNonoverlapBases
  /*
    모든 %의 분모를 한 문장으로 적는다. 값이 없으면 "전체 target 염기"까지만
    말하고 숫자를 지어내지 않는다.
  */
  const perBases = totalBases !== null
    ? `전체 target 염기 ${totalBases.toLocaleString()}개 기준`
    : '전체 target 염기 기준'

  return (
    <section className="flex flex-col gap-5">
      <SectionHeader
        eyebrow="COVERAGE"
        title="커버리지"
        meta="mosdepth 측정값"
      />

      {/*
        초보자용 orientation. 두 문장을 넘기지 않는다 — 여기서 용어를 다
        가르치려 들면 수치를 읽으러 온 사람이 강의문을 먼저 만난다.

        충분/불충분·좋음/나쁨은 쓰지 않는다. 이 프로젝트는 커버리지에 합격
        기준을 두지 않았다(§27-4).
      */}
      <p className="max-w-prose text-small text-text">
        커버리지는 분석 대상 DNA 영역이 얼마나 여러 번 읽혔는지를 보여줍니다.
        아래에는 염기 하나씩 세어 본 값과, target을 나눈 구간 단위로 본 값을
        나누어 표시합니다.
      </p>

      {/* --- 염기 단위 ------------------------------------------------- */}
      <div className="flex flex-col gap-3">
        <MeasurementHeading
          title="염기 단위"
          note={`염기 하나하나를 세어 집계한 값입니다. ${perBases}.`}
        />

        <div className="flex flex-wrap gap-x-12 gap-y-4">
          <Metric
            label="평균 타깃 깊이"
            value={numberOrDash(coverage.meanTargetDepth)}
            unit="×"
          />
          <Metric
            label="한 번도 덮이지 않은 염기"
            value={percentOrDash(coverage.zeroCoverageBasesPct, false)}
            unit="%"
            note={
              coverage.zeroCoverageBases !== null
                ? `${coverage.zeroCoverageBases.toLocaleString()} bp`
                : /*
                    옛 실행은 개수를 남기지 않았다. 비율은 1X breadth에서
                    나오지만 개수는 유도할 수 없으므로 0으로 채우지 않는다.
                  */
                  '개수는 이 실행에 기록되지 않았습니다'
            }
          />
        </div>

        {Object.keys(coverage.breadth).length > 0 ? (
          <dl className="flex flex-col">
            <p className="pb-1 text-caption text-text-muted">
              각 깊이 이상으로 덮인 염기의 비율 · {perBases}
            </p>
            {Object.entries(coverage.breadth).map(([label, pct]) => (
              <div
                key={label}
                className="flex min-h-9 items-center gap-x-4 border-b border-border-subtle py-1.5 last:border-b-0"
              >
                <dt className="w-16 flex-none font-mono text-data text-text">
                  ≥{label}
                </dt>
                <dd className="flex min-w-0 flex-1 items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="h-2 min-w-0 flex-1 overflow-hidden rounded-sm bg-ink-100"
                  >
                    <span
                      className="block h-full rounded-sm bg-cov-30"
                      style={{ width: `${clampPercent(pct)}%` }}
                    />
                  </span>
                  <span className="w-20 flex-none text-right font-mono text-data text-text-strong">
                    {pct} <span className="text-caption text-text-muted">%</span>
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>

      {/* --- 구간 단위 ------------------------------------------------- */}
      <div className="flex flex-col gap-3 border-t border-border pt-4">
        <MeasurementHeading
          title="구간 단위"
          note={
            'target을 나눈 구간마다 평균 깊이를 하나씩 계산한, 위와 다른 측정입니다. ' +
            '부분적으로만 덮인 구간은 평균이 0보다 커서 “완전히 0×인 구간”에 들어가지 않습니다.'
          }
        />

        {/*
          개수와 비율을 한 행에 붙여 쓰지 않는다. 비율의 분모는 구간 수가
          아니라 염기 수이고, 나란히 두면 그 %가 왼쪽 개수의 비율로 읽힌다.
        */}
        <dl className="flex flex-col">
          <Row
            label="완전히 0×인 구간"
            value={countOrDash(coverage.fullyUncoveredIntervals)}
          />
          <Row
            label="└ 그 구간에 속한 target 염기"
            value={basesWithPct(
              coverage.basesInFullyUncoveredIntervals,
              coverage.basesInFullyUncoveredIntervalsPct,
            )}
            hint={perBases}
          />
          <Row
            label={
              coverage.lowMeanDepthThresholdX !== null
                ? `평균 깊이가 ${coverage.lowMeanDepthThresholdX}× 미만인 구간`
                : '평균 깊이가 기준 미만인 구간'
            }
            value={countOrDash(coverage.lowMeanDepthIntervals)}
          />
          <Row
            label="└ 그 구간에 속한 target 염기"
            value={basesWithPct(
              coverage.basesInLowMeanDepthIntervals,
              coverage.basesInLowMeanDepthIntervalsPct,
            )}
            hint={perBases}
          />
        </dl>

        {/*
          두 값의 관계.

          일반 관계와 이번 실행의 관찰을 섞지 않는다. 완전히 0×인 구간에 속한
          염기는 0× 염기의 **부분집합**이므로 그 비율은 0× 염기 비율보다
          같거나 작다 — "항상 더 작다"가 아니다. 두 값이 같아지는 경우
          (0× 염기가 전부 완전 미커버 구간 안에만 있는 경우)도 성립한다.
        */}
        {coverage.basesInFullyUncoveredIntervalsPct !== null &&
        coverage.zeroCoverageBasesPct !== null ? (
          <p className="max-w-prose text-caption text-text-muted">
            완전히 0×인 구간에 속한 염기는 0× 염기의 부분집합이므로, 그 비율은
            염기 단위 0× 비율보다 같거나 작습니다. 이 실행에서는{' '}
            <span className="font-mono">
              {coverage.basesInFullyUncoveredIntervalsPct}%
            </span>{' '}
            와{' '}
            <span className="font-mono">{coverage.zeroCoverageBasesPct}%</span>
            입니다.
          </p>
        ) : null}
      </div>

      {/*
        깊이 중앙값.

        `medianNote`는 파이프라인이 영어로 적은 raw note다
        ("not computed: mosdepth runs with --no-per-base, ...").
        그것을 일반 본문에 그대로 두면 사용자가 가장 먼저 만나는 문장이
        도구 실행 옵션이 된다.

        사람이 읽는 문장을 먼저 두고 원문은 기술 정보로 내린다.
        `medianTargetDepth`는 계약상 항상 null이므로(mosdepth --no-per-base)
        "0"으로 표시하지 않는다 — 측정하지 않은 것과 0은 다르다.
      */}
      {coverage.medianNote ? (
        <div className="flex flex-col gap-1 border-t border-border pt-3">
          <p className="max-w-prose text-small text-text">
            깊이 중앙값은 계산되지 않았습니다. 이번 실행은 염기별 깊이를
            저장하지 않는 방식으로 측정 도구를 실행했기 때문입니다.
          </p>
          <details>
            <summary className="inline-flex min-h-6 cursor-pointer items-center text-caption font-medium text-text-muted">
              기술 정보
            </summary>
            <dl className="mt-2 flex flex-col">
              <div className="flex flex-col">
                <dt className="font-mono text-caption text-text-muted">
                  medianNote
                </dt>
                <dd className="text-caption break-words text-text">
                  {coverage.medianNote}
                </dd>
              </div>
            </dl>
          </details>
        </div>
      ) : null}
    </section>
  )
}

function MeasurementHeading({ title, note }: { title: string; note: string }) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-h3 font-semibold text-text-strong">{title}</h3>
      <p className="max-w-prose text-small text-text-muted">{note}</p>
    </div>
  )
}

function Metric({
  label,
  value,
  unit,
  note,
}: {
  label: string
  value: string
  unit?: string
  note?: string
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-small text-text-muted">{label}</span>
      <span className="font-mono text-metric-md text-text-strong">
        {value}
        {unit ? (
          <span className="ml-1 text-body text-text-muted">{unit}</span>
        ) : null}
      </span>
      {note ? <span className="text-caption text-text-muted">{note}</span> : null}
    </div>
  )
}

function Row({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 border-b border-border-subtle py-1.5 last:border-b-0">
      <dt className="min-w-56 flex-1 text-small text-text-muted">{label}</dt>
      <dd className="flex flex-col items-end text-right">
        <span className="font-mono text-data text-text-strong">{value}</span>
        {hint ? (
          <span className="text-caption text-text-muted">{hint}</span>
        ) : null}
      </dd>
    </div>
  )
}

function numberOrDash(value: number | null): string {
  return value === null ? '—' : value.toLocaleString()
}

/** 개수는 개수로만 적는다. 전체 구간 수가 계약에 없어 %를 만들 수 없다. */
function countOrDash(value: number | null): string {
  return value === null ? '—' : `${value.toLocaleString()}개`
}

/** 염기 수와 그 비율을 한 값으로 적는다. 비율의 분모는 호출부가 hint로 붙인다. */
function basesWithPct(bases: number | null, pct: number | null): string {
  if (bases === null && pct === null) return '—'
  if (bases === null) return `${pct}%`
  if (pct === null) return `${bases.toLocaleString()} bp`
  return `${bases.toLocaleString()} bp · ${pct}%`
}

function percentOrDash(value: number | null, withUnit = true): string {
  if (value === null) return '—'
  return withUnit ? `${value} %` : String(value)
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}
