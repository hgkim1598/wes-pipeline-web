import { useEffect } from 'react'
import { ChevronLeft } from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { HelpTerm } from '@/components/ui/HelpTerm'
import { SectionHeader } from '@/components/ui/SectionHeader'

/*
  분석 준비 안내 — 사용자용.

  ── 왜 앱 안에 있는가 ───────────────────────────────────────────────────

  파이프라인의 실패 메시지는 `docs/MAIN_SH_COMPLETE_GUIDE.md의 "6. 실행
  방법과 CLI option"과 "29. Linux smoke test 절차" 장을 보세요`라고 안내한다.
  그것은 **저장소를 열 수 있는 사람에게만** 유효한 안내다. 웹에서 분석을
  제출한 사용자는 그 파일에 접근할 수 없고, 접근할 수 있어도 4,900줄짜리
  운영 문서에서 필요한 두 절을 찾아야 한다.

  ── 무엇을 옮겼고 무엇을 옮기지 않았는가 ────────────────────────────────

  근거: docs/MAIN_SH_COMPLETE_GUIDE.md 6.7(실행 전 준비물), 29.1~29.4
        (smoke test 절차), script/main.sh의 validate_tools()

  옮긴 것    무엇이 필요한가 · 왜 파이프라인이 설치하지 않는가 ·
             준비됐는지 확인하는 방법
  옮기지 않은 것  CLI option 전수 · config 필드 전수 · resume 동작 ·
             운영자용 배포 절차

  개발자용 상세는 맨 아래에 secondary reference로만 남긴다.
  이 페이지는 사용자 문서이지 운영 문서의 사본이 아니다.

  ── 도구 목록의 출처 ────────────────────────────────────────────────────

  script/main.sh의 validate_tools()가 요구하는 목록 그대로다. 손으로 고른
  것이 아니라 실패 조건과 같은 목록이어야 한다 — 다르면 "안내대로 했는데
  실패한다"가 된다.
*/

/** validate_tools()의 필수 목록 (script/main.sh). 조건부 도구는 아래 표에 따로 둔다. */
const REQUIRED_TOOLS = [
  { id: 'bwa', note: '참조 유전체 정렬' },
  { id: 'samtools', note: 'BAM 정리·검증' },
  { id: 'gatk', note: '중복 표시·품질 보정·변이 검출' },
  { id: 'bcftools', note: '변이 파일 처리' },
  { id: 'tabix', note: '유전체 파일 색인' },
  { id: 'bgzip', note: '유전체 파일 압축' },
  { id: 'mosdepth', note: '커버리지 측정' },
  { id: 'fastqc', note: '원본 품질 검사' },
]

/** 없어도 실행은 되지만 일부 산출물이 빠지는 것들. 근거: 6.7의 조건부 표. */
const OPTIONAL_TOOLS = [
  { name: 'multiqc', when: '항상 선택', effect: '통합 QC 리포트만 생략됩니다. 개별 FastQC 결과는 그대로 생성됩니다' },
  { name: 'fastp', when: 'trim_mode가 force일 때', effect: '이 경우에는 없으면 실행이 멈춥니다' },
  { name: 'Rscript', when: 'BQSR 진단 플롯을 켰을 때', effect: '진단 그래프만 생략됩니다' },
]

/*
  hash로 진입했을 때 해당 절로 이동시킨다.

  브라우저의 hash 스크롤은 문서를 새로 불러올 때만 동작한다. 실행 상세에서
  /help/setup#tools로 넘어오는 것은 클라이언트 라우팅이라 새 문서가 아니고,
  react-router는 hash를 스크롤로 해석하지 않는다. 그래서 실패 카드의
  "프로그램 준비 방법 보기"가 문서 맨 위에 떨어진다.

  scrollIntoView만 쓴다. focus()는 옮기지 않는다 — 사용자가 링크를 눌러
  스스로 온 것이고, 여기서 focus를 가로채면 키보드 사용자의 다음 Tab 위치가
  예상과 달라진다. 목차와 절 제목이 이미 위치를 말해준다.
*/
function useHashScroll(hash: string) {
  useEffect(() => {
    const id = hash.replace(/^#/, '')
    if (!id) return
    const target = document.getElementById(id)
    if (!target) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  }, [hash])
}

export function SetupGuidePage() {
  useHashScroll(useLocation().hash)

  return (
    <main className="mx-auto flex max-w-content flex-col gap-10 px-6 py-8">
      <div className="flex flex-col gap-4 border-b border-border pb-6">
        <Link
          to="/runs"
          className="inline-flex min-h-6 items-center gap-1 self-start text-small text-text-muted no-underline hover:text-text hover:underline"
        >
          <ChevronLeft size={12} strokeWidth={1.5} aria-hidden="true" />
          실행 목록
        </Link>
        <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
          분석 준비 안내
        </h1>
        <p className="max-w-prose text-body text-text">
          이 파이프라인은 분석에 필요한 프로그램이나 참조 데이터를{' '}
          <strong className="font-medium text-text-strong">
            스스로 설치하지 않습니다
          </strong>
          . 실행 전에 갖춰져 있는지 확인만 하고, 준비되지 않았으면 분석을
          시작하지 않습니다. 잘못된 준비 상태로 몇 시간을 쓴 뒤 결과가 어긋나는
          것보다 낫기 때문입니다.
        </p>
      </div>

      {/* 1. 무엇이 필요한가 */}
      <section id="overview" className="flex flex-col gap-4 scroll-mt-6">
        <SectionHeader title="분석 실행 전에 필요한 것" />
        <ol className="flex flex-col gap-2">
          {[
            '분석 프로그램 — 정렬·변이 검출 등을 실제로 수행하는 도구',
            '참조 데이터 — 비교 기준이 되는 유전체와 관련 파일',
            '입력 FASTQ — 분석할 시퀀싱 결과 (웹에서 업로드)',
          ].map((item, index) => (
            <li key={item} className="flex gap-3 text-body text-text">
              <span className="font-mono text-data text-text-muted">
                {index + 1}
              </span>
              <span className="max-w-prose">{item}</span>
            </li>
          ))}
        </ol>
        <p className="max-w-prose text-small text-text-muted">
          이 중 1번과 2번은 서버에 한 번 준비해 두면 이후 실행에서 계속
          사용합니다. 매번 준비할 필요는 없습니다.
        </p>
      </section>

      {/* 2. 필요한 프로그램 */}
      <section id="tools" className="flex flex-col gap-4 scroll-mt-6">
        <SectionHeader
          title="필요한 분석 프로그램"
          meta={`${REQUIRED_TOOLS.length}개`}
        />
        <p className="max-w-prose text-body text-text">
          아래 프로그램이 모두 <HelpTerm termId="PATH" mono>PATH</HelpTerm>에
          있어야 합니다. 하나라도 없으면 사전 점검에서 멈춥니다.
        </p>
        <dl className="flex flex-col">
          {REQUIRED_TOOLS.map((tool) => (
            <div
              key={tool.id}
              className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border-subtle py-2 last:border-b-0"
            >
              <dt className="w-32 flex-none">
                <HelpTerm termId={tool.id} mono />
              </dt>
              <dd className="min-w-0 flex-1 text-small text-text">
                {tool.note}
              </dd>
            </div>
          ))}
        </dl>
        <p className="max-w-prose text-small text-text-muted">
          이 밖에 <code className="font-mono text-data">awk</code>·
          <code className="font-mono text-data">sed</code>·
          <code className="font-mono text-data">grep</code> 같은 기본 명령과
          Python도 필요하지만, 리눅스 서버에는 대개 이미 있습니다.
        </p>

        <div className="flex flex-col gap-2 border-t border-border-subtle pt-4">
          <h3 className="text-h3 font-semibold text-text-strong">
            없어도 실행되는 것
          </h3>
          <dl className="flex flex-col">
            {OPTIONAL_TOOLS.map((tool) => (
              <div
                key={tool.name}
                className="flex flex-col gap-0.5 border-b border-border-subtle py-2 last:border-b-0"
              >
                <dt className="flex flex-wrap items-baseline gap-x-2">
                  <code className="font-mono text-data text-text-strong">
                    {tool.name}
                  </code>
                  <span className="text-caption text-text-muted">
                    {tool.when}
                  </span>
                </dt>
                <dd className="max-w-prose text-small text-text">
                  {tool.effect}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* 3. PATH */}
      <section id="path" className="flex flex-col gap-4 scroll-mt-6">
        <SectionHeader title="PATH가 무엇인가" />
        <p className="max-w-prose text-body text-text">
          운영체제가 명령어를 찾는 디렉터리 목록입니다. 프로그램을 설치했더라도
          PATH에 등록되지 않았다면 파이프라인은 그것을 찾지 못하고 &ldquo;없다&rdquo;고
          판단합니다.
        </p>
        <p className="max-w-prose text-body text-text">
          conda 같은 환경 관리 도구를 쓴다면, 파이프라인을 실행하는 셸에서 해당
          환경이 활성화돼 있어야 합니다. 설치한 셸과 실행하는 셸이 다르면 같은
          서버에서도 찾지 못할 수 있습니다.
        </p>
      </section>

      {/* 4. 참조 데이터 */}
      <section id="resources" className="flex flex-col gap-4 scroll-mt-6">
        <SectionHeader title="참조 데이터 준비" />
        <p className="max-w-prose text-body text-text">
          <HelpTerm termId="reference-genome">참조 유전체</HelpTerm>는 내
          데이터의 어느 지점이 다른지를 판단하는 기준입니다. 서열 파일 하나만으로는
          부족하고, 함께 쓰는 파일들이 서로 맞아야 합니다.
        </p>
        <ul className="flex flex-col gap-2">
          {[
            '참조 유전체 서열과 그 색인 파일',
            '정렬 도구가 쓰는 별도 색인',
            '분석 대상 영역을 지정하는 target 파일',
            '품질 보정에 쓰는 known-sites 파일과 색인',
          ].map((item) => (
            <li
              key={item}
              className="max-w-prose text-body text-text before:mr-2 before:text-text-muted before:content-['·']"
            >
              {item}
            </li>
          ))}
        </ul>
        <p className="max-w-prose text-body text-text">
          사전 점검은 이 파일들이 서로 맞는지 — 염색체 이름과 길이가 일치하는지,
          색인이 있는지 — 를 확인합니다. 맞지 않으면 결과가 조용히 어긋날 수
          있으므로 분석을 시작하지 않습니다.
        </p>
        <p className="max-w-prose text-small text-text-muted">
          이 준비는 서버 관리자가 한 번 해 두는 작업입니다. 웹에서 분석을
          제출하는 사용자가 매번 준비하지 않습니다.
        </p>
      </section>

      {/* 5·6. 확인 방법 */}
      <section id="check" className="flex flex-col gap-4 scroll-mt-6">
        <SectionHeader title="준비가 됐는지 확인하는 방법" />
        <p className="max-w-prose text-body text-text">
          <HelpTerm termId="precheck">사전 점검</HelpTerm> 모드로 실행하면 실제
          분석을 하지 않고 준비 상태만 확인합니다. 입력 파일·참조 데이터·필요한
          프로그램을 모두 검사하고, 통과하면{' '}
          <HelpTerm termId="BAM" mono>BAM</HelpTerm>이나{' '}
          <HelpTerm termId="VCF" mono>VCF</HelpTerm> 같은 산출물 없이 끝납니다.
        </p>
        <p className="max-w-prose text-body text-text">
          몇 시간짜리 전체 분석을 돌리기 전에 이것부터 통과시키는 것이 순서입니다.
          실패하면 이 실행의 상세 화면에서 어느 항목이 걸렸는지 볼 수 있습니다.
        </p>

        <div className="flex flex-col gap-2 border-t border-border-subtle pt-4">
          <h3 className="text-h3 font-semibold text-text-strong">
            서버에서 직접 확인하는 경우
          </h3>
          <p className="max-w-prose text-body text-text">
            서버에 접근할 수 있다면, 웹에서 제출하기 전에 프로그램이 보이는지
            먼저 확인할 수 있습니다. 아래는 각 도구의 위치를 출력하고 없는 것을
            표시합니다.
          </p>
          <pre className="overflow-x-auto rounded-sm bg-sunken p-3 font-mono text-caption text-text">
{`for t in ${REQUIRED_TOOLS.map((tool) => tool.id).join(' ')}; do
  printf '%-10s %s\\n' "$t" "$(command -v $t || echo MISSING)"
done`}
          </pre>
          <p className="max-w-prose text-small text-text-muted">
            <code className="font-mono text-data">MISSING</code>으로 나오는
            항목이 사전 점검에서 걸리는 항목과 같습니다.
          </p>
        </div>
      </section>

      <div className="flex flex-col gap-2 border-t border-border pt-6">
        <p className="text-caption text-text-muted">
          이 페이지는 서버 준비에 필요한 범위만 다룹니다. CLI option·config
          필드·배포 절차 등 운영자용 상세는 저장소의{' '}
          <code className="font-mono text-data">
            docs/MAIN_SH_COMPLETE_GUIDE.md
          </code>
          에 있습니다.
        </p>
        <p className="text-caption text-text-muted">
          연구·교육 목적 전용 — 진단 결과가 아닙니다
        </p>
      </div>
    </main>
  )
}
