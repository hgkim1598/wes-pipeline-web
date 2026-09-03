/*
  슬롯 하나의 업로드 상태.

  이 hook은 인스턴스 하나가 파일 하나를 책임진다. R1과 R2는 각각 따로
  호출하고 서로의 상태를 모른다. 전역 store나 앱 단일 upload 객체를 쓰지
  않는 이유는, 나중에 샘플이 여러 개가 되면 슬롯도 여러 개가 되기 때문이다.
  그때 필요한 것은 이 hook을 더 호출하는 것뿐이어야 한다.

  업로드는 event handler에서 시작한다. effect에서 시작하지 않으므로
  StrictMode의 이중 실행이 파일을 두 번 보내지 않는다.
*/

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import type { FastqSlotId } from '@/features/new-analysis/fastq'
import { validateFastqFile } from '@/features/new-analysis/fastq'
import type {
  ResumableUpload,
  UploadStage,
} from '@/features/new-analysis/uploadFastq'
import { UploadFailure, uploadFastq } from '@/features/new-analysis/uploadFastq'

export type FastqUploadStatus = 'empty' | 'uploading' | 'completed' | 'failed'

export interface FastqUploadError {
  summary: string
  hint: string
  /** backend가 준 기술 상세. 낮은 우선순위로 표시한다. */
  detail: string | null
  /**
   * 같은 파일로 다시 시도해서 해결될 수 있는 실패인지.
   * 파일 자체가 규칙에 맞지 않으면 false다 — 다시 눌러도 같은 결과라
   * 버튼을 보여주는 것 자체가 잘못된 안내가 된다.
   */
  retryable: boolean
}

export interface FastqUploadController {
  slotId: FastqSlotId
  file: File | null
  status: FastqUploadStatus
  sentBytes: number
  totalBytes: number
  /** 0~100. 크기를 모르면 0. */
  percent: number
  /** 업로드가 끝난 뒤에만 값이 있다. POST /api/jobs에 넣는 토큰이다. */
  token: string | null
  error: FastqUploadError | null
  select: (file: File, sampleId: string | null) => void
  retry: (sampleId: string | null) => void
  clear: () => void
}

interface SlotState {
  file: File | null
  status: FastqUploadStatus
  sentBytes: number
  token: string | null
  error: FastqUploadError | null
}

const EMPTY: SlotState = {
  file: null,
  status: 'empty',
  sentBytes: 0,
  token: null,
  error: null,
}

export function useFastqUpload(slotId: FastqSlotId): FastqUploadController {
  const [state, setState] = useState<SlotState>(EMPTY)

  const abortRef = useRef<AbortController | null>(null)
  /** 재시도할 때 이어받을 지점. 파일을 바꾸면 버린다. */
  const resumeRef = useRef<ResumableUpload | null>(null)
  /** 언마운트 이후의 setState를 막는다. 업로드는 오래 걸린다. */
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  const start = useCallback(
    (file: File, sampleId: string | null, resume: ResumableUpload | null) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setState({
        file,
        status: 'uploading',
        sentBytes: 0,
        token: null,
        error: null,
      })

      void uploadFastq({
        file,
        slotId,
        sampleId,
        resume: resume ?? undefined,
        signal: controller.signal,
        onUploadCreated: (upload) => {
          resumeRef.current = upload
        },
        onProgress: (sentBytes) => {
          if (!mountedRef.current || controller.signal.aborted) return
          setState((prev) =>
            prev.status === 'uploading' ? { ...prev, sentBytes } : prev,
          )
        },
      })
        .then((result) => {
          if (!mountedRef.current || controller.signal.aborted) return
          setState((prev) => ({
            ...prev,
            status: 'completed',
            sentBytes: file.size,
            token: result.token,
            error: null,
          }))
        })
        .catch((cause: unknown) => {
          // 취소는 실패가 아니다. clear()나 언마운트가 이미 상태를 정리했다.
          if (controller.signal.aborted) return
          if (!mountedRef.current) return
          setState((prev) => ({
            ...prev,
            status: 'failed',
            error: describeUploadError(cause),
          }))
        })
    },
    [slotId],
  )

  const select = useCallback(
    (file: File, sampleId: string | null) => {
      const problem = validateFastqFile(file)
      if (problem) {
        abortRef.current?.abort()
        resumeRef.current = null
        setState({
          file,
          status: 'failed',
          sentBytes: 0,
          token: null,
          error: {
            summary: '이 파일은 사용할 수 없습니다.',
            hint: problem,
            detail: null,
            retryable: false,
          },
        })
        return
      }

      // 다른 파일이므로 이전 업로드를 이어받지 않는다.
      resumeRef.current = null
      start(file, sampleId, null)
    },
    [start],
  )

  const retry = useCallback(
    (sampleId: string | null) => {
      const file = state.file
      if (!file) return
      if (validateFastqFile(file)) return
      // 같은 파일이면 서버가 이미 받은 조각부터 이어서 보낸다.
      start(file, sampleId, resumeRef.current)
    },
    [start, state.file],
  )

  const clear = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    resumeRef.current = null
    setState(EMPTY)
  }, [])

  const totalBytes = state.file?.size ?? 0
  const percent =
    totalBytes > 0
      ? Math.min(100, Math.round((state.sentBytes / totalBytes) * 100))
      : 0

  return {
    slotId,
    file: state.file,
    status: state.status,
    sentBytes: state.sentBytes,
    totalBytes,
    percent,
    token: state.token,
    error: state.error,
    select,
    retry,
    clear,
  }
}

/*
  실패를 사용자 문구로.

  단계와 원인을 함께 본다. "업로드 실패" 하나로 뭉치면 서버가 꺼진 것과
  파일이 거절된 것이 같은 메시지가 되고, 사용자는 무엇을 해야 할지 모른다.
*/
const STAGE_SUMMARY: Record<UploadStage, string> = {
  create: '업로드를 시작하지 못했습니다.',
  chunk: '파일을 전송하는 중 오류가 발생했습니다.',
  complete: '전송한 파일을 서버가 마무리하지 못했습니다.',
}

function describeUploadError(cause: unknown): FastqUploadError {
  const stage = cause instanceof UploadFailure ? cause.stage : null
  const inner = cause instanceof UploadFailure ? cause.cause : cause
  const summary = stage
    ? STAGE_SUMMARY[stage]
    : '업로드 중 오류가 발생했습니다.'

  if (inner instanceof ApiError) {
    if (inner.kind === 'network') {
      return {
        summary,
        hint: '서버 연결이 끊어졌습니다. 연결을 확인한 뒤 다시 시도하면 전송된 부분 다음부터 이어서 보냅니다.',
        detail: inner.detail,
        retryable: true,
      }
    }
    if (inner.kind === 'http') {
      return {
        summary,
        hint:
          inner.status === 400
            ? '서버가 이 파일을 받지 않았습니다. 아래 사유를 확인해 주세요.'
            : '서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.',
        detail: inner.detail,
        // 400은 서버가 이 입력을 거절한 것이라 같은 파일로 다시 보내도 같다.
        retryable: inner.status !== 400,
      }
    }
    return {
      summary,
      hint: '서버 응답을 읽지 못했습니다. frontend와 backend의 업로드 계약이 어긋났을 수 있습니다.',
      detail: inner.detail,
      retryable: false,
    }
  }

  return {
    summary,
    hint: '알 수 없는 오류입니다. 다시 시도해 주세요.',
    detail: inner instanceof Error ? inner.message : null,
    retryable: true,
  }
}
