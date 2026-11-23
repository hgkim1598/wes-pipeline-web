/*
  "없음"을 말하는 문구가 실행의 실제 상태와 맞는가.

  두 결함(2026-11-23 점검, 개발판단기록 48장)에서 나왔다.

  1. 산출물 409 — 끝난 실행에도 "단계가 끝날 때마다 추가됩니다"라고 했다.
     main.sh가 산출물 목록을 만들기 전에 멈춘 실행은 산출물이 앞으로도
     생기지 않는다. 기다리면 될 것처럼 읽히면 안 된다(ResultsView의 409와
     같은 구분).
  2. 실패 카드 — 구조화된 실패(explanation.failures)가 없고 job의 원문 error만
     있을 때도 "아래 항목에서 실행이 중단되었습니다"라고 했는데, 아래에는
     실패 항목이 없었다(원문은 접힌 "기술 정보" 안). 경고만 보이면 그것이
     중단 원인처럼 읽힌다. 원인을 지어내지 않는다.

  React·경로 별칭을 쓰지 않는다: scripts/run-detail-copy.test.mjs가 node로
  직접 읽는다.
*/

export interface Copy {
  title: string
  body: string
}

/** `/artifacts`가 409(목록 없음)일 때의 문구. */
export function artifactsNotReadyCopy(running: boolean): Copy {
  return running
    ? {
        title: '산출물이 아직 없습니다',
        body: '이 실행은 아직 산출물을 등록하지 않았습니다. 단계가 끝날 때마다 추가됩니다. 0개로 확정된 것이 아닙니다.',
      }
    : {
        title: '이 실행은 산출물 목록을 만들지 않았습니다',
        body: '실행이 끝났지만 산출물 목록이 없습니다. 파이프라인이 산출물을 등록하기 전에 멈춘 경우입니다 — 원인은 실패 카드와 파이프라인 탭의 로그에서 확인하세요.',
      }
}

/**
 * 실패 카드(AttentionSection) 제목과 표식.
 *
 * 2026-11-23 화면 점검: 실패가 없고 "참고" 진단만 있는 완료 실행에서도 제목이
 * "확인이 필요한 사항이 있습니다"였다. 바로 위 요약 칸은 "확인 필요 0"이라
 * 두 문장이 서로 어긋났다. 확인 필요(attention)가 한 건이라도 있을 때만 그
 * 제목을 쓰고, 참고만 있으면 참고라고 말한다.
 */
export type AttentionTone = 'failure' | 'warning' | 'note'

export function attentionHeading(
  hasFailure: boolean,
  isPrecheck: boolean,
  attentionCount: number,
): { title: string; tone: AttentionTone } {
  if (hasFailure) {
    return {
      title: isPrecheck ? '분석을 시작하기 전 확인에서 멈췄습니다' : '분석이 완료되지 못했습니다',
      tone: 'failure',
    }
  }
  if (attentionCount > 0) {
    return { title: '확인이 필요한 사항이 있습니다', tone: 'warning' }
  }
  return { title: '이 실행에 함께 기록된 참고 사항', tone: 'note' }
}

/**
 * `/results`가 409(결과 문서 없음)일 때의 문구. 산출물과 같은 구분이다.
 *
 * 이 안내는 개요 탭에서 실패 카드·취소 안내 **아래**에 놓인다(2026-11-23).
 * 이전 문구는 "원인은 파이프라인 탭의 실패 사유"라고 해서, 바로 위에 있는 실패
 * 카드를 두고 다른 탭으로 보냈다.
 */
export function resultsNotReadyCopy(terminal: boolean): Copy {
  return terminal
    ? {
        title: '이 실행은 결과 문서를 만들지 않았습니다',
        body: '실행이 끝났지만 결과 문서가 없습니다. 파이프라인이 결과를 기록하기 전에 멈춘 경우입니다 — 멈춘 이유는 이 화면 위쪽 안내와 파이프라인 탭의 실행 로그에 있습니다.',
      }
    : {
        title: '결과가 아직 준비되지 않았습니다',
        body: '이 실행은 결과 문서를 아직 만들지 않았습니다. 결과가 0건이라는 뜻이 아닙니다.',
      }
}

/**
 * 실패 카드 첫 문장의 종류.
 *
 *   items    구조화된 실패 항목이 아래에 있다 → "아래 항목에서 …"
 *   rawOnly  항목은 없고 원문 error만 있다 → 원문을 펼쳐 보여 주고, 무엇이
 *            멈췄는지 구조화된 기록이 없다고 말한다
 *   none     실패가 아니다
 */
export type FailureLead = 'items' | 'rawOnly' | 'none'

export function failureLead(failureCount: number, rawError: string | null): FailureLead {
  if (failureCount > 0) return 'items'
  if (rawError && rawError.trim()) return 'rawOnly'
  return 'none'
}

export function failureLeadText(lead: FailureLead, isPrecheck: boolean): string | null {
  if (lead === 'items') {
    return isPrecheck
      ? '사전 점검에서 문제가 확인되어 분석을 시작하지 않았습니다. 아래 항목을 준비한 뒤 다시 실행하면 됩니다.'
      : '아래 항목에서 실행이 중단되었습니다.'
  }
  if (lead === 'rawOnly') {
    return isPrecheck
      ? '사전 점검에서 멈췄지만, 어떤 항목인지 구조화된 기록이 없습니다. 실행이 남긴 오류 원문을 아래에 그대로 보여 줍니다.'
      : '실행이 중단됐지만, 어느 항목에서 멈췄는지 구조화된 기록이 없습니다. 실행이 남긴 오류 원문을 아래에 그대로 보여 줍니다.'
  }
  return null
}
