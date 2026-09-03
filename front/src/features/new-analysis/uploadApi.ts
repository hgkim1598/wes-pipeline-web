/*
  Chunk upload 4개 endpoint의 계약.

  근거: backend/app/api/uploads.py, backend/app/schemas.py

    POST /api/uploads                  {filename,size,sampleId,slotId} -> {uploadId, chunkSize}
    GET  /api/uploads/{id}             -> {receivedChunks}
    PUT  /api/uploads/{id}/{index}     octet-stream -> 204
    POST /api/uploads/{id}/complete    -> {path}

  complete가 돌려주는 `path`는 서버 파일 경로가 아니라 upl_로 시작하는
  불투명한 토큰이다(uploads.py의 module docstring과 complete_upload).
  frontend는 그 값을 해석하지 않고 POST /api/jobs에 그대로 되돌려준다.
  경로처럼 다루는 순간 서버 파일 시스템을 아는 척하게 된다.

  chunkSize는 서버가 정한다. frontend가 8MiB를 안다고 가정하지 않는다 —
  backend config.CHUNK_SIZE가 바뀌면 complete가 chunk 수를 검사해서 거절한다.
*/

import { z } from 'zod'

import { ApiError, getJson, postJson, putBinary } from '@/api/client'

export const UPLOADS_PATH = '/api/uploads'

const UploadInitResponseSchema = z.object({
  uploadId: z.string(),
  chunkSize: z.number().int().positive(),
})

const UploadStatusResponseSchema = z.object({
  receivedChunks: z.array(z.number().int()),
})

const UploadCompleteResponseSchema = z.object({
  path: z.string(),
})

export type UploadInitResponse = z.infer<typeof UploadInitResponseSchema>

/** 계약 불일치는 조용히 넘기지 않는다. runs feature와 같은 처리다. */
function parse<T>(schema: z.ZodType<T>, payload: unknown, message: string): T {
  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiError(message, {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }
  return parsed.data
}

export interface CreateUploadInput {
  filename: string
  size: number
  /** 어느 샘플의 파일인지 서버가 기록해 두는 값. 분석 실행에는 쓰이지 않는다. */
  sampleId: string | null
  slotId: string
}

export async function createUpload(
  input: CreateUploadInput,
  signal?: AbortSignal,
): Promise<UploadInitResponse> {
  const payload = await postJson(UPLOADS_PATH, input, { signal })
  return parse(
    UploadInitResponseSchema,
    payload,
    '업로드 시작 응답이 예상한 형식과 다릅니다.',
  )
}

/**
 * 서버가 이미 받은 chunk 번호.
 *
 * 이어받기의 근거가 되는 값이다. 지금은 같은 세션 안에서 재시도할 때만
 * 쓰지만, uploadId를 보관해 두면 그대로 이어받기에 쓸 수 있다.
 */
export async function fetchReceivedChunks(
  uploadId: string,
  signal?: AbortSignal,
): Promise<number[]> {
  const payload = await getJson(`${UPLOADS_PATH}/${uploadId}`, { signal })
  return parse(
    UploadStatusResponseSchema,
    payload,
    '업로드 상태 응답이 예상한 형식과 다릅니다.',
  ).receivedChunks
}

export async function putUploadChunk(
  uploadId: string,
  chunkIndex: number,
  chunk: Blob,
  signal?: AbortSignal,
): Promise<void> {
  await putBinary(`${UPLOADS_PATH}/${uploadId}/${chunkIndex}`, chunk, { signal })
}

/** 성공하면 POST /api/jobs에 그대로 넣을 업로드 토큰을 돌려준다. */
export async function completeUpload(
  uploadId: string,
  signal?: AbortSignal,
): Promise<string> {
  const payload = await postJson(`${UPLOADS_PATH}/${uploadId}/complete`, null, {
    signal,
  })
  return parse(
    UploadCompleteResponseSchema,
    payload,
    '업로드 완료 응답이 예상한 형식과 다릅니다.',
  ).path
}
