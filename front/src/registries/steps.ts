/*
  Pipeline step — 화면 어휘.

  ── 이 파일이 소유하는 것 ───────────────────────────────────────────────

  **표시(presentation)뿐이다.**

    STEP_SUBTITLE   단계 이름 옆에 보이는 부제
    stepOrdinal     `03_alignment` -> `03`

  단계의 **의미**(label · purpose · tools)는 이 파일에 없다. 저장소 최상위의

    config/knowledge/wes_steps.json

  이 canonical source이고, backend도 같은 파일을 읽는다.
  로딩·검증은 registries/knowledge.ts가 맡는다.

  ── 왜 부제(subtitle)와 tools를 나눴는가 ────────────────────────────────

  이전에는 `tool: string` 하나에 세 가지가 섞여 있었다.

    실제 도구명        FastQC · fastp · BWA-MEM · mosdepth · …
    도구 아닌 절차명    "MarkDuplicates · BQSR"
    도구 아닌 한국어 부제 "FASTQ·reference·환경 사전 점검"

  이 혼재 때문에 `08_filtering`이 `GATK`, `10_annotation`이 `ANNOVAR`로
  적혀 있어도 **아무도 눈치채지 못했다.** 둘 다 파이프라인이 실행하지 않는
  도구였다(실제로는 bcftools).

  그래서 갈랐다.

    tools          shared source. main.sh와 기계적으로 대조할 수 있는 사실
    STEP_SUBTITLE  여기. 화면에 무엇을 쓸지의 문제

  부제는 도구 목록과 다를 수 있다 — 04는 "MarkDuplicates · BQSR"이 사용자에게
  더 유용하고(gatk·samtools보다), 00·99는 도구를 실행하지 않는다.
  **그것은 표시 판단이지 사실이 아니므로 여기 있는 것이 맞다.**

  ── step ID를 화면 코드에서 분기하지 않는다 ─────────────────────────────

  `if (stepId === '03_alignment')` 같은 분기를 만들지 않는다(CLAUDE.md 18장).
  registry에 없는 step이 와도 ID를 그대로 이름으로 쓴다.
*/

import { stepKnowledge } from '@/registries/knowledge'

export interface StepDefinition {
  /** 사용자에게 보이는 이름. */
  label: string
  /** 도구·부제. 없으면 빈 문자열. */
  tool: string
  /** 이 단계가 무엇을 하고 왜 필요한지 (Layer 1). */
  purpose: string
}

/*
  화면 부제.

  shared source의 `tools`와 다른 값일 수 있다 — 위 주석 참조.
  여기 없는 step은 `tools`를 " · "로 이어 붙여 쓴다.
*/
const STEP_SUBTITLE: Record<string, string> = {
  '00_input_validation': 'FASTQ·reference·환경 사전 점검',
  '01_raw_qc': 'FastQC',
  '03_alignment': 'BWA-MEM',
  '04_processing': 'MarkDuplicates · BQSR',
  '06_variant_calling': 'HaplotypeCaller',
  '99_finalization': '산출물·매니페스트 정리',
}

/**
 * 모르는 step이 와도 화면을 세우지 않는다.
 *
 * pipeline에 단계가 추가됐는데 shared source가 아직 모르는 경우, 의미를
 * 지어내는 대신 ID를 그대로 이름으로 쓴다. 사용자는 최소한 무엇이 실행됐는지
 * 대조할 수 있고, 개발자는 JSON에 한 항목을 추가하면 된다.
 */
export function describeStep(stepId: string): StepDefinition {
  const knowledge = stepKnowledge(stepId)
  if (!knowledge) return { label: stepId, tool: '', purpose: '' }
  return {
    label: knowledge.label,
    tool: STEP_SUBTITLE[stepId] ?? knowledge.tools.join(' · '),
    purpose: knowledge.purpose,
  }
}

/**
 * 목록에 보이는 짧은 번호. `03_alignment` -> `03`.
 * 접두 숫자가 없으면 빈 문자열이며, 그때 화면은 번호 열을 비운다.
 */
export function stepOrdinal(stepId: string): string {
  const match = /^(\d+)_/.exec(stepId)
  return match ? match[1] : ''
}
