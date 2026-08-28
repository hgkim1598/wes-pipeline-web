/**
 * class 문자열을 합친다. false/null/undefined는 버린다.
 *
 * clsx나 tailwind-merge를 쓰지 않는다. 현재 primitive는 조건부 class가
 * 거의 없고, 충돌하는 utility를 뒤에서 덮어쓸 일도 없어서 이 정도로 충분하다.
 */
export function cx(
  ...parts: Array<string | false | null | undefined>
): string {
  return parts.filter(Boolean).join(' ')
}
