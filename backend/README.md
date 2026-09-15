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
| GET | `/api/health` | 서버가 살아 있는지, 파이프라인 스크립트와 설정이 제자리에 있는지 확인 |
| POST | `/api/uploads` | 파일 업로드를 시작하고 업로드 ID와 조각 크기를 받아옴 |
| GET | `/api/uploads/{id}` | 이미 받은 조각 번호 목록 (중간에 끊겼을 때 이어받기용) |
| PUT | `/api/uploads/{id}/{index}` | 파일 조각 하나를 전송 |
| POST | `/api/uploads/{id}/complete` | 조각들을 합쳐 하나의 파일로 만들고 식별용 토큰을 반환 |
| POST | `/api/jobs` | 분석 요청 접수. 설정 파일을 만들고 대기열에 넣은 뒤 즉시 `jobId` 반환 |
| GET | `/api/jobs/{id}` | Job의 현재 상태·단계별 진행·실패 사유·최근 로그 조회 (Frontend가 3초마다 호출) |
| POST | `/api/jobs/{id}/cancel` | 실행 중인 분석 중단 요청 |
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

전체 WES 분석(`full` 모드)은 아직 실행해 보지 않았습니다.

## 현재 제한

- **한 번에 한 샘플만 제출할 수 있습니다.** 파이프라인이 실행 1건당 생물학적 샘플 1개를 요구합니다. 여러 개를 보내면 400 오류와 이유를 반환하며, 조용히 버리지 않습니다.
- **동시에 한 건만 실행합니다.** Worker 스레드가 1개입니다.
- **분석 결과 조회 API가 없습니다.** 상태와 로그만 제공하며, 변이 목록·커버리지 같은 결과 데이터 API는 아직 만들지 않았습니다.
- **취소는 Linux에서만 온전히 동작합니다.** Windows에서는 `main.sh`가 종료 신호를 받아 처리할 방법이 없어, 실행 중 취소하면 상태 파일과 잠금 폴더가 정리되지 않고 남을 수 있습니다.
- **Backend를 재시작하면 실행 중이던 Job을 다시 이어받지 않습니다.** 상태 조회는 디스크의 상태 파일을 읽으므로 정상 표시되지만, 데이터베이스의 Job 상태는 `RUNNING`으로 남습니다.
- **업로드 조각 크기에 상한이 없고 로그인/인증도 없습니다.** 로컬 개발 환경(127.0.0.1)에서만 사용하세요.
- **자동 테스트가 없습니다.**
