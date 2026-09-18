# Linux 배포 runbook

이 문서는 **WES web backend를 Linux 서버에 배포하고 다시 띄우는 절차**입니다.

파이프라인 자체를 단독으로 돌리는 방법은 `docs/MAIN_SH_COMPLETE_GUIDE.md`
29장(Linux smoke test 절차)에 있고, 이 문서는 그 위에 올라가는
**web backend 운영**을 다룹니다. Windows 개발 실행 방법은 `backend/README.md`
그대로이며 이 문서의 영향을 받지 않습니다.

## 역할 네 가지를 섞지 않는다

배포 도구가 하나로 뭉치면 "실행은 되는데 왜 되는지 모르는" 상태가 됩니다.
이 저장소는 네 역할을 **서로 다른 파일**로 나눠 둡니다.

| 역할 | 파일 | 질문 |
|---|---|---|
| **bootstrap / provision** | `script/bootstrap_server.sh` | 새 서버를 **처음 준비**한다 |
| **preflight** | `script/server_preflight.sh` | 지금 이 서버가 Full Run **준비가 됐는가** |
| **start / restart** | `script/start_backend.sh` | backend를 **어떻게 올바르게 실행**하는가 |
| **service manager** | `script/systemd/` + `script/install_systemd_service.sh` | 재부팅 후 **누가 살려 놓는가** |

의존 방향은 한쪽입니다.

```
bootstrap  ──끝에서 호출──▶  preflight
systemd unit ──ExecStart──▶  start_backend.sh --foreground
```

- bootstrap은 **준비만** 하고 판정하지 않습니다. 판정은 preflight입니다.
- systemd unit은 인터프리터·PATH 규칙을 **복제하지 않습니다.** `start_backend.sh`를
  그대로 실행합니다.
- preflight는 `main.sh`의 `00_input_validation`을 **복제하지 않습니다.**

관련 script:

| script | 하는 일 |
|---|---|
| `script/bootstrap_server.sh` | 최초 1회 provisioning. 디렉터리·shared storage·conda 환경·BED·`.env` 준비 후 preflight 호출 |
| `script/server_preflight.sh` | 분석을 시작할 수 있는 서버 상태인지 사전 점검 |
| `script/start_backend.sh` | backend 기동/재기동. 인터프리터와 도구 PATH를 고정하고 `/api/health`까지 확인 |
| `script/install_systemd_service.sh` | 부팅 시 자동 기동을 위한 systemd unit 설치 (sudo 필요) |
| `script/download_capture_beds.sh` | capture kit BED 내려받기 + SHA-256 검증 |

---

## 1. 일곱 가지 자산을 구분한다

배포 사고는 대부분 **"코드를 옮겼으니 다 옮겼다"**고 생각할 때 납니다.
이 프로젝트에서 서버에 있어야 하는 것은 성격이 다른 일곱 가지입니다.

| # | 자산 | 예 | Git에 있나 | 새 release로 자동 따라오나 |
|---|---|---|---|---|
| 1 | **Git source** | `backend/`, `front/`, `script/main.sh`, `config/` | O | O (archive/clone에 포함) |
| 2 | **release** | `releases/20260918_01_88e7230/` | X | 매번 새로 만드는 대상 |
| 3 | **runtime biological resources** | GRCh38 FASTA·index·known-sites, capture BED | **X** | **X — 사람이 옮기거나 연결해야 함** |
| 4 | **persistent data** | `runs/`, `uploads/`, SQLite DB | **X** | **X — shared로 유지해야 함** |
| 5 | **conda/runtime tools** | `wes-dev`(Python), `wes-tools`(bwa·samtools·gatk…) | X | X — 서버에 한 번 설치 |
| 6 | **`.env`** | `backend/.env` | **X (비밀·경로 설정)** | X — release마다 배치 |
| 7 | **`current` symlink** | `current -> releases/<id>` | X | 전환으로 바뀌는 대상 |

특히 **1과 3을 혼동하면 안 됩니다.**
`git archive`는 **Git이 추적하는 파일만** 담습니다. capture BED는
`.gitignore`의 `resources/capture_beds/` 대상이므로 **archive에 들어 있지 않습니다.**
2026-09-17에 실제로 이것 때문에 새 release에서 `resource_bundle` validation이
실패했습니다(registry는 멀쩡했고 BED 파일만 없었습니다).

> 대용량 reference와 BED를 Git에 넣는 것은 **해결책이 아닙니다.**
> BED는 `script/download_capture_beds.sh`가 공식 배포처에서 받아 SHA-256으로
> 검증하고, reference는 운영자가 서버에 한 번 준비합니다.

---

## 2. 서버 디렉터리 배치

현재 운영 중인 배치입니다.

```
~/sideprojects/wes-web/                     ← deploy root (WES_DEPLOY_ROOT)
├── current -> releases/20260918_01_88e7230 ← 지금 서비스 중인 release
├── releases/
│   ├── 20260907_02_946529e/
│   └── 20260918_01_88e7230/
│       ├── backend/  front/  script/  config/   ← Git source
│       ├── backend/.env                          ← 이 서버 전용 설정
│       ├── backend/data -> ../../../shared/backend-data
│       ├── runs        -> ../../shared/runs
│       ├── uploads     -> ../../shared/uploads
│       ├── resources/capture_beds/grch38/        ← runtime resource (Git 아님)
│       └── runtime/                              ← backend.pid / backend.log
└── shared/
    ├── runs/            ← 과거·현재 run 산출물
    ├── uploads/         ← 업로드된 FASTQ
    └── backend-data/    ← SQLite DB (app.db)
```

release 밖에 있는 것:

```
~/references/GRCh38/                 reference FASTA·index·known-sites
~/miniconda3/envs/wes-dev/           backend Python (uvicorn)
~/miniconda3/envs/wes-tools/         분석 도구 (bwa, samtools, gatk, …)
```

release 이름은 `<날짜>_<순번>_<commit>` 형식입니다. commit 해시가 들어 있어서
`/api/health`의 `pipelineScript` 경로만 봐도 **지금 도는 코드가 어느 commit인지**
알 수 있습니다.

> **왜 `runs`/`uploads`/DB를 shared에 두는가**
> release 디렉터리 안에 두면 release를 교체할 때 과거 run과 job 이력이
> 따라오지 않습니다. symlink 대신 `WES_RUNS_ROOT` / `WES_UPLOAD_ROOT` /
> `WES_DB_PATH` 환경변수로 shared 경로를 직접 지정해도 됩니다
> (`backend/app/config.py`가 세 값을 모두 지원합니다).

---

## 3. 새 서버에 처음 배포하기

### 3-0. 짧은 버전

source를 서버에 올린 다음, release 안에서:

```bash
script/bootstrap_server.sh          # 준비 (sudo 불필요)
# → 안내대로 reference 준비 + backend/.env 채우기
script/server_preflight.sh          # FAIL 0이 될 때까지
script/start_backend.sh             # 한 번 손으로 띄워 확인
script/install_systemd_service.sh   # 재부팅 대비 (sudo 필요)
```

`bootstrap_server.sh`는 **여러 번 실행해도 안전합니다.** 이미 있는 환경·디렉터리·
`.env`는 그대로 두고, 데이터가 든 디렉터리는 절대 건드리지 않습니다.
각 단계는 `[local]`(파일시스템만) · `[network]`(인터넷 필요) ·
`[manual]`(사람이 해야 함)로 표시되어 출력됩니다.

아래 3-1 ~ 3-8은 **bootstrap이 무엇을 대신해 주는지, 무엇이 남는지**를
단계별로 설명합니다.

### 3-1. source 준비 — **사람**

개발 머신에서 commit 기준 archive를 만들어 보냅니다.

```bash
# [개발 머신]
git archive --format=tar.gz -o wes-web_88e7230.tar.gz 88e7230
scp -P 2222 wes-web_88e7230.tar.gz vboxuser@127.0.0.1:~/sideprojects/wes-web/
```

서버에서 release로 전개합니다.

```bash
# [서버]
DEPLOY_ROOT=~/sideprojects/wes-web
RELEASE=$DEPLOY_ROOT/releases/20260918_01_88e7230
mkdir -p "$RELEASE"
tar -xzf "$DEPLOY_ROOT/wes-web_88e7230.tar.gz" -C "$RELEASE"
```

> `git clone` 후 특정 commit을 checkout해도 됩니다. 어느 쪽이든
> **`.gitignore` 대상(자산 3·4·6)은 들어오지 않는다**는 점은 같습니다.

### 3-2. Python / 도구 환경 준비 — **bootstrap이 함** `[network]`

`bootstrap_server.sh`의 3~5단계가 처리합니다. conda가 **이미 설치돼 있어야**
하며(없으면 설치 안내만 하고 넘어갑니다), 두 환경을 prefix로 만듭니다.

```bash
# bootstrap이 실행하는 것과 동등한 명령
conda create -y -p ~/miniconda3/envs/wes-dev python=3.12
~/miniconda3/envs/wes-dev/bin/python -m pip install -r "$RELEASE/backend/requirements.txt"

conda create -y -p ~/miniconda3/envs/wes-tools -c conda-forge -c bioconda \
    bwa samtools gatk4 bcftools htslib mosdepth fastqc fastp multiqc
```

패키지 이름과 실행 파일 이름은 다릅니다 — `gatk4`가 `gatk`를, `htslib`가
`tabix`/`bgzip`을 제공합니다. 목록의 출처는
`docs/MAIN_SH_COMPLETE_GUIDE.md` 6장이고, **실제로 그 실행 파일들이 PATH에서
잡히는지는 preflight가** `main.sh`의 required 목록을 직접 읽어 확인합니다.

**이미 있는 환경은 다시 만들지 않습니다.** bioconda 환경을 다시 solve하면 도구
버전이 조용히 움직일 수 있고, 그러면 같은 파이프라인이 다른 결과를 낼 수 있기
때문입니다.

두 환경을 **섞지 않습니다.** 인터프리터는 `wes-dev`, 분석 도구는 `wes-tools`이며
`start_backend.sh`가 그 분리를 유지합니다(5장).

> conda 자체는 bootstrap이 설치하지 않습니다. 배포판 선택·설치 위치·채널 정책은
> 그 머신을 소유한 사람의 결정입니다.

### 3-3. reference / capture resource 준비 — **capture BED만 bootstrap이 함**

**reference bundle** `[manual]` — 운영자가 서버에 직접 준비합니다. bootstrap도
파이프라인도 **내려받지 않습니다.** 수십 GB이고, 공식 URL을 이 저장소가 고정해
두지 않았으며, 잘못되거나 일부만 있는 reference는 아예 없는 것보다 위험하기
때문입니다(`main.sh`는 fail-closed입니다). bootstrap은 무엇이 필요한지 안내하고,
**검증은 preflight가** 합니다. 필요한 파일 목록과 각각의 이유는
`docs/MAIN_SH_COMPLETE_GUIDE.md` 4.2에 있습니다. 최소한 다음이 필요합니다.

```
Homo_sapiens_assembly38.fasta            + .fai + .dict
Homo_sapiens_assembly38.fasta.64.{amb,ann,bwt,pac,sa}   ← BWA index
known-sites VCF 1개 이상                  + .tbi 또는 .csi
```

> BWA index는 `.64.*`와 접두사 없는 형태 둘 다 정상입니다. bwa는 `<ref>.64.bwt`를
> 먼저 찾고 **다른 이름으로 되돌아가지 않으므로**, 선택된 prefix 쪽 5개 파일이
> 모두 있어야 합니다. preflight가 같은 규칙으로 검사합니다.

**capture BED** `[network]` — bootstrap 6단계가 기존 script를 **그대로 호출**합니다
(`--skip-beds`로 끌 수 있습니다). 따로 돌릴 때는:

```bash
cd "$RELEASE"
script/download_capture_beds.sh all
```

IDT / Twist / Roche는 자동으로 받아 SHA-256까지 검증합니다.
**Agilent SureSelect V8은 SureDesign 수동 다운로드가 필요**하며, 확인 전까지
registry에서 `unconfirmed`로 남습니다 — backend가 받지 않고 frontend 목록에도
없으므로, 준비하지 않아도 배포는 정상입니다. 자세한 절차는
`docs/CAPTURE_BED_RESOURCES.md`.

### 3-4. `.env` 작성 — **파일 생성은 bootstrap, 값은 사람**

bootstrap 8단계가 `.env`가 없을 때만 `.env.example`을 복사하고, 아직 비어 있는
운영자 입력 항목을 알려 줍니다. **이미 있는 `.env`는 절대 덮어쓰지 않습니다** —
그 서버의 결정이 담긴 유일한 파일이기 때문입니다.

```bash
cp "$RELEASE/backend/.env.example" "$RELEASE/backend/.env"   # bootstrap이 하는 일
```

이 서버에서 실제로 채우는 값:

```ini
WES_RUN_MODE=full
WES_CONTIG_STYLE=chr                  # .fai 첫 열을 직접 보고 적을 것. 추측 금지
WES_REFERENCE_FASTA=/home/<user>/references/GRCh38/Homo_sapiens_assembly38.fasta
WES_KNOWN_SITES=/home/<user>/references/GRCh38/Homo_sapiens_assembly38.known_indels.vcf.gz,/home/<user>/references/GRCh38/Mills_and_1000G_gold_standard.indels.hg38.vcf.gz
WES_DBSNP_VCF=                        # 선택. 없으면 rsID만 안 붙고 분석은 진행
WES_THREADS=2
WES_JAVA_MEM_GB=4
```

`.env`는 **Git에 올리지 않습니다.** 값의 전체 설명은 `backend/.env.example`과
`backend/README.md`에 있습니다.

### 3-5. shared persistent 디렉터리 연결 — **bootstrap이 함** `[local]`

bootstrap 1~2단계가 처리합니다. 동등한 수동 명령:

```bash
mkdir -p "$DEPLOY_ROOT/shared"/{runs,uploads,backend-data}

ln -sfn "$DEPLOY_ROOT/shared/runs"         "$RELEASE/runs"
ln -sfn "$DEPLOY_ROOT/shared/uploads"      "$RELEASE/uploads"
ln -sfn "$DEPLOY_ROOT/shared/backend-data" "$RELEASE/backend/data"
```

bootstrap은 위와 달리 `ln -sfn`으로 **덮어쓰지 않습니다.** 연결 지점의 상태에 따라:

| 현재 상태 | bootstrap의 행동 |
|---|---|
| 없음 | symlink 생성 |
| 이미 같은 shared 경로를 가리키는 symlink | 그대로 둠 |
| 다른 곳을 가리키는 symlink | **건드리지 않고** "어느 쪽에 데이터가 있는지 확인하라"고 보고 |
| 빈 디렉터리 | `rmdir`로 지우고 연결 (빈 경우에만 성공하므로 잃을 데이터가 없음) |
| **데이터가 든 디렉터리** | **건드리지 않고** "직접 옮긴 뒤 연결하라"고 보고 |

`current` symlink도 **없을 때만** 만듭니다. release 전환은 의도적인 배포 단계이지
bootstrap의 부작용이 아니기 때문입니다(6장).

### 3-6. preflight

```bash
"$RELEASE/script/server_preflight.sh"
```

검사 항목과 판정 기준:

| 구분 | 내용 | 실패 시 |
|---|---|---|
| pipeline tools | `main.sh`의 required 목록을 그대로 읽어 PATH에서 확인 | FAIL |
| MultiQC | 없으면 집계 리포트만 빠짐 | WARN |
| reference | FASTA · `.fai` · `.dict` · BWA index · known-sites + index | FAIL |
| dbSNP | 미설정이면 선택 항목 | SKIP |
| capture registry | `confirmed` kit의 BED 존재 + SHA-256 일치 | FAIL |
| `unconfirmed` kit | backend가 받지 않으므로 검사 대상 아님 | SKIP |
| persistent 경로 | 존재·쓰기 가능·release 안에 갇혀 있지 않은지 | FAIL / WARN |
| disk · memory · CPU | 정보 출력 (임계값 없음) | — |

FAIL이 하나라도 있으면 exit code가 0이 아닙니다.
**이 preflight는 `00_input_validation`을 대신하지 않습니다.** 실제 FASTQ·
contig style·디스크 요구량은 run마다 `main.sh`가 다시 검증합니다.

### 3-7. backend 기동 — 먼저 손으로 한 번

부팅 시 자동 기동은 4장에서 붙입니다. 그 전에 **한 번은 직접 띄워서** 뜨는 것을
확인하세요. 문제가 있으면 systemd 뒤가 아니라 여기서 보는 편이 훨씬 빠릅니다.

```bash
"$RELEASE/script/start_backend.sh"
```

기본 동작:

- `current`가 있으면 그 release, 없으면 script가 속한 checkout을 사용
- 인터프리터: `~/miniconda3/envs/wes-dev/bin/python` (**절대경로**)
- PATH: 인터프리터 디렉터리 → `~/miniconda3/envs/wes-tools/bin` → 기존 PATH
- `0.0.0.0:8000`에서 uvicorn 실행 (VM 포트 포워딩으로 host 브라우저가 접근)
- log·pid: `<release>/runtime/backend.log`, `backend.pid`
- 이전에 이 script로 띄운 backend가 있으면 SIGTERM → (필요 시) SIGKILL
- `/api/health`가 응답할 때까지 대기, 실패하면 **log를 출력하고 exit 1**

주요 override (전부 `$HOME` 기준 기본값):

```
WES_DEPLOY_ROOT  WES_RELEASE_DIR  WES_CONDA_ROOT  WES_PYTHON_BIN
WES_TOOLS_BIN    WES_BACKEND_HOST WES_BACKEND_PORT WES_RUNTIME_DIR
WES_HEALTH_TIMEOUT  WES_STOP_TIMEOUT
```

### 3-8. health 확인

기동 script가 이미 확인하고 JSON을 출력하지만, 따로 볼 때는:

```bash
curl -s http://127.0.0.1:8000/api/health
```

```json
{"status":"ok","runMode":"full","pipelineScript":".../releases/20260918_01_88e7230/script/main.sh",
 "pipelineScriptPresent":true,"captureKitRegistryPresent":true,"referenceConfigured":true}
```

> **`status: ok`는 "분석 준비 완료"가 아닙니다.**
> health는 설정값이 채워졌는지와 파일 두 개의 존재만 봅니다.
> `captureKitRegistryPresent: true`는 **registry 파일이 있다**는 뜻이지
> "선택 가능한 kit의 BED가 모두 실제로 있다"는 뜻이 아닙니다.
> 그 판단은 `server_preflight.sh`가 합니다.

여기까지 왔으면 서버는 동작합니다. 다만 **재부팅하면 backend는 다시 뜨지
않습니다** — 그것이 4장입니다.

---

## 4. 재부팅 후 자동 기동 (systemd)

지금까지 backend는 **수동 기동**이었습니다. VM을 재부팅하면 `nohup`으로 띄운
uvicorn은 사라지고, 다시 SSH로 들어가 손으로 올려야 했습니다.

Ubuntu의 init은 systemd이므로, 이 저장소는 systemd unit **template**과
**installer**를 관리합니다. 특정 사용자·홈·release 경로가 박힌 unit 파일을
저장소에 넣지 않습니다.

```
script/systemd/wes-backend.service.template   ← 치환 토큰만 있는 template
script/install_systemd_service.sh             ← 이 머신 값으로 렌더링 + 설치
```

### 4-1. unit이 실행하는 것

```ini
ExecStart=<deploy root>/current/script/start_backend.sh --foreground
```

**새 기동 로직을 만들지 않았습니다.** 인터프리터 절대경로, `wes-tools/bin` PATH,
release 해석, 포트 점유 검사는 전부 `start_backend.sh`에 그대로 있고 unit은 그것을
부릅니다. 규칙이 두 군데로 갈라지지 않습니다.

`--foreground`가 detached 기본 모드와 다른 점:

| | 기본 (`start_backend.sh`) | `--foreground` (systemd) |
|---|---|---|
| 프로세스 | `setsid nohup`으로 분리 | `exec`로 **이 프로세스가 uvicorn이 됨** |
| pid | `<release>/runtime/backend.pid` | systemd의 MAINPID |
| 로그 | `<release>/runtime/backend.log` | **journal** (`journalctl -u wes-backend`) |
| 기존 인스턴스 | SIGTERM 후 재기동 | 건드리지 않음 (재시작은 systemd 몫) |
| health 확인 | `/api/health` 응답까지 대기 | 하지 않음 (`systemctl status` + curl) |

**로그는 한 곳에만 쌓입니다.** foreground 모드는 자체 로그 파일을 쓰지 않으므로
journal과 `runtime/backend.log`가 같은 내용을 두 번 갖는 일은 없습니다.
(파이프라인 자체 로그는 이와 무관하게 run 디렉터리에 따로 남습니다.)

`current`를 가리키므로 **release를 바꿔도 unit은 그대로**입니다.

### 4-2. `KillMode=process` — 이유가 있는 선택

backend는 `main.sh`를 `start_new_session=True`로 띄웁니다. 즉 파이프라인은
**backend가 죽어도 살아남도록** 설계돼 있고, `worker.recover_orphans()`가
재기동 후 DB row를 다시 붙입니다(`backend/app/services/pipeline_executor.py`,
`worker.py`의 주석).

systemd 기본값(`KillMode=control-group`)을 쓰면 서비스를 재시작할 때 cgroup의
**모든** 프로세스가 죽습니다 — 웹 서버 하나 재시작하려고 몇 시간짜리 WES 분석을
같이 죽이는 셈입니다. 그래서 main process에만 신호를 보냅니다.

> 반대급부도 분명합니다: `systemctl stop` 후에도 파이프라인이 계속 돌면서
> backend 없이 run 디렉터리에 씁니다. 다음 기동 때 다시 붙습니다.
> **실행을 끝내려면 API로 job을 cancel하세요.**

### 4-3. 설치

```bash
"$DEPLOY_ROOT/current/script/install_systemd_service.sh" --dry-run   # 먼저 확인
"$DEPLOY_ROOT/current/script/install_systemd_service.sh"             # 설치
```

**sudo가 필요한 지점은 세 개뿐**이고, 실행 전에 각각 화면에 출력됩니다.

```
sudo install -D -m 0644 <렌더링된 unit> /etc/systemd/system/wes-backend.service
sudo systemctl daemon-reload
sudo systemctl enable wes-backend.service
```

installer는 **enable만 하고 start하지 않습니다.** 준비되지 않은 서버를 부팅마다
올리지 않기 위해서입니다. preflight를 통과시킨 뒤 직접 시작하세요.

```bash
"$DEPLOY_ROOT/current/script/server_preflight.sh"
sudo systemctl start wes-backend
sudo systemctl status wes-backend
curl -s http://127.0.0.1:8000/api/health
journalctl -u wes-backend -f
```

sudo를 쓸 수 없으면 user unit도 됩니다.

```bash
script/install_systemd_service.sh --user
```

단 user unit은 **로그인할 때** 시작합니다. 로그인 없이 부팅 시 올리려면 lingering을
한 번 켜야 하고, 그것은 권한이 필요합니다.

```bash
sudo loginctl enable-linger "$(id -un)"
```

### 4-4. 포트별 설정과 stop/restart

머신별 값(포트, bind 주소, storage 경로)은 unit이 아니라 운영자 파일에 둡니다.
unit이 있으면 읽고 없으면 무시합니다.

```
<deploy root>/shared/backend.env      # 예: WES_BACKEND_PORT=8000
```

| 동작 | 명령 | 결과 |
|---|---|---|
| 시작 | `systemctl start wes-backend` | `start_backend.sh --foreground` 실행 |
| 정지 | `systemctl stop wes-backend` | uvicorn에 SIGTERM. 실행 중 파이프라인은 4-2 참고 |
| 재시작 | `systemctl restart wes-backend` | 정지 후 시작. release 교체 후 쓰는 명령 |
| 비정상 종료 | (자동) | `Restart=on-failure`, 5초 후 재시도 |

systemd로 관리하기 시작했다면 **손으로 `start_backend.sh`를 또 띄우지 마세요.**
포트가 겹치고, 그 경우 script가 포트 점유를 감지해 거부합니다.

---

## 5. 두 번 겪은 사고와, 지금 그것을 막는 것

### 5-1. backend가 분석 도구 PATH를 상속받지 못한 경우

2026-09-17, `00_input_validation`이 bwa·samtools·gatk·bcftools·tabix·bgzip·
mosdepth·fastqc **여덟 개를 전부 missing**으로 판정했습니다. 도구는 모두
`~/miniconda3/envs/wes-tools/bin/`에 있었고, **uvicorn process의 PATH에만**
없었습니다.

구조를 알면 당연한 결과입니다.

```
FastAPI (wes-dev의 python)
   └─ worker → main.sh (subprocess)
        └─ PATH에서 bwa / samtools / gatk 를 찾는다
```

인터프리터는 **경로로 정해지고**, 분석 도구는 **PATH로 정해집니다.**
`start_backend.sh`는 둘을 각각 고정하고, `WES_TOOLS_BIN`이 존재하지 않으면
**기동 자체를 거부**합니다. 기동 후에도 `runMode=full`인데 `bwa`가 없으면
경고를 냅니다.

반대 방향의 함정도 있습니다(2026-09-04): `wes-tools/bin`을 PATH 맨 앞에 붙이면
그 안의 `python`이 선택되어 uvicorn을 찾지 못합니다. 그래서 인터프리터는
**항상 절대경로로** 부릅니다.

### 5-2. release에 capture BED가 없던 경우

새 release를 만들 때 `resources/capture_beds`를 옮기지 않아 registry가 가리키는
BED가 존재하지 않았고, `resource_bundle` validation이 실패했습니다.
`server_preflight.sh`가 **confirmed kit의 BED 존재와 SHA-256 일치**를 직접
확인하므로, 같은 상태라면 run 제출 전에 FAIL로 드러납니다.

---

## 6. release 교체 절차

```bash
DEPLOY_ROOT=~/sideprojects/wes-web
NEW=$DEPLOY_ROOT/releases/<새 release id>
OLD=$(readlink -f "$DEPLOY_ROOT/current")
```

- [ ] 새 release 전개 (3-1)
- [ ] `backend/.env` 배치 — `cp "$OLD/backend/.env" "$NEW/backend/.env"`
- [ ] persistent symlink 3개 연결 (3-5)
- [ ] **`resources/capture_beds` 준비** — `cp -a "$OLD/resources" "$NEW/"` 또는
      `"$NEW/script/download_capture_beds.sh" all`
- [ ] reference 경로가 그대로 유효한지 (`~/references/GRCh38`은 release 밖이라 안전)
- [ ] `"$NEW/script/server_preflight.sh"` — FAIL 0
- [ ] `ln -sfn "$NEW" "$DEPLOY_ROOT/current"`
- [ ] 기동 — systemd를 쓰면 `sudo systemctl restart wes-backend`,
      아니면 `"$DEPLOY_ROOT/current/script/start_backend.sh"`
- [ ] health의 `pipelineScript` 경로가 **새 release**를 가리키는지 확인
- [ ] 실행 중인 run이 없을 때 교체할 것 (진행 중 run은 이전 release 경로를 참조)

`runtime/`은 release마다 새로 생기므로 stale PID·로그가 섞이지 않습니다.
systemd로 운영 중이라면 unit이 `current`를 가리키므로 **unit은 수정하지 않습니다.**

> 새 release에서 `bootstrap_server.sh`를 다시 돌려도 됩니다. shared 연결과 `.env`
> 확인을 대신 해 주고, 이미 있는 것은 건드리지 않습니다. 다만 `current` 전환은
> 하지 않으므로 위 `ln -sfn`은 여전히 사람이 하는 단계입니다.

---

## 7. 아직 자동화되지 않은 것

bootstrap이 **일부러** 대신하지 않는, 서버마다 사람이 한 번은 해야 하는 일입니다.
각각 이유가 있습니다.

| 항목 | 왜 자동화하지 않는가 |
|---|---|
| **conda 배포판 설치** (3-2) | 제3자 installer이고, 설치 위치·채널 정책은 머신 소유자의 결정입니다. bootstrap은 없으면 안내만 합니다 |
| **GRCh38 reference bundle**과 BWA index (3-3) | 수십 GB이고 URL이 이 저장소에 고정돼 있지 않습니다. 잘못된 reference는 없는 것보다 나쁩니다 |
| **Agilent V8 capture kit** (3-3) | SureDesign 계정 로그인과 수동 확인이 필요합니다. 준비하지 않아도 배포는 정상입니다 |
| **`.env` 값**, 특히 `WES_CONTIG_STYLE` (3-4) | `.fai` 첫 열을 사람이 직접 보고 선언해야 합니다. 추측하면 안 되는 값입니다 |
| **InterVar / ANNOVAR humandb** | 자체 라이선스 조건이 있습니다. 쓸 때만, `backend/.env.example` 참고 |
| **`current` 전환** | release 교체는 의도적인 결정입니다. bootstrap의 부작용이 되면 안 됩니다 |

bootstrap은 이 항목들을 **끝에 목록으로 다시 출력**하고, preflight가 그중 검사
가능한 것을 다시 확인합니다.

## 8. 향후 개선 후보 (미적용)

- `resources/capture_beds`를 release마다 복사하는 대신 `shared/resources`에 두고
  release에서 symlink로 연결. registry 경로가 realpath로 해석되므로 동작할
  것으로 보이지만 **서버에서 아직 검증하지 않았습니다.**
- `/api/health`와 별개의 full-execution readiness endpoint.
  현재 그 역할은 `server_preflight.sh`가 CLI로만 합니다.
- release 교체 자체의 script화 (지금은 체크리스트 + `ln -sfn`).

### 제품화 관점 — 지금은 하지 않는다

현재 deployment automation은 **Linux VM/서버용 shell 기반**입니다.
provisioning(`bootstrap_server.sh`) · 검사(`server_preflight.sh`) ·
기동(`start_backend.sh`) · 프로세스 관리(systemd) 네 조각으로 재현성을 확보합니다.

실제 multi-customer / commercial distribution 단계로 간다면 Docker/OCI image,
Docker Compose, configuration management(Ansible 등), cloud image/IaC를 검토할
수 있습니다. 그중 Docker는 별도 항목으로 9장에 정리했습니다.

**다만 지금은 어느 것도 도입하지 않습니다.** 서버 한 대, 운영자 한 명 규모에서
컨테이너 런타임과 orchestration을 얹으면 재현성보다 인프라 복잡도가 먼저
늘어납니다. 현재 구조로 "새 서버에서 같은 순서를 밟으면 같은 상태가 된다"가
성립하는지를 먼저 확인합니다.

> 이 문단은 **계획이지 구현이 아닙니다.** 이 저장소에는 Dockerfile도,
> compose 파일도, Ansible playbook도 없습니다.

---

## 9. Future Dockerization — 후속 검토 예정 (현재 미구현)

> **상태: 검토 예정. 결정된 사항이 아닙니다.**
> 이 저장소에는 `Dockerfile`도 `compose.yml`도 container 설정도 **없습니다.**
> 이 장은 "나중에 별도 milestone에서 판단하기 위한 메모"입니다.

### 9-1. 현재 결정

- **지금은 native Ubuntu/Linux deployment를 먼저 완성한다.**
- `bootstrap_server.sh` + `server_preflight.sh` + `start_backend.sh` + systemd
  구조로 **재현 가능한 native deployment**를 확보한다.
- tail 5M Full Run 및 현재 portfolio 기능 검증을 먼저 완료한다.
- Docker 도입 여부는 **그 이후 별도 milestone에서 결정한다.**

### 9-2. 검토하려는 이유

- backend process의 **PATH 누락으로 pipeline tool을 찾지 못한 실제 장애**가 있었다
  (5-1). image에 고정하면 이 부류의 실수가 구조적으로 줄어든다.
- Python/runtime tool 버전을 **서버마다 다시 맞추는 문제**를 줄이고 싶다.
- frontend / backend / pipeline의 **release 단위를 더 명확히 고정**하고 싶다.
- 다른 Linux 서버에서도 **동일 실행환경을 재현**하기 쉽게 만들고 싶다.

### 9-3. 지금 지키는 Docker-ready 원칙

Docker를 쓰지 않더라도 **지금 지켜 두면 나중에 비용이 크게 줄어드는** 것들이고,
현재 구조가 이미 이렇게 되어 있습니다.

- application code에 특정 사용자/home/서버 경로를 **하드코딩하지 않는다.**
- 환경별 값은 **environment variable / `.env`로 전달**한다.
- reference·capture BED 등 **biological resource를 application과 분리**한다 (1장).
- `runs` · `uploads` · DB는 **persistent data로 분리**한다 (2장).
- **runtime resource와 application source를 구분**한다 (1장의 자산 1 vs 3).
- preflight는 source of truth(`main.sh`, capture registry)를 **중복 구현하지 않는다.**

### 9-4. 검토 시 예상 구조

| 구분 | 내용 |
|---|---|
| Docker image | FastAPI + Python dependencies + WES pipeline tools + application/pipeline code |
| external volume/resource | GRCh38, known-sites, capture BED |
| persistent volume | `runs`, `uploads`, DB |
| Docker Compose | container 실행 설정, volume mount, environment, restart policy |

### 9-5. 현재 native 구성과의 예상 관계

- `server_preflight.sh` — 가능한 범위에서 **재사용 검토** (검사 대상은 같다)
- `start_backend.sh`의 직접 uvicorn 기동 역할 — container **ENTRYPOINT/CMD로 이동 가능**
- systemd 역할의 일부 — Docker/Compose **restart policy로 대체 가능**
- `bootstrap_server.sh` — **Docker host/resource provisioning 쪽으로 축소 가능**

### 9-6. milestone 시작 조건

넷이 모두 충족된 뒤에 시작합니다.

1. 현재 native deployment가 정상 상태
2. **tail 5M Full Run 성공**
3. 현재 backend/Agent 기능 검증 완료
4. 기준이 되는 정상 실행 결과(**golden environment**) 확보

### 9-7. 전환 시 검증 계획

- 작은 **smoke test부터** 수행한다
- native 환경과 Docker 환경의 **pipeline/tool version 비교**
- 동일 입력에 대한 **주요 산출물/validation 결과 비교**
- **reference/BED SHA-256이 동일한지** 확인
- persistent volume **삭제/재생성 시 데이터 보존 동작** 확인

> Docker는 현재 구현도 확정 결정도 아니며,
> **후속 deployment hardening / 학습 milestone**입니다.
