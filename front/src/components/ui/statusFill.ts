/*
  면적 채움 전용 색.

  텍스트가 얹히지 않는 면(진행 바 · RunTape 셀)에만 쓴다. 배지의 배경은 옅은
  tint라서 6px 띠로 그리면 서로 구분되지 않으므로, 시안이 --fill-* 팔레트를
  따로 둔다(styles/tokens.css의 "진행 바 채움" 블록,
  docs/design/foundation.html).

  StatusBadge.tsx가 아니라 별도 모듈인 이유는 그 파일이 component 파일이고,
  상수를 함께 내보내면 fast refresh가 깨지기 때문이다(oxlint
  react/only-export-components). tone -> 색 대응은 여기 한 곳에만 있다.
*/

import type { StatusTone } from '@/components/ui/StatusBadge'

export const TONE_FILL_CLASS: Record<StatusTone, string> = {
  idle: 'bg-fill-idle',
  running: 'bg-fill-running',
  success: 'bg-fill-success',
  warning: 'bg-fill-warning',
  failure: 'bg-fill-failure',
  cancelled: 'bg-fill-skip',
}
