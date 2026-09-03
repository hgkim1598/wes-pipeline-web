/*
  분석 profile · capture kit 카탈로그.

  두 값 모두 backend에 목록 API가 없다. 그래서 화면이 고를 수 있는 값을
  여기 한 곳에 모은다. 나중에 GET /api/profiles · GET /api/capture-kits가
  생기면 이 파일만 교체하면 되도록, 다른 코드는 이 모듈이 주는 배열만 읽는다.

  중요: 여기 있는 값은 지어낸 것이 아니라 저장소의 실제 근거에서 가져왔다.
*/

/*
  Profile

  근거: git history의 front/src/features/analysis-profile/registry.ts에
  네 개의 profile ID가 있었고, 그중 현재 WES pipeline이 실제로 수행하는 것과
  일치하는 것은 germline-illumina-wes-full 하나다. 나머지 셋은
  유방암 유전자 소인 분석 · PacBio WGS · Somatic Tumor-Normal이고,
  script/main.sh에는 그런 실행 경로가 없다.

  breast profile을 쓰지 않은 이유는 하나 더 있다. backend는 profileId를
  job row에 기록만 하고 pipeline 동작을 바꾸지 않는다(backend/app/api/jobs.py).
  그런 상태에서 특정 유전자 패널을 뜻하는 ID를 보내면, 화면은 실제로
  일어나지 않는 분석을 약속하게 된다(CLAUDE.md 10장).

  설명 문구는 CLAUDE.md 10장이 허용한 범위 — 일반적인 Illumina WES Germline
  변이 분석 — 를 넘지 않는다.
*/
export interface AnalysisProfile {
  id: string
  label: string
  description: string
  /** 입력 형식처럼 사용자가 제출 전에 확인해야 하는 짧은 사실들. */
  facts: string[]
}

export const ANALYSIS_PROFILES: AnalysisProfile[] = [
  {
    id: 'germline-illumina-wes-full',
    label: 'Illumina WES Germline 변이 분석',
    description:
      'Exome 전체에서 germline SNV/Indel을 호출합니다. 분석 범위는 선택한 capture kit의 target 영역을 따릅니다.',
    facts: ['paired-end FASTQ 1쌍', '샘플 1개', 'GRCh38'],
  },
]

/**
 * 현재 선택 가능한 profile은 하나뿐이라 기본값을 둔다.
 * 목록이 늘어나면 화면이 선택 UI를 붙이고 이 값은 초기값으로 남는다.
 */
export const DEFAULT_PROFILE_ID = ANALYSIS_PROFILES[0].id

/*
  Capture kit

  근거: config/capture_kits.grch38.json (backend config.CAPTURE_KIT_REGISTRY).
  backend는 status가 'confirmed'인 kit만 받는다
  (services/config_builder.py resolve_capture_kit_id). 그래서 registry에
  있더라도 unconfirmed인 agilent_sureselect_human_all_exon_v8은 여기 없다 —
  목록에 넣으면 사용자가 고를 수 있는데 제출은 400으로 거절된다.

  label은 registry의 manufacturer / capture_kit_name / capture_kit_version을
  사람이 읽는 순서로 이어붙인 것이고, 값을 새로 지어내지 않았다.
*/
export interface CaptureKit {
  id: string
  label: string
  manufacturer: string
}

export const CAPTURE_KITS: CaptureKit[] = [
  {
    id: 'idt_xgen_exome_hyb_panel_v2',
    label: 'IDT xGen Exome Hyb Panel v2',
    manufacturer: 'Integrated DNA Technologies',
  },
  {
    id: 'twist_exome_2_0',
    label: 'Twist Exome 2.0',
    manufacturer: 'Twist Bioscience',
  },
  {
    id: 'roche_kapa_hyperexome_v2',
    label: 'Roche KAPA HyperExome V2',
    manufacturer: 'Roche',
  },
]

export function findCaptureKit(id: string): CaptureKit | undefined {
  return CAPTURE_KITS.find((kit) => kit.id === id)
}

/**
 * 참조 유전체.
 *
 * backend config.ASSEMBLY의 기본값이며 서버 bundle에 고정되어 있다. 사용자가
 * 고를 수 있는 값이 아니라서 선택지가 아니라 사실로만 보여준다. 요청에도
 * 넣지 않는다 — backend가 자기 설정과 다르면 400으로 거절하므로, 보내서
 * 얻는 것이 없다.
 */
export const SERVER_ASSEMBLY = 'GRCh38'
