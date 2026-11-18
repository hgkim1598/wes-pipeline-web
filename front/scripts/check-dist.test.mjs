// node --test scripts/check-dist.test.mjs  (npm run test:scripts)
// check-dist 자체의 테스트. 합성 dist만 쓰고 저장소의 dist는 건드리지 않는다.
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, test } from 'node:test'

import { checkDist, defaultReactSource, internalsPattern } from './check-dist.mjs'

const root = mkdtempSync(join(tmpdir(), 'check-dist-'))
after(() => rmSync(root, { recursive: true, force: true }))

const REACT_SOURCE = 'var ReactSharedInternals = { H: null, A: null, T: null, S: null },\n  x = 1;'
const reactSource = join(root, 'react.production.js')
writeFileSync(reactSource, REACT_SOURCE)

let n = 0
function dist(files) {
  const dir = join(root, `dist${n++}`)
  mkdirSync(join(dir, 'assets'), { recursive: true })
  for (const [name, text] of Object.entries(files)) writeFileSync(join(dir, 'assets', name), text)
  return dir
}

const MINIFIED = 'var w={H:null,A:null,T:null,S:null},o=Object.prototype;'
const FORMATTED = 'var ReactSharedInternals$1 = {\n\tH: null,\n\tA: null,\n\tT: null,\n\tS: null\n};'

test('정상: 인스턴스 1개(압축)는 0', () => {
  assert.equal(checkDist(dist({ 'index.js': MINIFIED }), reactSource).code, 0)
})

test('정상: 압축하지 않은 형식도 1개로 센다', () => {
  assert.equal(checkDist(dist({ 'index.js': FORMATTED }), reactSource).code, 0)
})

test('중복: 한 파일에 2개면 1', () => {
  const r = checkDist(dist({ 'index.js': MINIFIED + MINIFIED }), reactSource)
  assert.equal(r.code, 1)
  assert.match(r.message, /2개/)
})

test('중복: 서로 다른 청크에 나뉘어 있어도 1', () => {
  const r = checkDist(dist({ 'a.js': MINIFIED, 'b.js': FORMATTED }), reactSource)
  assert.equal(r.code, 1)
  assert.deepEqual(Object.values(r.perFile), [1, 1])
})

test('검증 불가: React가 하나도 없으면 2 (정상으로 통과시키지 않음)', () => {
  assert.equal(checkDist(dist({ 'index.js': 'console.log(1)' }), reactSource).code, 2)
})

test('검증 불가: dist가 없거나 JS가 없으면 2', () => {
  assert.equal(checkDist(join(root, 'nope'), reactSource).code, 2)
  assert.equal(checkDist(dist({ 'a.css': 'body{}' }), reactSource).code, 2)
})

test('검증 불가: React 소스 모양이 바뀌면 2', () => {
  const changed = join(root, 'changed.js')
  writeFileSync(changed, 'var ReactSharedInternals = createInternals();')
  assert.equal(checkDist(dist({ 'index.js': MINIFIED }), changed).code, 2)
})

test('비슷하지만 다른 객체는 세지 않는다', () => {
  const r = checkDist(dist({ 'index.js': MINIFIED + 'var z={H:null,A:null,T:null};var y={H:null,A:null,T:null,S:null,X:null};' }), reactSource)
  assert.equal(r.code, 0)
})

test('설치된 React에서 실제로 패턴을 만들 수 있다', async () => {
  const { readFileSync } = await import('node:fs')
  assert.ok(internalsPattern(readFileSync(defaultReactSource(), 'utf8')))
})
