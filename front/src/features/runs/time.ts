/*
  실행 목록의 시각 표기.

  backend는 ISO-8601 문자열(고정 오프셋)을 준다. 여기서 하는 일은 두 가지뿐이다.

    1. 읽지 못하는 값이 화면을 무너뜨리지 않게 막는다.
    2. 좁은 열에서 읽히도록 줄인다.

  상대 시간("3분 전")은 만들지 않는다. 매초 다시 렌더링해야 하고, 무엇보다
  분석이 며칠 단위로 이어지는 이 제품에서 절대 시각이 더 쓸모 있다.
  포맷은 브라우저 locale에 맡긴다 — 자체 date 라이브러리를 두지 않는다.
*/

const TIME_ONLY = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
})

const SAME_YEAR = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
})

const OTHER_YEAR = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
})

/** 잘린 표기 옆에 항상 붙는 전체 값. title로 노출한다. */
const FULL = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'long',
  timeStyle: 'medium',
})

export interface FormattedTimestamp {
  /** 화면에 보이는 짧은 표기. */
  display: string
  /** <time datetime>에 그대로 넣을 원본 문자열. */
  machine: string
  /** 날짜와 시각이 모두 담긴 전체 표기. */
  full: string
}

/**
 * ISO 문자열 하나를 표기 3종으로 바꾼다.
 *
 * 값이 없거나 Date가 읽지 못하면 null을 돌려준다. 호출부는 그때
 * "—"처럼 값이 없다는 사실을 그대로 보여준다. 잘못된 timestamp 하나가
 * 목록 전체를 막지 않게 하는 것이 이 함수의 계약이다.
 */
export function formatTimestamp(
  value: string | null,
  now: Date = new Date(),
): FormattedTimestamp | null {
  if (!value) return null

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null

  const sameYear = parsed.getFullYear() === now.getFullYear()
  const sameDay = sameYear && parsed.toDateString() === now.toDateString()

  let display: string
  if (sameDay) {
    display = TIME_ONLY.format(parsed)
  } else if (sameYear) {
    display = SAME_YEAR.format(parsed)
  } else {
    display = OTHER_YEAR.format(parsed)
  }

  return { display, machine: value, full: FULL.format(parsed) }
}

/**
 * 초 단위 소요 시간을 사람이 읽는 표기로.
 *
 * backend가 주는 elapsedSeconds(step의 실제 소요, /results의 run 소요)를 그대로
 * 옮긴다. 브라우저 시계로 계산한 값이 아니라 서버가 기록한 값이므로 신뢰할 수
 * 있다.
 */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60

  if (hours > 0) return `${hours}시간 ${minutes}분`
  if (minutes > 0) return `${minutes}분 ${secs}초`
  return `${secs}초`
}

/**
 * 두 ISO 시각의 차이. 둘 다 서버가 준 값일 때만 쓴다.
 *
 * 실행 중인 run의 경과 시간을 "지금 - startedAt"으로 만들지 않는다. 브라우저
 * 시계와 서버 시계가 다르면 사용자가 보는 숫자가 틀리고 그 오차를 확인할 방법도
 * 없다. 실행 중에는 시작 시각만 보여주고, 단계별 소요는 backend가 기록한 step
 * elapsedSeconds를 쓴다.
 */
export function durationBetween(
  startedAt: string | null,
  finishedAt: string | null,
): string | null {
  if (!startedAt || !finishedAt) return null
  const start = new Date(startedAt).getTime()
  const end = new Date(finishedAt).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null
  return formatDuration((end - start) / 1000)
}
