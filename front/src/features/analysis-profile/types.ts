/**
 * analysis-profile/types.ts
 * ============================================================================
 * 프론트엔드 확장성의 핵심 계약(contract).
 *
 * 지금은 "Illumina WES germline 유방암" 하나뿐이지만,
 * 나중에 PacBio / somatic / 다른 암 패널이 추가될 때
 * 이 타입을 만족하는 객체만 추가하면 UI가 자동으로 렌더링된다.
 * 화면 컴포넌트는 절대 수정하지 않는다.
 * ============================================================================
 */

// ── 1) 축(axis) 정의 ────────────────────────────────────────────────────────
// 새로운 값이 생기면 여기에만 추가한다.

/** 변이 종류 — germline(생식세포) vs somatic(체세포, tumor-normal 필요) */
export type VariantClass = 'germline' | 'somatic';

/** 시퀀싱 플랫폼 — short-read / long-read 구분의 근거 */
export type Platform = 'illumina' | 'pacbio' | 'ont';

/** 시퀀싱 범위 */
export type Assay = 'wes' | 'wgs' | 'panel';

/** 참조 게놈 빌드 */
export type Assembly = 'GRCh37' | 'GRCh38';

/** 프로파일 공개 상태 — UI에서 배지로 표시되고 'coming-soon'은 선택 불가 */
export type ProfileStatus = 'available' | 'beta' | 'coming-soon';

// ── 2) 옵션 필드 스키마 ─────────────────────────────────────────────────────
// ResFinder의 "? 말머리 툴팁 + 셀렉트박스" 를 데이터로 표현한 것.

export type OptionFieldType =
  | 'select' // 드롭다운
  | 'number' // 숫자 입력 (min/max/step)
  | 'slider' // 슬라이더 (스케일바) — 임계값 조정에 사용
  | 'boolean' // 체크박스 / 스위치
  | 'text'; // 자유 입력

export interface OptionChoice {
  value: string;
  label: string;
  /** 선택지 옆에 붙는 짧은 설명 — "권장", "실험적" 등 */
  note?: string;
  /** 리소스가 아직 준비되지 않은 선택지는 목록에 표시하되 선택하지 못하게 한다. */
  disabled?: boolean;
}

export interface OptionField {
  /** 백엔드로 전송될 key. run_config.json 의 필드명과 일치시킨다. */
  key: string;

  /** 화면에 보이는 라벨 */
  label: string;

  /** ? 버튼을 눌렀을 때 나오는 툴팁 본문 (말머리 설명) */
  help: string;

  type: OptionFieldType;

  /** 기본값 — 초보 사용자는 그대로 두고 실행만 누르면 되게 한다 */
  default: string | number | boolean;

  /** type: 'select' 일 때만 사용 */
  choices?: OptionChoice[];

  /** type: 'number' | 'slider' 일 때만 사용 */
  min?: number;
  max?: number;
  step?: number;
  /** 슬라이더 눈금에 붙는 단위 — "x", "bp", "%" */
  unit?: string;

  /**
   * 고급 옵션 여부.
   * true 면 기본적으로 접혀 있는 Accordion 안으로 들어간다.
   */
  advanced?: boolean;

  /**
   * 조건부 표시.
   * 예) somatic 프로파일에서 'tumor_purity' 는
   *     'caller' 가 'mutect2' 일 때만 보이게.
   */
  dependsOn?: {
    key: string;
    equals: string | number | boolean;
  };
}

// ── 3) 입력 파일 사양 ───────────────────────────────────────────────────────

export type InputMode =
  | 'paired-fastq' // R1/R2 한 쌍 (Illumina)
  | 'single-fastq' // 단일 FASTQ (PacBio HiFi, ONT)
  | 'paired-fastq-tn' // tumor/normal 각각 R1/R2 (somatic)
  | 'bam' // 정렬 완료 BAM부터 시작
  | 'vcf'; // 변이 호출 완료 VCF부터 시작 (주석만 수행)

export interface InputSpec {
  mode: InputMode;

  /** 허용 확장자 — react-dropzone accept 에 그대로 전달 */
  accept: string[];

  /** 단일 파일 최대 크기 (GB). 초과 시 업로드 전에 차단 */
  maxFileSizeGb: number;

  /**
   * 업로드 슬롯 정의.
   * paired-fastq 면 [R1, R2], paired-fastq-tn 이면 4개 슬롯이 된다.
   * UI는 이 배열 길이만큼 드롭존을 그린다.
   */
  slots: {
    id: string; // "tumor_r1"
    label: string; // "종양 시료 R1"
    required: boolean;
    /** 파일명 자동 매칭 패턴 — 정규식 문자열 */
    matchPattern?: string;
  }[];
}

// ── 4) 프로파일 본체 ────────────────────────────────────────────────────────

export interface AnalysisProfile {
  /** 고유 ID — 백엔드 전송값. kebab-case 권장 */
  id: string;

  /** 선택 목록에 뜨는 이름 */
  label: string;

  /** 카드 하단 한 줄 설명 */
  description: string;

  // 필터링 축 3개 — 계층형 선택 UI가 이 값으로 목록을 좁힌다
  variantClass: VariantClass;
  platform: Platform;
  assay: Assay;

  /** 패널 ID — assay가 'panel'이거나 유전자 서브셋을 쓸 때 */
  panelId?: string;

  /** 분석 대상 유전자 목록 — 사이드바에 배지로 표시 */
  targetGenes?: string[];

  status: ProfileStatus;

  input: InputSpec;

  /** 이 프로파일에서 노출할 옵션들 */
  options: OptionField[];

  /**
   * 결과 화면에서 렌더링할 뷰 컴포넌트 ID 목록.
   * results/registry.ts 의 키와 매칭된다.
   * germline 이면 ACMG 분류 뷰, somatic 이면 TMB 뷰 식으로 달라진다.
   */
  resultViews: string[];

  /** 백엔드 파이프라인 연결 정보 */
  pipeline: {
    /** main.sh 등 실행할 스크립트 식별자 */
    scriptId: string;
    /** run_config.json 의 resource_bundle.bundle_id */
    bundleId: string;
    assembly: Assembly;
  };

  /** 예상 소요 시간 (분) — 진행 화면에서 ETA 계산에 사용 */
  estimatedMinutes?: number;
}

// ── 5) 사용자가 실제로 제출하는 요청 형태 ──────────────────────────────────

export interface SubmitRequest {
  profileId: string;
  /** WES capture-kit registry key. 백엔드는 이 값을 run_config.capture_kit.id로 기록한다. */
  captureKitId?: string;
  /** 슬롯 ID → 업로드 완료된 파일 참조(서버 경로 또는 업로드 세션 ID) */
  files: Record<string, string>;
  /** OptionField.key → 사용자가 선택한 값 */
  options: Record<string, string | number | boolean>;
  /** 사용자가 붙인 실행 이름. 비우면 서버가 자동 생성 */
  runLabel?: string;
}
