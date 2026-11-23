/*
  AI 설명 요청이 HTTP 단계에서 실패했을 때의 문구(POST /api/jobs/{id}/synthesis).

  응답 값만으로 정해지는 순수 함수다. 모델 응답이 아니라 요청 자체가 거절·실패한
  경우만 다룬다(available:false 응답은 RunSynthesisPanel이 따로 보여 준다).

  409는 두 가지다(backend/app/api/synthesis.py).
    runNotFinished       실행이 아직 끝나지 않았다. 모델을 부르지 않았다.
    synthesisInProgress  같은 실행의 설명이 이미 만들어지는 중이다. 이 요청은
                         모델을 부르지 않았고, 진행 중인 요청은 계속된다.
  429 synthesisBusy      서버가 다른 실행의 설명을 만드는 중이다(동시 호출 상한).
*/

export interface SynthesisErrorInput {
  kind: 'network' | 'http' | 'malformed' | null
  status: number | null
  code: string | null
}

export interface SynthesisErrorCopy {
  title: string
  body: string
  tone: 'info' | 'warning'
}

export function synthesisErrorCopy({ kind, status, code }: SynthesisErrorInput): SynthesisErrorCopy {
  if (kind === 'network') {
    return {
      tone: 'warning',
      title: '서버에 연결하지 못했습니다',
      body: 'backend가 실행 중인지, 주소가 맞는지 확인한 뒤 다시 요청하세요.',
    }
  }
  if (kind === 'malformed') {
    return {
      tone: 'warning',
      title: '응답 형식이 예상과 다릅니다',
      body: '서버의 응답을 frontend가 아는 계약대로 읽지 못했습니다. frontend와 backend의 버전이 맞는지 확인해야 합니다.',
    }
  }
  if (status === 400) {
    return { tone: 'warning', title: '잘못된 요청입니다', body: '실행 ID 형식이 올바르지 않습니다. 실행 목록에서 다시 선택하세요.' }
  }
  if (status === 404) {
    return { tone: 'warning', title: '이 실행을 찾을 수 없습니다', body: '서버에 이 실행의 기록이 없습니다. 실행 목록에서 다시 선택하세요.' }
  }
  if (status === 409 && code === 'synthesisInProgress') {
    return {
      tone: 'info',
      title: '이 실행의 설명을 이미 만드는 중입니다',
      body: '다른 탭이나 이전 요청이 아직 진행 중입니다. 이 요청은 모델을 호출하지 않았습니다. 진행 중인 요청이 끝난 뒤 다시 요청하세요. 설명은 서버에 저장되지 않으므로, 진행 중인 요청의 결과는 그 요청을 보낸 화면에만 나타납니다.',
    }
  }
  if (status === 409) {
    return { tone: 'info', title: '아직 끝나지 않은 실행입니다', body: '실행이 끝난 뒤 다시 요청하세요. 이 요청은 모델을 호출하지 않았습니다.' }
  }
  if (status === 429 && code === 'synthesisBusy') {
    return {
      tone: 'info',
      title: '서버가 다른 설명을 만드는 중입니다',
      body: '동시에 만들 수 있는 설명 수에 도달했습니다. 이 요청은 모델을 호출하지 않았습니다. 잠시 뒤 다시 요청하세요.',
    }
  }
  if (status !== null && status >= 500) {
    return {
      tone: 'warning',
      title: '서버 내부 오류가 발생했습니다',
      body: `서버가 HTTP ${status}로 응답했습니다. 실행 기록을 읽는 중 문제가 생겼을 수 있으며, 서버 로그를 확인해야 합니다.`,
    }
  }
  return {
    tone: 'warning',
    title: '요청이 실패했습니다',
    body: status !== null ? `서버가 HTTP ${status}로 응답했습니다.` : 'AI 설명 요청을 처리하지 못했습니다.',
  }
}
