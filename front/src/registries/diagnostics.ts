/*
  Diagnostic(진단 사건) registry.

  main.sh의 step_warning()이 남기는 code를 사용자 어휘로 옮긴다.

  ── 왜 frontend에 이 registry가 있는가 ──────────────────────────────────

  현재 backend 계약에는 severity가 없다. main.sh의 step_warning()은
  <code> <message> <impact> <can_continue> 네 값만 기록하고(script/main.sh:697),
  28개 code가 전부 같은 무게로 warnings[]에 들어간다. 그래서

    DBSNP_MISSING          번들이 선언한 파일을 읽지 못함 → 실제 설정 오류
    DBSNP_NOT_CONFIGURED   번들이 dbSNP를 선언하지 않음   → 정상적인 미설정

  두 사건이 **구조적으로 완전히 동일한 모양**으로 도착한다. 구분은 code
  문자열에만 존재한다.

  올바른 최종 해법은 pipeline이 자기 판단을 함께 기록하는 것이다
  (step_warning에 severity 인자 추가 → step JSON → API). 그 전까지의
  분류처가 이 파일이다. backend가 severity를 주기 시작하면 이 파일은
  "backend가 주지 않은 code의 기본값"으로 축소되고, 호출부는 바뀌지 않는다.

  ── 두 축을 합치지 않는다 ──────────────────────────────────────────────

  severity(확인이 필요한가)와 resolution(파이프라인이 이미 해결했는가)은
  서로 다른 질문이다. NM_MD_REPAIRED는 "확인 불필요"이면서 동시에
  "복구 완료"이고, DBSNP_NOT_CONFIGURED는 "확인 불필요"이지만 복구할
  대상이 아니다. 하나의 enum으로 만들면 이 차이가 사라진다.

  두 축은 여기까지 분리된 채로 오고, describeDiagnostic()이 표시 직전에
  한 번만 합친다. 사용자는 축이 둘이라는 사실을 몰라도 된다.

  ── 분류 근거 ─────────────────────────────────────────────────────────

  각 code의 severity는 main.sh가 그 자리에 적어 둔 impact 문장을 근거로
  정했다. 지어낸 판단이 아니라 pipeline 자신의 진술을 옮긴 것이다. 예:

    DBSNP_NOT_CONFIGURED
      impact: "Variant records will carry no rsID; the calls themselves are
               unaffected"                              script/main.sh:3802
      → 분석 결과에 영향 없음 → info

    UNCOVERED_TARGETS
      impact: "Variants cannot be called in uncovered intervals"
                                                        script/main.sh:3707
      → 결과 해석에 영향 있음 → attention
*/

/** 확인이 필요한 사건인가. 사건의 무게. */
export type DiagnosticSeverity = 'attention' | 'info'

/** 파이프라인이 이 사건을 이미 처리했는가. 무게와 독립된 축이다. */
export type DiagnosticResolution = 'repaired' | null

export interface DiagnosticDefinition {
  severity: DiagnosticSeverity
  resolution: DiagnosticResolution
  /**
   * 한 줄 제목. backend의 영문 message를 대체한다.
   *
   * message 원문은 버리지 않는다 — 화면이 제목 아래에 함께 보여주므로
   * 사용자는 요약과 서버 원문을 모두 볼 수 있다.
   */
  title: string
  /**
   * 초보자용 설명 (Layer 1). "무슨 일이 있었고 그래서 무엇을 뜻하는가".
   *
   * backend의 impact는 영문 기술 문장이라 그대로 두면 초보자가 읽지
   * 못한다. 여기서는 같은 사실을 한국어로 쓰되 impact가 말하지 않는
   * 내용을 덧붙이지 않는다.
   */
  meaning: string
}

const DIAGNOSTICS: Record<string, DiagnosticDefinition> = {
  // --- 04_processing ---------------------------------------------------
  NM_MD_REPAIRED: {
    severity: 'info',
    resolution: 'repaired',
    title: 'NM/MD 태그를 자동 보정한 뒤 재검증을 통과했습니다',
    meaning:
      'NM·MD는 read가 참조 서열과 몇 군데 다른지를 적어 두는 보조 태그입니다. 정렬 과정에서 이 값이 어긋나 samtools calmd로 다시 계산했고, 재검증에서 오류가 남지 않았습니다. read 서열·좌표·중복 표시는 바뀌지 않습니다.',
  },
  BQSR_DIAG_FAILED: {
    severity: 'info',
    resolution: null,
    title: '품질 보정 진단 그래프를 만들지 못했습니다',
    meaning:
      '보정 전후를 비교하는 참고용 그래프입니다. 보정 자체는 정상 수행되었고 BAM에는 영향이 없습니다.',
  },
  RSCRIPT_MISSING: {
    severity: 'info',
    resolution: null,
    title: 'Rscript가 없어 진단 그래프를 건너뛰었습니다',
    meaning: '그래프 생성용 도구가 서버에 없습니다. 분석 결과에는 영향이 없습니다.',
  },
  READ_NAME_MODE_UNKNOWN: {
    severity: 'info',
    resolution: null,
    title: 'BAM의 첫 read 이름을 읽지 못했습니다',
    meaning:
      'read 이름 형식을 확인해 기록해 두는 절차입니다. 확인만 실패했을 뿐 정렬 결과에는 영향이 없습니다.',
  },

  // --- 05_coverage_qc --------------------------------------------------
  ZERO_COVERAGE_TARGET_BASES: {
    severity: 'attention',
    resolution: null,
    title: 'read가 한 번도 덮지 않은 target 염기가 있습니다',
    meaning:
      'target 영역 안에 read가 한 번도 덮지 않은(0×) 염기가 있습니다. 그 위치에서는 변이가 있어도 검출할 근거가 부족합니다. 결과에 변이가 없다는 것이 그 자리가 정상이라는 뜻은 아닙니다. 깊이 분포는 mosdepth의 regions·thresholds 산출물에서 확인할 수 있습니다.',
  },
  /*
    legacy. 2026-09-07 이전 run이 남긴 code다.

    당시 이 warning은 **구간 단위** 값(평균 depth가 0인 interval이 차지하는
    비율)으로 판단하면서 메시지는 "target 염기의 X%가 zero coverage"라고 말했다.
    두 값은 다르고 구간 값이 항상 더 작다. 그래서 새 run은
    ZERO_COVERAGE_TARGET_BASES를 쓴다.

    이 entry를 지우지 않는 이유는 옛 run을 계속 읽어야 하기 때문이다. 설명은
    그 run이 실제로 측정한 것(구간)에 맞춰 적는다 — 옛 값을 염기 비율로
    다시 해석하지 않는다.
  */
  UNCOVERED_TARGETS: {
    severity: 'attention',
    resolution: null,
    title: '평균 depth가 0인 target 구간이 있습니다',
    meaning:
      '이 실행은 target을 나눈 구간마다 평균 depth를 보고, 그 값이 0인 구간의 비율을 기록했습니다. 해당 구간에서는 변이를 검출할 수 없습니다. 이 수치는 구간 단위이므로, 부분적으로만 덮인 구간에 남아 있는 0× 염기는 포함되지 않습니다 — 실제 0× 염기 비율은 이보다 큽니다.',
  },
  LOW_MEAN_COVERAGE: {
    severity: 'attention',
    resolution: null,
    title: '평균 깊이가 설정된 기준값보다 낮습니다',
    meaning:
      '깊이가 낮으면 실제로 존재하는 변이를 놓칠 가능성이 커집니다. 분석은 그대로 진행되었습니다.',
  },

  // --- 06_variant_calling ----------------------------------------------
  DBSNP_NOT_CONFIGURED: {
    severity: 'info',
    resolution: null,
    title: 'dbSNP가 설정되지 않아 rsID가 부여되지 않았습니다',
    meaning:
      'rsID는 이미 알려진 변이에 붙는 공개 식별자입니다. 참조용 정보이며, 변이를 찾아내는 과정 자체에는 관여하지 않습니다.',
  },
  DBSNP_MISSING: {
    severity: 'attention',
    resolution: null,
    title: 'dbSNP 파일이 선언되어 있으나 읽지 못했습니다',
    meaning:
      '서버 설정에는 dbSNP 경로가 있지만 실제 파일을 열 수 없었습니다. 설정 오류일 가능성이 높으므로 서버의 참조 데이터 구성을 확인해야 합니다. 변이 검출 결과 자체는 영향받지 않았습니다.',
  },
  NO_VARIANTS_PASSED: {
    severity: 'attention',
    resolution: null,
    title: '품질 필터를 통과한 변이가 없습니다',
    meaning:
      '설정된 기준을 넘은 변이가 하나도 없습니다. 입력 데이터의 양이나 품질, 또는 필터 기준을 함께 확인해야 합니다.',
  },
  BCFTOOLS_STATS_FAILED: {
    severity: 'info',
    resolution: null,
    title: 'VCF 통계 요약을 만들지 못했습니다',
    meaning: '참고용 통계입니다. VCF 파일 자체는 정상적으로 생성되었습니다.',
  },

  // --- 01_raw_qc -------------------------------------------------------
  MULTIQC_MISSING: {
    severity: 'info',
    resolution: null,
    title: 'MultiQC가 설치되어 있지 않습니다',
    meaning:
      'MultiQC는 여러 QC 결과를 하나로 모아 보여주는 도구입니다. 개별 FastQC 리포트는 정상적으로 생성되었습니다.',
  },
  MULTIQC_FAILED: {
    severity: 'attention',
    resolution: null,
    title: 'MultiQC가 실행 중 종료되었습니다',
    meaning:
      '통합 QC 리포트가 없습니다. 개별 FastQC 리포트는 파일 탭에서 확인할 수 있습니다.',
  },
  MULTIQC_NO_REPORT: {
    severity: 'attention',
    resolution: null,
    title: 'MultiQC가 실행됐지만 리포트가 생성되지 않았습니다',
    meaning:
      '통합 QC 리포트가 없습니다. 개별 FastQC 리포트는 파일 탭에서 확인할 수 있습니다.',
  },

  // --- 00_input_validation ---------------------------------------------
  GZIP_MISSING: {
    severity: 'attention',
    resolution: null,
    title: 'gzip이 없어 FASTQ 압축 무결성 검사를 하지 못했습니다',
    meaning:
      '입력 파일이 중간에 잘렸는지 확인하는 절차를 건너뛰었습니다. 파일이 손상되어 있어도 이 단계에서는 드러나지 않습니다.',
  },
  DISK_UNKNOWN: {
    severity: 'info',
    resolution: null,
    title: '여유 디스크 용량을 확인하지 못했습니다',
    meaning: '사전 점검 항목 하나를 건너뛰었습니다. 실행 자체는 계속됩니다.',
  },
  RAM_UNKNOWN: {
    severity: 'info',
    resolution: null,
    title: '사용 가능한 메모리를 확인하지 못했습니다',
    meaning: '사전 점검 항목 하나를 건너뛰었습니다. 실행 자체는 계속됩니다.',
  },
  SAMPLESHEET_INSIDE_RUN: {
    severity: 'info',
    resolution: null,
    title: 'samplesheet가 실행 디렉터리 안에 있습니다',
    meaning:
      '입력 파일이 결과물과 같은 위치에 있습니다. 재실행 시 덮어써질 수 있다는 안내이며, 이번 분석에는 영향이 없습니다.',
  },

  // --- 10_annotation ---------------------------------------------------
  CLINVAR_NOT_CONFIGURED: {
    severity: 'info',
    resolution: null,
    title: 'ClinVar가 설정되지 않아 임상 주석이 부여되지 않았습니다',
    meaning:
      'ClinVar는 변이의 알려진 임상적 해석을 모아 둔 공개 데이터베이스입니다. 참조 정보이며 변이 검출에는 관여하지 않습니다.',
  },
  CLINVAR_MISSING: {
    severity: 'attention',
    resolution: null,
    title: 'ClinVar 파일이 선언되어 있으나 읽지 못했습니다',
    meaning: '서버의 참조 데이터 구성을 확인해야 합니다.',
  },
  CLINVAR_INCOMPATIBLE: {
    severity: 'attention',
    resolution: null,
    title: 'ClinVar와 이번 분석의 참조 유전체가 맞지 않습니다',
    meaning:
      '염색체 이름 표기나 assembly가 달라 주석을 붙일 수 없습니다. 잘못된 주석이 붙는 것을 막기 위해 건너뛰었습니다.',
  },
  CLINVAR_ANNOTATE_FAILED: {
    severity: 'attention',
    resolution: null,
    title: 'ClinVar 주석 부여가 완료되지 않았습니다',
    meaning: '주석이 없는 VCF는 그대로 남아 있습니다.',
  },
  VEP_NOT_WIRED: {
    severity: 'info',
    resolution: null,
    title: 'VEP는 아직 연결되지 않은 기능입니다',
    meaning:
      '서버에 VEP와 캐시가 있지만 파이프라인이 아직 호출하지 않습니다. 예정된 기능이며 오류가 아닙니다.',
  },
  VEP_MISSING: {
    severity: 'info',
    resolution: null,
    title: 'VEP 캐시는 설정되어 있으나 실행 파일이 없습니다',
    meaning: 'VEP 주석을 건너뛰었습니다. 다른 주석과 변이 검출에는 영향이 없습니다.',
  },

  // --- 11_intervar -----------------------------------------------------
  AUTOMATED_EVIDENCE_ONLY: {
    severity: 'info',
    resolution: null,
    title: 'ACMG 분류는 자동 근거 적용 결과입니다',
    meaning:
      'InterVar가 규칙에 따라 근거 코드를 자동으로 붙인 것이며 최종 분류가 아닙니다. 병원성 판정이 없다는 것이 양성을 뜻하지 않습니다.',
  },
  TSV_FAILED: {
    severity: 'info',
    resolution: null,
    title: '표 형식 변환에 실패했습니다',
    meaning: '보기 편한 TSV를 만들지 못했습니다. 주석이 붙은 VCF는 그대로 있습니다.',
  },

  // --- 99_finalization -------------------------------------------------
  METHODS_DOCUMENT_INCOMPLETE: {
    severity: 'attention',
    resolution: null,
    title: '재현성 기록(methods.md)이 완전하게 작성되지 않았습니다',
    meaning:
      '어떤 도구와 설정으로 분석했는지 사람이 읽을 수 있게 정리한 문서입니다. 분석 결과와 산출물은 정상이며, 같은 정보를 provenance.json에서 확인할 수 있습니다.',
  },
  OPTIONAL_STEPS_FAILED: {
    severity: 'attention',
    resolution: null,
    title: '선택 단계 일부가 완료되지 않았습니다',
    meaning:
      '핵심 분석(정렬·변이 검출)은 모두 끝났고 결과 파일은 정상입니다. 부가 단계의 산출물만 없습니다.',
  },
  OPTIONAL_CMD_FAILED: {
    severity: 'info',
    resolution: null,
    title: '부가 명령 하나가 정상 종료되지 않았습니다',
    meaning: '핵심 산출물에는 영향이 없습니다.',
  },
}

/**
 * 알 수 없는 code의 기본값.
 *
 * attention으로 둔다. 모르는 사건을 "참고"로 낮추면 실제 문제가 조용히
 * 묻힌다. 반대 방향의 실수(참고 사항이 확인 필요로 보이는 것)가 훨씬 낫다.
 */
const UNKNOWN: DiagnosticDefinition = {
  severity: 'attention',
  resolution: null,
  title: '',
  meaning: '',
}

/** 사용자에게 보이는 한 가지 구분. 위 두 축을 여기서 한 번만 합친다. */
export type DiagnosticKind = 'repaired' | 'attention' | 'note' | 'failure'

export interface DiagnosticView extends DiagnosticDefinition {
  kind: DiagnosticKind
  /** "자동 복구" · "확인 필요" · "참고" · "실패". 색 없이도 읽히는 유일한 단서. */
  label: string
}

const KIND_LABEL: Record<DiagnosticKind, string> = {
  repaired: '자동 복구',
  attention: '확인 필요',
  note: '참고',
  failure: '실패',
}

/**
 * code -> 표시 어휘.
 *
 * registry에 없는 code도 화면을 세우지 않는다. title이 비어 있으면 호출부가
 * backend의 원문 message를 제목 자리에 쓴다 — 의미를 지어내지 않고, 최소한
 * 서버가 말한 것은 보여준다.
 */
export function describeDiagnostic(code: string): DiagnosticView {
  const definition = DIAGNOSTICS[code] ?? UNKNOWN
  const kind: DiagnosticKind =
    definition.resolution === 'repaired'
      ? 'repaired'
      : definition.severity === 'attention'
        ? 'attention'
        : 'note'
  return { ...definition, kind, label: KIND_LABEL[kind] }
}

/** 실패는 registry를 거치지 않는다. code와 무관하게 항상 실패다. */
export function describeFailure(): DiagnosticView {
  return {
    severity: 'attention',
    resolution: null,
    title: '',
    meaning: '',
    kind: 'failure',
    label: KIND_LABEL.failure,
  }
}
