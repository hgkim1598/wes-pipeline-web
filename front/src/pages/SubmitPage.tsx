import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { ProfileSelector } from '@/features/analysis-profile/ProfileSelector';
import {
  DynamicOptionForm,
  buildDefaults,
} from '@/features/analysis-profile/DynamicOptionForm';
import { UploadZone } from '@/features/upload/UploadZone';
import { useChunkedUpload } from '@/features/upload/useChunkedUpload';
import { getProfile } from '@/features/analysis-profile/registry';
import type { BatchAssignmentResult } from '@/features/upload/pairDetection';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import type { OptionValues } from '@/features/analysis-profile/DynamicOptionForm';

export default function SubmitPage() {
  const navigate = useNavigate();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [options, setOptions] = useState<OptionValues>({});
  const [batch, setBatch] = useState<BatchAssignmentResult>({ groups: [], problemFiles: [] });
  const [submitting, setSubmitting] = useState(false);
  const [progressLabel, setProgressLabel] = useState<string | null>(null);

  const { state: uploadState, upload } = useChunkedUpload();

  const profile = selectedId ? getProfile(selectedId) : undefined;

  function handleSelectProfile(id: string) {
    setSelectedId(id);
    const p = getProfile(id);
    if (p) setOptions(buildDefaults(p.options));
    setBatch({ groups: [], problemFiles: [] });
  }

  function handleOptionChange(key: string, value: string | number | boolean) {
    setOptions((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit() {
    if (!profile || batch.groups.length === 0) return;
    setSubmitting(true);

    try {
      // ── 1) 샘플별 파일을 실제로 업로드 ──────────────────────────────────
      const totalFiles = batch.groups.reduce((sum, g) => sum + Object.keys(g.slots).length, 0);
      let fileIndex = 0;

      const samples: { sampleId: string; files: Record<string, string> }[] = [];

      for (const group of batch.groups) {
        const filePaths: Record<string, string> = {};

        for (const [slotId, file] of Object.entries(group.slots)) {
          fileIndex++;
          setProgressLabel(`업로드 중 (${fileIndex}/${totalFiles}): ${file.name}`);

          const path = await upload(file, { sampleId: group.sampleId, slotId });
          if (!path) throw new Error(`${file.name} 업로드에 실패했습니다`);

          filePaths[slotId] = path;
        }

        samples.push({ sampleId: group.sampleId, files: filePaths });
      }

      // ── 2) 업로드된 경로를 포함해 분석 작업 생성 ────────────────────────
      setProgressLabel('분석 작업 생성 중...');

      const captureKitId =
        typeof options.capture_kit_id === 'string' ? options.capture_kit_id : undefined;

      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profileId: profile.id, captureKitId, options, samples }),
      });
      if (!res.ok) throw new Error(`제출 실패 (${res.status})`);
      const { jobId } = await res.json();

      navigate(`/jobs/${jobId}`, { state: { profileLabel: profile.label } });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '분석 제출 중 오류가 발생했습니다');
    } finally {
      setSubmitting(false);
      setProgressLabel(null);
    }
  }

  const readyCount = batch.groups.length;

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-8">
      <div>
        <h1 className="mb-6 text-xl font-semibold">분석 선택</h1>
        <ProfileSelector value={selectedId} onChange={handleSelectProfile} />
      </div>

      {profile && (
        <div
          className="rounded-xl border border-slate-200 bg-white p-6
                        dark:border-slate-700 dark:bg-slate-900"
        >
          <h2 className="mb-1 text-base font-semibold">파일 업로드</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            여러 샘플을 한 번에 올릴 수 있습니다. 파일명으로 자동 구분됩니다.
          </p>
          <UploadZone spec={profile.input} onChange={setBatch} />
        </div>
      )}

      {profile && (
        <div
          className="rounded-xl border border-slate-200 bg-white p-6
                        dark:border-slate-700 dark:bg-slate-900"
        >
          <h2 className="mb-1 text-base font-semibold">분석 옵션</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            기본값이 채워져 있어 바로 실행해도 됩니다. (업로드된 모든 샘플에 동일하게
            적용됩니다)
          </p>

          <DynamicOptionForm
            fields={profile.options}
            values={options}
            onChange={handleOptionChange}
            disabled={submitting}
          />

          {submitting && progressLabel && (
            <div className="mt-4 space-y-1.5">
              <p className="text-xs text-slate-500">{progressLabel}</p>
              <Progress value={uploadState.progress} />
            </div>
          )}

          <div
            className="mt-6 flex items-center justify-between border-t
                          border-slate-100 pt-4 dark:border-slate-800"
          >
            <span className="text-xs text-muted-foreground">
              {readyCount > 0
                ? `${readyCount}개 샘플 분석 준비 완료`
                : '분석할 샘플을 업로드해 주세요'}
            </span>
            <Button disabled={readyCount === 0 || submitting} onClick={handleSubmit}>
              {submitting
                ? '처리 중...'
                : `분석 시작${readyCount > 0 ? ` (${readyCount}개 샘플)` : ''}`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
