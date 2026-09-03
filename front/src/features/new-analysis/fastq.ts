/*
  FASTQ 입력 규칙.

  backend가 이미 같은 검사를 하지만(api/uploads.py의 _accepted_extension,
  api/jobs.py의 _sanitize_sample_id), 6GB를 다 보낸 뒤 400을 받는 것과
  파일을 고르는 순간 알려주는 것은 사용자에게 전혀 다른 경험이다.
  그래서 같은 규칙을 여기서도 확인한다. 다르게 만들지 않는 것이 중요하다.
*/

/** backend config.ALLOWED_FASTQ_SUFFIXES 와 같은 목록이다. */
export const ALLOWED_FASTQ_SUFFIXES = ['.fastq.gz', '.fq.gz'] as const

/** 한 번의 제출이 받는 paired-end 슬롯. backend의 slotId와 같은 값이다. */
export type FastqSlotId = 'r1' | 'r2'

export const FASTQ_SLOTS: FastqSlotId[] = ['r1', 'r2']

export function hasAllowedFastqSuffix(filename: string): boolean {
  const lowered = filename.toLowerCase()
  return ALLOWED_FASTQ_SUFFIXES.some((suffix) => lowered.endsWith(suffix))
}

/**
 * 업로드를 시작해도 되는 파일인지.
 *
 * 돌려주는 것은 사용자 문구다. null이면 문제 없음. 압축되지 않은 FASTQ를
 * 따로 짚는 이유는 그것이 가장 흔한 실수이고, "확장자가 틀렸다"보다
 * "gzip으로 압축해야 한다"가 실제로 다음 행동을 알려주기 때문이다.
 */
export function validateFastqFile(file: File): string | null {
  const lowered = file.name.toLowerCase()

  if (!hasAllowedFastqSuffix(lowered)) {
    if (lowered.endsWith('.fastq') || lowered.endsWith('.fq')) {
      return '압축되지 않은 FASTQ는 사용할 수 없습니다. gzip으로 압축한 .fastq.gz 또는 .fq.gz 파일을 선택해 주세요.'
    }
    return `FASTQ 파일이 아닙니다. ${ALLOWED_FASTQ_SUFFIXES.join(' 또는 ')} 파일을 선택해 주세요.`
  }

  if (file.size <= 0) {
    return '파일이 비어 있습니다. 전송할 내용이 없습니다.'
  }

  return null
}

/*
  Sample ID

  backend는 [A-Za-z0-9._-] 밖의 문자를 _로 바꾸고, 그러고도 규칙에 맞지
  않으면 400으로 거절한다(api/jobs.py). 화면에서는 조용히 바꾸지 않고
  규칙을 알려준 뒤 사용자가 직접 고치게 한다 — 사용자가 입력한 이름과
  samplesheet에 들어가는 이름이 달라지면 나중에 결과를 대조할 수 없다.
*/
const SAMPLE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

export function validateSampleId(sampleId: string): string | null {
  const value = sampleId.trim()
  if (!value) return '샘플 이름을 입력해 주세요.'
  if (!SAMPLE_ID_RE.test(value)) {
    return '샘플 이름은 영문자 또는 숫자로 시작하고, 영문자·숫자·마침표·밑줄·하이픈만 쓸 수 있습니다.'
  }
  return null
}

/**
 * R1 파일 이름에서 샘플 이름을 추측한다.
 *
 * 어디까지나 제안이다. 입력란을 채워줄 뿐 사용자가 언제든 고칠 수 있고,
 * 추측이 규칙에 맞지 않으면 아무것도 채우지 않는다. FASTQ 파일 이름 관행
 * (SAMPLE_R1.fastq.gz, SAMPLE_1.fq.gz, SAMPLE_S1_L001_R1_001.fastq.gz)에서
 * 흔한 꼬리표만 떼어낸다.
 */
export function suggestSampleId(filename: string): string | null {
  let base = filename
  for (const suffix of ALLOWED_FASTQ_SUFFIXES) {
    if (base.toLowerCase().endsWith(suffix)) {
      base = base.slice(0, -suffix.length)
      break
    }
  }

  const trimmed = base
    .replace(/_001$/i, '')
    .replace(/[._-]R?[12]$/i, '')
    .replace(/_L\d{3}$/i, '')
    .replace(/_S\d+$/i, '')
    .replace(/[._-]+$/, '')

  return SAMPLE_ID_RE.test(trimmed) ? trimmed : null
}
