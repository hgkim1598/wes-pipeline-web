/*
  서버 실행 모드를 화면 문구로.

  CreateJobRequest에는 runMode가 없다. backend가 서버 설정
  (config.RUN_MODE, 기본값 check_only)을 쓰기 때문에 사용자가 고를 수 있는
  값이 아니다. 그래서 이 모듈은 선택지가 아니라 "지금 이 서버가 무엇을
  하는지"를 설명하는 데만 쓰인다.

  값은 GET /api/health의 runMode에서 온다. 화면이 full을 고른 척하지 않는다.
*/

import type { MessageTone } from '@/components/ui/MessageBlock'

export interface RunModeView {
  label: string
  title: string
  description: string
  tone: MessageTone
}

const RUN_MODE_VIEW: Record<string, RunModeView> = {
  check_only: {
    label: '사전 점검',
    title: '이 서버는 사전 점검 모드입니다',
    description:
      '입력과 참조 데이터가 올바른지만 검사하고, 분석 산출물(BAM·VCF)은 생성하지 않습니다. 전체 분석으로 바꾸려면 서버 설정을 변경해야 합니다.',
    tone: 'warning',
  },
  full: {
    label: '전체 분석',
    title: '이 서버는 전체 분석 모드입니다',
    description:
      'WES pipeline 전체를 실행합니다. 샘플 하나에 수 시간이 걸릴 수 있습니다.',
    tone: 'info',
  },
}

/**
 * 모르는 값이면 원문만 보여주고 의미를 붙이지 않는다.
 * health를 아직 읽지 못했으면 null이다 — 서버 모드를 추측하지 않는다.
 */
export function describeRunMode(runMode: string | undefined): RunModeView | null {
  if (!runMode) return null
  return (
    RUN_MODE_VIEW[runMode] ?? {
      label: runMode,
      title: `이 서버의 실행 모드는 ${runMode}입니다`,
      description:
        'frontend가 모르는 실행 모드입니다. 어떤 단계가 실행되는지는 서버 설정을 확인해 주세요.',
      tone: 'info',
    }
  )
}
