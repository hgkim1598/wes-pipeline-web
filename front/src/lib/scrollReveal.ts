/*
  가로 스크롤 컨테이너 안의 한 항목이 보이도록 할 scrollLeft (2026-11-23, 개발판단기록 54장).

  파이프라인 단계 띠는 넓은 화면에서 가로 스크롤 컨테이너다. 다른 곳(목록 행·
  실패 카드·URL ?step=)에서 단계를 고르면 선택은 바뀌었는데 띠의 스크롤은 그대로라
  선택된 점이 화면 밖에 남을 수 있었다.

  element.scrollIntoView()를 쓰지 않는다. 가로만 맞추려 해도 띠가 화면 아래에
  있으면 페이지 전체가 세로로 움직인다. 컨테이너의 scrollLeft만 바꾼다.

  이미 다 보이면 그대로 둔다 — 사용자가 직접 옮긴 스크롤을 빼앗지 않는다.
  좌표는 모두 컨테이너 내용 기준(offsetLeft)이다. DOM을 읽지 않는 순수 함수라
  scripts/run-detail-policy.test.mjs가 node로 직접 읽는다.
*/

export function revealScrollLeft(
  /** 지금 컨테이너의 scrollLeft. */
  scrollLeft: number,
  /** 컨테이너의 보이는 폭(clientWidth). */
  viewWidth: number,
  /** 항목의 왼쪽 위치(내용 기준). */
  itemLeft: number,
  /** 항목 폭. */
  itemWidth: number,
): number {
  const itemRight = itemLeft + itemWidth
  if (itemLeft >= scrollLeft && itemRight <= scrollLeft + viewWidth) return scrollLeft
  if (itemLeft < scrollLeft || itemWidth > viewWidth) return Math.max(0, itemLeft)
  return itemRight - viewWidth
}
