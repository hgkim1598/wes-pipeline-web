# WES Backend

FastAPI로 만든 Backend입니다.
Frontend의 요청을 받아, 이 저장소의 실제 WES 분석 파이프라인인 `script/main.sh`를 실행하고
그 결과 상태를 다시 Frontend에 돌려줍니다.

> **중요:** 이 Backend는 WES 분석 로직을 Python으로 다시 구현하지 않습니다.
> 분석은 전부 `script/main.sh`가 하고, Backend는 그것을 **실행시키고 상태를 읽어 전달**할 뿐입니다.

## 전체 구조

```
Frontend (브라우저)
   ↓  API 요청
FastAPI
   ↓
SQLite / Job
   ↓
Worker
   ↓
PipelineExecutor
   ↓
script/main.sh   ← 실제 분석은 여기서 일어남
```

| 구성요소 | 하는 일 |
|---|---|
| **FastAPI** | API 요청을 접수하고 응답을 돌려주는 웹 서버 |
| **SQLite** | Job의 상태와 실행 정보를 저장하는 아주 작은 파일 기반 데이터베이스 |
| **Job** | 사용자가 요청한 분석 작업 한 건 |
| **Worker** | 대기 중인 Job을 실제로 실행하는 Backend 내부 담당자 (백그라운드 스레드 1개) |
| **PipelineExecutor** | Worker의 지시로 `main.sh`를 별도 프로세스(subprocess)로 띄우는 담당자 |

## 왜 FastAPI와 Worker를 나눴는가

WES 분석은 실제 데이터에서 몇 시간이 걸릴 수 있습니다.
그런데 웹 요청은 몇 초 안에 응답해야 합니다.

그래서 역할을 나눴습니다.

```
FastAPI = 접수 창구   →  요청을 받고 "접수됐습니다(jobId)" 를 즉시 반환
Worker  = 실행 담당   →  뒤에서 시간이 걸리는 main.sh 를 실행
```

`POST /api/jobs`는 설정 파일을 만들고 Job을 대기열에 넣은 뒤 **바로 응답**합니다.
분석이 끝날 때까지 기다리지 않습니다.

## 디렉터리 구조

```
backend/
├── requirements.txt
├── .env.example              설정 예시 파일
├── .env                      실제 설정 (git에 올라가지 않음)
├── .venv/                    Python 가상환경 (git에 올라가지 않음)
├── data/app.db               SQLite 파일 (git에 올라가지 않음)
└── app/
    ├── main.py               FastAPI 앱, 시작/종료 처리, /api/health
    ├── config.py             경로·환경변수 설정
    ├── db.py                 SQLite 스키마와 접근 함수
    ├── schemas.py            요청/응답 형식 정의
    ├── api/
    │   ├── uploads.py        파일 업로드 API
    │   └── jobs.py           Job 생성·조회·취소 API
    └── services/
        ├── config_builder.py     요청 → run_config.json + samplesheet.csv 변환
        ├── pipeline_executor.py  main.sh 를 subprocess 로 실행
        ├── run_status_reader.py  파이프라인 상태 JSON → 화면용 형식으로 변환
        └── worker.py             대기열에서 Job 을 꺼내 실행
```

## Python 환경

- Python **3.12**
- 의존성은 `requirements.txt` 한 줄뿐입니다.

```
fastapi[standard]==0.141.1
```

`[standard]`에 웹 서버 uvicorn이 함께 들어 있어 별도 설치가 필요 없습니다.
데이터베이스는 Python 표준 라이브러리 `sqlite3`를 쓰므로 추가 패키지가 없습니다.
(SQLAlchemy, Celery, Redis, PostgreSQL 드라이버는 사용하지 않습니다.)

가상환경은 `backend/.venv`에 만들고, **git에는 포함되지 않습니다.** 각자 로컬에서 만들어야 합니다.

## 최초 환경 준비

저장소 최상위 폴더에서 실행합니다.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

**Linux / macOS**

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

> PowerShell 실행 정책 때문에 `Activate.ps1`이 막히면, 위처럼 가상환경의 `python.exe`를
> 직접 호출하면 됩니다. 활성화(activate)는 필수가 아닙니다.

설정 파일을 만듭니다.

```bash
# backend/.env.example 을 복사해서 backend/.env 로 저장한 뒤 값을 채웁니다
```

## 실행 방법

저장소 최상위 폴더에서 실행합니다.

**Windows**

```powershell
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

**Linux / macOS**

```bash
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

확인:

```
http://127.0.0.1:8000/api/health   → {"status":"ok", ...}
http://127.0.0.1:8000/docs         → API 목록을 브라우저에서 확인/시험 가능
```

**배포된 Linux 서버**에서는 위 명령을 직접 치지 말고 `script/start_backend.sh`를
쓰세요. 인터프리터(`wes-dev`)와 분석 도구 PATH(`wes-tools/bin`)를 고정하고
`/api/health`까지 확인합니다 — 이 두 가지를 손으로 맞추다가 실제로 두 번
장애가 났습니다. 배포 절차 전체는 `docs/DEPLOYMENT.md`, 실행 전 서버 점검은
`script/server_preflight.sh`입니다.

## 환경 설정 (`backend/.env`)

`backend/.env.example`을 복사해서 만듭니다. 실제 값은 각 PC마다 다르므로 git에 올리지 않습니다.

reference(참조 유전체) 경로 같은 값은 **서버 운영자가 `.env`에 넣습니다.**
브라우저는 절대로 서버의 파일 경로를 지정할 수 없습니다.

### `WES_RUN_MODE` — 가장 중요한 설정

| 값 | 의미 |
|---|---|
| `check_only` | `main.sh --check-only`를 실행합니다. 실제 분석 도구는 하나도 돌리지 않고, 입력 파일과 환경이 올바른지만 사전 검증합니다 |
| `full` | 전체 파이프라인을 실행합니다. bwa/samtools/gatk 등 분석 도구와 참조 유전체가 모두 준비된 Linux 환경에서만 사용해야 합니다 |

**이 두 값 외에는 허용하지 않습니다.** 예를 들어 `chek_only`처럼 오타가 나면
서버가 시작되지 않고 다음과 같이 즉시 멈춥니다.

```
ConfigError: Invalid WES_RUN_MODE: 'chek_only'. Expected one of: check_only, full.
```

오타가 실수로 전체 분석 실행으로 해석되는 것을 막기 위한 안전장치입니다(fail-closed).
값을 비워 두거나 설정하지 않으면 안전한 쪽인 `check_only`가 적용됩니다.

> **현재 Windows 로컬 개발에서는 `check_only`만 사용하세요.**
> 이 PC에는 WES 분석 도구와 참조 유전체가 설치되어 있지 않습니다.

### 그 밖의 설정

| 변수 | 설명 |
|---|---|
| `WES_BASH` | bash 실행 파일. Windows는 Git Bash, Linux는 시스템 bash (기본 `bash`) |
| `WES_ASSEMBLY` | 참조 유전체 버전 (기본 `GRCh38`) |
| `WES_CONTIG_STYLE` | 염색체 이름 표기 방식. `chr1` 형식이면 `chr`, `1` 형식이면 `plain`. **추측하지 말고 참조 FASTA의 `.fai` 첫 열을 직접 확인** |
| `WES_REFERENCE_FASTA` | 참조 유전체 FASTA 파일 경로 |
| `WES_KNOWN_SITES` | BQSR에 쓰이는 known-sites VCF 경로 목록 (쉼표 구분) |
| `WES_DBSNP_VCF` | dbSNP VCF 경로 (선택) |
| `WES_THREADS` / `WES_JAVA_MEM_GB` | 분석에 쓸 CPU 스레드 수 / Java 메모리 |

## 주요 API

| Method | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 서버가 살아 있는지, 파이프라인 스크립트와 설정이 제자리에 있는지 확인. 서버 절대경로는 보내지 않음(`pipelineScript`는 저장소 기준 상대경로, `release`는 배포 디렉터리 이름) |
| POST | `/api/uploads` | 파일 업로드를 시작하고 업로드 ID와 조각 크기를 받아옴 |
| GET | `/api/uploads/{id}` | 이미 받은 조각 번호 목록 (중간에 끊겼을 때 이어받기용) |
| PUT | `/api/uploads/{id}/{index}` | 파일 조각 하나를 전송 |
| POST | `/api/uploads/{id}/complete` | 조각들을 합쳐 하나의 파일로 만들고 식별용 토큰을 반환 |
| POST | `/api/jobs` | 분석 요청 접수. 설정 파일을 만들고 대기열에 넣은 뒤 즉시 `jobId` 반환 |
| GET | `/api/jobs/{id}` | Job의 현재 상태·단계별 진행·실패 사유·최근 로그 조회 (Frontend가 3초마다 호출) |
| GET | `/api/jobs` | 이 backend의 DB에 있는 실행 목록 |
| POST | `/api/jobs/{id}/cancel` | 실행 중인 분석 중단 요청 |
| GET | `/api/jobs/{id}/results` | 분석 결과 요약. 결과 문서가 아직 없으면 409 |
| GET | `/api/jobs/{id}/artifacts` | 산출물 목록 |
| GET | `/api/jobs/{id}/artifacts/{fileId}/download` | 산출물 다운로드 |
| GET | `/api/jobs/{id}/steps/{stepId}` | 단계별 상세 |
| GET | `/api/jobs/{id}/explanation` | 모델 없이 만든 실행 설명(결정론). 실패한 실행도 설명함 |
| POST | `/api/jobs/{id}/synthesis` | AI 종합 설명(Claude Code CLI, 구독 로그인 전용). 버튼을 눌렀을 때만 실행. 아직 끝나지 않은 실행(`queued`·`running`)은 모델을 부르지 않고 409 |
| GET | `/api/jobs/{id}/stream` | **의도적으로 404를 반환합니다.** 실시간 스트리밍(SSE)은 아직 만들지 않았고, Frontend가 이 404를 보고 자동으로 polling(주기적 재조회)으로 전환합니다 |

### 업로드 경로를 노출하지 않는 이유

`POST /api/uploads/{id}/complete`는 `{"path": "upl_4de82306..."}` 형태를 돌려줍니다.
`path`라는 이름이지만 실제 값은 **서버 파일 경로가 아니라 식별용 토큰**입니다.
브라우저는 서버의 파일 경로를 알 수 없고, Backend가 토큰을 데이터베이스에서 실제 경로로 바꿉니다.

## Job 실행 흐름

```
Frontend
   ↓  POST /api/uploads → PUT 조각 → POST complete
FastAPI          파일을 서버 디스크(uploads/)에 저장
   ↓  POST /api/jobs
FastAPI          요청 검증 → run_id 발급
   ↓
config_builder   runs/_jobs/<run_id>/samplesheet.csv
                 runs/_jobs/<run_id>/run_config.json  생성
   ↓
SQLite           Job 기록 (상태 QUEUED)
   ↓             ← 여기서 즉시 {jobId} 응답
Worker           대기열에서 꺼냄
   ↓
PipelineExecutor bash script/main.sh --config ... --check-only
   ↓
script/main.sh   runs/<run_id>/status/run_status.json
                 runs/<run_id>/status/steps/*.json  생성
   ↓
run_status_reader  파이프라인 상태 → 화면용 형식으로 변환
   ↓  GET /api/jobs/{id}
Frontend         JobPage 에 표시
```

생성되는 폴더 (모두 git에 올라가지 않습니다):

```
runs/_jobs/<run_id>/    Backend가 만든 설정 파일과 실행 로그
runs/<run_id>/          main.sh가 만든 실제 결과와 상태 파일
uploads/upl_<...>/      업로드된 FASTQ 파일
```

## 현재 확인된 범위

Windows + Git Bash 환경에서 다음까지 실제로 확인했습니다.

```
Frontend → Backend → 실제 script/main.sh --check-only
        → 00_input_validation 결과가 JobPage 까지 반환됨
```

이때 검증은 **실패로 끝납니다.** 이 PC에 WES 분석 도구(bwa, samtools, gatk 등)와
참조 유전체가 설치되어 있지 않기 때문이며, **현재 환경에서는 정상적인 결과입니다.**
중요한 것은 그 실패 사유가 조작 없이 파이프라인에서 화면까지 그대로 전달된다는 점입니다.

전체 WES 분석(`full` 모드)은 **Ubuntu VM**에서 실제 도구와 GRCh38로 `00 → 99`까지
완주했습니다(루트 `README.md` "WES Validation"). 그 실행 하나(`real_cba73e`,
`completed_with_warnings`)의 상태 문서와 DB 행을 보존해 두었고(`evals/real_runs.py`),
Windows에서는 이 사본을 `python -m evals.dev_restore`로 복원해 웹 화면과 AI 설명을
확인합니다. 이 사본은 원본 VM과 연결되어 있지 않습니다.

### 운영체제별 지원 범위

| | Windows (개발) | Ubuntu (VM) |
|---|---|---|
| Frontend · Backend 실행 | ✅ | ✅ (`docs/DEPLOYMENT.md`) |
| `check_only` 실행 | ✅ (도구가 없어 검증 실패로 끝나는 것이 정상) | ✅ |
| `full` 실행 | ❌ 도구·참조 유전체 없음 | ✅ 1회 완주 기록 |
| 실행 중 취소 | 부분적 (아래 "현재 제한") | ✅ |
| 실제 Run 보기 | 보존 사본 복원(`evals/dev_restore.py`) | 그 backend가 만든 실행 |

Windows의 backend와 VM의 backend는 DB와 실행 폴더를 공유하지 않습니다. 한 backend는
자기 DB에 행이 있는 실행만 보여 줍니다.

## 현재 제한

- **한 번에 한 샘플만 제출할 수 있습니다.** 파이프라인이 실행 1건당 생물학적 샘플 1개를 요구합니다. 여러 개를 보내면 400 오류와 이유를 반환하며, 조용히 버리지 않습니다.
- **동시에 한 건만 실행합니다.** Worker 스레드가 1개입니다.
- **결과 API는 요약과 산출물까지입니다.** `/results`·`/artifacts`·`/explanation`이 있으며, 변이 목록을 행 단위로 돌려주는 API는 없습니다.
- **취소는 Linux에서만 온전히 동작합니다.** Windows에서는 `main.sh`가 종료 신호를 받아 처리할 방법이 없어, 실행 중 취소하면 상태 파일과 잠금 폴더가 정리되지 않고 남을 수 있습니다.
- **재시작 시 정리(`worker.recover_orphans`)는 DB 행만 맞춥니다.** 시작할 때 `RUNNING`·`CANCELLING` 행을 보고, 파이프라인 프로세스가 살아 있으면 그대로 둡니다(Linux는 `setsid`로 띄우므로 backend 재시작에도 분석이 계속됨). 프로세스가 사라졌으면 `run_status.json`이 있을 때 `DONE`, 없을 때 `EXEC_FAILED`로 닫고, `QUEUED` 행은 다시 대기열에 넣습니다. 살아 있던 분석이 끝난 뒤에도 DB 행은 다음 재시작 전까지 `RUNNING`일 수 있지만, 화면의 상태는 디스크의 상태 파일을 읽으므로 정확합니다.
- **업로드 조각 크기에 상한이 없고 로그인/인증도 없습니다.** 로컬 개발 환경(127.0.0.1)에서만 사용하세요.
- **AI 설명은 선택 기능입니다.** 모델 응답은 화면에 나가기 전에 근거 ID · 수치 · 내부 필드 이름 · 실행 사실 · 근거 적합성 검사를 통과해야 하며, 하나라도 걸리면 응답 전체를 버리고 이유를 표시합니다(`services/explanation/llm/synthesis.py`). 초보자용 설명 품질 검사기(`evals/explanation_quality.py`)는 **평가 전용**이며 실제 응답 경로에서는 실행되지 않습니다.
- **AI 설명 자동 수정은 기본 꺼짐입니다.** 아래 "AI 설명 자동 수정"을 보세요.

## 실행 사실 · 근거 적합성 검사 (gate 6 · 7)

수치 검사(gate 4)는 "그 숫자가 데이터 어딘가에 있는가"만 봅니다. 그래서 다른 지표의 실제 값을 붙인 문장이 통과했습니다
(예: "평균 깊이는 1420배" — 1420은 변이 검출 단계의 소요 초). `services/explanation/llm/claims.py`가 그 연결을 되살립니다.

| 검사 | 무엇을 비교하나 | 비교 기준(실행 시 payload에서 읽음) |
|---|---|---|
| `runFactMismatch` | "평균 깊이", "한 번도 읽히지 않은 염기(0×)", "변이 후보 기록" 바로 뒤의 숫자(그 항목의 단위로 쓴 것만) | `coverage.meanTargetDepth`, `zeroCoverageBasesPct`·`zeroCoverageBases`, `variantCalling.rawVariantRecords` |
| `runFactMismatch` | "세 단계에서 경고", "경고 단계는 N개", "경고 없이 완료", "<단계 이름> 단계에서 경고" | `steps.planned`에서 status가 `warning`인 단계 |
| `evidenceMismatch` | dbSNP·rsID, NM/MD 태그처럼 knowledge가 진단에만 연결한 용어를 쓴 문장의 인용 | 이 Run이 낸 그 진단의 `dx:` ID, 용어 ID, 그 근거 문서 |
| `evidenceMismatch` | 변이 후보 수를 말하면서 필터 미적용 한계를 답 어디에도 인용하지 않음 | `lim:UNFILTERED_VARIANTS`가 payload에 있을 때만 |

- **좁게 판정합니다.** 문장이 위 표현과 정확히 맞을 때만 비교하고, 구간(interval) 단위 수치 · 기준값("20배 미만") · 괄호 안 설명은 건너뜁니다. 알아보지 못한 표현은 통과시킵니다. 통과가 "맞다"는 뜻은 아닙니다.
- **반올림은 걸립니다.** "평균 깊이 약 11배"는 거부됩니다. prompt의 "반올림·환산 금지" 규칙과 같은 방향입니다.
- 기존 검사 뒤에 실행되므로 기존 거부 사유(category)는 그대로입니다. 기록된 실제 답 17개(baseline · A/B)는 모두 통과합니다(`evals/test_recorded_answers_pass_claims.py`).

## AI 설명 자동 수정 (선택 기능, 기본 꺼짐)

**목적:** 런타임 안전 검사에 걸린 AI 설명을 바로 버리지 않고, 무엇이 문제였는지 알려준 뒤 **한 번만** 다시 쓰게 합니다.
고친 설명도 처음과 **똑같은 검사**를 통과해야 사용자에게 보입니다. 검사 기준은 바뀌지 않았습니다.

**켜는 법:** `backend/.env`(또는 환경 변수)에 `WES_SYNTHESIS_REPAIR=on`을 둡니다.
값은 `on`/`off`(`1`/`0`, `true`/`false`, `yes`/`no`도 가능)이고, 비어 있으면 꺼짐입니다. 그 밖의 값이면 서버가 시작하지 않습니다.
읽는 곳은 `app/config.py`의 `SYNTHESIS_REPAIR`, 쓰는 곳은 `services/explanation/llm/synthesis.py`의 `build_run_synthesis`입니다.

**흐름** (`build_run_synthesis`):

```
첫 호출 (기존과 같은 prompt, Tool 제공)
  → _check: 형식(Pydantic) → 근거 ID → 수치 → 내부 필드명 → 실행 사실 → 근거 적합성
  → 통과: 그대로 제공 (호출 1회)
  → 거부 + 꺼짐: 기존처럼 폐기 (호출 1회)
  → 거부 + 켜짐: prompt.build_repair_prompt로 수정 요청 1회 (Tool 없음)
       → 지적된 항목만 교체(_splice) → 같은 _check, 같은 사실 목록 · 허용 근거 ID
       → 통과: 고친 설명 제공 / 거부: 폐기 (호출 2회)
```

- **수정 요청에 들어가는 것:** 첫 호출과 똑같은 `<run_data>`, 첫 호출 때 Tool이 반환한 단계 기록(`<step_details>`, 있을 때만), 거부된 답(`<previous_answer>`), 검사가 찾은 내용(`<check_findings>`: 허용되지 않은 근거 ID와 허용 목록 · 데이터에 없는 수치 · 노출된 필드명 · 실행 사실과 맞지 않는 값 · 맞지 않는 인용 · 형식 오류 위치, 그리고 각 발견이 나온 항목 위치 `locations`).
- **고칠 수 있는 범위:** 지적된 항목(`locations`)만 고친 답에서 가져오고, 나머지 항목은 첫 답 그대로 둡니다(`_splice`). 실제 Claude 실험에서 근거 하나를 고치며 요약까지 바꾸고 NM/MD를 "염기 보조 표시"로 잘못 쓴 일이 있었습니다. 지금은 그런 변경이 사용자에게 가지 않습니다. 첫 답이 형식 오류였으면 고친 답 전체를 씁니다. 교체된 항목 자체의 의미가 맞는지는 증명하지 못하며, 다른 답과 똑같이 전체 검사만 다시 받습니다.
  경로 · 예외 메시지 · 인증 정보는 들어가지 않습니다.
- **고친 답이 얻지 못하는 것:** 사실 목록과 허용 근거 ID는 첫 호출 때 것을 그대로 씁니다. 수정 요청에 적힌 숫자(거부 사유)는 사실로 인정되지 않고, 열지 않은 단계의 `step:` ID도 여전히 거부됩니다.
- **재시도하지 않는 경우:** provider 오류 전부(timeout · 로그인 없음 · API key 감지 · 사용량 한도 · CLI 실패 · 응답 해석 불가), 409(끝나지 않은 Run), 실행 기록 자체의 오류(500). 수정 요청이 provider 오류로 끝나면 그 오류를 그대로 돌려주고 더 시도하지 않습니다.
- **제한:** 요청당 provider 호출은 최대 2회입니다. 설정값이 아니라 코드 흐름(직선 코드에 호출 하나 추가)으로 고정돼 있습니다. timeout은 호출마다 적용되므로 최악의 경우 대기 시간이 두 배가 됩니다.
- **평가 전용 검사기와 무관:** `evals/explanation_quality.py`의 PASS / REVIEW / FAIL은 수정 조건에 쓰이지 않습니다.
- **API 응답 형태는 그대로입니다.** 수정 여부는 응답에 넣지 않고 trace에만 남깁니다. 실패 시 화면에 나가는 문구도 기존 안내문 그대로입니다.

**trace(`synthesis_traces`)에 추가된 칸** (모두 NULL 허용, 기존 DB에는 시작 시 자동 추가):

| 칸 | 의미 |
|---|---|
| `repair_enabled` | 이 요청에서 기능이 켜져 있었는지 |
| `attempts` | 실제 provider 호출 수(실패한 호출 포함). 1 또는 2 |
| `first_rejection` | 첫 답을 거부한 검사 이름. 통과했거나 provider 오류면 NULL. 기능이 꺼져 있어도 기록 |

수정이 있었으면 `models`는 두 호출의 모델, `duration_ms`·`num_turns`는 두 호출의 합입니다. 최종 결과는 기존 `available`·`error_category`입니다.
이 세 칸이 NULL인 행은 기능 추가 전 backend가 남긴 단일 생성 기록입니다. 답변 문장과 prompt는 여전히 저장하지 않습니다.

**평가 도구와의 관계:** `evals/run_eval.py`는 항상 `repair=False`로 호출합니다. 서버 설정과 상관없이 eval 기록은 기존 A/B와 같은 단일 생성 측정입니다.

**검증 상태:** fake provider로 `app/tests/test_synthesis_repair.py` 46개 통과(2026-11-05).
실제 Claude 통제 실험 3건(2026-11-05): 첫 오답은 테스트 스크립트가 심은 것(숫자 · 근거 ID · 필드명 각 1건)이고 수정만 실제 Claude가 했습니다. 3건 모두 수정 후 재검사 통과, 수정 1회당 약 11–12초.
이 실험은 항목 교체(`_splice`)와 gate 6 · 7 도입 **전**의 코드로 했습니다. 기록된 그 수정 답을 지금 코드에 다시 넣으면 3건 모두 통과하고, 근거 수정 건에서 요청하지 않은 문장 변경 5곳과 요약 변경이 버려집니다(모델 재호출 없이 확인). 실제 모델의 일반적인 수정 성공률은 3건으로 말할 수 없습니다.

웹 API 경로 검증(2026-11-05, fake provider, 실제 Run 복사본): `POST /api/jobs/{id}/synthesis` → Vite proxy → frontend API 함수(Zod)로
정상 · 수치 불일치 · 경고 단계 수 불일치 · 주제와 맞지 않는 근거 → 수정 후 통과, 수정 중 정상 항목 변경 → 원래 항목 유지,
수정 후에도 오류 → 폐기, timeout → 안내문(호출 1회), 자동 수정 꺼짐 → 호출 1회 후 폐기, 끝나지 않은 Run → 409, 없는 Run → 404를 확인했습니다.
모든 호출에서 `<run_data>`는 같았고, 수정 호출에는 Tool이 없었습니다. 브라우저 화면 확인과는 별개입니다.

**남은 한계:** 자연어 의미 오류(모순 · 임상 표현 · 원인 단정)는 검사하지 않습니다. gate 6 · 7이 알아보지 못한 표현은 통과합니다.
gate 6 · 7과 항목 교체를 적용한 상태로는 실제 Claude를 아직 호출하지 않았습니다. Ubuntu 실제 분석부터 Agent까지의 전체 연결은 별도 단계입니다.

## 테스트

```bash
cd backend
.venv/Scripts/python.exe -m pytest -o addopts=""          # app/tests (모델 호출 없음)
.venv/Scripts/python.exe -m pytest evals -o addopts=""    # 평가 도구 테스트 (모델 호출 없음)
```

2026-11-05 Windows에서 실행: app 687 passed · 1 skipped(일반 계정에 file symlink 권한이 없어 건너뜀),
evals 257 passed · 3 skipped(답변이 없는 기록). capture가 없는 PC에서는 실제 Run을 쓰는 evals 테스트가 skip됩니다.
모델을 실제로 호출하는 것은 `python -m evals.run_eval`뿐이며 pytest는 이를 실행하지 않습니다.
