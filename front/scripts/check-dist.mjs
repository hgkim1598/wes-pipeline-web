#!/usr/bin/env node
/*
  check-dist — production 빌드에 React 인스턴스가 정확히 1개인지 검사한다.

  왜 필요한가 (2026-11-17)
    `tsc -b && vite build`가 exit 0으로 끝났는데 결과물의 화면이 통째로 비는
    빌드가 14회 중 2회 나왔다. 번들 안에 React가 두 번 들어가 있었고, 두 번째
    사본의 훅 dispatcher가 null이라 렌더링 첫 단계에서
    "Cannot read properties of null (reading 'useContext')"로 죽었다.
    원인은 빌드를 시작한 작업 폴더의 드라이브 문자 대소문자(c:\ vs C:\)였고
    vite.config.ts의 경로 정규화(fromHere)로 고쳤다(개발판단기록 23장).
    이 검사는 그 수정과 별개로 남겨 두는 **2차 방어**다: 같은 종류의 중복이
    다른 경로로 다시 생겨도 그 결과물을 시연에 쓰지 못하게 막는다.

  무엇을 세나
    React의 공유 내부 객체를 만드는 초기화 리터럴이다. React 19.2의
    react.production.js에는 `var ReactSharedInternals = { H: null, A: null,
    T: null, S: null }`가 한 번 있고, 훅 호출(useState, useContext …)은 모두 이
    객체의 H(dispatcher)를 거친다. 리터럴이 둘이면 내부 객체도 둘이고, 렌더러가
    채우지 않은 쪽의 훅은 null을 읽는다. 그래서 개수가 곧 고장의 원인과 같다.

    검토했다가 쓰지 않은 지표 (2026-11-17 실험)
      - `__CLIENT_INTERNALS_..._UPGRADE =` 대입 횟수: 트리 셰이킹된 두 번째
        사본에는 이 export가 빠져서 중복 빌드에서도 1로 나왔다(놓침).
      - `Symbol.for("react.transitional.element")` 개수: react와 jsx-runtime이
        같은 문자열을 쓰므로 정상값이 3이고, 무엇이 중복됐느냐에 따라 4나 5가
        된다. 기준값이 번들 구성에 따라 바뀌어 판정 기준으로 쓰기 어렵다.

  패턴은 코드에 적지 않고 설치된 React에서 읽는다
    React가 바뀌어 초기화 모양이 달라지면 검사가 조용히 0을 세는 대신
    "검증할 수 없음"(exit 2)으로 멈춘다. 그때는 이 파일을 다시 검토한다.

  종료 코드
    0  인스턴스 1개
    1  인스턴스 2개 이상 — 이 dist를 쓰지 말고 다시 빌드한다
    2  검증할 수 없음(dist 없음, JS 없음, 패턴을 찾지 못함, 0개)

  사용
    node scripts/check-dist.mjs [distDir] [--react-source <react.production.js>]
    npm run build가 끝나면 postbuild로 자동 실행된다.
*/

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const FRONT = resolve(HERE, '..')

/** 설치된 react.production.js의 경로. */
export function defaultReactSource() {
  const require = createRequire(join(FRONT, 'package.json'))
  return join(dirname(require.resolve('react/package.json')), 'cjs', 'react.production.js')
}

/**
 * React 소스에서 공유 내부 객체 초기화 리터럴을 찾아, 공백·줄바꿈에 상관없이
 * 번들에서 같은 리터럴을 찾는 정규식을 만든다. 찾지 못하면 null.
 */
export function internalsPattern(reactSource) {
  const m = /ReactSharedInternals\s*=\s*\{([^{}]*)\}/.exec(reactSource)
  if (!m) return null
  const pairs = m[1]
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => p.split(':').map((s) => s.trim()))
  if (pairs.length === 0 || pairs.some((kv) => kv.length !== 2 || !/^\w+$/.test(kv[0]) || kv[1] !== 'null')) {
    return null
  }
  const body = pairs.map(([k]) => `${k}\\s*:\\s*null`).join('\\s*,\\s*')
  return new RegExp(`\\{\\s*${body}\\s*\\}`, 'g')
}

function jsFiles(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...jsFiles(p))
    else if (/\.(m?js)$/.test(name)) out.push(p)
  }
  return out
}

/** @returns {{ code: 0|1|2, message: string, perFile: Record<string, number> }} */
export function checkDist(distDir, reactSourcePath = defaultReactSource()) {
  const perFile = {}
  if (!existsSync(distDir)) {
    return { code: 2, message: `dist 폴더가 없습니다: ${distDir}`, perFile }
  }
  let reactSource
  try {
    reactSource = readFileSync(reactSourcePath, 'utf8')
  } catch {
    return { code: 2, message: `React 소스를 읽지 못했습니다: ${reactSourcePath}`, perFile }
  }
  const pattern = internalsPattern(reactSource)
  if (!pattern) {
    return {
      code: 2,
      message:
        'React 소스에서 공유 내부 객체 초기화(ReactSharedInternals = {...})를 찾지 못했습니다. ' +
        'React 버전이 바뀌었을 수 있습니다. scripts/check-dist.mjs를 다시 검토하세요.',
      perFile,
    }
  }
  const files = jsFiles(distDir)
  if (files.length === 0) {
    return { code: 2, message: `JS 파일이 없습니다: ${distDir}`, perFile }
  }
  let total = 0
  for (const f of files) {
    const n = (readFileSync(f, 'utf8').match(pattern) || []).length
    if (n > 0) perFile[relative(distDir, f).replace(/\\/g, '/')] = n
    total += n
  }
  if (total === 1) {
    return { code: 0, message: 'React 인스턴스 1개 — 정상', perFile }
  }
  if (total === 0) {
    return {
      code: 2,
      message:
        'React 공유 내부 객체를 번들에서 찾지 못했습니다. React가 external로 빠졌거나 ' +
        '번들 형식이 바뀌었을 수 있습니다. 이 결과로는 정상 여부를 판단할 수 없습니다.',
      perFile,
    }
  }
  return {
    code: 1,
    message:
      `React 인스턴스가 ${total}개 묶였습니다. 이 빌드는 화면이 하얗게 빌 수 있으니 ` +
      '시연에 쓰지 말고 다시 빌드하세요. 반복되면 이 dist를 지우지 말고 보존해 원인 조사에 쓰세요.',
    perFile,
  }
}

function main(argv) {
  let dist = join(FRONT, 'dist')
  let reactSource
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--react-source') reactSource = argv[++i]
    else dist = resolve(argv[i])
  }
  const result = checkDist(dist, reactSource ?? defaultReactSource())
  const stream = result.code === 0 ? process.stdout : process.stderr
  stream.write(`[check-dist] ${result.message}\n`)
  for (const [file, n] of Object.entries(result.perFile)) {
    stream.write(`[check-dist]   ${file}: ${n}\n`)
  }
  return result.code
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2))
}
