/**
 * 바이트 수를 사람이 읽는 크기로.
 *
 * WES FASTQ는 보통 GB 단위라 1024 기준 이진 접두어를 쓴다. 파일 탐색기가
 * 보여주는 값과 자릿수를 맞추기 위해서다. 정확한 바이트 수가 필요한 곳은
 * 없으므로 유효숫자 3자리 정도로 줄인다.
 */
const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${Math.round(bytes)} B`

  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${UNITS[unit]}`
}
