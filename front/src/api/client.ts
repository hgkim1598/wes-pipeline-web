/*
  공통 HTTP 요청 계층.

  이 파일이 아는 것은 transport뿐이다. 어떤 endpoint가 있고 응답 shape가
  무엇인지는 각 feature의 api.ts가 안다.

  두 가지 규칙을 여기서 강제한다.

  1. 요청은 항상 상대경로다. backend 주소는 개발에서 vite.config.ts의
     '/api' proxy가 정한다. frontend 코드에 host:port가 들어가는 순간
     환경마다 코드가 갈라진다.

  2. 실패는 전부 ApiError로 정규화한다. 호출부가 network 끊김 · HTTP 오류 ·
     응답 형식 불일치를 구분해 다른 문구를 보여줄 수 있어야 해서,
     하나의 Error로 뭉개지 않고 kind를 남긴다.

  인증 · retry · interceptor는 없다. 필요해진 시점에 근거를 갖고 추가한다.
*/

/**
 * 실패 지점.
 *
 * network   요청이 backend에 도달하지 못했다 (서버 중지, 포트 미개방 등).
 * http      backend가 응답했지만 2xx가 아니다.
 * malformed 2xx로 응답했지만 본문을 기대한 형태로 읽지 못했다.
 */
export type ApiErrorKind = 'network' | 'http' | 'malformed'

interface ApiErrorOptions {
  kind: ApiErrorKind
  /** HTTP 응답을 받은 경우에만 존재한다. */
  status?: number
  /** 사용자 문구가 아닌 기술 상세. 화면에서 낮은 우선순위로 표시한다. */
  detail?: string
  cause?: unknown
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number | null
  readonly detail: string | null

  constructor(message: string, options: ApiErrorOptions) {
    super(message, { cause: options.cause })
    this.name = 'ApiError'
    this.kind = options.kind
    this.status = options.status ?? null
    this.detail = options.detail ?? null
  }
}

/**
 * FastAPI 오류 본문에서 사람이 읽을 부분만 꺼낸다.
 *
 * 이 backend는 두 형태를 쓴다 (backend/app/api/*.py).
 *   detail: "malformed job id"
 *   detail: { code: "resultsNotReady", message: "..." }
 * 둘 다 아니면 본문 앞부분을 그대로 쓴다. 본문을 읽지 못하는 것 자체는
 * 오류가 아니므로 조용히 undefined를 돌려준다.
 */
async function readErrorDetail(response: Response): Promise<string | undefined> {
  let text: string
  try {
    text = await response.text()
  } catch {
    return undefined
  }
  if (!text) return undefined

  try {
    const body: unknown = JSON.parse(text)
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail: unknown = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      if (detail !== null && typeof detail === 'object' && 'message' in detail) {
        const message: unknown = (detail as { message: unknown }).message
        if (typeof message === 'string') return message
      }
    }
  } catch {
    // JSON이 아니면 원문을 쓴다.
  }
  return text.slice(0, 500)
}

/**
 * JSON GET 요청 하나.
 *
 * 반환 타입이 unknown인 것은 의도다. 응답 shape의 책임은 계약을 아는
 * feature에 있고, 여기서 타입을 주장하면 검증 없이 통과해 버린다.
 */
export async function getJson(
  path: string,
  options?: { signal?: AbortSignal },
): Promise<unknown> {
  if (!path.startsWith('/')) {
    throw new ApiError(`API 경로는 상대경로여야 합니다: ${path}`, {
      kind: 'network',
    })
  }

  let response: Response
  try {
    response = await fetch(path, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options?.signal,
    })
  } catch (cause) {
    // 취소는 실패가 아니다. React Query가 취소로 인식하도록 그대로 던진다.
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause
    }
    throw new ApiError('서버에 연결하지 못했습니다.', {
      kind: 'network',
      detail: cause instanceof Error ? cause.message : undefined,
      cause,
    })
  }

  if (!response.ok) {
    throw new ApiError(`요청이 실패했습니다 (HTTP ${response.status}).`, {
      kind: 'http',
      status: response.status,
      detail: await readErrorDetail(response),
    })
  }

  try {
    return (await response.json()) as unknown
  } catch (cause) {
    throw new ApiError('응답을 JSON으로 읽지 못했습니다.', {
      kind: 'malformed',
      status: response.status,
      detail: cause instanceof Error ? cause.message : undefined,
      cause,
    })
  }
}
