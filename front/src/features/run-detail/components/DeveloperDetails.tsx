/*
  개발자 정보 — backend 원본 응답.

  첫 full 실행 동안에는 화면이 요약한 값이 아니라 서버가 실제로 보낸 것을 봐야
  한다. 그렇다고 raw JSON을 본문에 던지면 제품 화면이 디버그 콘솔이 된다. 그래서
  기본 접힌 <details> 하나에 격리한다.

  이 파일 하나가 그 영역의 전부다. 나중에 dev 전용으로 좁히거나 제거할 때
  호출부에서 이 component만 빼면 된다 — 다른 화면 코드에 raw 처리가 섞이지
  않게 하는 것이 이 격리의 목적이다.

  JSON.stringify를 그대로 쓴다. 접기 UI나 문법 강조를 만들 이유가 없다.
*/

export interface DeveloperDetailsSection {
  label: string
  /** 없으면(아직 조회 안 함) 그 절을 그리지 않는다. */
  value: unknown
}

export interface DeveloperDetailsProps {
  sections: DeveloperDetailsSection[]
}

export function DeveloperDetails({ sections }: DeveloperDetailsProps) {
  const present = sections.filter((section) => section.value !== undefined)
  if (present.length === 0) return null

  return (
    <details className="border-t border-border-subtle pt-4">
      <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
        개발자 정보 — 서버 원본 응답 {present.length}건
      </summary>
      <div className="mt-3 flex flex-col gap-4">
        {present.map((section) => (
          <div key={section.label} className="flex flex-col gap-1">
            <span className="font-mono text-caption text-text-muted">
              {section.label}
            </span>
            <pre className="overflow-x-auto rounded-sm bg-sunken p-3 font-mono text-caption text-text">
              {safeStringify(section.value)}
            </pre>
          </div>
        ))}
      </div>
    </details>
  )
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    // 순환 참조 등. 이 영역이 화면을 죽이면 안 된다.
    return '(직렬화할 수 없는 값)'
  }
}
