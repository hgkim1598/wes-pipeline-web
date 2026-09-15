/**
 * analysis-profile/ProfileSelector.tsx
 * ============================================================================
 * 계층형 분석 선택 UI.
 *
 *   변이 유형 → 플랫폼 → 분석 범위 → 프로파일 카드
 *
 * 각 단계는 레지스트리에서 "실제로 존재하는 값"만 보여준다.
 * 따라서 조합했는데 결과가 0개인 상황이 발생하지 않는다.
 *
 * 새 프로파일이 registry.ts 에 추가되면 이 화면은 자동으로 반영된다.
 * ============================================================================
 */

import { useState, useMemo, useEffect } from 'react';
import { Check, Lock, FlaskConical } from 'lucide-react';
import type { AnalysisProfile, VariantClass, Platform, Assay } from './types';
import { PROFILES, filterProfiles, availableValues } from './registry';
import { cn } from '@/lib/utils';

// ── 표시용 라벨 사전 ────────────────────────────────────────────────────────
// 새 값이 추가되면 여기에 한 줄만 넣으면 된다.
const LABELS = {
  variantClass: {
    germline: { title: 'Germline',  sub: '생식세포 변이 · 유전됨' },
    somatic:  { title: 'Somatic',   sub: '체세포 변이 · 종양 조직' },
  } as Record<VariantClass, { title: string; sub: string }>,

  platform: {
    illumina: { title: 'Illumina',  sub: 'Short-read (75~300bp)' },
    pacbio:   { title: 'PacBio',    sub: 'HiFi long-read' },
    ont:      { title: 'Nanopore',  sub: 'ONT long-read' },
  } as Record<Platform, { title: string; sub: string }>,

  assay: {
    wes:   { title: 'WES',   sub: '엑솜 전체' },
    wgs:   { title: 'WGS',   sub: '전장 유전체' },
    panel: { title: 'Panel', sub: '타깃 유전자' },
  } as Record<Assay, { title: string; sub: string }>,
};

const STATUS_BADGE = {
  available:     { text: '사용 가능', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  beta:          { text: 'Beta',      cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  'coming-soon': { text: '준비 중',   cls: 'bg-slate-100 text-slate-500 border-slate-200' },
};

// ── 축 선택 버튼 그룹 ───────────────────────────────────────────────────────
function AxisGroup<T extends string>({
  legend, values, labels, selected, onSelect,
}: {
  legend: string;
  values: T[];
  labels: Record<string, { title: string; sub: string }>;
  selected: T | null;
  onSelect: (v: T | null) => void;
}) {
  if (values.length === 0) return null;

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {legend}
      </legend>
      <div className="flex flex-wrap gap-2">
        {values.map((v) => {
          const meta = labels[v] ?? { title: v, sub: '' };
          const active = selected === v;
          return (
            <button
              key={v}
              type="button"
              onClick={() => onSelect(active ? null : v)}
              className={cn(
                'rounded-lg border px-3.5 py-2 text-left transition-all',
                'focus:outline-none focus:ring-2 focus:ring-teal-400',
                active
                  ? 'border-teal-500 bg-teal-50 shadow-sm dark:bg-teal-950'
                  : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900',
              )}
            >
              <div className={cn(
                'text-sm font-medium',
                active ? 'text-teal-800 dark:text-teal-200' : 'text-slate-700 dark:text-slate-200',
              )}>
                {meta.title}
              </div>
              {meta.sub && (
                <div className="text-[11px] text-slate-500">{meta.sub}</div>
              )}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

// ── 메인 ────────────────────────────────────────────────────────────────────
interface Props {
  value: string | null;
  onChange: (profileId: string) => void;
}

export function ProfileSelector({ value, onChange }: Props) {
  const [variantClass, setVariantClass] = useState<VariantClass | null>('germline');
  const [platform,     setPlatform]     = useState<Platform | null>('illumina');
  const [assay,        setAssay]        = useState<Assay | null>(null);

  // 상위 축이 바뀌면 하위 선택이 유효하지 않을 수 있으므로 정리
  useEffect(() => {
    const ok = availableValues('platform', { variantClass: variantClass ?? undefined });
    if (platform && !ok.includes(platform)) setPlatform(null);
  }, [variantClass]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ok = availableValues('assay', {
      variantClass: variantClass ?? undefined,
      platform:     platform ?? undefined,
    });
    if (assay && !ok.includes(assay)) setAssay(null);
  }, [variantClass, platform]); // eslint-disable-line react-hooks/exhaustive-deps

  // 각 축에서 선택 가능한 값 (상위 필터 반영)
  const variantOpts = useMemo(
    () => availableValues('variantClass') as VariantClass[],
    [],
  );
  const platformOpts = useMemo(
    () => availableValues('platform', { variantClass: variantClass ?? undefined }) as Platform[],
    [variantClass],
  );
  const assayOpts = useMemo(
    () => availableValues('assay', {
      variantClass: variantClass ?? undefined,
      platform:     platform ?? undefined,
    }) as Assay[],
    [variantClass, platform],
  );

  const matched = useMemo(
    () => filterProfiles({
      variantClass: variantClass ?? undefined,
      platform:     platform ?? undefined,
      assay:        assay ?? undefined,
    }),
    [variantClass, platform, assay],
  );

  return (
    <div className="space-y-6">
      {/* 축 선택 */}
      <div className="grid gap-5 sm:grid-cols-3">
        <AxisGroup
          legend="변이 유형"
          values={variantOpts}
          labels={LABELS.variantClass}
          selected={variantClass}
          onSelect={setVariantClass}
        />
        <AxisGroup
          legend="시퀀싱 플랫폼"
          values={platformOpts}
          labels={LABELS.platform}
          selected={platform}
          onSelect={setPlatform}
        />
        <AxisGroup
          legend="분석 범위"
          values={assayOpts}
          labels={LABELS.assay}
          selected={assay}
          onSelect={setAssay}
        />
      </div>

      {/* 프로파일 카드 목록 */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
            분석 프로파일
          </h3>
          <span className="text-xs text-slate-400">
            {matched.length}개 / 전체 {PROFILES.length}개
          </span>
        </div>

        {matched.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 p-6
                        text-center text-sm text-slate-500">
            조건에 맞는 분석이 없습니다. 위 필터를 조정해 주세요.
          </p>
        ) : (
          <div className="grid gap-2.5 md:grid-cols-2">
            {matched.map((p) => (
              <ProfileCard
                key={p.id}
                profile={p}
                selected={value === p.id}
                onSelect={() => p.status !== 'coming-soon' && onChange(p.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 프로파일 카드 ───────────────────────────────────────────────────────────
function ProfileCard({
  profile, selected, onSelect,
}: {
  profile: AnalysisProfile;
  selected: boolean;
  onSelect: () => void;
}) {
  const locked = profile.status === 'coming-soon';
  const badge  = STATUS_BADGE[profile.status];

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={locked}
      className={cn(
        'group relative rounded-xl border p-4 text-left transition-all',
        'focus:outline-none focus:ring-2 focus:ring-teal-400',
        locked   && 'cursor-not-allowed opacity-60',
        selected && 'border-teal-500 bg-teal-50/60 shadow-sm dark:bg-teal-950/40',
        !selected && !locked &&
          'border-slate-200 bg-white hover:border-teal-300 hover:shadow-sm dark:border-slate-700 dark:bg-slate-900',
        !selected && locked && 'border-slate-200 bg-slate-50 dark:bg-slate-900',
      )}
    >
      <div className="mb-1.5 flex items-start justify-between gap-3">
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {profile.label}
        </span>
        <span className={cn(
          'shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium',
          badge.cls,
        )}>
          {profile.status === 'beta' && <FlaskConical className="mr-0.5 inline h-2.5 w-2.5" />}
          {locked && <Lock className="mr-0.5 inline h-2.5 w-2.5" />}
          {badge.text}
        </span>
      </div>

      <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
        {profile.description}
      </p>

      {/* 대상 유전자 배지 */}
      {profile.targetGenes && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {profile.targetGenes.slice(0, 6).map((g) => (
            <span key={g}
              className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]
                         text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {g}
            </span>
          ))}
          {profile.targetGenes.length > 6 && (
            <span className="px-1 text-[10px] text-slate-400">
              +{profile.targetGenes.length - 6}
            </span>
          )}
        </div>
      )}

      {/* 메타 정보 */}
      <div className="mt-2.5 flex items-center gap-3 text-[10px] text-slate-400">
        <span>{profile.pipeline.assembly}</span>
        <span>·</span>
        <span>{profile.input.mode}</span>
        {profile.estimatedMinutes && (
          <>
            <span>·</span>
            <span>약 {Math.round(profile.estimatedMinutes / 60)}시간</span>
          </>
        )}
      </div>

      {selected && (
        <Check className="absolute right-3 top-3 h-4 w-4 text-teal-600" />
      )}
    </button>
  );
}
