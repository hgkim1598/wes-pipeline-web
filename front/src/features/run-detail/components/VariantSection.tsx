import { Info } from 'lucide-react'

import { SectionHeader } from '@/components/ui/SectionHeader'
import type { Results } from '@/features/run-detail/api'

/*
  변이 검출 — 숫자와 자격 조건을 떼어 놓지 않는다.

  ── 무엇이 문제였나 ─────────────────────────────────────────────────────

  이전에는 KV 세 행이었다.

    검출 레코드   52,379
    필터 적용     아니오
    결과 지점     raw VCF (no filtering applied)

  첫 행만 읽으면 "52,379개의 확정 변이"가 된다. 세 값이 함께 읽혀야만 참인
  사실인데, 표는 그 순서를 강제하지 못한다. 아래로 갈수록 덜 중요해 보이는
  것이 표의 시각적 성질이라 자격 조건이 각주처럼 읽힌다.

  그래서 숫자와 자격을 **하나의 블록**으로 묶고, 숫자 바로 옆에 무엇을 센
  것인지를 적는다.

  ── 문구의 출처 ─────────────────────────────────────────────────────────

  새로 쓰지 않았다. `filteringApplied === false`일 때 backend deterministic
  explanation이 만드는 `UNFILTERED_VARIANTS` limitation과 같은 사실이고,
  `coreEndpoint`는 파이프라인이 기록한 문자열 그대로다.

  ⚠️ 여기서 limitation 문장을 다시 렌더링하지는 않는다. 그 문장은
  RunLimitations가 탭 바깥에서 이미 말하고 있고, 두 곳에 두면 §26-3에서
  제거한 것과 같은 종류의 중복이 된다. 이 섹션은 **숫자에 붙는 자격**만
  말한다 — 숫자를 보는 사람이 그 자리에서 알아야 하는 것이기 때문이다.

  ── path는 본문이 아니다 ────────────────────────────────────────────────

  raw VCF·gVCF의 상대 경로는 결과를 이해하는 데 필요하지 않다. 파일 탭이
  산출물을 다루고, 여기서는 기술 정보로 접어 둔다.
*/

export interface VariantSectionProps {
  variantCalling: NonNullable<Results['variantCalling']>
}

export function VariantSection({ variantCalling }: VariantSectionProps) {
  const { rawVariantRecords, filteringApplied, coreEndpoint } = variantCalling
  const count =
    rawVariantRecords === null ? '—' : rawVariantRecords.toLocaleString()

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader eyebrow="VARIANTS" title="변이 검출" />

      <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
        {/*
          숫자와 그것이 무엇인지가 같은 시각 단위 안에 있다. "후보 기록"이
          값의 라벨이지 아래에 붙는 설명이 아니다.
        */}
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="font-mono text-metric-lg text-text-strong">
            {count}
          </span>
          <span className="text-body text-text">
            {filteringApplied ? '변이 기록' : '변이 후보 기록'}
          </span>
        </div>

        {/*
          필터가 적용되지 않았다는 사실은 숫자와 분리될 수 없다. tint 카드가
          아니라 같은 블록 안의 한 줄이다 — 경고가 아니라 이 숫자의 정의다.
        */}
        {!filteringApplied ? (
          <div className="flex items-start gap-2 border-t border-border pt-3">
            <Info
              size={14}
              strokeWidth={1.5}
              aria-hidden="true"
              className="mt-0.5 flex-none text-text-muted"
            />
            <p className="max-w-prose text-small text-text">
              품질 필터가 적용되지 않은 상태의 수치입니다. 확정된 변이 목록이
              아니라 이후 검토가 필요한 후보 기록입니다.
            </p>
          </div>
        ) : null}

        {/*
          결과 단계.

          `coreEndpoint`는 파이프라인이 적은 기술 명칭이다
          ("raw VCF (no filtering applied)"). 정확하지만 초보자에게 의미가
          바로 전달되지 않는다 — "raw"가 품질이 낮다는 뜻인지, 파일 형식인지
          알 수 없다.

          사람 말을 먼저 두고 원래 명칭은 기술 정보에서 병기한다.
          문장을 지어내지 않고 `filteringApplied`가 정하는 두 갈래만 쓴다.
        */}
        <dl className="flex flex-col border-t border-border pt-3">
          <Row
            label="결과 단계"
            value={
              filteringApplied ? '품질 필터가 적용된 변이 결과' : '필터 적용 전 변이 결과'
            }
          />
        </dl>

        <details>
          <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
            기술 정보
          </summary>
          <dl className="mt-2 flex flex-col">
            {/* 파이프라인이 적은 원래 명칭. 위의 "결과 단계"와 짝이다. */}
            <Row label="결과 지점 (원문)" value={coreEndpoint || '—'} mono />
            <Row
              label="필터 적용"
              value={filteringApplied ? '예' : '아니오'}
            />
            <Row
              label="raw VCF"
              value={variantCalling.rawVcfRelative ?? '—'}
              mono
            />
            <Row label="gVCF" value={variantCalling.gvcfRelative ?? '—'} mono />
            <Row label="assembly" value={variantCalling.assembly ?? '—'} mono />
          </dl>
        </details>
      </div>
    </section>
  )
}

function Row({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 border-b border-border-subtle py-1.5 last:border-b-0">
      <dt className="min-w-40 flex-1 text-small text-text-muted">{label}</dt>
      <dd
        className={
          mono
            ? 'font-mono text-data break-all text-text-strong'
            : 'text-small text-text-strong'
        }
      >
        {value}
      </dd>
    </div>
  )
}
