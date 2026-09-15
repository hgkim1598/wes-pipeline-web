/**
 * analysis-profile/registry.ts
 * ============================================================================
 * 프로파일 레지스트리.
 *
 * [중요] 새 분석을 추가할 때 수정하는 파일은 여기 하나뿐이다.
 *        화면 컴포넌트(ProfileSelector, DynamicOptionForm, UploadZone)는
 *        절대 건드리지 않는다.
 *
 * [운영 전환] 초기에는 이 파일의 static 배열을 쓰고,
 *            백엔드가 GET /api/profiles 를 제공하면
 *            fetchProfiles() 만 교체하면 된다. 타입은 동일하다.
 * ============================================================================
 */

import type { AnalysisProfile, OptionField } from './types';

// ── 공통 옵션 조각 ──────────────────────────────────────────────────────────
// 여러 프로파일이 공유하는 옵션은 여기서 만들어 재사용한다.

const OPT_MIN_BASE_QUALITY: OptionField = {
  key: 'min_base_quality',
  label: '최소 염기 품질 (Phred Q)',
  help:
    'Phred 품질 점수 기준입니다. Q20은 염기 판독 오류율 1%(정확도 99%)를 뜻합니다. ' +
    '이 값보다 낮은 염기는 트리밍 단계에서 제거됩니다. ' +
    '일반적인 Illumina WES에서는 Q20이 표준입니다.',
  type: 'slider',
  default: 20,
  min: 10,
  max: 35,
  step: 1,
  unit: 'Q',
};

const OPT_MIN_READ_LENGTH: OptionField = {
  key: 'min_read_length',
  label: '최소 read 길이',
  help:
    '트리밍 후 이 길이보다 짧아진 read는 버립니다. ' +
    '너무 짧은 read는 게놈 여러 곳에 모호하게 정렬되어 위양성 변이의 원인이 됩니다. ' +
    '원본 read가 125~150bp인 Illumina WES에서는 50bp가 적절합니다.',
  type: 'number',
  default: 50,
  min: 20,
  max: 150,
  step: 5,
  unit: 'bp',
};

const OPT_ASSEMBLY: OptionField = {
  key: 'assembly',
  label: '참조 게놈 빌드',
  help:
    '이 파이프라인은 GRCh38 좌표계로 고정되어 있습니다. ' +
    '참조 FASTA, capture BED, known-sites 및 annotation 리소스가 모두 GRCh38이어야 합니다.',
  type: 'select',
  default: 'GRCh38',
  choices: [{ value: 'GRCh38', label: 'GRCh38 / hg38', note: '고정' }],
};

const OPT_CAPTURE_KIT: OptionField = {
  key: 'capture_kit_id',
  label: 'Exome capture kit',
  help:
    'FASTQ 라이브러리를 제작할 때 실제로 사용한 capture kit과 동일한 항목을 선택해야 합니다. ' +
    '선택값은 백엔드의 capture_kit.id로 전달되며, 해당 GRCh38 target BED와 메타데이터를 불러옵니다.',
  type: 'select',
  default: 'idt_xgen_exome_hyb_panel_v2',
  choices: [
    {
      value: 'agilent_sureselect_human_all_exon_v8',
      label: 'Agilent SureSelect Human All Exon V8',
      note: 'BED 확인 필요',
      disabled: true,
    },
    {
      value: 'idt_xgen_exome_hyb_panel_v2',
      label: 'IDT xGen Exome Hyb Panel v2',
      note: '기본값',
    },
    {
      value: 'twist_exome_2_0',
      label: 'Twist Exome 2.0',
      note: 'GRCh38',
    },
    {
      value: 'roche_kapa_hyperexome_v2',
      label: 'Roche KAPA HyperExome V2',
      note: 'GRCh38',
    },
  ],
};

const OPT_MIN_DEPTH: OptionField = {
  key: 'min_depth',
  label: '변이 최소 depth',
  help:
    '해당 위치를 덮는 read 수가 이 값 미만이면 변이를 신뢰하지 않고 필터링합니다. ' +
    'depth가 낮으면 우연히 시퀀싱 오류가 반복된 것을 진짜 변이로 오인할 수 있습니다.',
  type: 'slider',
  default: 5,
  min: 1,
  max: 50,
  step: 1,
  unit: 'x',
  advanced: true,
};

const OPT_MIN_GQ: OptionField = {
  key: 'min_gq',
  label: '최소 Genotype Quality (GQ)',
  help:
    'GATK가 산출한 genotype 신뢰도입니다. GQ 20은 genotype이 틀릴 확률 1%를 의미합니다. ' +
    '값을 올리면 정확도는 올라가지만 실제 변이를 놓칠 수 있습니다.',
  type: 'slider',
  default: 10,
  min: 0,
  max: 60,
  step: 5,
  advanced: true,
};

const OPT_GNOMAD_MAF: OptionField = {
  key: 'gnomad_maf_cutoff',
  label: 'gnomAD 집단 빈도 상한 (MAF)',
  help:
    '일반 인구 집단에서 이 빈도보다 흔한 변이는 질환 원인일 가능성이 낮아 제외합니다. ' +
    '희귀 유전질환은 보통 1%(0.01), 더 엄격하게 보려면 0.1%(0.001)를 씁니다.',
  type: 'select',
  default: '0.01',
  choices: [
    { value: '0.05', label: '5%  (느슨함)' },
    { value: '0.01', label: '1%  (표준)', note: '권장' },
    { value: '0.001', label: '0.1% (엄격)' },
    { value: 'none', label: '필터 사용 안 함' },
  ],
  advanced: true,
};

// ── 유방암 소인 유전자 세트 ─────────────────────────────────────────────────
const BREAST_CANCER_GENES = ['BRCA1', 'BRCA2', 'PALB2', 'ATM', 'CHEK2', 'TP53', 'PTEN', 'CDH1'];

// ── 프로파일 정의 ───────────────────────────────────────────────────────────

export const PROFILES: AnalysisProfile[] = [
  // ────────────────────────────────────────────────────────────────────────
  // [1] 현재 구현 완료 — Illumina WES germline 유방암
  // ────────────────────────────────────────────────────────────────────────
  {
    id: 'germline-illumina-wes-breast',
    label: '유방암 소인 Germline 변이 분석',
    description:
      'Illumina WES 데이터에서 BRCA1/2 등 8개 유방암 소인 유전자의 ' +
      'germline SNV/Indel을 탐지하고 ACMG 기준으로 분류합니다.',
    variantClass: 'germline',
    platform: 'illumina',
    assay: 'wes',
    panelId: 'breast-cancer-8gene',
    targetGenes: BREAST_CANCER_GENES,
    status: 'available',

    input: {
      mode: 'paired-fastq',
      accept: ['.fastq.gz', '.fq.gz', '.fastq', '.fq'],
      maxFileSizeGb: 30,
      slots: [
        { id: 'r1', label: 'Read 1 (R1)', required: true, matchPattern: '_R1[_.]|_1\\.' },
        { id: 'r2', label: 'Read 2 (R2)', required: true, matchPattern: '_R2[_.]|_2\\.' },
      ],
    },

    options: [
      OPT_ASSEMBLY,
      OPT_CAPTURE_KIT,
      OPT_MIN_BASE_QUALITY,
      OPT_MIN_READ_LENGTH,
      {
        key: 'variant_caller',
        label: '변이 호출 도구',
        help:
          'GATK HaplotypeCaller는 Illumina germline 분석의 표준 도구로 ' +
          'local haplotype assembly 기반입니다. ' +
          'DeepVariant는 딥러닝 기반으로 일부 조건에서 Indel 정확도가 더 높습니다.',
        type: 'select',
        default: 'gatk-haplotypecaller',
        choices: [
          { value: 'gatk-haplotypecaller', label: 'GATK HaplotypeCaller', note: '표준' },
          { value: 'deepvariant', label: 'DeepVariant (WES 모델)', note: '준비 중' },
        ],
      },
      OPT_MIN_DEPTH,
      OPT_MIN_GQ,
      OPT_GNOMAD_MAF,
      {
        key: 'run_acmg',
        label: 'ACMG 자동 분류 수행',
        help:
          'InterVar를 사용해 ACMG/AMP 2015 가이드라인의 18개 기준을 자동 적용하여 ' +
          'Pathogenic / Likely Pathogenic / VUS / Likely Benign / Benign 5단계로 분류합니다. ' +
          '분석 시간이 20~40분 추가됩니다.',
        type: 'boolean',
        default: true,
      },
    ],

    resultViews: ['coverage-summary', 'variant-table', 'acmg-donut', 'gene-lollipop'],

    pipeline: {
      scriptId: 'main.sh',
      bundleId: 'grch38_wes_germline',
      assembly: 'GRCh38',
    },

    estimatedMinutes: 330,
  },

  // ────────────────────────────────────────────────────────────────────────
  // [2] 확장 예시 — 전체 exome germline (패널 제한 없음)
  //     유전자 서브셋만 다르므로 옵션은 거의 동일하다.
  // ────────────────────────────────────────────────────────────────────────
  {
    id: 'germline-illumina-wes-full',
    label: '전체 Exome Germline 변이 분석',
    description:
      '특정 패널로 제한하지 않고 exome 전체에서 germline 변이를 호출합니다. ' +
      '희귀질환 원인 변이 탐색 등에 사용합니다.',
    variantClass: 'germline',
    platform: 'illumina',
    assay: 'wes',
    status: 'beta',

    input: {
      mode: 'paired-fastq',
      accept: ['.fastq.gz', '.fq.gz'],
      maxFileSizeGb: 30,
      slots: [
        { id: 'r1', label: 'Read 1 (R1)', required: true, matchPattern: '_R1[_.]|_1\\.' },
        { id: 'r2', label: 'Read 2 (R2)', required: true, matchPattern: '_R2[_.]|_2\\.' },
      ],
    },

    options: [
      OPT_ASSEMBLY,
      OPT_CAPTURE_KIT,
      OPT_MIN_BASE_QUALITY,
      OPT_MIN_READ_LENGTH,
      OPT_MIN_DEPTH,
      OPT_MIN_GQ,
      OPT_GNOMAD_MAF,
    ],

    resultViews: ['coverage-summary', 'variant-table', 'acmg-donut'],

    pipeline: {
      scriptId: 'main.sh',
      bundleId: 'grch38_wes_germline',
      assembly: 'GRCh38',
    },

    estimatedMinutes: 340,
  },

  // ────────────────────────────────────────────────────────────────────────
  // [3] 확장 예시 — PacBio HiFi long-read germline
  //     플랫폼이 바뀌면 입력 모드(단일 FASTQ)와 도구 선택지가 달라진다.
  //     UI 코드 변경 없이 이 객체 추가만으로 동작한다.
  // ────────────────────────────────────────────────────────────────────────
  {
    id: 'germline-pacbio-wgs',
    label: 'PacBio HiFi Germline 변이 분석',
    description:
      'PacBio HiFi long-read 데이터에서 SNV/Indel 및 구조 변이(SV)를 탐지합니다. ' +
      'short-read로 접근하기 어려운 반복 서열 영역까지 커버합니다.',
    variantClass: 'germline',
    platform: 'pacbio',
    assay: 'wgs',
    status: 'coming-soon',

    input: {
      mode: 'single-fastq',
      accept: ['.fastq.gz', '.fq.gz', '.bam'],
      maxFileSizeGb: 100,
      slots: [{ id: 'reads', label: 'HiFi Reads', required: true }],
    },

    options: [
      OPT_ASSEMBLY,
      {
        key: 'aligner',
        label: '정렬 도구',
        help:
          'pbmm2는 PacBio 공식 정렬 도구로 minimap2를 HiFi에 맞게 감싼 것입니다. ' +
          'BWA는 short-read 전용이라 long-read에는 사용하지 않습니다.',
        type: 'select',
        default: 'pbmm2',
        choices: [
          { value: 'pbmm2', label: 'pbmm2 (PacBio 공식)', note: '권장' },
          { value: 'minimap2', label: 'minimap2 (-x map-hifi)' },
        ],
      },
      {
        key: 'variant_caller',
        label: '변이 호출 도구',
        help:
          'DeepVariant의 PACBIO 모델은 HiFi read의 오류 특성에 맞춰 학습되어 있습니다. ' +
          'GATK HaplotypeCaller는 Illumina 오류 모델 기반이라 HiFi에는 적합하지 않습니다.',
        type: 'select',
        default: 'deepvariant-pacbio',
        choices: [
          { value: 'deepvariant-pacbio', label: 'DeepVariant (PACBIO 모델)', note: '권장' },
          { value: 'clair3', label: 'Clair3' },
        ],
      },
      {
        key: 'call_sv',
        label: '구조 변이(SV) 호출',
        help:
          'pbsv를 사용해 50bp 이상의 삽입/결실/역위/전좌를 탐지합니다. ' +
          'long-read의 가장 큰 강점 영역이지만 분석 시간이 늘어납니다.',
        type: 'boolean',
        default: true,
      },
      OPT_MIN_DEPTH,
    ],

    resultViews: ['coverage-summary', 'variant-table', 'sv-table'],

    pipeline: {
      scriptId: 'main_longread.sh',
      bundleId: 'grch38_pacbio_hifi',
      assembly: 'GRCh38',
    },

    estimatedMinutes: 600,
  },

  // ────────────────────────────────────────────────────────────────────────
  // [4] 확장 예시 — Somatic (tumor-normal 쌍)
  //     입력 슬롯이 4개로 늘어나고 somatic 전용 옵션이 추가된다.
  //     dependsOn 을 이용한 조건부 옵션 표시 예시 포함.
  // ────────────────────────────────────────────────────────────────────────
  {
    id: 'somatic-illumina-panel-tn',
    label: '고형암 Somatic 변이 분석 (Tumor-Normal)',
    description:
      '종양 조직과 정상 조직을 쌍으로 비교하여 체세포 변이만 선별합니다. ' +
      'TMB 계산과 돌연변이 시그니처 분석을 포함합니다.',
    variantClass: 'somatic',
    platform: 'illumina',
    assay: 'panel',
    panelId: 'solid-tumor-500gene',
    status: 'coming-soon',

    input: {
      mode: 'paired-fastq-tn',
      accept: ['.fastq.gz', '.fq.gz'],
      maxFileSizeGb: 30,
      slots: [
        { id: 'tumor_r1', label: '종양 R1', required: true, matchPattern: '_R1[_.]|_1\\.' },
        { id: 'tumor_r2', label: '종양 R2', required: true, matchPattern: '_R2[_.]|_2\\.' },
        { id: 'normal_r1', label: '정상 R1', required: true, matchPattern: '_R1[_.]|_1\\.' },
        { id: 'normal_r2', label: '정상 R2', required: true, matchPattern: '_R2[_.]|_2\\.' },
      ],
    },

    options: [
      OPT_ASSEMBLY,
      OPT_MIN_BASE_QUALITY,
      {
        key: 'somatic_caller',
        label: 'Somatic 변이 호출 도구',
        help:
          'Mutect2는 GATK의 somatic 전용 caller로 tumor-normal 쌍 비교에 최적화되어 있습니다. ' +
          'Strelka2는 속도가 빠르고 Indel 정확도가 좋습니다.',
        type: 'select',
        default: 'mutect2',
        choices: [
          { value: 'mutect2', label: 'GATK Mutect2', note: '표준' },
          { value: 'strelka2', label: 'Strelka2' },
        ],
      },
      {
        key: 'min_vaf',
        label: '최소 VAF (변이 대립유전자 빈도)',
        help:
          '종양 순도와 클론 구조에 따라 somatic 변이의 VAF는 매우 낮을 수 있습니다. ' +
          '값을 낮추면 서브클론 변이까지 잡히지만 위양성도 함께 증가합니다. ' +
          'germline은 보통 50%/100% 근처에 몰리는 것과 대조적입니다.',
        type: 'slider',
        default: 0.05,
        min: 0.01,
        max: 0.5,
        step: 0.01,
        unit: '',
      },
      {
        key: 'tumor_purity',
        label: '종양 순도 추정치',
        help:
          '병리 판독으로 얻은 종양 세포 비율입니다. ' +
          'Mutect2의 contamination 보정에 사용됩니다. 모르면 기본값을 두세요.',
        type: 'slider',
        default: 0.6,
        min: 0.1,
        max: 1.0,
        step: 0.05,
        advanced: true,
        // 조건부 표시 — Mutect2를 선택했을 때만 노출
        dependsOn: { key: 'somatic_caller', equals: 'mutect2' },
      },
      {
        key: 'calc_tmb',
        label: 'TMB (종양 변이 부담) 계산',
        help:
          'Mb당 비동의 체세포 변이 수를 계산합니다. ' +
          '면역항암제 반응 예측 바이오마커로 사용됩니다.',
        type: 'boolean',
        default: true,
      },
      {
        key: 'mutational_signature',
        label: '돌연변이 시그니처 분석',
        help: 'COSMIC SBS 시그니처와 대조하여 변이 발생 원인(흡연, UV, MMR 결손 등)을 추정합니다.',
        type: 'boolean',
        default: false,
        advanced: true,
      },
    ],

    resultViews: ['coverage-summary', 'variant-table', 'tmb-card', 'signature-plot'],

    pipeline: {
      scriptId: 'main_somatic.sh',
      bundleId: 'grch38_solid_tumor_panel',
      assembly: 'GRCh38',
    },

    estimatedMinutes: 480,
  },
];

// ── 조회 헬퍼 ───────────────────────────────────────────────────────────────

export function getProfile(id: string): AnalysisProfile | undefined {
  return PROFILES.find((p) => p.id === id);
}

/** 계층형 선택 UI에서 사용 — 축 값으로 후보를 좁힌다 */
export function filterProfiles(filters: {
  variantClass?: string;
  platform?: string;
  assay?: string;
}): AnalysisProfile[] {
  return PROFILES.filter((p) => {
    if (filters.variantClass && p.variantClass !== filters.variantClass) return false;
    if (filters.platform && p.platform !== filters.platform) return false;
    if (filters.assay && p.assay !== filters.assay) return false;
    return true;
  });
}

/** 특정 축에서 실제로 선택 가능한 값만 추출 — 빈 결과가 나오는 조합을 막는다 */
export function availableValues(
  axis: 'variantClass' | 'platform' | 'assay',
  filters: { variantClass?: string; platform?: string; assay?: string } = {},
): string[] {
  const pool = filterProfiles(filters);
  return Array.from(new Set(pool.map((p) => p[axis])));
}

/**
 * 백엔드 API 전환용 훅.
 * 서버가 /api/profiles 를 제공하기 시작하면 이 함수 본문만 fetch 로 교체한다.
 * 반환 타입이 같으므로 호출부는 수정 불필요.
 */
export async function fetchProfiles(): Promise<AnalysisProfile[]> {
  // return (await fetch('/api/profiles')).json();
  return Promise.resolve(PROFILES);
}
