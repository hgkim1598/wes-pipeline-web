// node --test scripts/breakpoints.test.mjs  (npm run test:scripts에 포함)
// 반응형 접두어가 tokens.css에 정의된 구간만 쓰는가.
//
// tokens.css는 Tailwind 기본 구간을 지우고(--breakpoint-*: initial) md·lg·xl만
// 다시 정의한다. 정의되지 않은 접두어(예: sm:)는 Tailwind가 조용히 무시해서
// tsc·oxlint·build 모두 통과하는데 화면에서는 아무 일도 일어나지 않는다.
// 2026-11-23 모바일 작업에서 sm:으로 쓴 좁은 화면 규칙이 넓은 화면에도 그대로
// 적용될 뻔했다(개발판단기록 54장). 파일을 읽기만 한다.
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const TAILWIND_DEFAULTS = ['sm', 'md', 'lg', 'xl', '2xl']

function defined() {
  const css = readFileSync(join(SRC, 'styles', 'tokens.css'), 'utf8')
  const names = [...css.matchAll(/--breakpoint-([a-z0-9]+)\s*:/g)].map((m) => m[1])
  return new Set(names)
}

function* sources(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* sources(path)
    else if (/\.(tsx|ts)$/.test(name)) yield path
  }
}

test('tokens.css가 기본 구간을 지우고 쓰는 구간만 다시 정의한다', () => {
  const css = readFileSync(join(SRC, 'styles', 'tokens.css'), 'utf8')
  assert.match(css, /--breakpoint-\*:\s*initial/)
  assert.ok(defined().size > 0)
})

test('className에 정의되지 않은 반응형 접두어가 없다', () => {
  const ok = defined()
  const missing = TAILWIND_DEFAULTS.filter((bp) => !ok.has(bp))
  const pattern = new RegExp(`(?<![\\w-])(?:max-)?(${missing.join('|')}):[a-z\\[]`, 'g')
  const found = []
  for (const file of sources(SRC)) {
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, i) => {
      // class 문자열 안의 접두어만 본다(객체 키 `sm: 'text-small'` 같은 것은 제외).
      for (const m of line.matchAll(pattern)) {
        found.push(`${file.slice(SRC.length)}:${i + 1} ${m[0]}`)
      }
    })
  }
  assert.deepEqual(found, [], `정의되지 않은 구간(${missing.join(', ')})을 쓴 곳:\n${found.join('\n')}`)
})
