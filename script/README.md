# WES Pipeline

`script/main.sh`는 이 프로젝트의 **실제 WES 분석 파이프라인**입니다.

WES(Whole Exome Sequencing, 전장 엑솜 시퀀싱)는 사람 DNA 중 단백질을 만드는 부분(엑솜, 전체의 약 1~2%)만
집중적으로 읽어내는 방법입니다. 이 스크립트는 시퀀싱 장비가 만든 원시 파일(FASTQ)을 받아
"이 사람의 DNA는 표준 유전체와 어디가 다른가"를 정리한 파일(VCF)까지 만들어 냅니다.

> Backend(FastAPI)는 이 스크립트를 **실행시키고 상태 파일을 읽을 뿐**입니다.
> 분석 로직 자체는 전부 `main.sh` 안에 있고, Python으로 다시 구현하지 않았습니다.

## 현재 버전

```
PIPELINE_NAME    = variant-pipeline-lab-wes
PIPELINE_VERSION = 1.2.0
JSON_SCHEMA_VERSION = 1.0     (상태 JSON 파일 형식 버전)
```

파일 하나로 되어 있습니다 (`script/main.sh`, 약 5,200줄).

## 분석 흐름

`main.sh` 안의 `STEP_KIND` 표에 선언된 실제 단계입니다.
**core**는 반드시 실행되고, **optional**은 설정에서 켰을 때만 실행됩니다(기본값 꺼짐).

| 단계 ID | 구분 | 하는 일 |
|---|---|---|
| `00_input_validation` | core | 필요한 도구·입력 파일·참조 유전체·디스크/메모리가 준비됐는지 사전 점검 |
| `01_raw_qc` | core | 원시 FASTQ의 품질 확인 (FastQC) — 읽기가 얼마나 정확한지 |
| `02_preprocessing` | core | 품질이 낮은 부분을 잘라내는 트리밍 (기본 설정은 건너뜀) |
| `03_alignment` | core | FASTQ의 짧은 조각(read)들을 표준 유전체의 어느 위치인지 찾아 붙임 (BWA) |
| `04_processing` | core | 중복 read 표시(MarkDuplicates)와 품질 점수 보정(BQSR) |
| `05_coverage_qc` | core | 목표 영역이 얼마나 깊고 고르게 읽혔는지 계산 (mosdepth) |
| `06_variant_calling` | core | 표준 유전체와 다른 염기를 찾아 VCF 파일 생성 (GATK) — **핵심 결과물** |
| `08_filtering` | optional | 신뢰도가 낮은 변이를 걸러냄 |
| `10_annotation` | optional | 각 변이가 어떤 유전자·어떤 의미인지 정보를 붙임 |
| `11_intervar` | optional | ACMG 기준으로 변이의 병원성을 자동 분류 (InterVar) |
| `99_finalization` | core | 결과 목록·재현 정보·요약 보고서 정리 |

- 번호 `07`, `09`는 존재하지 않습니다.
- 핵심 완료 지점은 `06_variant_calling`이 만드는 raw VCF입니다.
- optional 단계가 실패해도 core 결과는 유지되며, 실행 전체가 실패로 바뀌지 않습니다.

## 실행 방법

저장소 최상위 폴더에서 실행합니다.

**사전 검증만 (분석 도구를 하나도 실행하지 않음)**

```bash
bash script/main.sh --config <run_config.json> --check-only
```

**전체 실행**

```bash
bash script/main.sh --config <run_config.json>
```

> ⚠️ **전체 실행은 Linux WES 환경에서만 하세요.**
> bwa, samtools, gatk, bcftools, tabix, bgzip, mosdepth, fastqc가 `PATH`에 있어야 하고,
> GRCh38 참조 유전체와 각종 인덱스, known-sites 파일이 모두 준비되어 있어야 합니다.
> 이 파이프라인은 **도구를 스스로 설치하지 않습니다.**
> 준비물은 `docs/MAIN_SH_COMPLETE_GUIDE.md`의 "6. 실행 방법과 CLI option", "29. Linux smoke test 절차"를 보세요.

## 주요 옵션

`main.sh --help` 출력 기준입니다.

| 옵션 | 설명 |
|---|---|
| `--config FILE` | 실행 설정 JSON 파일. `--help` 외에는 **필수** |
| `--check-only` | 모든 사전 검증만 수행하고, 분석 도구를 실행하기 전에 멈춤 |
| `--resume` | 기존 실행 폴더에 다시 들어가, 이미 정상 완료된 단계는 건너뜀 |
| `--from-step ID` | 지정한 단계부터 시작 (앞 단계 산출물은 그래도 검증함) |
| `--to-step ID` | 지정한 단계까지만 실행하고 멈춤 |
| `--help` | 사용법 출력 |

## 주요 입력

### 1. `run_config.json` — 실행 설정

예시 템플릿: `config/run_config.grch38.template.json`

주요 항목:

| 키 | 설명 |
|---|---|
| `run_id` | 실행 식별자. 영숫자로 시작하고 영숫자·`.`·`_`·`-`만 사용 |
| `samplesheet` | samplesheet.csv 경로 |
| `output_root` | 결과를 만들 상위 폴더. 실제 결과는 `<output_root>/<run_id>/`에 생성 |
| `capture_kit` | `{ "id": ..., "registry": ... }` — 아래 3번 참고 |
| `resource_bundle` | 참조 유전체·known-sites 등 리소스 경로 묶음 |
| `optional_steps` | `filtering` / `annotation` / `intervar` 켜기·끄기 |
| `threads`, `java_mem_gb`, `trim_mode` 등 | 실행 자원과 동작 설정 |

### 2. `samplesheet.csv` — 어떤 파일을 분석할지

필수 열:

```csv
sample,lane,fastq_1,fastq_2
DEMO01,L001,/path/to/DEMO01_R1.fastq.gz,/path/to/DEMO01_R2.fastq.gz
```

선택 열: `rg_id`, `library`, `platform`, `platform_unit`, `patient`, `sex`, `status`
(적지 않으면 `sample.lane` / `sample` / `ILLUMINA` / `lane`이 자동으로 채워집니다.)

규칙:

- FASTQ는 `.fastq.gz` 또는 `.fq.gz`여야 하고, 실제 gzip 파일이어야 합니다
- **한 번의 실행에는 생물학적 샘플 1개만** 허용합니다 (여러 lane은 허용)

### 3. capture kit registry — 어떤 엑솜 키트를 썼는지

`config/capture_kits.grch38.json`

엑솜 캡처 키트는 "DNA 중 어느 영역을 집중적으로 읽을지" 정하는 실험 시약입니다.
어떤 키트를 썼는지에 따라 분석 대상 영역(BED 파일)이 달라집니다.

`run_config.json`에 키트 **ID만** 적으면 `main.sh`가 이 레지스트리에서
BED 파일 경로와 제조사·버전·SHA-256 체크섬 같은 정보를 자동으로 찾아옵니다.

```json
"capture_kit": {
  "id": "idt_xgen_exome_hyb_panel_v2",
  "registry": "/abs/path/to/config/capture_kits.grch38.json"
}
```

등록된 키트: IDT xGen Exome Hyb Panel v2, Twist Exome 2.0, Roche KAPA HyperExome V2 (이상 `confirmed`),
Agilent SureSelect V8 (`unconfirmed` — BED 확인 전까지 사용 불가).

BED 파일 자체는 git에 포함되지 않으며 `script/download_capture_beds.sh`로 내려받습니다.
자세한 내용은 `docs/CAPTURE_BED_RESOURCES.md`를 보세요.

### 4. reference / resource bundle

`run_config.json`의 `resource_bundle`에 적습니다.
`00_input_validation`이 다음을 모두 확인하며, 하나라도 없으면 실패합니다.

- 참조 유전체 FASTA와 그 인덱스 `.fai`, 시퀀스 사전 `.dict`
- BWA 인덱스 5종 (`.amb .ann .bwt .pac .sa`)
- known-sites VCF 1개 이상과 각각의 인덱스(`.tbi` 또는 `.csi`) — BQSR에 필수
- target BED / coverage BED (capture kit registry가 제공) 및 SHA-256 일치
- `assembly`와 `contig_style` 선언값이 실제 파일과 맞는지

## 주요 상태 / 산출물

결과는 `<output_root>/<run_id>/` 아래에 만들어집니다.

| 경로 | 설명 |
|---|---|
| `status/run_status.json` | 실행 전체의 현재 상태. **Backend가 상태를 읽는 기준 파일** |
| `status/steps/<step_id>.json` | 단계별 상세 상태 — 성공/실패, 소요 시간, 경고·실패 메시지, 입출력 |
| `metrics/<step_id>.json` | 단계별 품질 지표 숫자 (예: 평균 깊이, 정렬률) |
| `artifacts/<step_id>.json` | 단계가 만든 결과 파일 목록 (파일 ID, 상대 경로, 크기) |
| `artifact_manifest.json` | 위 artifacts를 전부 합친 목록 |
| `provenance.json` | 재현에 필요한 정보 — 설정 전문, 도구 버전, 리소스 체크섬 |
| `core_summary.json` | 기계가 읽는 실행 요약 |
| `methods.md` | 사람이 읽는 분석 방법 기록 |
| `final_validation.tsv` | 최종 점검 결과 표 (통과/경고/실패) |
| `logs/pipeline.log` | 사람이 읽는 전체 실행 로그 |
| `logs/stage_status.tsv`, `logs/execution_trace.tsv` | 단계 상태 변화와 소요 시간 기록 |
| `logs/commands.sh`, `logs/software_versions.txt`, `logs/resource_sha256.txt` | 실행된 명령, 도구 버전, 리소스 해시 |
| `config/run_config.snapshot.json` | 실행 시점 설정 전체와 설정 식별 해시 |
| `config/normalized_manifest.json` | samplesheet를 정리한 구조화 정보 |
| `00_input_validation/` … `06_variant_calling/` | 각 core 단계의 실제 결과 파일 |
| `optional/filtering|annotation|intervar/` | optional 단계 결과 (core와 분리 보관) |
| `.run.lock/` | 같은 실행이 동시에 두 번 돌지 않게 막는 잠금 폴더 |
| `RUN_COMPLETED` / `RUN_COMPLETED_WITH_WARNINGS` / `RUN_FAILED` / `RUN_CANCELLED` | 최종 결과를 한눈에 알려주는 표시 파일 (항상 정확히 하나) |

### 상태 판단은 로그가 아니라 JSON으로

`logs/pipeline.log`는 **사람이 읽는 기록**입니다.
프로그램이 상태를 판단할 때는 반드시 `status/run_status.json`과 `status/steps/*.json`을 읽어야 합니다.
Backend도 그렇게 동작합니다.

## Backend와의 관계

```
Frontend (브라우저)
   ↓  API
FastAPI
   ↓
Worker
   ↓
PipelineExecutor
   ↓  bash script/main.sh --config ... [--check-only]
script/main.sh
   ↓  status/run_status.json, status/steps/*.json 생성
FastAPI (상태 읽기)
   ↓
Frontend
```

Backend는 `main.sh`를 **수정하지 않습니다.** 다음 규칙을 지킵니다.

- 실행 설정(`run_config.json`)과 `samplesheet.csv`를 만들어서 넘겨줌
- 실행은 별도 프로세스로 띄우고, 끝날 때까지 웹 요청을 붙잡지 않음
- 상태는 로그 문자열을 해석하지 않고 상태 JSON에서만 읽음
- 실행 1건당 `run_id` 하나를 새로 발급 (기존 실행 폴더를 덮어쓰지 않음)

## 현재 검증 상태

| 항목 | 상태 |
|---|---|
| 문법 검사 (`bash -n`), `--help`, 코드↔문서 정합성 | **완료** |
| 웹 연동에서 `--check-only` 실행 (Windows + Git Bash) | **확인됨** — 실제 실행되어 `run_status.json`과 `00_input_validation` 결과 생성 |
| 실제 리소스로 `--check-only` 통과 | **미완료** — GRCh38 참조 유전체·known-sites가 아직 준비되지 않음 |
| 부분/전체 WES 실행 (`full` 모드) | **미완료** |

위 표의 아래 두 줄은 `docs/MAIN_SH_COMPLETE_GUIDE.md`의 "28. 현재 한계" 장에 기록된 내용과 같습니다.

Windows 개발 PC에는 WES 분석 도구와 참조 유전체가 없기 때문에
`--check-only`를 돌리면 다음과 같은 실패가 나오며, 이는 **현재 환경에서 정상**입니다.

```
[required_tools]  missing from PATH: bwa samtools gatk bcftools tabix bgzip mosdepth fastqc
[resource_bundle] reference_fasta missing or empty: ...
                  known_sites is empty; BQSR is a core step and requires known sites
```

## 이 폴더의 다른 파일

| 파일 | 설명 |
|---|---|
| `main.sh` | **메인 파이프라인.** Backend가 실행하는 대상 |
| `download_capture_beds.sh` | capture kit BED 파일을 공식 배포처에서 내려받고 SHA-256으로 검증. 이미 올바른 파일이 있으면 건너뜀 |
| `run_vcf_annotation.sh` / `run_vcf_annotation.py` | VEP·ClinVar·gnomAD·PanelApp을 이용한 **별도의 VCF 주석 도구**. `main.sh`가 호출하지 않는 독립 스크립트이며, 현재 웹 연동 대상이 아닙니다 |

## 더 자세한 내용

- `docs/MAIN_SH_COMPLETE_GUIDE.md` — 파이프라인 종합 설명서 (설정 전체 설명, samplesheet 규칙, 단계별 상세, 현재 한계, Linux smoke test 절차)
- `docs/CAPTURE_BED_RESOURCES.md` — capture kit BED 파일 준비 방법
