# CI (GitHub Actions)

PR을 열거나 PR 브랜치에 추가로 push하면 GitHub가 직접 검사를 실행합니다.
결과는 PR 화면 아래쪽 **Checks**에 나타납니다.
AI나 개발자가 "테스트를 돌렸다"고 말하는 것과 별개로 확인할 수 있는 기록입니다.

설정 파일은 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) 하나입니다.

## 언제 실행되는가

| 이벤트 | 대상 |
|---|---|
| `pull_request` | `main`으로 향하는 PR을 열 때, 그리고 그 PR 브랜치에 push할 때마다 |
| `push` | `main`에 push(병합 포함)될 때 |
| `workflow_dispatch` | Actions 탭에서 수동 실행 |

같은 PR에 새 push가 오면 이전 실행은 취소됩니다(`concurrency`).

## 무엇을 검사하는가

두 job이 동시에 실행됩니다. 둘 다 GitHub-hosted `ubuntu-24.04`에서 실행됩니다.

### Backend (pytest)

- 이력 전체를 checkout합니다(`fetch-depth: 0`). `evals/test_ab_compare.py`가 A/B 프로토콜의 기준 커밋을 `git archive`로 읽기 때문입니다. 기본값(depth 1)으로는 이 테스트가 실패합니다.
- Python 3.12에 `backend/requirements-dev.txt`를 설치합니다(pip 캐시 사용).
- 모델 자격증명(`ANTHROPIC_API_KEY` 등)이 환경에 없는지 확인합니다. 하나라도 있으면 실패합니다.
- `python -m pytest app/tests -ra`: 앱 테스트를 실행합니다.
- `python -m pytest evals -ra`: 평가 도구 테스트를 실행합니다(채점기, A/B 실행 계약, 기록된 답 검사). 모델 호출은 없습니다.
  - 이 중 `test_the_default_protocol_explains_every_arm_difference`는 기본 A/B 프로토콜의 두 arm 사이에서 다른 파일이 모두 분류돼 있는지 확인합니다. v4부터 두 arm 모두 커밋이라 제품 코드 수정으로는 실패하지 않습니다. 실패하면 메시지에 해당 파일이 모두 나옵니다. 검사를 건너뛰거나 파일을 제외하지 말고 `backend/evals/ab_compare/protocols/README.md`의 절차를 따르세요.

`-ra`를 붙였기 때문에 로그 끝에 skip된 테스트와 그 이유가 함께 출력됩니다.

### Frontend (lint, types, tests, build)

- Node 22.16.0을 쓰고, `npm ci`로 `front/package-lock.json`에 적힌 버전 그대로 설치합니다(npm 캐시 사용).
- 검사 순서:
  1. `npm run lint` (oxlint)
  2. `npm run typecheck` (`tsc -b --force`)
  3. 스크립트 테스트 10종(`test:scripts`는 check-dist와 반응형 구간 검사 포함): `test:scripts`, `test:trace`, `test:placement`, `test:docview`, `test:workspace`, `test:facts`, `test:compare`, `test:policy`, `test:copy`, `test:entry`
  4. `npm run build`: `tsc -b`와 `vite build`를 실행한 뒤 postbuild로 `check-dist`를 실행합니다.

## 안전 경계

CI는 다음을 하지 않습니다.

- **실제 Claude 호출 없음.**
  - workflow는 secret을 하나도 참조하지 않으므로, runner에 자격증명이 전달되지 않습니다.
  - `backend/conftest.py`가 모든 테스트보다 먼저 `real_cli_guard`를 설치합니다. 이 guard는 `claude`라는 이름의 프로그램 실행을 거부하고, 외부 주소로 나가는 소켓 연결도 거부합니다. 시도하면 테스트가 실패합니다.
- **실제 WES 파이프라인 실행 없음.**
  - `script/main.sh`를 실행하는 단계가 없습니다.
  - 일부 테스트는 `main.sh` 안의 짧은 헬퍼나 Python 블록만 꺼내, 가짜 입력으로 실행합니다. `samtools`도 셸 함수로 만든 가짜를 씁니다.
- **유전체 데이터 다운로드나 분석 없음.**
- **원본 Run, DB, capture, 로컬 설정 접근 없음.** `runs/`, `uploads/`, `config/local/`, `.capture_*`, `backend/data/*.db`, `backend/evals/ab_store/`는 모두 gitignore 대상이라 checkout에 들어 있지 않습니다.
- 권한은 `contents: read`뿐이고, checkout도 자격증명을 남기지 않습니다(`persist-credentials: false`).
- action은 커밋 SHA로 고정했습니다. 버전 태그는 주석에 적어 두었습니다.

## CI에서 실행되지 않는(skip되는) 검사

아래 테스트는 git에 없는 로컬 자료가 있어야 의미가 있습니다. 그래서 자료가 없으면 이유를 남기고 skip하도록 이미 작성되어 있습니다. CI에서는 skip되고, 개발자 PC에서만 실행됩니다.

| 테스트 | 필요한 자료 | 이유 |
|---|---|---|
| `evals/test_real_runs.py`, `test_rejected_output.py`, `test_recorded_answers_pass_claims.py` 일부 | 실제 Run capture와 보관본(`.capture_*`, archive) | 실제 샘플 데이터라 git에 넣지 않음 |
| `evals/test_retrieval_compare.py` | 비공개 고정 질의 세트 | 미공개 자료 |
| `app/tests/test_resource_bundle_*` 일부 | 실제 Run 원본과 로컬 등록 | 실제 샘플 데이터 |
| `test_statement_kinds.py`의 `docPassages/` 고아 검사 | 로컬 문서 발췌 `config/knowledge/wes_doc_passages.json` | 미공개 문서 내용. 공개 checkout에는 빈 공개 발췌만 있으므로 이 부분만 검사에서 뺌. 나머지 분류 검사는 CI에서도 실행됨 |

CI가 통과했다고 해서 위 항목까지 검증된 것은 아닙니다. 해당 변경은 로컬 실행 결과로 따로 확인합니다.

## 로컬에서 같은 검사를 실행하는 법

각 블록은 저장소 루트에서 시작합니다.

```bash
# Backend (Windows)
cd backend
.venv/Scripts/python.exe -m pytest app/tests -ra
.venv/Scripts/python.exe -m pytest evals -ra
cd ..

# Frontend
cd front
npm ci
npm run lint && npm run typecheck
npm run test:scripts && npm run test:trace && npm run test:placement && npm run test:docview \
  && npm run test:workspace && npm run test:facts && npm run test:compare && npm run test:policy \
  && npm run test:copy && npm run test:entry
npm run build
```

## 실패했을 때

1. PR의 **Checks**에서 실패한 job(Backend 또는 Frontend)을 엽니다.
2. 빨간 단계를 펼칩니다. 단계 이름이 검사 이름입니다.
3. pytest라면 로그 끝의 `short test summary info`에 실패한 테스트 이름이 나옵니다.

## 유지보수

- 프론트 스크립트 테스트를 추가하면 `ci.yml`의 "Script tests" 단계에도 한 줄 추가합니다.
- action 버전을 올릴 때는 새 태그의 커밋 SHA로 바꾸고, 주석의 버전도 함께 고칩니다.
- Python은 `3.12`까지만 고정했습니다. 그래서 runner가 제공하는 최신 3.12.x patch 버전이 쓰이고, 로컬(3.12.3)과 다를 수 있습니다.
- Python 간접 의존성은 고정되어 있지 않습니다. `fastapi`, `mcp`는 정확히 고정되어 있고 `pytest`는 `8.*`입니다. 그래서 같은 커밋이라도 시간이 지나면 설치되는 하위 패키지 버전이 달라질 수 있습니다. 재현성이 문제가 되면 Linux에서 만든 constraints 파일을 추가합니다. Windows에서 만든 `pip freeze`에는 `pywin32` 같은 Windows 전용 패키지가 들어가므로 그대로 쓸 수 없습니다.
