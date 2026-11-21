import {
  ChartColumn,
  ClipboardCheck,
  FileText,
  FlaskConical,
  Layers,
  ScanSearch,
  Scissors,
  Wrench,
  CircleDot,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/*
  단계 아이콘 (2026-11-20 승인 시안의 목록 행 아이콘).

  아이콘은 단계의 성질을 알아보게 하는 표식일 뿐이고 상태를 말하지 않는다 —
  상태는 옆의 상태 표시(아이콘 + 글자)가 맡는다. 장식용 DNA·현미경 그림은
  쓰지 않는다(CLAUDE.md 23장). 모르는 단계는 중립 표식이다.
*/
const STEP_ICON: Record<string, LucideIcon> = {
  '00_input_validation': ClipboardCheck,
  '01_raw_qc': FlaskConical,
  '02_preprocessing': Scissors,
  '03_alignment': Layers,
  '04_processing': Wrench,
  '05_coverage_qc': ChartColumn,
  '06_variant_calling': ScanSearch,
  '99_finalization': FileText,
}

export function stepIcon(stepId: string): LucideIcon {
  return STEP_ICON[stepId] ?? CircleDot
}
