// node --test scripts/storage-boundary.test.mjs  (npm run test:scripts)
// CLAUDE.md §20: 브라우저 저장소 접근은 지정된 모듈 안에서만 한다.
// .tsx(컴포넌트·페이지)에서 localStorage/sessionStorage를 부르면 실패한다(log 61).
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
// 허용 모듈: 저장소를 감싸는 곳은 여기뿐이다.
const ALLOWED = new Set(['lib/evalGrader.ts', 'features/eval-compare/api.ts'])
const CALL = /\b(localStorage|sessionStorage)\s*\./

function files(dir, prefix = '') {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name), `${prefix}${e.name}/`) : [`${prefix}${e.name}`],
  )
}

function codeLines(text) {
  // 주석 줄은 제외한다(설계 설명 속 단어는 호출이 아니다).
  return text.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
}

test('브라우저 저장소를 부르는 곳은 허용 모듈뿐이다', () => {
  const offenders = files(SRC)
    .filter((f) => /\.(ts|tsx)$/.test(f) && !ALLOWED.has(f))
    .filter((f) => codeLines(readFileSync(join(SRC, f), 'utf8')).some((l) => CALL.test(l)))
  assert.deepEqual(offenders, [])
})

test('허용 모듈은 실제로 존재한다(목록이 낡지 않게)', () => {
  const all = new Set(files(SRC))
  for (const f of ALLOWED) assert.ok(all.has(f), f)
})
