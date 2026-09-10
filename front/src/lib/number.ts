/*
  화면에 숫자를 적는 방법.

  ── 왜 필요한가 `[코드근거]` ────────────────────────────────────────────

  `Number.prototype.toLocaleString()`의 기본값은 `maximumFractionDigits: 3`이다.
  그래서 평균 깊이 `10.9967`이 화면에 **`10.997`로 나왔다.** 측정값을 화면이
  조용히 바꾼 것이고, 이 저장소의 규율(파이프라인이 준 사실을 정확히 보여준다)에
  정면으로 어긋난다.

  ── 값의 종류마다 다르게 적는다 ─────────────────────────────────────────

  전부 같은 소수 자리로 맞추지 않는다. 자리수는 값의 성질이 정한다.

    개수      정수다. 천 단위 구분만 넣는다              54,692
    측정값    소수 자리를 그대로 살린다                  10.9967
    비율      파이프라인이 준 자리수를 그대로 쓴다        7.2115

  ── 반올림으로 판정하지 않는다 ──────────────────────────────────────────

  "10.99×를 11×로 보여주자" 같은 정리는 하지 않는다. 자리수를 줄이는 순간
  값이 어느 임계값 위인지 아래인지가 달라질 수 있고, 이 프로젝트는 커버리지에
  임계값을 두지 않기로 했다(§27-4). 화면이 반올림으로 판정을 만들면 안 된다.
*/

/** 천 단위 구분이 있는 정수. 소수가 섞여 들어오면 그대로 살린다. */
export function formatCount(value: number): string {
  return new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 20 }).format(
    value,
  )
}

/**
 * 측정값. 소수 자리를 **버리지 않는다.**
 *
 * `maximumFractionDigits: 20`은 IEEE 754 double이 의미 있게 표현할 수 있는
 * 범위를 넘으므로, 실질적으로 "받은 그대로"가 된다.
 */
export function formatMeasured(value: number): string {
  return new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 20 }).format(
    value,
  )
}
