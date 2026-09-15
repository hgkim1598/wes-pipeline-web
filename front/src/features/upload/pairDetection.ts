/**
 * upload/pairDetection.ts
 * ============================================================================
 * 여러 파일을 한 번에 업로드했을 때, 파일명을 기준으로
 * "샘플별 세트"로 자동 그룹핑하는 로직.
 *
 * 지원 패턴 (paired-fastq)
 *   sample_R1_001.fastq.gz  <->  sample_R2_001.fastq.gz
 *   sample_R1.fastq.gz      <->  sample_R2.fastq.gz
 *   sample_1.fastq.gz       <->  sample_2.fastq.gz
 *
 * 짝이 안 맞거나(한쪽만 있음), 형식이 안 맞거나, 파일명에서
 * R1/R2를 구분 못하는 파일은 problemFiles 로 분리된다.
 * ============================================================================
 */

import type { InputSpec, InputMode } from '../analysis-profile/types'

// ── R1/R2 판별 ──────────────────────────────────────────────────────────────
const R1_PATTERNS = [/_R1_\d+\./i, /_R1\./i, /_1\.(fastq|fq)/i]
const R2_PATTERNS = [/_R2_\d+\./i, /_R2\./i, /_2\.(fastq|fq)/i]

export type ReadSide = 'R1' | 'R2' | 'unknown'

export function detectReadSide(filename: string): ReadSide {
  if (R1_PATTERNS.some((re) => re.test(filename))) return 'R1'
  if (R2_PATTERNS.some((re) => re.test(filename))) return 'R2'
  return 'unknown'
}

// ── tumor / normal 판별 (paired-fastq-tn 용) ─────────────────────────────────
export type TissueSide = 'tumor' | 'normal' | 'unknown'

export function detectTissue(filename: string): TissueSide {
  const lower = filename.toLowerCase()
  if (/(^|[_\-.])(tumou?r|tum|_t_|-t-)/.test(lower)) return 'tumor'
  if (/(^|[_\-.])(normal|norm|blood|germ|_n_|-n-)/.test(lower)) return 'normal'
  return 'unknown'
}

// ── Sample ID 추출 ──────────────────────────────────────────────────────────
export function extractSampleId(filename: string): string {
  let id = filename
  id = id.replace(/\.gz$/i, '')
  id = id.replace(/\.(fastq|fq)$/i, '')
  id = id.replace(/_R[12]_\d+$/i, '')
  id = id.replace(/_R[12]$/i, '')
  id = id.replace(/_[12]$/i, '')
  id = id.replace(/_L\d{3}$/i, '')
  return id || filename
}

/** tumor/normal 표기까지 제거해 tumor·normal 파일을 같은 샘플로 묶기 위한 ID */
export function extractBaseSampleId(filename: string): string {
  let id = extractSampleId(filename)
  id = id.replace(/[_\-.](tumou?r|tum|normal|norm|blood|germ|t|n)$/i, '')
  id = id.replace(/^(tumou?r|tum|normal|norm|blood|germ|t|n)[_\-.]/i, '')
  return id
}

// ── 확장자 / 용량 검증 ────────────────────────────────────────────────────────
export function isAcceptedExtension(filename: string, accept: string[]): boolean {
  const lower = filename.toLowerCase()
  return accept.some((ext) => lower.endsWith(ext.toLowerCase()))
}

// ── 배치(다중 샘플) 그룹핑 ───────────────────────────────────────────────────

export interface ProblemFile {
  file: File
  reason: string
}

export interface SampleGroup {
  /** 자동 감지된 샘플 ID */
  sampleId: string
  /** slotId -> File (예: r1, r2 / tumor_r1, normal_r2) */
  slots: Record<string, File>
}

export interface BatchAssignmentResult {
  /** 필수 파일이 모두 짝지어진, 분석 가능한 샘플 목록 */
  groups: SampleGroup[]
  /** 형식 오류, 짝 없음, 중복 등으로 분석에 쓸 수 없는 파일 */
  problemFiles: ProblemFile[]
}

export function buildBatchAssignment(files: File[], spec: InputSpec): BatchAssignmentResult {
  const problemFiles: ProblemFile[] = []
  const valid: File[] = []

  // 1) 확장자 / 용량 검증
  for (const f of files) {
    if (!isAcceptedExtension(f.name, spec.accept)) {
      problemFiles.push({
        file: f,
        reason: `지원하지 않는 형식입니다 (허용: ${spec.accept.join(', ')})`,
      })
      continue
    }
    const sizeGb = f.size / 1e9
    if (sizeGb > spec.maxFileSizeGb) {
      problemFiles.push({
        file: f,
        reason: `${sizeGb.toFixed(1)}GB — 최대 ${spec.maxFileSizeGb}GB를 초과합니다`,
      })
      continue
    }
    valid.push(f)
  }

  // 2) sampleId -> { slotId: File } 로 임시 버킷팅
  const buckets = new Map<string, Record<string, File>>()

  function place(sampleId: string, slotId: string, file: File) {
    const bucket = buckets.get(sampleId) ?? {}
    if (bucket[slotId]) {
      problemFiles.push({
        file,
        reason: `${sampleId} 샘플에 ${slotId.toUpperCase()} 파일이 이미 있습니다 (중복)`,
      })
      return
    }
    bucket[slotId] = file
    buckets.set(sampleId, bucket)
  }

  switch (spec.mode) {
    case 'single-fastq':
    case 'bam':
    case 'vcf': {
      const slotId = spec.slots[0].id
      for (const f of valid) place(extractSampleId(f.name), slotId, f)
      break
    }
    case 'paired-fastq': {
      for (const f of valid) {
        const side = detectReadSide(f.name)
        if (side === 'unknown') {
          problemFiles.push({ file: f, reason: 'R1/R2를 파일명에서 구분하지 못했습니다' })
          continue
        }
        place(extractSampleId(f.name), side.toLowerCase(), f)
      }
      break
    }
    case 'paired-fastq-tn': {
      for (const f of valid) {
        const side = detectReadSide(f.name)
        const tissue = detectTissue(f.name)
        if (side === 'unknown' || tissue === 'unknown') {
          problemFiles.push({
            file: f,
            reason: '종양/정상 또는 R1/R2 구분을 파일명에서 찾지 못했습니다',
          })
          continue
        }
        place(extractBaseSampleId(f.name), `${tissue}_${side.toLowerCase()}`, f)
      }
      break
    }
  }

  // 3) 필수 슬롯이 다 채워진 것만 groups 로, 아니면 problemFiles 로
  const groups: SampleGroup[] = []
  for (const [sampleId, slots] of buckets) {
    const missing = spec.slots.filter((s) => s.required && !slots[s.id])

    if (missing.length > 0) {
      const missingLabels = missing.map((s) => s.label).join(', ')
      for (const file of Object.values(slots)) {
        problemFiles.push({
          file,
          reason: `${sampleId}: 짝이 되는 파일(${missingLabels})이 없습니다`,
        })
      }
      continue
    }

    groups.push({ sampleId, slots })
  }

  groups.sort((a, b) => a.sampleId.localeCompare(b.sampleId))

  return { groups, problemFiles }
}

// ── 입력 모드별 파일 형식 안내 (말머리 툴팁용) ───────────────────────────────
export const FORMAT_HELP: Record<InputMode, { title: string; body: string[] }> = {
  'paired-fastq': {
    title: 'Paired-end FASTQ (Illumina)',
    body: [
      '샘플 1개당 R1, R2 두 파일이 필요합니다.',
      '지원 파일명 패턴:',
      '  SAMPLE_R1.fastq.gz  /  SAMPLE_R2.fastq.gz',
      '  SAMPLE_R1_001.fastq.gz  /  SAMPLE_R2_001.fastq.gz',
      '  SAMPLE_1.fastq.gz  /  SAMPLE_2.fastq.gz',
      '같은 SAMPLE 이름의 R1·R2가 자동으로 한 세트로 묶입니다.',
      '여러 샘플을 한 번에 올려도 이름 기준으로 자동 구분됩니다.',
    ],
  },
  'single-fastq': {
    title: '단일 FASTQ / BAM (PacBio, ONT)',
    body: [
      '샘플 1개당 파일 1개만 필요합니다.',
      '파일명(확장자 제외)이 그대로 Sample ID로 사용됩니다.',
      '예: HG002.fastq.gz -> Sample ID: HG002',
    ],
  },
  'paired-fastq-tn': {
    title: 'Tumor-Normal Paired FASTQ',
    body: [
      '샘플 1개당 종양(tumor) R1/R2, 정상(normal) R1/R2 총 4개 파일이 필요합니다.',
      '파일명에 tumor 또는 normal(약자 t, n)이 포함되어야 합니다.',
      '예: SAMPLE_tumor_R1.fastq.gz, SAMPLE_normal_R2.fastq.gz',
    ],
  },
  bam: {
    title: 'BAM 파일',
    body: ['정렬이 완료된 BAM 파일 1개를 업로드합니다.', '파일명이 Sample ID로 사용됩니다.'],
  },
  vcf: {
    title: 'VCF 파일',
    body: ['변이 호출이 완료된 VCF 파일 1개를 업로드합니다 (주석 단계부터 시작).'],
  },
}

// ── 표시용 헬퍼 ─────────────────────────────────────────────────────────────
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 2 : 1)} ${units[i]}`
}
