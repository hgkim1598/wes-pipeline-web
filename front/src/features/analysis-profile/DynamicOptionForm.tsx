/**
 * analysis-profile/DynamicOptionForm.tsx
 * ============================================================================
 * OptionField[] 스키마를 받아 폼을 자동 생성하는 컴포넌트.
 *
 * [핵심] 이 파일은 특정 분석에 대한 지식이 전혀 없다.
 *        "select면 드롭다운, slider면 슬라이더" 만 안다.
 *        따라서 PacBio나 somatic 옵션이 추가돼도 수정할 필요가 없다.
 *
 * 기능
 *  - ? 버튼 → 말머리 툴팁 (ResFinder 스타일)
 *  - advanced: true 옵션은 접이식 Accordion 안에 배치
 *  - dependsOn 조건 미충족 시 자동 숨김
 *  - 기본값 자동 주입 → 사용자는 그대로 두고 실행만 눌러도 됨
 * ============================================================================
 */

import { useMemo } from 'react';
import { HelpCircle } from 'lucide-react';
import type { OptionField } from './types';

import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Tooltip, TooltipContent, TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from '@/components/ui/accordion';

export type OptionValues = Record<string, string | number | boolean>;

interface Props {
  fields: OptionField[];
  values: OptionValues;
  onChange: (key: string, value: string | number | boolean) => void;
  disabled?: boolean;
}

// ── 말머리 툴팁 ─────────────────────────────────────────────────────────────
function HelpTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        aria-label="설명 보기"
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center
                   rounded-full bg-sky-50 text-sky-700 transition-colors
                   hover:bg-sky-100 focus:outline-none focus:ring-2
                   focus:ring-sky-400 dark:bg-sky-950 dark:text-sky-300"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs leading-relaxed">
        <p className="text-xs">{text}</p>
      </TooltipContent>
    </Tooltip>
  );
}

// ── 단일 필드 렌더러 ────────────────────────────────────────────────────────
function FieldRenderer({
  field, value, onChange, disabled,
}: {
  field: OptionField;
  value: string | number | boolean;
  onChange: (v: string | number | boolean) => void;
  disabled?: boolean;
}) {
  const labelBlock = (
    <div className="flex items-center gap-2">
      <Label htmlFor={field.key} className="text-sm font-medium">
        {field.label}
      </Label>
      <HelpTip text={field.help} />
    </div>
  );

  switch (field.type) {
    // ── 드롭다운 ────────────────────────────────────────────────────────────
    case 'select':
      return (
        <div className="flex items-center justify-between gap-4 py-2.5">
          {labelBlock}
          <Select
            value={String(value)}
            onValueChange={(nextValue) => {
              if (nextValue !== null) {
                onChange(nextValue)
              }
            }}
            disabled={disabled}
          >
            <SelectTrigger id={field.key} className="w-[260px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {field.choices?.map((c) => (
                <SelectItem key={c.value} value={c.value} disabled={c.disabled}>
                  <span>{c.label}</span>
                  {c.note && (
                    <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5
                                     text-[10px] font-medium text-emerald-700">
                      {c.note}
                    </span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );

    // ── 슬라이더 (스케일바) ─────────────────────────────────────────────────
    case 'slider':
      return (
        <div className="py-2.5">
          <div className="flex items-center justify-between gap-4">
            {labelBlock}
            <span className="min-w-[64px] rounded bg-slate-100 px-2 py-1
                             text-right font-mono text-xs text-slate-700
                             dark:bg-slate-800 dark:text-slate-200">
              {value}{field.unit ?? ''}
            </span>
          </div>
          <Slider
            id={field.key}
            value={[Number(value)]}
            min={field.min ?? 0}
            max={field.max ?? 100}
            step={field.step ?? 1}
            disabled={disabled}
            onValueChange={(v) => onChange(Array.isArray(v) ? v[0] : (v as number))}
            className="mt-3"
          />
          <div className="mt-1 flex justify-between text-[10px] text-slate-400">
            <span>{field.min}{field.unit}</span>
            <span>{field.max}{field.unit}</span>
          </div>
        </div>
      );

    // ── 숫자 입력 ───────────────────────────────────────────────────────────
    case 'number':
      return (
        <div className="flex items-center justify-between gap-4 py-2.5">
          {labelBlock}
          <div className="flex items-center gap-1.5">
            <Input
              id={field.key}
              type="number"
              value={Number(value)}
              min={field.min}
              max={field.max}
              step={field.step}
              disabled={disabled}
              onChange={(e) => onChange(Number(e.target.value))}
              className="w-[110px] text-right font-mono"
            />
            {field.unit && (
              <span className="text-xs text-slate-500">{field.unit}</span>
            )}
          </div>
        </div>
      );

    // ── 스위치 ──────────────────────────────────────────────────────────────
    case 'boolean':
      return (
        <div className="flex items-center justify-between gap-4 py-2.5">
          {labelBlock}
          <Switch
            id={field.key}
            checked={Boolean(value)}
            disabled={disabled}
            onCheckedChange={onChange}
          />
        </div>
      );

    // ── 자유 입력 ───────────────────────────────────────────────────────────
    case 'text':
    default:
      return (
        <div className="flex items-center justify-between gap-4 py-2.5">
          {labelBlock}
          <Input
            id={field.key}
            type="text"
            value={String(value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            className="w-[260px]"
          />
        </div>
      );
  }
}

// ── 메인 ────────────────────────────────────────────────────────────────────
export function DynamicOptionForm({ fields, values, onChange, disabled }: Props) {
  // dependsOn 조건 평가
  const visible = useMemo(
    () =>
      fields.filter((f) => {
        if (!f.dependsOn) return true;
        return values[f.dependsOn.key] === f.dependsOn.equals;
      }),
    [fields, values],
  );

  const basic = visible.filter((f) => !f.advanced);
  const advanced = visible.filter((f) => f.advanced);

  return (
    <div className="space-y-1">
      {/* 기본 옵션 — 항상 펼침 */}
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {basic.map((f) => (
          <FieldRenderer
            key={f.key}
            field={f}
            value={values[f.key] ?? f.default}
            onChange={(v) => onChange(f.key, v)}
            disabled={disabled}
          />
        ))}
      </div>

      {/* 고급 옵션 — 접이식 */}
      {advanced.length > 0 && (
        <Accordion className="mt-2">
          <AccordionItem value="advanced" className="border-t border-slate-100">
            <AccordionTrigger className="py-3 text-sm text-slate-600 hover:no-underline">
              <span className="flex items-center gap-2">
                고급 옵션
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px]
                                 font-medium text-slate-500">
                  {advanced.length}
                </span>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {advanced.map((f) => (
                  <FieldRenderer
                    key={f.key}
                    field={f}
                    value={values[f.key] ?? f.default}
                    onChange={(v) => onChange(f.key, v)}
                    disabled={disabled}
                  />
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}
    </div>
  );
}

/** 프로파일 전환 시 옵션 기본값을 초기화하는 헬퍼 */
export function buildDefaults(fields: OptionField[]): OptionValues {
  return Object.fromEntries(fields.map((f) => [f.key, f.default]));
}
