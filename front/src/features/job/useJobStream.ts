/**
 * job/useJobStream.ts
 * ============================================================================
 * 파이프라인 실행 상태를 실시간으로 받아오는 훅.
 *
 * [전송 방식] SSE(Server-Sent Events) 우선, 실패 시 폴링으로 자동 강등.
 *   - SSE는 단방향이라 WebSocket보다 구현이 단순하고 프록시 호환성이 좋다
 *   - 우리가 필요한 건 서버 → 브라우저 단방향 로그뿐이라 SSE로 충분하다
 *
 * [서버 엔드포인트]
 *   GET /api/jobs/:id/stream   (text/event-stream)
 *   GET /api/jobs/:id          (폴링 폴백)
 *
 * [main.sh 와의 연결]
 *   main.sh 가 출력하는 로그를 백엔드가 파싱해서
 *   { stepId, status, elapsed } 형태로 변환해 흘려보낸다.
 *   status/run_status.json 을 그대로 읽어 보내도 된다.
 * ============================================================================
 */

import { useEffect, useRef, useState, useCallback } from 'react';

// ── main.sh 의 단계 정의와 1:1 대응 ─────────────────────────────────────────
export type StepStatus = 'pending' | 'running' | 'completed' | 'warning' | 'failed' | 'skipped';

export interface StepState {
  stepId: string;        // "03_alignment"
  label: string;         // "정렬 (BWA-MEM2)"
  status: StepStatus;
  elapsedSeconds: number;
  /** 해당 단계에서 발생한 경고/에러 메시지 */
  messages: string[];
}

export type JobStatus =
  | 'queued' | 'running' | 'completed' | 'completed_with_warnings' | 'failed' | 'cancelled';

export interface JobState {
  jobId: string;
  status: JobStatus;
  /** 0~100 */
  progress: number;
  steps: StepState[];
  /** 최근 로그 라인 (터미널 뷰에 표시) */
  logTail: string[];
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  /** 연결 방식 — UI에서 표시 */
  transport: 'sse' | 'polling' | 'disconnected';
}

const MAX_LOG_LINES = 300;
const POLL_INTERVAL_MS = 3000;

const EMPTY: JobState = {
  jobId: '', status: 'queued', progress: 0, steps: [], logTail: [],
  startedAt: null, finishedAt: null, error: null, transport: 'disconnected',
};

const TERMINAL: JobStatus[] = ['completed', 'completed_with_warnings', 'failed', 'cancelled'];

export function useJobStream(jobId: string | null) {
  const [job, setJob] = useState<JobState>({ ...EMPTY, jobId: jobId ?? '' });
  const esRef   = useRef<EventSource | null>(null);
  const pollRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  // ── 폴링 폴백 ────────────────────────────────────────────────────────────
  const startPolling = useCallback((id: string) => {
    setJob((j) => ({ ...j, transport: 'polling' }));

    const tick = async () => {
      try {
        const res = await fetch(`/api/jobs/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        setJob((j) => ({ ...j, ...data, transport: 'polling' }));
        if (TERMINAL.includes(data.status)) cleanup();
      } catch { /* 네트워크 일시 오류는 무시하고 다음 tick */ }
    };

    void tick();
    pollRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
  }, [cleanup]);

  // ── SSE 연결 ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!jobId) return;
    cleanup();
    setJob({ ...EMPTY, jobId });

    let fellBack = false;

    try {
      const es = new EventSource(`/api/jobs/${jobId}/stream`);
      esRef.current = es;

      es.onopen = () => setJob((j) => ({ ...j, transport: 'sse' }));

      // 단계 상태 갱신
      es.addEventListener('step', (ev) => {
        const step: StepState = JSON.parse((ev as MessageEvent).data);
        setJob((j) => {
          const idx = j.steps.findIndex((s) => s.stepId === step.stepId);
          const steps = idx >= 0
            ? j.steps.map((s, i) => (i === idx ? { ...s, ...step } : s))
            : [...j.steps, step];

          const done = steps.filter((s) =>
            ['completed', 'warning', 'skipped'].includes(s.status)).length;

          return {
            ...j,
            steps,
            progress: steps.length ? Math.round((done / steps.length) * 100) : 0,
          };
        });
      });

      // 로그 라인
      es.addEventListener('log', (ev) => {
        const line = (ev as MessageEvent).data as string;
        setJob((j) => ({
          ...j,
          logTail: [...j.logTail, line].slice(-MAX_LOG_LINES),
        }));
      });

      // 전체 작업 상태
      es.addEventListener('status', (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        setJob((j) => ({ ...j, ...data }));
        if (TERMINAL.includes(data.status)) cleanup();
      });

      es.onerror = () => {
        // 종료된 작업이면 정상 종료, 아니면 폴링으로 강등
        es.close();
        esRef.current = null;
        if (!fellBack) {
          fellBack = true;
          startPolling(jobId);
        }
      };
    } catch {
      startPolling(jobId);
    }

    return cleanup;
  }, [jobId, cleanup, startPolling]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
  }, [jobId]);

  return { job, cancel };
}

// ── main.sh 단계 → 한글 라벨 매핑 ───────────────────────────────────────────
// 백엔드가 라벨을 안 보내줄 때 프론트에서 보완한다.
export const STEP_LABELS: Record<string, string> = {
  '00_input_validation': '입력 검증',
  '01_raw_qc':           'Raw QC (FastQC)',
  '02_preprocessing':    '전처리 / 트리밍',
  '03_alignment':        '정렬 (BWA-MEM)',
  '04_processing':       '중복 제거 + BQSR',
  '05_coverage_qc':      'Coverage QC',
  '06_variant_calling':  '변이 호출 (GATK)',
  '08_filtering':        '변이 필터링',
  '10_annotation':       '변이 주석',
  '11_intervar':         'ACMG 분류 (InterVar)',
  '99_finalization':     '결과 정리',
};

export function stepLabel(stepId: string): string {
  return STEP_LABELS[stepId] ?? stepId;
}
