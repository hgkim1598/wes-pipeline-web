/*
  용어 도움말 registry.

  ── 범위 ────────────────────────────────────────────────────────────────

  **화면에 실제로 등장하는 용어만** 담는다. 생물정보학 사전을 만드는 것이
  아니다. 지금은 실패 카드와 준비 안내 페이지에 나오는 것뿐이고, 새 화면이
  새 용어를 쓰면 그때 추가한다.

  ── 내용의 근거 ─────────────────────────────────────────────────────────

  설명은 **이 파이프라인에서 그 도구가 실제로 하는 일**을 기준으로 쓴다.
  일반적인 도구 소개를 옮겨 적지 않는다 — 사용자가 알고 싶은 것은
  "이게 없으면 내 분석에서 무엇이 안 되는가"이기 때문이다.

  근거:
    script/main.sh                 validate_tools()의 필수 목록과 각 step의 실제 호출
    config/knowledge/wes_steps.json 단계별 tools
    docs/MAIN_SH_COMPLETE_GUIDE.md 6.7 실행 전 준비물

  근거가 불충분한 설명은 넣지 않는다. 모르는 용어는 등록하지 않는 편이
  틀린 설명을 다는 것보다 낫다.

  ── 자동 링크를 하지 않는다 ─────────────────────────────────────────────

  backend가 준 자유 문자열에서 단어를 찾아 도움말을 붙이지 않는다.
  화면이 **구조화된 값으로 직접 렌더링하는 자리에만** 호출부가 명시적으로
  붙인다. 그래야 어디에 도움말이 붙는지 코드에서 보인다.
*/

export interface GlossaryTerm {
  /** 조회 키. 화면 표기와 다를 수 있다(대소문자·한국어). */
  id: string
  /** 도움말 제목. 기본 표기다. */
  label: string
  /** 한두 문장. popover에 들어갈 길이를 넘지 않는다. */
  description: string
  /**
   * 더 긴 설명이 있는 앱 내부 경로. 없으면 popover가 전부다.
   * 저장소 문서 경로를 여기 넣지 않는다 — 사용자는 저장소를 열지 않는다.
   */
  helpPath?: string
}

const TERMS: Record<string, GlossaryTerm> = {
  PATH: {
    id: 'PATH',
    label: 'PATH',
    description:
      '운영체제가 명령어를 찾는 디렉터리 목록입니다. 프로그램이 설치돼 있어도 PATH에 등록돼 있지 않으면 파이프라인이 찾지 못합니다.',
    helpPath: '/help/setup#tools',
  },
  bwa: {
    id: 'bwa',
    label: 'BWA',
    description:
      '읽어들인 짧은 DNA 조각(read)이 참조 유전체의 어느 위치에서 왔는지 찾아 붙이는 정렬 도구입니다. 이후 모든 분석이 이 위치 정보 위에서 이루어집니다.',
  },
  samtools: {
    id: 'samtools',
    label: 'SAMtools',
    description:
      '정렬 결과(BAM)를 정렬·색인·검사하는 도구입니다. 이 파이프라인은 정렬·BAM 정리·검증 단계에서 사용합니다.',
  },
  gatk: {
    id: 'gatk',
    label: 'GATK',
    description:
      '중복 read 표시, 염기 품질 보정, 변이 검출에 쓰이는 도구 모음입니다. 이 파이프라인의 BAM 정리·보정과 변이 검출 단계가 이것을 사용합니다.',
  },
  bcftools: {
    id: 'bcftools',
    label: 'bcftools',
    description:
      '변이 파일(VCF)을 읽고 거르고 통계를 내는 도구입니다. 이 파이프라인은 변이 검출 검증과 선택 단계인 필터링·주석에서 사용합니다.',
  },
  mosdepth: {
    id: 'mosdepth',
    label: 'mosdepth',
    description:
      '분석 대상 영역이 read로 얼마나 덮였는지(커버리지) 계산하는 도구입니다. 결과를 어디까지 신뢰할 수 있는지 판단하는 근거가 됩니다.',
  },
  fastqc: {
    id: 'fastqc',
    label: 'FastQC',
    description:
      '장비에서 나온 원본 read의 품질을 측정하는 도구입니다. 염기 품질 점수와 어댑터 잔존량처럼 이후 결과를 좌우하는 특성을 미리 확인합니다.',
  },
  tabix: {
    id: 'tabix',
    label: 'tabix',
    description:
      '압축된 유전체 파일에 색인을 만들어 특정 위치를 빠르게 찾을 수 있게 하는 도구입니다. htslib에 포함돼 있습니다.',
  },
  bgzip: {
    id: 'bgzip',
    label: 'bgzip',
    description:
      '유전체 파일을 부분적으로 읽을 수 있는 형태로 압축하는 도구입니다. tabix와 함께 htslib에 포함돼 있으며, 설치가 온전한지 확인하는 용도로 필수 목록에 있습니다.',
  },
  BAM: {
    id: 'BAM',
    label: 'BAM',
    description:
      '읽어들인 DNA 조각이 참조 유전체의 어느 위치에 정렬됐는지 기록한 파일입니다. 변이 검출은 이 파일을 근거로 이루어집니다.',
  },
  VCF: {
    id: 'VCF',
    label: 'VCF',
    description:
      '참조 유전체와 다른 지점(변이)을 모아 기록한 파일입니다. 이 파이프라인의 핵심 결과물입니다.',
  },
  'reference-genome': {
    id: 'reference-genome',
    label: '참조 유전체',
    description:
      '비교 기준이 되는 사람 유전체 서열입니다. 내 데이터의 어느 지점이 다른지는 항상 이 기준에 대해 말합니다. 이 서버는 GRCh38을 사용합니다.',
    helpPath: '/help/setup#resources',
  },
  precheck: {
    id: 'precheck',
    label: '사전 점검',
    description:
      '분석을 시작하기 전에 입력 파일·참조 데이터·필요한 프로그램이 갖춰졌는지만 확인하는 실행입니다. 분석 산출물(BAM·VCF)은 만들지 않습니다.',
    helpPath: '/help/setup#check',
  },
}

/** 등록된 용어. 없으면 undefined — 호출부가 그냥 평범한 텍스트로 렌더링한다. */
export function glossaryTerm(id: string): GlossaryTerm | undefined {
  return TERMS[id]
}

/** 등록 여부만 필요할 때. */
export function hasGlossaryTerm(id: string): boolean {
  return id in TERMS
}
