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
  /**
   * 이 단계가 무엇을 하고 왜 필요한지 (Layer 1).
   *
   * 유전체 분석을 처음 보는 사용자가 단계 이름만으로는 알 수 없는 것을
   * 한두 문장으로 적는다. 이번 Run의 결과가 아니라 **단계의 성질**이므로
   * 실행마다 달라지지 않는다 — 실제 측정값과 섞이지 않도록 표시도 분리한다
   * (CLAUDE.md 21장: 설명과 실제 데이터를 혼동시키지 않는다).
   *
   * 없으면 빈 문자열이고, 화면은 설명 줄을 그리지 않는다.
   */
  purpose: string
}

const STEP_DEFINITIONS: Record<string, StepDefinition> = {
  '00_input_validation': {
    label: '입력 검증',
    tool: 'FASTQ·reference·환경 사전 점검',
    purpose:
      '분석을 시작하기 전에 입력 FASTQ와 참조 유전체, 필요한 도구가 모두 갖춰져 있는지 확인합니다. 여기서 걸러내지 못한 문제는 몇 시간 뒤 중간 단계에서 실패로 나타납니다.',
  },
  '01_raw_qc': {
    label: '원본 품질 검사',
    tool: 'FastQC',
    purpose:
      '장비에서 나온 원본 read의 품질을 그대로 측정합니다. 염기 품질 점수, 어댑터 잔존량, GC 분포처럼 이후 결과를 좌우하는 특성을 미리 파악하는 단계입니다.',
  },
  '02_preprocessing': {
    label: '전처리',
    tool: 'fastp',
    purpose:
      '품질이 낮은 구간과 시퀀싱 어댑터를 잘라냅니다. 남겨 두면 참조 유전체에 잘못 정렬되어 없는 변이를 만들어낼 수 있습니다.',
  },
  '03_alignment': {
    label: '참조 유전체 정렬',
    tool: 'BWA-MEM',
    purpose:
      '수천만 개의 짧은 read가 각각 유전체의 어느 위치에서 온 것인지 찾아 붙입니다. 이후 모든 분석이 이 위치 정보 위에서 이루어집니다.',
  },
  '04_processing': {
    label: 'BAM 정리·보정',
    tool: 'MarkDuplicates · BQSR',
    purpose:
      'PCR 증폭 과정에서 생긴 중복 read를 표시하고, 장비가 매긴 염기 품질 점수를 실제 오류율에 맞게 보정합니다. 같은 변이가 여러 번 세어지거나 품질이 과대평가되는 것을 막습니다.',
  },
  '05_coverage_qc': {
    label: '커버리지 검사',
    tool: 'mosdepth',
    purpose:
      '분석 대상 영역이 read로 얼마나 덮였는지 측정합니다. 깊이가 얕은 구간에서는 변이가 있어도 검출되지 않으므로, 결과를 어디까지 신뢰할 수 있는지 판단하는 근거가 됩니다.',
  },
  '06_variant_calling': {
    label: '변이 검출',
    tool: 'HaplotypeCaller',
    purpose:
      '정렬된 read를 참조 서열과 비교해 이 샘플에서 다른 지점을 찾아냅니다. 이 단계의 산출물(VCF)이 분석의 핵심 결과입니다.',
  },
  '08_filtering': {
    label: '변이 필터링',
    tool: 'GATK',
    purpose:
      '검출된 변이 중 품질 지표가 낮아 위양성일 가능성이 높은 것을 걸러냅니다.',
  },
  '10_annotation': {
    label: '변이 주석',
    tool: 'ANNOVAR',
    purpose:
      '각 변이가 어떤 유전자의 어느 위치에 있는지, 알려진 데이터베이스에 기록이 있는지를 덧붙입니다. 변이 목록을 해석 가능한 정보로 바꾸는 단계입니다.',
  },
  '11_intervar': {
    label: 'ACMG 자동 분류',
    tool: 'InterVar',
    purpose:
      'ACMG 지침의 근거 코드를 규칙에 따라 자동으로 적용합니다. 자동 적용 결과이며 최종 판정이 아닙니다.',
  },
  '99_finalization': {
    label: '결과 정리',
    tool: '산출물·매니페스트 정리',
    purpose:
      '생성된 파일 목록과 사용한 도구 버전·설정을 기록으로 남깁니다. 나중에 같은 분석을 재현하거나 결과의 출처를 확인할 때 쓰입니다.',
  },
}

/**
 * 모르는 step이 와도 화면을 세우지 않는다.
 *
 * pipeline에 단계가 추가됐는데 이 registry가 아직 모르는 경우, 의미를 지어내는
 * 대신 ID를 그대로 이름으로 쓴다. 사용자는 최소한 무엇이 실행됐는지 대조할 수
 * 있고, 개발자는 registry에 한 줄을 추가하면 된다.
 */
export function describeStep(stepId: string): StepDefinition {
  return STEP_DEFINITIONS[stepId] ?? { label: stepId, tool: '', purpose: '' }
}

/**
 * 목록에 보이는 짧은 번호. `03_alignment` -> `03`.
 * 접두 숫자가 없으면 빈 문자열이며, 그때 화면은 번호 열을 비운다.
 */
export function stepOrdinal(stepId: string): string {
  const match = /^(\d+)_/.exec(stepId)
  return match ? match[1] : ''
}
