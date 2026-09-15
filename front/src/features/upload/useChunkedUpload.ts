/**
 * upload/useChunkedUpload.ts
 * ============================================================================
 * 대용량 FASTQ 업로드용 청크 업로더.
 *
 * [왜 필요한가]
 *   WES FASTQ는 파일당 12~15GB다.
 *   단순 <input type="file"> + FormData 로 보내면
 *     - 브라우저 메모리에 전체를 올리다 탭이 죽는다
 *     - 중간에 끊기면 처음부터 다시 올려야 한다
 *     - nginx/프록시의 body size 제한에 걸린다
 *
 * [해결]
 *   File.slice() 로 8MB씩 잘라 순차 전송하고,
 *   서버는 uploadId 기준으로 이어붙인다.
 *   새로고침 후에도 uploadId 를 알면 이어받기가 가능하다.
 *
 * [서버가 구현해야 하는 엔드포인트]
 *   POST   /api/uploads            → { uploadId, chunkSize }
 *   GET    /api/uploads/:id        → { receivedChunks: number[] }   (이어받기용)
 *   PUT    /api/uploads/:id/:index → 204
 *   POST   /api/uploads/:id/complete → { path }  (서버 저장 경로)
 * ============================================================================
 */

import { useCallback, useRef, useState } from 'react';

const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024; // 8MB
const MAX_RETRY = 3;

export type UploadStatus =
  | 'idle' | 'preparing' | 'uploading' | 'finalizing' | 'done' | 'error' | 'aborted';

export interface UploadState {
  status: UploadStatus;
  /** 0~100 */
  progress: number;
  /** 초당 바이트 */
  speed: number;
  /** 남은 시간 (초). 계산 불가 시 null */
  etaSeconds: number | null;
  uploadId: string | null;
  /** 완료 시 서버가 알려준 저장 경로 */
  serverPath: string | null;
  error: string | null;
}

const INITIAL: UploadState = {
  status: 'idle', progress: 0, speed: 0, etaSeconds: null,
  uploadId: null, serverPath: null, error: null,
};

export function useChunkedUpload() {
  const [state, setState] = useState<UploadState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL);
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, status: 'aborted' }));
  }, []);

  const upload = useCallback(async (file: File, meta: Record<string, string> = {}) => {
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // ── 1) 업로드 세션 생성 ───────────────────────────────────────────
      setState({ ...INITIAL, status: 'preparing' });

      const initRes = await fetch('/api/uploads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          size: file.size,
          ...meta,
        }),
        signal: controller.signal,
      });
      if (!initRes.ok) throw new Error(`업로드 세션 생성 실패 (${initRes.status})`);

      const { uploadId, chunkSize = DEFAULT_CHUNK_SIZE } = await initRes.json();
      const totalChunks = Math.ceil(file.size / chunkSize);

      // ── 2) 이미 올라간 청크 확인 (이어받기) ───────────────────────────
      let received = new Set<number>();
      try {
        const statusRes = await fetch(`/api/uploads/${uploadId}`, { signal: controller.signal });
        if (statusRes.ok) {
          const { receivedChunks = [] } = await statusRes.json();
          received = new Set<number>(receivedChunks);
        }
      } catch { /* 이어받기 조회 실패는 무시하고 처음부터 */ }

      setState((s) => ({ ...s, status: 'uploading', uploadId }));

      // ── 3) 청크 순차 전송 ─────────────────────────────────────────────
      const startedAt = Date.now();
      let sentBytes = received.size * chunkSize;

      for (let i = 0; i < totalChunks; i++) {
        if (controller.signal.aborted) throw new DOMException('aborted', 'AbortError');
        if (received.has(i)) continue;

        const start = i * chunkSize;
        const blob  = file.slice(start, Math.min(start + chunkSize, file.size));

        let ok = false;
        let lastErr: unknown = null;
        for (let attempt = 0; attempt < MAX_RETRY; attempt++) {
          try {
            const res = await fetch(`/api/uploads/${uploadId}/${i}`, {
              method: 'PUT',
              headers: {
                'Content-Type': 'application/octet-stream',
                'X-Total-Chunks': String(totalChunks),
              },
              body: blob,
              signal: controller.signal,
            });
            if (!res.ok) throw new Error(`chunk ${i} 실패 (${res.status})`);
            ok = true;
            break;
          } catch (e) {
            if (controller.signal.aborted) throw e;
            lastErr = e;
            // 지수 백오프
            await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
          }
        }
        if (!ok) throw lastErr instanceof Error ? lastErr : new Error('청크 전송 실패');

        sentBytes += blob.size;
        const elapsed = (Date.now() - startedAt) / 1000;
        const speed   = elapsed > 0 ? sentBytes / elapsed : 0;
        const left    = file.size - sentBytes;

        setState((s) => ({
          ...s,
          progress: Math.round((sentBytes / file.size) * 100),
          speed,
          etaSeconds: speed > 0 ? Math.round(left / speed) : null,
        }));
      }

      // ── 4) 병합 요청 ──────────────────────────────────────────────────
      setState((s) => ({ ...s, status: 'finalizing', progress: 100 }));

      const doneRes = await fetch(`/api/uploads/${uploadId}/complete`, {
        method: 'POST',
        signal: controller.signal,
      });
      if (!doneRes.ok) throw new Error(`병합 실패 (${doneRes.status})`);
      const { path } = await doneRes.json();

      setState((s) => ({ ...s, status: 'done', serverPath: path }));
      return path as string;

    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setState((s) => ({ ...s, status: 'aborted' }));
        return null;
      }
      setState((s) => ({
        ...s,
        status: 'error',
        error: e instanceof Error ? e.message : '알 수 없는 오류',
      }));
      return null;
    }
  }, []);

  return { state, upload, abort, reset };
}

// ── 표시용 헬퍼 ─────────────────────────────────────────────────────────────
export function formatSpeed(bytesPerSec: number): string {
  if (bytesPerSec <= 0) return '—';
  const mb = bytesPerSec / 1e6;
  return mb >= 1 ? `${mb.toFixed(1)} MB/s` : `${(bytesPerSec / 1e3).toFixed(0)} KB/s`;
}

export function formatEta(seconds: number | null): string {
  if (seconds == null || !isFinite(seconds)) return '—';
  if (seconds < 60) return `${seconds}초`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}분`;
  const h = Math.floor(m / 60);
  return `${h}시간 ${m % 60}분`;
}
