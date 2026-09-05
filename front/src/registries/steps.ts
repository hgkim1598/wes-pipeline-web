/*
  Pipeline step registry.

  step ID는 backend/pipeline의 어휘다. 화면에 그 문자열을 그대로 노출하면
  사용자는 무엇이 실행되는지 알 수 없고, 반대로 화면 코드에서
  `if (stepId === '03_alignment')` 같은 분기를 하기 시작하면 step이 하나 늘 때
  고쳐야 할 곳이 흩어진다(CLAUDE.md 18장). 그래서 이 파일 하나가 어휘를 갖는다.

  ID 근거 — backend/app/services/config_builder.py
    CORE_STEPS  00_input_validation · 01_raw_qc · 02_preprocessing ·
                03_alignment · 04_processing · 05_coverage_qc · 06_variant_calling
    FINAL_STEP  99_finalization
    optional    11_intervar (planned_steps가 붙인다)

  main.sh의 build_step_plan()은 optional_steps 설정에 따라 08_filtering ·
  10_annotation도 계획에 넣는다(script/main.sh:4665). 현재 backend는
  build_run_config()에서 두 값을 false로 고정해 그 경로가 열리지 않지만,
  열렸을 때 화면이 원문 ID를 노출하지 않도록 라벨만 미리 둔다.

  라벨 근거 — docs/design/prototype.html · pipeline-tab.html의 한국어 표기.
  단 시안의 ID(01_input_validation, 03_preprocess, 07_finalize 등)는 실제
  backend ID와 다르므로, 라벨만 가져오고 키는 실제 ID로 맞췄다.

  tool은 그 단계가 실제로 쓰는 도구다. 시안이 부제로 쓰던 값이며, 사용자가
  로그에서 보게 될 이름과 화면을 연결해 준다.
*/

export interface StepDefinition {
  /** 사용자에게 보이는 이름. */
  label: string
  /** 도구·부제. 없으면 빈 문자열. */
  tool: string
}

const STEP_DEFINITIONS: Record<string, StepDefinition> = {
  '00_input_validation': {
    label: '입력 검증',
    tool: 'FASTQ·reference·환경 사전 점검',
  },
  '01_raw_qc': { label: '원본 품질 검사', tool: 'FastQC' },
  '02_preprocessing': { label: '전처리', tool: 'fastp' },
  '03_alignment': { label: '참조 유전체 정렬', tool: 'BWA-MEM' },
  '04_processing': { label: 'BAM 정리·보정', tool: 'MarkDuplicates · BQSR' },
  '05_coverage_qc': { label: '커버리지 검사', tool: 'mosdepth' },
  '06_variant_calling': { label: '변이 검출', tool: 'HaplotypeCaller' },
  '08_filtering': { label: '변이 필터링', tool: 'GATK' },
  '10_annotation': { label: '변이 주석', tool: 'ANNOVAR' },
  '11_intervar': { label: 'ACMG 자동 분류', tool: 'InterVar' },
  '99_finalization': { label: '결과 정리', tool: '산출물·매니페스트 정리' },
}

/**
 * 모르는 step이 와도 화면을 세우지 않는다.
 *
 * pipeline에 단계가 추가됐는데 이 registry가 아직 모르는 경우, 의미를 지어내는
 * 대신 ID를 그대로 이름으로 쓴다. 사용자는 최소한 무엇이 실행됐는지 대조할 수
 * 있고, 개발자는 registry에 한 줄을 추가하면 된다.
 */
export function describeStep(stepId: string): StepDefinition {
  return STEP_DEFINITIONS[stepId] ?? { label: stepId, tool: '' }
}

/**
 * 목록에 보이는 짧은 번호. `03_alignment` -> `03`.
 * 접두 숫자가 없으면 빈 문자열이며, 그때 화면은 번호 열을 비운다.
 */
export function stepOrdinal(stepId: string): string {
  const match = /^(\d+)_/.exec(stepId)
  return match ? match[1] : ''
}
