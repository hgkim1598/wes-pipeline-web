/*
  FASTQ 한 개를 chunk로 나눠 보내는 절차.

  이 함수는 상태를 갖지 않는다. 전역 currentUpload도, 모듈 변수도 없다.
  필요한 것은 전부 인자로 받고 결과는 반환값으로 돌려준다. 그래서 R1과 R2가
  같은 코드를 동시에 쓸 수 있고, 나중에 여러 샘플을 올리게 되어도
  이 함수는 그대로 여러 번 호출되기만 하면 된다.

  절차는 backend/app/api/uploads.py를 그대로 따른다.

    1. POST /api/uploads          uploadId와 chunkSize를 받는다
    2. (이어받기면) GET           서버가 이미 가진 chunk를 건너뛴다
    3. PUT ... /{index}           0부터 순서대로, 빠짐없이
    4. POST ... /complete         업로드 토큰을 받는다

  chunk를 병렬로 보내지 않는다. 서버는 순서를 요구하지 않지만, WES FASTQ는
  수 GB이고 브라우저의 동시 연결은 6개다. 동시에 밀어 넣으면 진행률이
  실제 전송량과 어긋나고, 실패했을 때 어디까지 갔는지도 흐려진다.
*/

import {
  completeUpload,
  createUpload,
  fetchReceivedChunks,
  putUploadChunk,
} from '@/features/new-analysis/uploadApi'

/** 어느 단계에서 실패했는지. 사용자에게 다른 안내가 필요한 지점들이다. */
export type UploadStage = 'create' | 'chunk' | 'complete'

export class UploadFailure extends Error {
  readonly stage: UploadStage

  constructor(stage: UploadStage, cause: unknown) {
    super(`upload failed at stage: ${stage}`, { cause })
    this.name = 'UploadFailure'
    this.stage = stage
  }
}

/** 이어받기에 필요한 최소 정보. chunkSize를 모르면 조각 경계를 맞출 수 없다. */
export interface ResumableUpload {
  uploadId: string
  chunkSize: number
}

export interface UploadFastqOptions {
  file: File
  slotId: string
  sampleId: string | null
  /**
   * 이미 발급받은 업로드. 주면 새로 만들지 않고 서버가 가진 chunk를 건너뛴
   * 뒤 이어서 보낸다. 지금은 같은 세션에서 재시도할 때 쓰이지만, 이 값을
   * 어딘가에 보관하면 세션을 넘는 이어받기도 같은 경로로 동작한다.
   */
  resume?: ResumableUpload
  /** 업로드가 만들어지는 즉시 알려준다. 중단 지점을 기억하기 위한 것이다. */
  onUploadCreated?: (upload: ResumableUpload) => void
  onProgress?: (sentBytes: number) => void
  signal?: AbortSignal
}

export interface UploadFastqResult {
  uploadId: string
  /** POST /api/jobs의 files에 그대로 넣는 값. */
  token: string
}

export async function uploadFastq(
  options: UploadFastqOptions,
): Promise<UploadFastqResult> {
  const { file, slotId, sampleId, signal } = options

  let uploadId: string
  let chunkSize: number
  let received = new Set<number>()

  try {
    if (options.resume) {
      // 새로 만들지 않는다. 새 uploadId를 받으면 서버에 이미 올라간 조각을
      // 버리게 되고, 쓰이지 않는 업로드 행만 하나 남는다.
      uploadId = options.resume.uploadId
      chunkSize = options.resume.chunkSize
      received = new Set(await fetchReceivedChunks(uploadId, signal))
    } else {
      const created = await createUpload(
        { filename: file.name, size: file.size, sampleId, slotId },
        signal,
      )
      uploadId = created.uploadId
      chunkSize = created.chunkSize
    }
  } catch (cause) {
    if (isAbort(cause)) throw cause
    throw new UploadFailure('create', cause)
  }

  options.onUploadCreated?.({ uploadId, chunkSize })

  const chunkCount = Math.ceil(file.size / chunkSize)
  let sentBytes = 0

  for (let index = 0; index < chunkCount; index += 1) {
    const start = index * chunkSize
    const end = Math.min(start + chunkSize, file.size)

    if (received.has(index)) {
      // 이미 서버에 있는 조각. 진행률에는 포함시킨다.
      sentBytes = end
      options.onProgress?.(sentBytes)
      continue
    }

    try {
      await putUploadChunk(uploadId, index, file.slice(start, end), signal)
    } catch (cause) {
      if (isAbort(cause)) throw cause
      throw new UploadFailure('chunk', cause)
    }

    sentBytes = end
    options.onProgress?.(sentBytes)
  }

  try {
    const token = await completeUpload(uploadId, signal)
    return { uploadId, token }
  } catch (cause) {
    if (isAbort(cause)) throw cause
    throw new UploadFailure('complete', cause)
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
