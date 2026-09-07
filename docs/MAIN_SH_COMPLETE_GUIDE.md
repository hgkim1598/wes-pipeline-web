# main.sh 종합 설명서 — germline WES 파이프라인 전체 안내

> [!IMPORTANT]
> 이 문서는 현재 `script/main.sh`의 코드 구조와 설계 의도를 설명합니다.
> 코드 감사와 정적·mock 검증은 완료되었지만,
> 실제 Linux 서버에서 BWA, samtools, GATK, mosdepth 등을 사용한
> subset 및 full WES 실행은 아직 수행되지 않았습니다.
> 따라서 실제 도구 버전, index 파일명 생성 방식, 서버 자원 사용량,
> 전체 파이프라인의 실제 완주 여부는 Linux smoke test에서 최종 확인해야 합니다.

## 엔진과 profile은 다릅니다

이 문서를 읽을 때 두 가지를 반드시 구분하세요.

| 구분 | 내용 |
|---|---|
| **pipeline engine** (`main.sh`) | **config-driven 범용 germline WES 엔진**입니다. assembly, reference 경로, capture kit, 사람 이름, 서버 경로 중 **어느 것도 코드에 하드코딩되어 있지 않습니다.** 다른 호환 bundle은 **코드가 아니라 config를 바꿔서** 쓸 수 있습니다 |
| **current recommended profile** | **GRCh38**입니다. 이 문서의 config 예시가 GRCh38 기준이고, InterVar build 매핑도 현재는 `GRCh38 -> hg38` 하나만 등록되어 있습니다. 이는 **권장 profile이지 엔진의 제약이 아닙니다** |

엔진은 특정 assembly만 허용하지 않습니다.
대신 **선언되지 않았거나 구조적으로 호환되지 않는 bundle**을 preflight에서 막습니다.

## 현재 검증 상태

검증에는 세 단계가 있고, 지금은 1단계까지만 끝났습니다.

| 단계 | 무엇을 확인하는가 | 상태 |
|---|---|---|
| **1. static validation** | `bash -n`, `--help`, 코드↔문서 정합성, 코드 정적 검토 | **완료** |
| **2. resource validation** (`--check-only`) | 선언한 bundle의 파일이 실제로 존재하고 구조적으로 호환되는가 | **미완료** — 실제 config와 resource가 아직 없음 |
| **3. execution validation** | subset/full WES를 실제 도구로 완주하는가 | **미완료** |

| 검증 항목 | 상태 |
|---|---|
| 단일 `main.sh` 통합 | 완료 |
| 코드 정적 검토 | 완료 |
| mock/fixture 검증 | 완료 |
| 코드 BLOCKER | 0건 |
| 코드 HIGH | 0건 |
| **GRCh38 profile `--check-only`** | **미완료** |
| Linux 실제 실행 | **미완료** |
| subset smoke test | **미완료** |
| full WES 실행 | **미완료** |
| optional 단계 실제 실행 | **미완료** |

> [!WARNING]
> 따라서 이 문서 어디에서도 **"GRCh38 profile이 검증되었다"고 말하지 않습니다.**
> GRCh38은 **현재 문서화된 권장 profile**일 뿐이고,
> 실제 resource로 `--check-only`나 실행을 마친 상태가 아닙니다.

"코드에 결함이 발견되지 않았다"와 "실행이 성공한다"는 서로 다른 명제입니다.
이 문서의 모든 설명은 **코드를 읽어서 확인한 사실**이며,
실행해 봐야만 알 수 있는 항목은 [28장](#28-현재-한계)에 따로 모아 두었습니다.

---

## 목차

1. [문서의 목적](#1-문서의-목적)
2. [파이프라인의 목표와 현재 범위](#2-파이프라인의-목표와-현재-범위)
3. [전체 분석 흐름](#3-전체-분석-흐름)
4. [입력 파일과 reference resource](#4-입력-파일과-reference-resource)
5. [main.sh의 전체 구조](#5-mainsh의-전체-구조)
6. [실행 방법과 CLI option](#6-실행-방법과-cli-option)
7. [config 전체 설명](#7-config-전체-설명)
8. [samplesheet 전체 설명](#8-samplesheet-전체-설명)
9. [입력 검증](#9-입력-검증)
10. [Raw QC](#10-raw-qc)
11. [preprocessing과 trimming 분기](#11-preprocessing과-trimming-분기)
12. [Alignment](#12-alignment)
13. [Processing](#13-processing)
14. [Coverage QC](#14-coverage-qc)
15. [Variant Calling](#15-variant-calling)
16. [Optional filtering](#16-optional-filtering)
17. [Optional annotation](#17-optional-annotation)
18. [Optional InterVar](#18-optional-intervar)
19. [함수 간 handoff](#19-함수-간-handoff)
20. [상태, 로그, metrics, artifact, provenance](#20-상태-로그-metrics-artifact-provenance)
21. [resume와 멱등성](#21-resume와-멱등성)
22. [part 파일, atomic rename, lock, marker](#22-part-파일-atomic-rename-lock-marker)
23. [core와 optional 상태 정책](#23-core와-optional-상태-정책)
24. [조원 코드 통합 판단](#24-조원-코드-통합-판단)
25. [옵션과 파라미터 선택 이유](#25-옵션과-파라미터-선택-이유)
26. [결과 파일 읽는 방법](#26-결과-파일-읽는-방법)
27. [오류가 났을 때 확인 순서](#27-오류가-났을-때-확인-순서)
28. [현재 한계](#28-현재-한계)
29. [Linux smoke test 절차](#29-linux-smoke-test-절차)
30. [향후 단계 분리와 백엔드 연동 계획](#30-향후-단계-분리와-백엔드-연동-계획)
31. [전체 과정 요약](#31-전체-과정-요약)
32. [용어 사전](#32-용어-사전)

---

## 1. 문서의 목적

이 문서 하나가 `script/main.sh`에 대한 **유일한 설명 문서**입니다.

예전에는 설계 근거(`MAIN_SH_ARCHITECTURE.md`), 함수 계약
(`MAIN_SH_FUNCTION_CONTRACT.md`), 실행 매뉴얼(`MAIN_SH_USAGE.md`),
코드 보존 기록(`MAIN_SH_CODE_PRESERVATION.md`)이 따로 있었습니다.
같은 내용이 네 곳에 흩어져 서로 조금씩 달라지는 문제가 있어,
**네 문서의 고유 내용을 모두 이 문서로 옮기고 원본은 삭제**했습니다.

### 이 문서가 답하는 질문

- 이 파이프라인은 무엇을 입력받아 무엇을 만드는가
- 각 분석 단계가 생물학적으로 무슨 일을 하는가
- 코드의 각 함수가 어떤 역할을 하고, 무엇을 검증하고, 언제 실패하는가
- 왜 그 옵션과 그 기본값을 선택했는가
- 조원들이 따로 작성한 코드를 어떤 기준으로 합치고, 남기고, 껐는가
- 어떻게 실행하고, 결과를 어떻게 읽고, 문제가 생기면 어디를 보는가
- 지금 무엇이 검증되었고 무엇이 아직 검증되지 않았는가

### 읽는 사람

**바이오인포매틱스를 처음 접하는 사람**을 기준으로 씁니다.
WES, read, FASTQ, BAM, VCF 같은 용어는 처음 나올 때 설명하고,
[32장 용어 사전](#32-용어-사전)에 다시 모아 두었습니다.

### 코드를 가리키는 방식

이 문서는 코드 위치를 **함수 이름**으로 가리킵니다.
예: `위치: script/main.sh > run_processing()`
줄 번호는 코드를 조금만 고쳐도 어긋나므로 기준으로 쓰지 않습니다.

> [!NOTE]
> `script/main.sh` 안의 주석과 `--help` 출력에는 아직
> `docs/MAIN_SH_USAGE.md`, `docs/MAIN_SH_CODE_PRESERVATION.md`,
> `docs/MAIN_SH_ARCHITECTURE.md`를 가리키는 문장이 남아 있습니다.
> 이번 정리에서 **코드는 한 글자도 수정하지 않았기 때문**입니다.
> 그 문서들의 내용은 전부 이 문서로 옮겨졌으므로,
> 코드에서 위 파일명을 보게 되면 이 문서의 다음 장을 보면 됩니다.
>
> | 코드가 가리키는 옛 문서 | 지금 봐야 할 곳 |
> |---|---|
> | `MAIN_SH_USAGE.md` | [6장](#6-실행-방법과-cli-option), [7장](#7-config-전체-설명), [8장](#8-samplesheet-전체-설명), [27장](#27-오류가-났을-때-확인-순서) |
> | `MAIN_SH_CODE_PRESERVATION.md` | [24장](#24-조원-코드-통합-판단) |
> | `MAIN_SH_ARCHITECTURE.md` | [5장](#5-mainsh의-전체-구조), [20장](#20-상태-로그-metrics-artifact-provenance), [22장](#22-part-파일-atomic-rename-lock-marker) |

---

## 2. 파이프라인의 목표와 현재 범위

### 2.1 무엇을 하는 파이프라인인가

사람의 **엑솜(exome)** 을 시퀀싱한 원시 데이터를 받아,
그 사람이 태어날 때부터 가지고 있는 유전 변이 목록을 만드는 파이프라인입니다.

한 문장으로:

> "DNA 서열을 읽은 기계 출력 파일을 받아서, 표준 인간 유전체와 비교했을 때
> 어디가 다른지를 근거와 함께 정리한 목록을 만든다."

### 2.2 먼저 알아야 할 용어

| 용어 | 쉬운 설명 |
|---|---|
| **DNA / 염기서열** | 생물의 설계도. `A`, `T`, `G`, `C` 네 글자가 길게 이어진 문자열이라고 보면 됩니다. |
| **유전체(genome)** | 한 사람이 가진 DNA 전체. 사람은 약 30억 글자입니다. |
| **엑손(exon)** | 유전체 중 실제로 단백질을 만드는 데 쓰이는 구간. |
| **WES** (Whole Exome Sequencing, 전장 엑솜 시퀀싱) | 유전체 전체가 아니라 엑손만 골라 읽는 방식. 전체의 1~2%지만 질병 관련 변이가 많이 모여 있어 비용 대비 효율이 좋습니다. |
| **read** | 시퀀싱 기계가 한 번에 읽어낸 짧은 DNA 조각. 보통 100~150 글자. |
| **paired-end** | DNA 조각 하나의 **양쪽 끝**을 각각 읽는 방식. 앞쪽을 읽은 파일이 R1, 뒤쪽이 R2이며 둘이 한 쌍입니다. 양끝을 알면 유전체 위 위치를 훨씬 정확히 찾을 수 있습니다. |
| **lane** | 시퀀싱 기계 안의 물리적 통로. 같은 검체를 여러 lane에 나눠 넣어 더 많이 읽는 일이 흔합니다. |
| **germline 변이** | 부모에게 물려받아 몸의 **모든 세포**가 가진 변이. 반대말은 somatic(암세포 등 일부 세포에서만 생긴 변이)이며 somatic은 이 파이프라인의 범위 밖입니다. |
| **SNV** (Single Nucleotide Variant) | 한 글자만 바뀐 변이. 예: `A` → `G`. |
| **short Indel** | 짧은 삽입(insertion) 또는 결실(deletion). 예: `AT` → `A`. |

### 2.3 현재 권장 profile

| 항목 | 현재 값 |
|---|---|
| 분석 종류 | germline WES, paired-end Illumina |
| 한 run당 biological sample 수 | **1개** (같은 sample의 여러 lane은 허용) |
| 찾는 변이 | SNV, short Indel |
| reference genome | **GRCh38** — 현재 문서화된 권장값. 구체적인 FASTA release는 config의 `resource_bundle`에서 선언 |
| capture kit / target BED | 선언한 bundle과 좌표계가 일치하는 whole-exome target BED (config에서 선언) |
| known-sites | 선언한 bundle과 같은 build |
| InterVar build (optional) | `hg38` — `GRCh38 -> hg38` 매핑에 따름 |
| 핵심 완료 지점 | **raw VCF** |

> [!NOTE]
> **이 표는 권장 profile이지 엔진의 제약이 아닙니다.**
>
> 이 값들은 **코드에 하드코딩되어 있지 않습니다.**
> 특정 reference FASTA 파일 이름은 `main.sh`의 제어 흐름 어디에도 등장하지 않습니다.
> 전부 실행 설정(config)의 `resource_bundle`에서 옵니다.
> 다른 reference나 다른 capture kit를 쓰려면 **config만 바꾸면 되고 코드는 그대로**입니다.
> 자세한 내용은 [4장](#4-입력-파일과-reference-resource)을 보세요.
>
> 유일한 예외는 optional InterVar 단계입니다.
> 이 단계는 assembly와 도구 build 이름의 매핑표가 필요해서
> `main.sh`의 `INTERVAR_BUILD_FOR_ASSEMBLY`에 한 줄을 추가해야 합니다
> ([18.3](#183-사전-설치가-필수인-이유) 참고). **core 파이프라인은 영향받지 않습니다.**
>
> 또한 위 표는 **"이 조합으로 실행 검증을 마쳤다"는 뜻이 아닙니다.**
> 실제 resource로 `--check-only`나 실행을 한 적은 아직 없습니다.

### 2.4 현재 범위 밖

- somatic 분석 (암 조직 vs 정상 조직 비교)
- CNV(복제수 변이), SV(구조 변이), fusion(유전자 융합)
- RNA-seq, single-cell, long-read
- 여러 sample 동시 joint calling
- GIAB truth set 대비 정확도 benchmark (**config key만 있고 로직은 미구현**)
- **자동 최종 임상 판정** — 이 파이프라인은 연구·교육용이며 진단 결과를 내지 않습니다

---

## 3. 전체 분석 흐름

### 3.1 데이터가 어떻게 변해 가는가

```
samplesheet + FASTQ + reference/resource
        ↓
입력 검증                (00_input_validation)
        ↓
Raw QC                   (01_raw_qc)
        ↓
preprocessing 분기       (02_preprocessing)
        ↓
BWA-MEM Alignment        (03_alignment)
        ↓
coordinate-sorted BAM
        ↓
MarkDuplicates           (04_processing)
        ↓
조건부 NM/MD 보정
        ↓
BQSR
        ↓
analysis-ready BAM
        ↓
Coverage QC              (05_coverage_qc)
        ↓
HaplotypeCaller          (06_variant_calling)
        ↓
gVCF
        ↓
GenotypeGVCFs
        ↓
raw VCF                  ← 핵심 완료 지점
        ↓
선택적 filtering / annotation / InterVar   (08 / 10 / 11)
        ↓
최종 metrics·artifact·provenance·methods   (99_finalization)
```

### 3.2 단계별 한눈에 보기

각 단계의 "입력 → 하는 일 → 출력 → 실패하면 어떻게 되나"를 먼저 요약합니다.
자세한 설명은 각 장에 있습니다.

| 단계 | 입력 | 하는 일 | 왜 필요한가 | 핵심 출력 | 실패하면 | 확인할 결과 파일 |
|---|---|---|---|---|---|---|
| **00 입력 검증** | config, samplesheet, resource | 파일 실체·정합성 확인 | 몇 시간 뒤가 아니라 몇 분 안에 문제를 잡기 위해 | `manifest.tsv` | run 실패 | `00_input_validation/*_validation.txt` |
| **01 Raw QC** | 원본 FASTQ | lane별 FastQC, MultiQC 집계 | 결과가 이상할 때 "원본이 나빴나"를 구분하려고 | FastQC HTML | run 실패 (MultiQC는 warning) | `01_raw_qc/multiqc/multiqc_report.html` |
| **02 preprocessing** | `manifest.tsv` | trimming 여부 결정, 정렬용 FASTQ 목록 확정 | 다음 단계가 어떤 FASTQ를 쓸지 명시적으로 고정 | `fastq_manifest.tsv` | run 실패 | `preprocessing_decision.json` |
| **03 Alignment** | FASTQ, reference | read를 유전체 제자리에 붙이고 좌표순 정렬·merge | 서열만으로는 위치를 모르므로 | sample BAM | run 실패 | `sample_bam/*.flagstat.txt` |
| **04 Processing** | sample BAM | 중복 표시 → BAM 검증 → (필요시) NM/MD 보정 → BQSR | 변이 호출이 신뢰할 수 있는 BAM을 만들려고 | analysis-ready BAM | run 실패 | `qc/*.validation.txt`, `*.markdup.metrics.txt` |
| **05 Coverage QC** | analysis-ready BAM, target BED | 목표 영역이 얼마나 읽혔는지 측정 | "변이 없음"과 "확인 불가"를 구분하려고 | `coverage_metrics.json` | run 실패 (낮은 depth는 warning) | `coverage_metrics.json`, `low_mean_depth_intervals.bed` |
| **06 Variant Calling** | analysis-ready BAM | HaplotypeCaller → gVCF → GenotypeGVCFs → raw VCF | 이 파이프라인의 목적 그 자체 | **raw VCF** | run 실패 | `*.raw.vcf.gz`, `*.raw.bcftools.stats.txt` |
| **08 filtering** (선택) | raw VCF | genotype 품질 기준으로 걸러내기 | 후속 해석 편의 | filtered VCF | **run 실패 아님** | `optional/filtering/` |
| **10 annotation** (선택) | raw/filtered VCF | 정규화 + 로컬 ClinVar 주석 | 변이에 알려진 의미를 붙이려고 | 주석 VCF, 변이 TSV | **run 실패 아님** | `optional/annotation/` |
| **11 InterVar** (선택) | 주석 VCF | ACMG 근거 항목 자동 산출 | 해석 근거 정리 보조 | InterVar 결과표 | **run 실패 아님** | `optional/intervar/` |
| **99 finalization** | 전체 기록 | 검증 집계, manifest·provenance·methods 작성 | 결과를 신뢰·재현할 수 있게 만들려고 | `artifact_manifest.json` 등 | run 실패 | `final_validation.tsv`, `methods.md` |

### 3.3 데이터의 "의미"가 어떻게 바뀌는가

확장자가 바뀌는 게 핵심이 아니라 **정보의 의미**가 바뀝니다.

| 시점 | 파일 | 이 파일이 담고 있는 의미 |
|---|---|---|
| 입력 | **FASTQ** | 기계가 읽은 염기서열과 각 글자의 품질 점수. **아직 유전체 어디인지 모름** |
| Alignment 후 | **BAM** | 각 read가 표준 유전체의 **몇 번 염색체 몇 번 위치**에 붙는지 기록됨 |
| MarkDuplicates 후 | BAM (flag 추가) | 어떤 read가 PCR 증폭 중복인지 **표시됨** (삭제하지는 않음) |
| BQSR 후 | **analysis-ready BAM** | 중복 표시 + 품질 점수 보정까지 끝나 **변이 호출에 바로 쓸 수 있는** BAM |
| HaplotypeCaller 후 | **gVCF** | 변이가 있는 자리뿐 아니라 **"여기는 변이가 없다"는 근거(reference block)** 까지 포함 |
| GenotypeGVCFs 후 | **raw VCF** | 이 sample의 **genotype이 확정된** 원시 변이 목록. 아직 필터링하지 않음 |

> **gVCF와 raw VCF를 왜 나누나요?**
> gVCF는 "모든 위치에 대한 증거", raw VCF는 "이 sample의 판정"입니다.
> 지금은 sample이 1개라 한 번에 해도 되지만, 나중에 여러 sample을 함께 분석
> (joint calling)하려면 각 sample의 gVCF가 필요합니다.
> 나중에 구조를 갈아엎지 않으려고 지금부터 두 단계로 나눠 두었습니다.

---

## 4. 입력 파일과 reference resource

파이프라인이 받는 입력은 세 종류입니다.

1. **samplesheet** — 무엇을 분석할지 적은 CSV ([8장](#8-samplesheet-전체-설명))
2. **FASTQ** — 시퀀싱 기계의 출력 파일
3. **resource bundle** — 비교 기준이 되는 참조 자료 모음

### 4.1 FASTQ

시퀀싱 기계가 만든 텍스트 파일이며, 반드시 **gzip 압축**(`.fastq.gz` 또는 `.fq.gz`)이어야 합니다.
read 하나당 4줄로 이루어집니다.

```
@READ_ID_1                       ← read 이름
ATCGGATCCAGT...                  ← 염기서열
+
IIIIJJJJHHHH...                  ← 각 염기의 품질 점수(문자로 인코딩)
```

paired-end이므로 **R1과 R2 두 파일이 한 쌍**이며, 같은 순번의 read는
같은 DNA 조각에서 나온 짝입니다. 그래서 R1과 R2가 같은 파일이면 안 됩니다.

### 4.2 resource bundle

`run_config.json`의 `resource_bundle` 안에 모아 선언합니다.

| Resource | 무엇인가 | 왜 필요한가 | 필수 여부 |
|---|---|---|---|
| **reference FASTA** | 표준 인간 유전체 서열 파일 | read를 여기에 붙여서 위치를 찾음 | 필수 |
| **`.fai`** | FASTA 인덱스 | 특정 좌표를 빠르게 찾기 위함 | 필수 |
| **`.dict`** | sequence dictionary | GATK가 염색체 목록·길이를 확인할 때 요구 | 필수 |
| **BWA index** (`.amb .ann .bwt .pac .sa`) | 정렬 전용 색인 5종 | BWA가 read 위치를 빠르게 찾기 위함 | 필수 |
| **target BED** | capture kit이 실제로 잡아내는 영역 목록 | WES는 유전체 전체가 아니라 이 영역만 분석 | 필수 |
| **known-sites** | 이미 알려진 변이 목록 (dbSNP, Mills indel, 1000G indel 등) | BQSR이 진짜 변이를 오류로 학습하지 않게 함 | 필수 (1개 이상) |
| **known-sites index** (`.tbi` 또는 `.csi`) | 위 파일의 인덱스 | 빠른 조회 | 필수 |
| **dbSNP** | 알려진 변이 식별자(rsID) 데이터베이스 | VCF에 rsID를 붙임. 변이 자체는 안 바뀜 | 선택 |
| **ClinVar** | 임상적 의미가 보고된 변이 DB | annotation 단계에서 사용 | 선택 |
| **VEP cache** | 변이 기능 예측용 로컬 DB | annotation 단계에서 참조 (현재 실제 호출은 미배선) | 선택 |
| **InterVar / ANNOVAR humandb** | ACMG 근거 자동 산출 도구와 DB | InterVar 단계에서 사용 | 선택 |
| **truth VCF / truth BED** | benchmark용 정답 세트 | **config key만 존재하고 비교 로직은 미구현** | 선택 |

> **target BED가 뭔가요?**
> BED는 "몇 번 염색체의 몇 번부터 몇 번까지"를 한 줄씩 적은 단순한 표입니다.
> WES는 유전체 전체를 읽지 않고 capture kit이 잡아낸 영역만 읽는데,
> 그 영역 목록이 target BED입니다.
> **kit마다 잡는 영역이 다르므로 kit이 바뀌면 BED도 반드시 바꿔야 합니다.**

### 4.3 권장 profile은 하드코딩이 아니다

현재 권장 조합은 **GRCh38 resource bundle** + 그 bundle과 좌표계가 일치하는
whole-exome target BED입니다.

이것이 **설정이지 코드가 아니라는 근거**:

- reference FASTA, `.fai`/`.dict`/BWA index, target BED, known-sites 목록,
  선택 resource가 전부 config의 `resource_bundle`에서 옵니다.
- `assembly`와 `contig_style`은 **추정하지 않고 실제 reference와 대조 검증**합니다.
  `plain`(접두사 없음)이라고 선언했는데 reference가 `chr` 접두사를 쓰면
  preflight에서 거부합니다. 반대의 경우도 마찬가지입니다.
- 어떤 함수도 reference 경로, sample 이름, assembly 이름을 제어 흐름에 담고 있지 않습니다.
- **`assembly` 값을 특정 문자열로 제한하는 검사는 없습니다.** `GRCh38`이 아니면
  실패하는 코드는 존재하지 않습니다. 엔진이 막는 것은 "GRCh38이 아닌 값"이 아니라
  **"선언되지 않은 값"**입니다 — 빈 문자열, `null`, 공백뿐인 값,
  `TODO_...` 같은 미치환 placeholder.

**왜 assembly를 필수로 막는가**

선언하지 않아도 core 분석은 돌아갑니다. 그런데 값이 비어 있으면
provenance와 `methods.md`에 좌표계가 기록되지 않고,
InterVar build 대조 검사도 무력화됩니다.
즉 **조용히 검사가 꺼지는 것**이 문제라서 필수로 만들었습니다.

**다른 assembly로 바꾸려면**

| 대상 | 필요한 작업 |
|---|---|
| core 전체 (QC ~ raw VCF) | **config의 `resource_bundle`만 교체.** 코드 수정 없음 |
| optional filtering / annotation | 동일. 코드 수정 없음 |
| optional InterVar | `main.sh`의 `INTERVAR_BUILD_FOR_ASSEMBLY`에 `[<assembly 소문자>]=<도구 build 이름>` 한 줄 추가 |

### 4.4 build가 안 맞으면 왜 위험한가

가장 흔하고 가장 조용한 사고입니다. 좌표계가 다르면 **에러 없이 틀린 답**이 나옵니다.

| Mismatch | 무슨 일이 일어나나 | 비유 |
|---|---|---|
| **reference FASTA와 다른 build의 known-sites** | BQSR이 엉뚱한 위치를 "알려진 변이"로 취급 → 품질 보정이 왜곡됨 | 새 지도에 옛 주소록을 겹쳐 놓는 것 |
| **`1` contig + `chr1` BED** | 이름이 안 맞아 target을 하나도 못 찾음 → coverage가 0으로 보고됨 | "서울시"와 "Seoul"을 다른 곳으로 인식 |
| **다른 capture kit BED** | 실제로 읽지 않은 영역을 "커버리지 부족"으로 보고 | 다른 회사 지도로 길을 찾는 것 |
| **reference와 안 맞는 truth set** | benchmark 수치가 통째로 무의미해짐 | 다른 시험지의 정답지로 채점 |
| **ClinVar build mismatch** | 엉뚱한 변이에 임상 해석이 붙음 | **가장 위험** — 조용히 잘못된 의미가 붙음 |

그래서 파이프라인은 실행 전에 다음을 **직접 확인**합니다
(`validate_reference_bundle()`):

- reference의 `.fai`와 `.dict`가 **완전히 같은 contig 순서·길이**를 갖는가
- config에 선언한 `contig_style`이 실제 reference의 `chr` 접두사 사용과 일치하는가
- target BED의 모든 contig가 reference에 존재하는가
- target BED 좌표가 음수가 아니고 contig 길이를 벗어나지 않는가
- known-sites의 인덱스가 있고, 헤더가 파싱되며, 모든 contig가 reference에 존재하는가
- known-sites 헤더에 contig 길이가 적혀 있으면 reference `.fai`의 길이와 같은가
- `dbsnp_vcf`를 선언했다면 위와 **똑같은 검사**를 통과하는가

annotation 단계는 여기에 더해 ClinVar VCF에 대해
**index 존재, 헤더 파싱, contig subset, 헤더의 contig 길이, 명명 규칙**을
주석 붙이기 직전에 확인하고, 하나라도 어긋나면 주석을 건너뜁니다.

#### 이 검사가 증명하는 것과 증명하지 못하는 것

> [!IMPORTANT]
> 위 검사는 **구조적 호환성(structural compatibility)** 을 확인합니다.
> **같은 build에서 왔다는 출처(build provenance)를 증명하지는 못합니다.**

| 검사가 보장하는 것 | 검사가 보장하지 못하는 것 |
|---|---|
| contig 이름이 서로 맞는다 | 같은 assembly **release**에서 왔다 |
| contig 길이가 서로 맞는다 | 같은 patch level이다 |
| 좌표가 contig 범위 안에 있다 | 같은 공식 bundle에서 배포되었다 |
| 도구가 좌표를 잘못 매핑하지 않는다 | 파일이 중간에 수정되지 않았다 |

같은 assembly의 서로 다른 release는 주요 염색체의 이름과 길이가 **동일할 수 있습니다.**
그래서 구조 검사만으로는 구분되지 않습니다.

출처는 **`resource_bundle` 계약**이 담당합니다 —
`resource_bundle` 안의 모든 resource는 선언한 `assembly`의 것이어야 하며,
정확한 release는 config나 bundle provenance에 사람이 기록해야 합니다.

따라서 코드와 문서는 이 검사 결과를
`structurally compatible`이라고만 표현하고,
`build verified`나 `same build confirmed`라고 쓰지 않습니다.

---

## 5. main.sh의 전체 구조

### 5.1 왜 파일이 하나인가

실행 코드는 `script/main.sh` **한 파일**뿐입니다.
단계별 `.sh` 파일도, 공용 라이브러리 파일도, 별도 Python runner도 없습니다.

이유는 취향이 아니라 **순서** 때문입니다.

1. 이 파이프라인은 아직 처음부터 끝까지 한 번도 돌아 본 적이 없습니다.
   직전 리비전은 `bash -n` 구문 검사조차 통과하지 못했습니다.
2. 파일을 나누는 것은 **정리 문제**를 해결합니다. 지금 문제는
   **연결 문제** — 서로 연결된 적 없는 블록들이었습니다.
3. 함수 경계는 **실행해 보면 검증**됩니다. 파일 경계는 그렇지 않습니다.
   맞아 보일 뿐입니다.
4. 실제로 FASTQ에서 raw VCF까지 나온 뒤에야 어디가 진짜 경계인지 알 수 있고,
   **그때 나눈 경계**가 의미 있는 경계입니다.

그래서 지금은 "한 파일 + 명확한 함수 경계"로 두고, 검증이 끝난 뒤
그 함수 경계를 파일로 분리할 계획입니다 ([30장](#30-향후-단계-분리와-백엔드-연동-계획)).

### 5.2 파일 내부 순서

```
 0. 파이프라인 메타데이터와 기본값     PIPELINE_NAME, PIPELINE_VERSION, DEFAULT_*
    Step 메타데이터                    STEP_KIND, STEP_DEPENDS, CORE_STEPS,
                                       OPTIONAL_STEPS, FINAL_STEP
 1. 런타임 상태 변수                   RUN_ID, SAMPLE_BAM, RAW_VCF, 경로 변수 …
 2. 공통 helper                        로그·Python·JSON·경로·해시·lock·감사기록·
                                       명령 실행
 2b. Step 생명주기                     start_step … finish_step, write_run_status
 3. CLI와 config                       usage, parse_args, load_config, normalize_config
 4. Run 초기화                         initialize_run, render_config_snapshot
 5. Preflight                          validate_* 함수 6종
 6. Core 파이프라인 함수               run_input_validation … run_variant_calling
 7. Optional 후처리 함수               run_filtering, run_annotation, run_intervar
 8. Finalisation                       run_final_validation, write_*, run_finalization
 9. 실행 제어                          build_step_plan, validate_step_artifacts,
                                       step_is_reusable, run_pipeline …
10. Trap 핸들러                        on_signal, on_error, on_exit
11. 진입점                             main, 그리고 마지막 줄 `main "$@"`
```

**파일이 반드시 지키는 불변식 4가지:**

- 최상위 `main "$@"`는 **파일 맨 끝에 정확히 하나**
- 파일 중간에 최상위 `exit` 없음
- 함수 밖에서 분석 명령을 실행하지 않음
- 최상위에서 다운로드·설치·파일 생성을 하지 않음

이 네 가지는 그냥 스타일 규칙이 아니라, 직전 리비전에서 실제로 사고를 일으킨
항목들입니다 ([24장](#24-조원-코드-통합-판단) 참고).

### 5.3 함수 전수 분류

아래는 `main.sh`에 **실제로 존재하는 함수 전부**입니다.
여기 없는 이름은 코드에 없습니다.

| 분류 | 함수 |
|---|---|
| **공통 helper — 시각·로그** | `timestamp` `iso_now` `log` `warn` `die` |
| **공통 helper — 요구사항** | `have_command` `require_command` `require_readable_file` |
| **공통 helper — Python·JSON** | `resolve_python` `require_python` `json_get` `json_list` `atomic_write_json` |
| **공통 helper — 경로·해시** | `normalize_path` `path_under` `sha256_file` `file_size` |
| **Lock** | `acquire_run_lock` `release_run_lock` |
| **감사 기록** | `append_status_tsv` `append_trace_tsv` `record_command` |
| **명령 실행** | `run_cmd` `run_cmd_stdout` `require_cmd_ok` `run_optional_cmd` |
| **Step 생명주기** | `sanitize_field` `start_step` `step_input` `step_output` `step_check_pass` `step_check_fail` `step_warning` `step_metric` `add_artifact` `step_has_failures` `step_has_warnings` `finish_step` `complete_step` `fail_step` `skip_step` |
| **Step 종류 판정** | `step_kind` `is_optional_step` `is_core_step` |
| **전체 상태** | `write_run_status` |
| **CLI·config** | `usage` `parse_args` `load_config` `normalize_config` |
| **Run 초기화** | `initialize_run` |
| **snapshot·identity** | `render_config_snapshot` `report_identity_diff` |
| **Preflight** | `validate_samplesheet` `validate_reference_bundle` `validate_tools` `validate_fastq_integrity` `validate_compute_resources` `validate_output_root` |
| **Raw QC 보조** | `fastqc_stem` |
| **Processing 보조** | `classify_validation` |
| **Core 분석** | `run_input_validation` `run_raw_qc` `run_preprocessing` `run_alignment` `run_processing` `run_coverage_qc` `run_variant_calling` |
| **Optional** | `run_filtering` `run_annotation` `run_intervar` |
| **Marker** | `clear_run_markers` `set_run_marker` |
| **Finalisation** | `run_final_validation` `write_artifact_manifest` `write_provenance` `write_final_report` `run_finalization` |
| **실행 계획** | `build_step_plan` `dispatch_step` `gate_next_step` `run_pipeline` |
| **artifact 검증** | `validate_step_artifacts` `validate_bam_artifact` `validate_vcf_artifact` |
| **resume·무효화** | `step_is_reusable` `should_run_step` `mark_step_invalidated` `assert_from_step_inputs` |
| **Trap** | `on_signal` `on_error` `on_exit` |
| **진입점** | `main` |

### 5.4 반드시 이해해야 할 helper

작은 helper 중에서도 이 파이프라인의 안전성을 떠받치는 것들입니다.

#### 명령 실행과 기록

| 함수 | 하는 일 | 실패 시 |
|---|---|---|
| `record_command` | 실행할 명령을 `logs/commands.sh`에 `%q`로 안전하게 인용해 기록 | — |
| `run_cmd` | 명령을 실행하고 stderr를 `logs/<step>.<label>.stderr.log`로 분리 저장, 종료 코드 반환 | 종료 코드를 그대로 반환 |
| `run_cmd_stdout` | 위와 같지만 stdout을 지정 파일로 저장 | 동일 |
| `require_cmd_ok` | `run_cmd` 실행 후 0이 아니면 `step_check_fail` 기록 | **step 실패로 이어짐** |
| `run_optional_cmd` | `run_cmd` 실행 후 0이 아니면 **warning만** 기록하고 0을 반환 | step을 실패시키지 않음 |

> **핵심 설계**: 명령은 항상 **argv 배열로 실행**되며, 셸 문자열로 조립되지 않습니다.
> config나 samplesheet에서 온 값이 셸 문법으로 재해석될 수 없습니다.
> `eval`도 `bash -c`도 사용하지 않습니다.
>
> 또한 `if "$@"; then rc=0; else rc=$?; fi` 형태로 감싸므로,
> `set -e`와 ERR trap이 도구의 진짜 종료 코드를 가려 버리지 않습니다.

#### 상태 JSON 갱신과 artifact 등록

| 함수 | 하는 일 |
|---|---|
| `start_step` | step 작업 디렉터리(`status/steps/.<step>.work`)를 만들고 TSV 스크래치 7종을 초기화, `stage_status.tsv`에 `STARTED` 기록, run 상태를 `running`으로 갱신 |
| `step_input` / `step_output` | 이 step이 읽은/쓴 파일을 스크래치에 기록 |
| `step_check_pass` / `step_check_fail` | 검사 결과 기록. `fail`은 `next_step_ready`를 0으로 내림 |
| `step_warning` | 코드·메시지·영향·`can_continue` 4요소로 warning 기록. `can_continue=false`면 `next_step_ready`를 0으로 내림 |
| `step_metric` | 지표 기록. 숫자/문자를 자동 판별 |
| `add_artifact` | 산출물 등록. **파일이 비어 있으면 조용히 등록하지 않음** |
| `finish_step` | 스크래치를 읽어 `status/steps/<step>.json`, `metrics/<step>.json`, `artifacts/<step>.json` 3종을 원자적으로 작성하고 스크래치를 삭제 |
| `complete_step` | 실패가 있으면 `failed`, warning만 있으면 `warning`, 없으면 `completed`로 마무리 |
| `fail_step` | 실패 사유를 기록하고 즉시 `failed`로 마무리 |

`sanitize_field()`는 값 안의 탭·개행·캐리지리턴을 공백으로 바꿉니다.
경로에 탭이 들어 있어도 TSV 스크래치 형식이 깨지지 않게 하기 위함입니다.

#### checksum과 artifact ID

`add_artifact`의 5번째 인자가 `1`이면 `finish_step`이 그 파일의 **SHA-256을 계산**합니다.
그리고 모든 artifact에 `file_id`를 부여합니다.

```
file_id = "f_" + sha256("<run_id>:<step_id>:<run 기준 상대경로>")의 앞 16자리
```

절대 경로 대신 **run 기준 상대 경로**를 기록하므로,
나중에 백엔드가 서버 디렉터리 구조를 드러내지 않고 파일을 제공할 수 있습니다.

`sha256_file()`은 `sha256sum` → `shasum -a 256` 순서로 시도합니다.
둘 다 없으면 실패를 반환하며, 이 경우 resource 체크섬 기록이 비게 됩니다.

#### config snapshot과 identity 비교

| 함수 | 하는 일 |
|---|---|
| `render_config_snapshot <경로>` | 유효 설정 전체를 지정 경로에 JSON으로 쓰고, **identity 해시를 표준출력으로 반환** |
| `report_identity_diff <옛 snapshot> <새 snapshot>` | 두 snapshot의 `resume_identity_detail`을 재귀 비교해 **달라진 필드만** 출력 |

`render_config_snapshot`은 **어디에 쓸지를 인자로 받습니다.**
그래서 resume일 때는 임시 파일에 쓰고 기존 snapshot과 비교할 수 있습니다.
자세한 이유는 [21장](#21-resume와-멱등성)에 있습니다.

#### resume 재사용 판정과 artifact 검증

| 함수 | 하는 일 |
|---|---|
| `step_is_reusable` | 의존 step 무효화 여부 → 상태값 → `next_step_ready` → artifact 검증 순으로 확인 |
| `validate_step_artifacts` | 기록된 출력이 전부 존재·비어있지 않은지, 상태 문서가 이 run·이 step의 것인지, 그리고 step별 의미 검사 |
| `validate_bam_artifact` | `samtools quickcheck` + 인덱스 존재 + `idxstats` 읽기 가능 + `@HD … SO:coordinate` + 기대하는 `SM` 태그 |
| `validate_vcf_artifact` | 비어있지 않음 + `bcftools view -h` 파싱 + `.tbi`/`.csi` 존재 + `tabix -l` 읽기 가능 + 기대하는 sample 컬럼 |
| `mark_step_invalidated` | 재실행될 step을 기록해, 그것에 의존하는 step이 재사용되지 못하게 함 |
| `assert_from_step_inputs` | `--from-step`으로 시작할 때 그 step의 upstream artifact를 검증하고, 무효하면 중단 |

#### lock

| 함수 | 하는 일 |
|---|---|
| `acquire_run_lock` | `mkdir "$RUN_DIR/.run.lock"`으로 원자적 lock 획득, `owner` 파일에 pid·host·시작 시각 기록 |
| `release_run_lock` | 이 프로세스가 잡은 lock만 해제 |

#### trap

| Trap | 함수 | 하는 일 |
|---|---|---|
| `INT` / `TERM` | `on_signal` | 자식 프로세스에 `TERM` 전달, 진행 중 step을 `cancelled`로 마감, run 상태 `cancelled`, `RUN_CANCELLED` marker, lock 해제, exit 130 |
| `ERR` | `on_error` | 예상치 못한 오류 지점(줄 번호·명령·종료 코드)을 기록, 진행 중 step을 `failed`로 마감, `RUN_FAILED` marker, lock 해제 |
| `EXIT` | `on_exit` | **lock 해제만** 수행 |

> `on_exit`는 lock만 풉니다. 최종 상태 기록과 marker 작성은
> `run_pipeline`, `on_signal`, `on_error`가 담당합니다.

#### 현재 정의만 되어 있고 호출되지 않는 helper

정직하게 기록합니다. 아래 함수는 정의되어 있지만 현재 코드에서 호출부가 없습니다.

| 함수 | 상태 |
|---|---|
| `atomic_write_json` | 정의만 존재. 실제 JSON 작성은 각 Python heredoc이 `.part` → `os.replace`로 직접 수행 |
| `require_command` | 정의만 존재. 도구 확인은 `validate_tools`가 `have_command`로 수행 |
| `skip_step` | 정의만 존재. **어떤 step도 현재 `skipped` 상태를 기록하지 않음** (비활성 optional step은 실행 계획에 아예 들어가지 않아 상태 문서 자체가 생기지 않음) |

`step_is_reusable`, `gate_next_step`, `run_final_validation`은 `skipped`를
정상 상태로 취급하도록 이미 작성되어 있으므로, 나중에 이 값이 쓰이더라도
로직을 바꿀 필요는 없습니다.

### 5.5 Python heredoc에 대해

Bash에는 JSON 파서가 없습니다. `jq`는 좋은 도구지만 서버에 항상 있지는 않습니다.
그래서 JSON 처리와 복잡한 검증은 `main.sh` 안의 **Python heredoc**으로 합니다.

> [!NOTE]
> 이건 "별도 Python runner 프로그램"이 **아닙니다.**
> 별도 `.py` 파일은 저장소에 존재하지 않습니다.
> 실행 순서 제어와 분석 도구 실행은 전부 Bash가 합니다.

안전 규칙 두 가지가 예외 없이 지켜집니다.

- 모든 heredoc이 **따옴표로 묶인 구분자**(`<<'PYJSONGET'`)를 씁니다.
  Bash가 Python 코드 안의 `$`나 백틱을 건드리지 않습니다.
- 값은 전부 **argv로 전달**합니다. 셸 값이 Python 소스에 문자열 보간되는 일이 없습니다.

인터프리터는 `resolve_python()`이 `python3` → `python` 순서로 **탐색**합니다.
단순히 `python3`을 가정하지 않는 이유는, `python`만 있는 장비가 있고
Windows에는 실행되지 않고 종료하는 `python3` 스텁이 있기 때문입니다.
`import json,sys`가 실제로 되는지까지 확인한 뒤에 채택합니다.

---

## 6. 실행 방법과 CLI option

### 6.1 실행 형식

```bash
bash script/main.sh --config <run_config.json> [옵션]
```

> `main.sh`는 git에서 실행 권한 없는 파일(mode `100644`)입니다.
> `./script/main.sh`가 아니라 **`bash script/main.sh`** 로 실행하세요.

### 6.2 CLI option 전수

`parse_args()`가 실제로 인식하는 옵션 전부입니다. 그 외 옵션은 usage를 출력하고 중단합니다.

| Option | 역할 | 사용 시점 | 주의점 |
|---|---|---|---|
| `--config FILE` | 실행 설정 JSON 지정 | **`--help` 외에는 항상 필수** | 값이 없으면 즉시 중단 |
| `--check-only` | preflight 검증만 하고 분석 도구 실행 전에 중단 | 실제 실행 전 사전 점검 | **완전한 무부작용 dry-run이 아닙니다.** 아래 6.3 참고 |
| `--resume` | 기존 run 디렉터리를 이어서 실행 | 중단·실패 후 재시작 | config가 바뀌었으면 거부 |
| `--from-step ID` | 지정 step부터 시작 | 특정 지점부터 다시 돌릴 때 | upstream artifact를 검증하고 무효하면 시작 거부 |
| `--to-step ID` | 지정 step까지만 실행하고 중단 | 부분 실행·중간 확인 | **완료 marker를 만들지 않음** |
| `-h`, `--help` | 사용법 출력 후 정상 종료 | — | 아무 파일도 만들지 않음 |

Step ID 목록:
`00_input_validation` `01_raw_qc` `02_preprocessing` `03_alignment`
`04_processing` `05_coverage_qc` `06_variant_calling`
`08_filtering` `10_annotation` `11_intervar` `99_finalization`

### 6.3 `--check-only`의 실제 동작

> [!WARNING]
> `--check-only`는 **"아무 파일도 만들지 않는 dry-run"이 아닙니다.**
> 코드를 확인한 결과를 그대로 적습니다.

| 질문 | 실제 동작 | 근거 |
|---|---|---|
| BWA/GATK/mosdepth 같은 분석 도구를 실행하나? | **아니오** | `run_input_validation`만 호출하고 반환 |
| run 디렉터리를 만드나? | **예** | `initialize_run`이 `--check-only` 여부와 무관하게 먼저 실행됨 |
| lock을 잡나? | **예** (끝나면 해제) | `initialize_run` → `acquire_run_lock` |
| config snapshot을 쓰나? | **예** | `main`의 snapshot 분기가 먼저 실행됨 |
| status JSON을 쓰나? | **예** (`status: check_only`) | `write_run_status check_only` |
| `pipeline.log`를 남기나? | **예** | `initialize_run`이 로그 리다이렉션을 켬 |
| `RUN_*` marker를 남기나? | **아니오** | 성공 경로는 marker를 쓰지 않고, 실패 경로는 `clear_run_markers`를 호출 |
| 나중에 같은 `run_id`로 실제 실행할 수 있나? | **예. `--resume` 없이 그대로 가능** | `initialize_run`이 이전 상태가 `check_only`면 실제 실행을 허용 |

정리하면 `--check-only`는 **"분석은 하지 않지만 검증 결과는 디스크에 남기는 사전 점검"** 입니다.

검증 과정에서 `bcftools view -h`와 `tabix -l`로 known-sites의 헤더와 contig 목록을
읽기는 합니다. 이건 **resource 검증**이지 분석이 아닙니다.
read를 정렬하거나 변이를 찾지 않습니다.

```bash
bash script/main.sh --config cfg.json --check-only   # 점검
bash script/main.sh --config cfg.json                # 같은 run_id로 그대로 실행
```

### 6.4 `--resume`의 실제 동작

단순히 "중간부터 계속"이 아닙니다. 다음을 확인한 뒤에만 이어집니다.

1. **기존 snapshot 보존** — `config/run_config.snapshot.json`을 **먼저 읽습니다.**
   이 파일은 resume 과정에서 **절대 덮어쓰지 않습니다.**
   이 파일이 실제 산출물을 만들어 낸 설정의 유일한 기록이기 때문입니다.
2. **새 요청의 config identity 계산** — 들어온 config로 identity를 계산해
   임시 파일 `config/.run_config.requested.json`에 씁니다.
3. **identity 비교** — 두 해시가 다르면 **즉시 중단**하고 달라진 필드를 출력합니다.

   ```
   RESUME REFUSED — the configuration changed since this run was created.
     recorded identity : 0b423fae...
     requested identity: 7c19aa02...
     differences:
       - settings.trim_mode: recorded='skip' requested='force'
   ```

   원본 snapshot은 그대로 두고, 거부된 요청은
   `config/run_config.rejected_resume.json`으로 옮겨 보존합니다.
   run 상태는 `resume_refused`가 됩니다.
4. **FASTQ·resource identity 포함** — identity에는 설정값뿐 아니라
   samplesheet·reference FASTA·target BED·known-sites·dbSNP의 **내용 해시**와
   각 lane FASTQ의 지문이 들어갑니다. 경로는 그대로인데 파일만 바꿔치기한 경우를 잡습니다.
5. **artifact 무결성 재검증** — identity가 같아도 파일 존재만으로 건너뛰지 않습니다.
   BAM은 quickcheck·인덱스·정렬순서·`SM`을, VCF는 파싱·인덱스·sample 컬럼을 실제로 확인합니다.
6. **최초 invalid step부터 downstream 무효화** — 어떤 step이 재사용 불가로 판정되면
   `STEP_DEPENDS`를 따라 **그 뒤 모든 step**이 함께 재실행 대상이 됩니다.

**왜 단순 파일 존재 확인이 아닌가**: [21.2](#212-순진한-resume이-위험한-이유)에서
구체적인 사고 시나리오로 설명합니다.

identity가 일치하면 들어온 요청은 `config/run_config.resume_request.json`으로
보관되고, **snapshot은 여전히 다시 쓰이지 않습니다.**

### 6.5 `--from-step` / `--to-step`

- **upstream artifact validation** — `--from-step`은 `assert_from_step_inputs()`가
  그 step의 `STEP_DEPENDS` 항목들을 검증합니다. 상태 문서가 없거나 artifact가
  무효하면 **시작 자체를 거부**합니다. 검증되지 않은 입력을 그대로 소비하지 않기 위함입니다.
- **순서 역전 거부** — `--from-step`과 `--to-step`을 **함께** 주었을 때,
  실행 계획에서 from이 to보다 뒤면 "범위가 비었다"며 거부합니다.
- **비활성 optional step 처리** — 두 옵션을 함께 준 경우, config에서 켜지 않은
  optional step을 지정하면 "실행 계획에 없다"며 거부합니다.
  `--from-step`만 단독으로 비활성 optional step에 준 경우에는 `build_step_plan`이
  ID 존재만 확인하고 넘어가지만, 이어지는 `assert_from_step_inputs`가
  upstream 상태 문서를 요구하므로 새 run에서는 그 지점에서 중단됩니다.
- **부분 실행은 전체 완료와 다름** — `--to-step`으로 멈추면 run 상태는
  `stopped_at_requested_step`이 되고 **`RUN_*` marker를 만들지 않습니다.**
  부분 실행을 완료로 오인하지 않게 하기 위함입니다.
- **부작용 전 검증** — 실행 계획 검증은 `initialize_run`보다 **먼저** 수행됩니다.
  잘못된 옵션 조합이 run 디렉터리나 lock을 남기지 않습니다.

### 6.6 실행 예시

```bash
# 1) 구문 검사 — 아무 것도 실행하지 않음
bash -n script/main.sh

# 2) 사용법
bash script/main.sh --help

# 3) preflight 검증만 (분석 도구 미실행)
bash script/main.sh \
  --config /path/to/run_config.json \
  --check-only

# 4) 전체 실행
bash script/main.sh \
  --config /path/to/run_config.json

# 5) 긴 실행을 세션과 분리해서 백그라운드로
nohup bash script/main.sh \
  --config /path/to/run_config.json \
  > /path/to/driver.log 2>&1 &

# 6) 중단 후 재개
bash script/main.sh \
  --config /path/to/run_config.json \
  --resume
```

부분 실행 (step ID는 위 6.2의 목록에서 그대로 사용합니다):

```bash
# 정렬까지만
bash script/main.sh --config cfg.json --to-step 03_alignment

# 변이 호출부터 (upstream artifact를 검증한 뒤 시작)
bash script/main.sh --config cfg.json --resume --from-step 06_variant_calling

# 한 단계만
bash script/main.sh --config cfg.json \
  --from-step 05_coverage_qc --to-step 05_coverage_qc
```

진행 확인:

```bash
RUN=/data/runs/run_20260728_001
tail -f $RUN/logs/pipeline.log
column -t -s$'\t' $RUN/logs/stage_status.tsv
```

### 6.7 실행 전 준비물

파이프라인은 **어떤 소프트웨어도 설치하지 않습니다.**
존재를 확인하고, 버전을 기록하고, 없으면 실행 가능한 안내와 함께 preflight에서 실패합니다.

`validate_tools()`가 요구하는 도구 (PATH에 있어야 함):

```
bwa  samtools  gatk  bcftools  tabix  bgzip  mosdepth  fastqc
awk  sed  grep  sort  cut  wc
python3 (또는 python)
```

조건부:

| 도구 | 필요한 조건 | 없으면 |
|---|---|---|
| `fastp` | `trim_mode`가 `force`일 때 | preflight 실패 |
| `multiqc` | 항상 선택 | warning (`MULTIQC_MISSING`). 개별 FastQC는 그대로 생성 |
| `Rscript` | `bqsr_diagnostics`가 `true`일 때만 | warning (`RSCRIPT_MISSING`). 진단 플롯만 생략 |
| `gzip` | `verify_fastq_gzip`이 `true`일 때만 | warning (`GZIP_MISSING`). 매직 넘버 검사만 수행 |
| `vep` | `vep_cache`를 설정했을 때 | warning. **현재 offline VEP 호출은 미배선** |
| InterVar + ANNOVAR + `humandb` | `intervar` step을 켰을 때 | 해당 optional step 실패 (core는 무사) |

> `bgzip`은 필수 목록에 있지만 현재 코드가 직접 호출하지는 않습니다.
> htslib 설치가 온전한지 확인하는 용도로 남아 있습니다.

**설치는 실행이 아니라 준비 작업입니다.** 참고용 한 번짜리 설치 예시:

```bash
# 일회성 환경 준비 — run의 일부가 아님
conda create -n wes -c bioconda -c conda-forge \
    bwa samtools gatk4 bcftools htslib mosdepth fastqc fastp multiqc
conda activate wes

# InterVar를 쓸 계획일 때만
git clone https://github.com/WGLab/InterVar.git /opt/InterVar
cd /opt/InterVar && pip install -r requirements.txt
# ANNOVAR humandb는 자체 라이선스 조건에 따라 별도로 준비합니다.
# build는 resource bundle에 맞춰 고르세요. 현재 기준(GRCh38)에서는 hg38입니다.
```

reference resource(FASTA, `.fai`, `.dict`, BWA index, target BED, known-sites와 인덱스)는
bundle 단위로 **한 번 준비**해 두고, run 중에는 읽기 전용으로만 사용합니다.

---

## 7. config 전체 설명

`run_config.json` 한 파일에 run마다 달라지는 값이 전부 들어갑니다.
**코드에는 아무것도 하드코딩되어 있지 않습니다.**

### 7.1 전체 예시

```json
{
  "run_id": "run_20260728_001",
  "samplesheet": "/data/runs/input/samplesheet.csv",
  "output_root": "/data/runs",

  "threads": 8,
  "sort_threads": 4,
  "sort_mem": "2G",
  "fastqc_threads": 2,
  "pairhmm_threads": 4,
  "java_mem_gb": 16,
  "interval_padding": 100,
  "mosdepth_mapq": 20,
  "low_coverage_depth": 20,
  "coverage_min_mean_depth": 0,
  "min_available_ram_gb": 8,

  "trim_mode": "skip",
  "bqsr_target_only": false,
  "bqsr_diagnostics": false,
  "verify_fastq_gzip": false,
  "resume_strict_checksums": false,

  "resource_bundle": {
    "bundle_id": "grch38_wes",
    "assembly": "GRCh38",
    "contig_style": "chr",
    "reference_fasta": "TODO_GRCH38_REFERENCE_FASTA",
    "target_bed": "TODO_GRCH38_TARGET_BED",
    "known_sites": [
      "TODO_GRCH38_KNOWN_SITE_1",
      "TODO_GRCH38_KNOWN_SITE_2"
    ],
    "dbsnp_vcf": "TODO_GRCH38_DBSNP_VCF",
    "clinvar_vcf": null,
    "vep_cache": null,
    "truth_vcf": null,
    "truth_bed": null
  },

  "optional_steps": {
    "filtering": false,
    "annotation": false,
    "intervar": false
  }
}
```

> [!IMPORTANT]
> **이 예시는 그대로 실행되지 않습니다.**
> 이 저장소에는 GRCh38 resource 파일이 포함되어 있지 않고 확정된 경로도 없어서,
> 가짜 경로를 지어내는 대신 `TODO_GRCH38_*` placeholder를 두었습니다.
> 실행 전에 각 항목을 **실제로 준비한 GRCh38 파일 경로**로 바꾸세요.
>
> `TODO_...`로 시작하는 값을 그대로 두면
> preflight가 **placeholder임을 인식하고 실행을 거부합니다.**
> 조용히 넘어가지 않습니다.

> [!WARNING]
> **`contig_style`의 `"chr"`은 예시 값이지 확정 값이 아닙니다.**
>
> GRCh38이라는 이유만으로 `chr`이 되지 않습니다.
> 같은 GRCh38이라도 배포본에 따라 contig 이름이 `chr1`일 수도 `1`일 수도 있습니다.
> 준비한 FASTA의 `.fai` 첫 열을 직접 확인하세요.
>
> ```bash
> cut -f1 <reference>.fa.fai | head -5
> ```
>
> - `chr1` 형식이면 → `chr` (또는 `ucsc`)
> - `1` 형식이면 → `plain` (또는 `nochr`, `ensembl`)
>
> 잘못 적어도 **조용히 넘어가지 않습니다.** preflight가 실제 FASTA와 대조해
> 불일치하면 실행을 거부합니다. 그래서 이 필드는 "추측해서 맞히는 값"이 아니라
> **"내가 의도한 바를 선언하고 파이프라인이 검증하게 하는 값"**입니다.

> [!NOTE]
> known-sites, dbSNP, ClinVar, truth set, ANNOVAR humandb가 **모두 같은
> GRCh38 파일과 좌표계·contig 이름이 호환되는지** 직접 확인해야 합니다.
> "GRCh38"이라는 이름만 같다고 primary assembly, UCSC hg38, analysis set,
> ALT/decoy 포함 여부가 자동으로 일치하지는 않습니다.
>
> preflight는 이 중 **구조적으로 확인 가능한 부분**(contig 이름, contig 길이, 좌표 범위)을
> 검사하지만, **같은 release에서 왔다는 사실까지 증명하지는 못합니다.**
> 자세한 내용은 [4.4](#44-build가-안-맞으면-왜-위험한가)를 보세요.

### 7.2 최상위 key

| Key | 타입 | 필수 | 기본값 | 의미 | 기본값 선택 이유 | 변경 영향 |
|---|---|:---:|---|---|---|---|
| `run_id` | string | 필수 | — | run 식별자이자 디렉터리 이름 | — | 다르면 결과가 완전히 분리됨. `^[A-Za-z0-9][A-Za-z0-9._-]*$`만 허용 |
| `samplesheet` | path | 필수 | — | samplesheet CSV 경로 | — | 분석 대상 자체가 바뀜 |
| `output_root` | path | 필수 | — | 결과 저장 루트. **미리 존재하고 쓰기 가능해야 함** | — | 저장 위치가 바뀜 |
| `threads` | int | 선택 | `4` | BWA, samtools, mosdepth 등의 스레드 | 공유 서버에서 무난한 보수적 값 | 속도 향상, CPU 경합 위험. **논리 코어 수를 넘으면 preflight 실패** |
| `sort_threads` | int | 선택 | `threads` 값 | `samtools sort` 스레드 | 정렬만 따로 조절하는 게 유용 | 메모리 사용량에 직접 영향 |
| `sort_mem` | string | 선택 | `"2G"` | `samtools sort` **스레드당** 메모리 | 총 사용량 = `sort_threads` × 이 값 | 너무 크면 OOM. `2G`, `768M` 형식만 허용 |
| `fastqc_threads` | int | 선택 | `2` | FastQC 스레드 | FastQC는 스레드를 많이 줘도 이득이 적음 | 미미. 실제로는 `threads`와 비교해 작은 값이 쓰임 |
| `pairhmm_threads` | int | 선택 | `4` | HaplotypeCaller의 PairHMM 스레드 | GATK 관례값 | 변이 호출 속도 |
| `java_mem_gb` | int | 선택 | `8` | GATK Java 힙 크기(GB) | **최소 4 이상 강제** | 너무 작으면 GATK OOM |
| `interval_padding` | int | 선택 | `100` | target 경계 확장 bp | 경계에 걸친 read와 indel 문맥 보존 | 호출·집계 영역 크기가 바뀜 |
| `mosdepth_mapq` | int | 선택 | `20` | coverage 계산 시 최소 MAPQ | 애매한 정렬이 depth를 부풀리지 않게 | coverage 수치 전체가 바뀜 |
| `low_coverage_depth` | int | 선택 | `20` | low-coverage로 볼 depth 기준 | 보고용 기준선 | 보고서 수치만 바뀜. 실패 판정과 무관 |
| `min_available_ram_gb` | int | 선택 | `8` | preflight RAM 하한 | 최소 안전선 | 미달이면 **preflight 실패** |
| `coverage_min_mean_depth` | number | 선택 | `0` | 평균 depth 참고 기준 | **`0` = 비교 자체를 비활성화** | 설정하면 미달 시 **warning**(실패 아님) |
| `trim_mode` | `skip`/`force` | 선택 | `"skip"` | trimming 수행 여부 | 근거 없는 자동 데이터 변형 방지 | FASTQ 전처리 유무. **다른 값은 즉시 거부** |
| `bqsr_target_only` | bool | 선택 | `false` | BQSR 모델 학습을 target 영역으로 제한 | 학습 데이터가 많은 전체 적용이 안정적 | 보정 모델의 학습 범위 |
| `bqsr_diagnostics` | bool | 선택 | `false` | BQSR 전후 진단 플롯 생성 | Rscript가 필요하고 핵심이 아님 | 플롯 산출 유무. 분석 결과는 불변 |
| `verify_fastq_gzip` | bool | 선택 | `false` | FASTQ 전체 `gzip -t` 검사 | 전체 WES에서 수 분 소요 | 잘린 FASTQ를 조기에 탐지 |
| `resume_strict_checksums` | bool | 선택 | `false` | resume identity에서 FASTQ 내용까지 해시 | 전체 해시는 느림 | 재사용 판정 엄격도 |

### 7.3 `resource_bundle` 하위 key

| Key | 타입 | 필수 | 기본값 | 의미 | 변경 영향 |
|---|---|:---:|---|---|---|
| `bundle_id` | string | 선택 | `""` | bundle 이름 (기록·로그용) | 기록만 |
| `assembly` | string | **필수** | — | 이 bundle의 reference assembly 이름. 권장값 `GRCh38`. **특정 문자열로 제한하지 않으며, 명시적으로 선언되기만 하면 됩니다** | 비었거나 `TODO...` placeholder면 **즉시 실패**. provenance·methods 기록, InterVar build 대조에 사용 |
| `contig_style` | string | **필수** | — | **assembly가 아니라 염색체 이름 표기 방식**입니다. `chr`/`ucsc` 또는 `plain`/`nochr`/`ensembl`만 허용. **실제 reference와 대조 검증됨** | 목록 밖의 값·오타·placeholder·assembly 이름이면 **즉시 실패**. 실제 FASTA와 불일치해도 preflight 실패 |
| `reference_fasta` | path | 필수 | `""` | reference FASTA 경로 | 분석 기준 전체가 바뀜 |
| `target_bed` | path | 필수 | `""` | target BED 경로 | 분석 영역 전체가 바뀜 |
| `known_sites` | array | 필수 | `[]` | known-sites 파일 배열. **비어 있으면 preflight 실패** | BQSR 결과가 바뀜 |
| `dbsnp_vcf` | path | 선택 | `""` | rsID 부여용. **선언하지 않으면** warning 후 진행(변이 자체는 불변). **선언했다면** known-sites와 동일한 구조 검사를 통과해야 함 | 선언 후 구조 불일치면 **core 실행 전에 preflight 실패** |
| `clinvar_vcf` | path | 선택 | `""` | annotation용 ClinVar VCF | annotation 결과 |
| `vep_cache` | path | 선택 | `""` | VEP 로컬 캐시 경로 | 현재는 경고 메시지에만 영향 |
| `truth_vcf` | path | 선택 | `""` | benchmark용 | **비교 로직 미구현** |
| `truth_bed` | path | 선택 | `""` | benchmark용 | **비교 로직 미구현** |

#### `assembly` 검증 규칙 (`normalize_config`)

| 값 | 결과 |
|---|---|
| `"GRCh38"` | 통과 (현재 권장 profile) |
| `"CHM13v2.0"` 등 다른 명시적 assembly 이름 | **통과** — 엔진은 assembly를 제한하지 않습니다 |
| `""` (빈 문자열) | **실패** |
| `null` | **실패** (빈 문자열로 읽힘) |
| `"   "` (공백만) | **실패** |
| `"TODO_GRCH38_ASSEMBLY"` | **실패** (placeholder 인식) |

> `GRCh38`이 아니면 실패시키는 검사는 **없습니다.**
> 막는 것은 "다른 assembly"가 아니라 **"선언되지 않은 assembly"**입니다.
> 값이 비어 있으면 provenance 기록과 InterVar build 대조가 조용히 무력화되기 때문입니다.

#### `contig_style` 검증 규칙

**1단계 — 어휘 검사 (`normalize_config`)**

허용값은 다섯 개뿐입니다. 대소문자는 구분하지 않고 소문자로 정규화됩니다.

| 표기 방식 | 허용값 |
|---|---|
| `1`, `2`, … `MT` | `plain`, `nochr`, `ensembl` |
| `chr1`, `chr2`, … `chrM` | `chr`, `ucsc` |

다음은 **모두 즉시 실패**합니다.

| 값 | 실패 이유 |
|---|---|
| `""`, `null`, `"  "` | 선언되지 않음 |
| `"TODO_GRCH38_CONTIG_STYLE"` | 미치환 placeholder |
| `"chrs"`, `"plian"` | 허용 목록에 없는 오타 |
| `"GRCh38"`, `"hg38"` | **assembly/build 이름은 contig style이 아닙니다** |

**2단계 — 실제 FASTA와 대조 (`validate_reference_bundle`)**

- `plain`/`nochr`/`ensembl`을 선언했는데
  reference contig의 과반이 `chr`로 시작하면 → **실패**
- `chr`/`ucsc`를 선언했는데
  reference가 `chr`를 쓰지 않으면 → **실패**

> [!NOTE]
> 예전에는 허용 목록에 없는 값을 적으면 대조 검사를 **조용히 건너뛰었습니다.**
> 지금은 1단계에서 먼저 막히고, 2단계에도 명시적 `else` 분기가 있어
> **어떤 경우에도 검사가 조용히 꺼지지 않습니다.**
>
> 또한 `GRCh38`이라는 이유만으로 `chr`을 강제하지 않습니다.
> 판정 기준은 언제나 **실제 FASTA의 contig 이름**입니다.

### 7.4 optional step 설정

| Key | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `optional_steps.filtering` | bool | `false` | filtering step 실행 여부 |
| `optional_steps.annotation` | bool | `false` | annotation step 실행 여부 |
| `optional_steps.intervar` | bool | `false` | InterVar step 실행 여부 |
| `filtering.preset` | string | `balanced` | `balanced` / `strict` / `pass-only` 중 하나. 다른 값이면 step 실패 |
| `filtering.min_dp` | int | preset 값 | `FORMAT/DP` 하한 |
| `filtering.min_gq` | int | preset 값 | `FORMAT/GQ` 하한 |
| `filtering.min_alt_depth` | int | preset 값 | `FORMAT/AD[0:1]` 하한 |
| `intervar.install_dir` | path | `""` | InterVar 설치 디렉터리. 없으면 step 실패 |
| `intervar.build` | string | `""` | InterVar genome build. **반드시 명시**해야 하며, 비어 있거나 `resource_bundle.assembly`와 대응하지 않으면 step 실패 |
| `intervar.humandb_dir` | path | `""` | ANNOVAR humandb 경로. 없으면 step 실패 |

#### `intervar.build`와 `assembly`의 대응 검사

`intervar.build`는 이제 **비어 있는지만 보지 않고, 선언한 assembly와 실제로
대응하는지까지 확인**합니다. 검사는 **optional InterVar step 안에서만** 수행되며,
core 파이프라인에는 영향을 주지 않습니다.

매핑표는 `main.sh` 상단의 `INTERVAR_BUILD_FOR_ASSEMBLY`에 있습니다.

```bash
declare -A INTERVAR_BUILD_FOR_ASSEMBLY=(
    [grch38]=hg38
)
```

| assembly | intervar.build | 결과 |
|---|---|---|
| `GRCh38` | `hg38` | 통과 |
| `GRCh38` | `hg19` | **실패** — `intervar_build_mismatch` |
| `GRCh38` | `hg38x` (오타) | **실패** — `intervar_build_mismatch` |
| 매핑표에 없는 assembly | 무엇이든 | **실패** — `intervar_assembly_unmapped` |

> [!IMPORTANT]
> 매핑표에 없는 assembly라도 **core 파이프라인(QC ~ raw VCF)은 정상 실행됩니다.**
> 막히는 것은 optional InterVar 단계 하나뿐이고,
> 실패 메시지도 "core가 아니라 optional 설정 문제"임을 명시합니다.
>
> 새 assembly를 쓰려면 해당 build의 ANNOVAR humandb를 준비한 뒤
> 위 표에 한 줄만 추가하면 됩니다.
> 파이프라인을 GRCh38 전용으로 만들지 않기 위한 구조입니다.

```json
"filtering": { "preset": "balanced", "min_dp": 5, "min_gq": 10, "min_alt_depth": 3 },
"intervar":  { "install_dir": "/opt/InterVar", "build": "hg38",
               "humandb_dir": "/opt/InterVar/humandb" }
```

### 7.5 resume identity에 포함되는 key와 포함되지 않는 key

`render_config_snapshot`이 계산하는 `config_identity_sha256`은
**설정 전체가 아니라 "분석 결과를 바꾸는 값"만** 담습니다.

| identity에 **포함** | identity에 **미포함** |
|---|---|
| `run_id` | `threads`, `sort_threads`, `sort_mem`, `fastqc_threads` |
| `samplesheet` 경로 + **내용 해시** | `java_mem_gb`, `min_available_ram_gb` |
| `trim_mode` | `low_coverage_depth`, `coverage_min_mean_depth` |
| `interval_padding` | `bqsr_diagnostics` |
| `mosdepth_mapq` | `verify_fastq_gzip` |
| `pairhmm_threads` | `optional_steps.*` 토글 |
| `bqsr_target_only` | `filtering.*` 전부 |
| `resource_bundle` 전체 (경로) | `intervar.*` 전부 |
| reference FASTA / target BED / known-sites / dbSNP의 **내용 해시** | |
| lane별 FASTQ 지문 (기본은 크기+수정시각, `resume_strict_checksums=true`면 SHA-256) | |

> [!NOTE]
> **현재 한계.** `filtering.preset`, `filtering.min_dp`, `intervar.build` 같은
> **optional step 세부 설정은 identity에 포함되지 않습니다.**
> `load_config`가 이 값들을 읽지 않고, 각 optional 함수가 실행 시점에
> config에서 직접 읽기 때문입니다.
>
> 결과적으로 filtering threshold만 바꾸고 `--resume` 하면
> **기존 filtering 결과가 그대로 재사용될 수 있습니다.**
> core raw VCF에는 영향이 없지만, optional을 새 기준으로 다시 돌리려면
> 새 `run_id`를 쓰는 편이 확실합니다.
> [28장](#28-현재-한계)에 다시 정리해 두었습니다.

---

## 8. samplesheet 전체 설명

무엇을 분석할지 적는 CSV 파일입니다.

```csv
sample,lane,fastq_1,fastq_2
HG002,L001,/data/fastq/HG002_L001_R1.fastq.gz,/data/fastq/HG002_L001_R2.fastq.gz
HG002,L002,/data/fastq/HG002_L002_R1.fastq.gz,/data/fastq/HG002_L002_R2.fastq.gz
```

### 8.1 Column 전수

| Column | 의미 | 예시 | 필수 | 검증 내용 |
|---|---|---|:---:|---|
| `sample` | 검체 이름 | `HG002` | 필수 | 비어 있지 않고 `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| `lane` | 시퀀싱 lane 식별자 | `L001` | 필수 | 동일 규칙 |
| `fastq_1` | R1(앞쪽 read) 경로 | `/data/…_R1.fastq.gz` | 필수 | `.fastq.gz`/`.fq.gz`로 끝남, 존재, 일반 파일, 읽기 가능, 비어있지 않음, gzip 매직 넘버 |
| `fastq_2` | R2(뒤쪽 read) 경로 | `/data/…_R2.fastq.gz` | 필수 | 위와 동일 + R1과 달라야 함 |
| `rg_id` | read group ID | `HG002.L001` | 선택 | 없으면 `sample.lane`으로 생성. ID 문자 규칙 적용 |
| `library` | 라이브러리 이름 | `HG002` | 선택 | 없으면 `sample` |
| `platform` | 시퀀싱 플랫폼 | `ILLUMINA` | 선택 | 없으면 `ILLUMINA` |
| `platform_unit` | 플랫폼 단위 | `L001` | 선택 | 없으면 `lane` |
| `patient`, `sex`, `status` | 과거 호환용 | — | 선택 | **받아들이되 현재 profile에서는 사용하지 않음** |

그 밖의 컬럼은 **경고와 함께 무시**됩니다
(`Unknown columns are ignored: …`). 오류가 아니므로 실행은 계속됩니다.
헤더가 없거나, 컬럼 이름이 중복되거나, 빈 컬럼 이름이 있으면 실패합니다.

상대 경로는 **samplesheet 파일이 있는 디렉터리 기준**으로 해석됩니다.
혼동을 피하려면 절대 경로를 권합니다.

### 8.2 왜 한 run에 biological sample 하나만 허용하는가

현재 검증 profile이 단일 sample이기 때문입니다.
sample ID가 2개 이상이면 preflight에서 명시적으로 거부합니다.

```
The current verification profile supports exactly one biological sample per run.
Found 2: HG002, HG003. Multi-sample joint calling is out of scope.
```

이건 **구조적 제약이 아니라 범위 선언**입니다.
manifest는 이미 lane별 행 구조를 갖고 있어서, 여러 sample을 지원하려면
`GenomicsDBImport` + cohort `GenotypeGVCFs` 단계를 **추가**하면 되지 다시 쓸 필요가 없습니다.
검증하지 않은 기능을 "된다"고 열어 두지 않으려고 막아 둔 것입니다.

### 8.3 왜 여러 lane은 허용하는가

같은 검체를 여러 lane에 나눠 넣어 더 깊이 읽는 것은 아주 흔한 실험 설계입니다.
파이프라인은 **lane별로 따로 QC하고 따로 정렬한 뒤 sample 단위로 merge**합니다.

lane별로 나눠 처리하는 이유:

- lane마다 품질이 다를 수 있습니다. 합쳐 버리면 "3번 lane만 이상하다"를 알 수 없습니다.
- read group을 lane 단위로 붙여야 GATK가 lane별 오류 경향을 구분해 학습합니다.

### 8.4 R1과 R2

DNA 조각 하나의 앞쪽 끝을 읽은 것이 R1, 뒤쪽 끝을 읽은 것이 R2입니다.
두 파일의 같은 순번 read는 **같은 DNA 조각**에서 나온 짝입니다.

그래서 `fastq_1`과 `fastq_2`가 **같은 파일이면 거부**합니다.
복사·붙여넣기 실수로 흔히 발생하며, 그대로 두면 짝이 맞지 않는 정렬 결과가 나옵니다.

### 8.5 read group, library, platform, platform unit

**read group(RG)** 은 "이 read가 어떤 검체의, 어떤 라이브러리의, 어떤 lane에서
나왔는지"를 BAM 안에 적어 두는 꼬리표입니다.

정렬 시 다음 형태로 BAM에 기록됩니다.

```
@RG  ID:<rg_id>  SM:<sample>  LB:<library>  PL:<platform>  PU:<platform_unit>
```

| 필드 | 의미 | 왜 필요한가 |
|---|---|---|
| `ID` | 이 read group의 고유 식별자 | 여러 lane을 merge해도 출처를 구분 |
| `SM` | sample 이름 | **최종 VCF의 sample 컬럼 이름이 됨** |
| `LB` | library 이름 | MarkDuplicates가 **같은 라이브러리 안에서만** 중복을 판정 |
| `PL` | 플랫폼 (`ILLUMINA` 등) | 도구가 플랫폼별 특성을 반영 |
| `PU` | 플랫폼 단위 (보통 lane) | BQSR이 lane별 오류 경향을 구분해 학습 |

GATK는 이 정보를 필수로 요구합니다.

### 8.6 BAM의 SM 태그와 sample 이름이 일치해야 하는 이유

`SM` 값이 그대로 **최종 VCF의 sample 컬럼 이름**이 되기 때문입니다.
여기가 어긋나면 "이 변이가 누구 것인지"가 틀어지고, 이후 모든 해석이 무의미해집니다.

파이프라인은 이걸 말로만 요구하지 않고 **세 곳에서 실제로 확인**합니다.

| 확인 위치 | 확인 내용 | 실패 시 |
|---|---|---|
| `run_alignment` — lane BAM | 헤더에 `SM:<sample>`이 있는가 | step 실패 |
| `run_alignment` — merged BAM | `SM` 값이 **정확히 하나**이고 manifest의 sample과 같은가 | step 실패 |
| `run_processing` — analysis-ready BAM | 헤더에 `SM:<sample>`이 있는가 | step 실패 |
| `run_variant_calling` — raw VCF | sample 컬럼이 정확히 하나이고 `SM`과 같은가 | step 실패 |

### 8.7 중복 차단 규칙

| 규칙 | 왜 |
|---|---|
| **동일 FASTQ 재사용 금지** | 같은 파일이 두 행에 나오면 같은 read를 두 번 세게 됩니다. coverage가 부풀려지고 duplicate 비율 계산도 틀어집니다 |
| **sample + lane 조합 중복 금지** | 같은 lane을 두 번 처리하는 실수 방지 |
| **lane 간 library/platform 일치 필수** | 같은 sample인데 metadata가 다르면 merge 후 read group 해석이 위험해집니다 |
| **값 안의 탭·개행 금지** | manifest TSV 형식이 깨집니다 |

### 8.8 검증 통과 후 만들어지는 것

| 파일 | 형식 | 내용 |
|---|---|---|
| `00_input_validation/manifest.tsv` | 8컬럼 TSV (헤더 없음) | `sample`, `lane`, `rg_id`, `library`, `platform`, `platform_unit`, `fastq_1`(절대경로), `fastq_2`(절대경로) |
| `config/normalized_manifest.json` | JSON | `sample`, `library`, `platform`, `lane_count`, `lanes[]` |
| `00_input_validation/samplesheet_validation.txt` | 텍스트 | 검증 과정에서 나온 모든 경고·오류 |

오류가 하나라도 있으면 manifest는 **아예 만들어지지 않고**,
발견된 오류가 **전부 한꺼번에** 출력됩니다.
하나 고치고 다시 돌리기를 반복하지 않게 하기 위함입니다.

---

## 9. 입력 검증

**위치: `script/main.sh > run_input_validation()` — step `00_input_validation`**

### `run_input_validation()`

**한 줄 역할**
분석 산출물을 만들기 전에, 이 run이 진행 가능한 상태인지 전부 확인합니다.

**왜 필요한가**
WES 전체 실행은 몇 시간이 걸립니다. 3시간 뒤에 "known-sites 인덱스가 없다"로
실패하는 것보다 시작 3분 안에 알아내는 편이 압도적으로 낫습니다.
더 중요한 이유는, **build mismatch 같은 오류는 에러 없이 틀린 답을 만들기 때문에**
사전 검증이 사실상 유일한 방어선이라는 점입니다.

**입력**
run config, samplesheet, resource bundle 선언

**주요 처리**
아래 6개 검증 함수를 순서대로 호출합니다.

| 순서 | 함수 | 확인 내용 | 실패 시 |
|---|---|---|---|
| 1 | `validate_tools` | 필수 도구가 PATH에 있는가, 버전 기록 | 검사 실패 기록 (step 실패로 이어짐) |
| 2 | `validate_samplesheet` | samplesheet 구조·ID·FASTQ 실체 | **즉시 step 실패** |
| 3 | `validate_reference_bundle` | reference·인덱스·BED·known-sites 정합성 | **즉시 step 실패** |
| 4 | `validate_output_root` | run 디렉터리가 `output_root` 안에 있는가 | 검사 실패 기록 |
| 5 | `validate_fastq_integrity` | (선택) FASTQ 전체 gzip 스트림 검사 | 검사 실패 기록 |
| 6 | `validate_compute_resources` | 디스크·RAM·CPU | 검사 실패 기록 |

2번과 3번은 실패하면 뒤 검사를 하지 않고 즉시 중단합니다.
samplesheet가 깨져 있으면 이후 검사가 의미 없기 때문입니다.

**사용하는 명령과 옵션**
분석 도구는 하나도 실행하지 않습니다. resource 검증을 위해
`bcftools view -h`(헤더 파싱)와 `tabix -l`(contig 목록)만 읽기 전용으로 사용합니다.

**출력**

| 파일 | 내용 |
|---|---|
| `00_input_validation/manifest.tsv` | 정규화된 8컬럼 manifest |
| `config/normalized_manifest.json` | sample/lane 구조화 JSON |
| `00_input_validation/samplesheet_validation.txt` | samplesheet 검증 출력 |
| `00_input_validation/resource_validation.txt` | resource 검증 출력 |
| `logs/software_versions.txt` | 도구 버전 기록 |
| `logs/resource_sha256.txt` | reference·BED·known-sites의 SHA-256 |

**성공 판정**
실패로 기록된 검사가 0건. warning은 있어도 진행합니다.

**실패 처리**
발견한 오류를 **모아서** 보고하고 step을 `failed`로 마감합니다.

**다음 단계 전달**
`SAMPLE_ID`, `LANE_COUNT` 변수와 `manifest.tsv` / `normalized_manifest.json` 파일.

**이렇게 구현한 이유**
"실패는 빠르고 시끄럽게"가 원칙입니다.
특히 resource 검증은 조용한 오답을 막는 유일한 지점이라 타협하지 않았습니다.

**초보자가 헷갈릴 부분**
이 단계가 `bcftools`와 `tabix`를 실행하는 걸 보고 "분석이 시작됐나?" 오해할 수 있는데,
헤더와 인덱스를 **읽기만** 하는 검증입니다. read를 정렬하거나 변이를 찾지 않습니다.

### 9.1 `validate_samplesheet()`가 실제로 잡아내는 것

| 검사 | 왜 |
|---|---|
| 필수 컬럼 4개 존재 | 없으면 이후 단계가 전부 실패 |
| 컬럼 이름 중복·공백 없음 | 파싱 결과가 예측 불가능해짐 |
| ID 문자 규칙 `^[A-Za-z0-9][A-Za-z0-9._-]*$` | 공백·슬래시는 경로를 깨뜨리고, **`-`로 시작하면 명령 옵션으로 오인**될 수 있음 |
| FASTQ 확장자가 `.fastq.gz` / `.fq.gz` | 압축되지 않은 입력을 조기 차단 |
| FASTQ 존재·일반 파일·읽기 가능·비어있지 않음 | 가장 흔한 실수 |
| gzip 매직 넘버(앞 2바이트 `\x1f\x8b`) | 압축이 아닌 파일을 즉시 탐지 |
| R1 ≠ R2 | 같은 파일을 짝으로 넣는 실수 방지 |
| 동일 FASTQ 재사용 금지 | coverage 부풀림 방지 |
| sample+lane 중복 금지 | 같은 lane 이중 처리 방지 |
| sample이 정확히 1개 | 현재 검증 profile의 범위 |
| lane 간 library/platform 일치 | merge 후 read group 해석 안전성 |
| 값 안에 탭·개행 없음 | manifest TSV 형식 보호 |
| 데이터 행이 1개 이상 | 헤더만 있는 파일 차단 |

### 9.2 `validate_reference_bundle()`가 실제로 잡아내는 것

- reference FASTA, `.fai`, `.dict`, BWA index 5종(`.amb .ann .bwt .pac .sa`) **존재와 비어있지 않음**
- `.fai`와 `.dict`의 **contig 순서와 길이가 완전히 동일**한가
- 선언한 `contig_style`이 실제 reference의 `chr` 접두사 사용과 맞는가
- target BED: 컬럼 3개 이상, 좌표가 정수, contig가 reference에 존재,
  `start >= 0`, `end > start`, `end <= contig 길이`
- target BED에 사용 가능한 구간이 1개 이상 있는가
- known-sites가 **비어 있지 않은가** (`BQSR is a core step and requires known sites`)
- known-sites마다 `.tbi` 또는 `.csi` 인덱스가 있는가
- known-sites 헤더가 `bcftools view -h`로 파싱되는가
- known-sites의 모든 contig가 reference contig의 부분집합인가
- known-sites 헤더에 contig 길이가 있으면 reference `.fai`의 길이와 같은가
- **`dbsnp_vcf`를 선언했다면 위 다섯 항목을 똑같이 통과하는가**

known-sites와 dbSNP는 `check_vcf_resource()`라는 **하나의 helper**를 공유합니다.
같은 종류의 resource에 서로 다른 기준을 적용하지 않기 위해서입니다.

부수적으로 다음 지표를 기록합니다:
`target_rows`(원본 BED 행 수), `target_merged_rows`(겹침 제거 후 행 수),
`target_merged_bases`(겹침 제거 후 총 염기 수), `assembly`, `contig_style`, `bundle_id`.

> [!IMPORTANT]
> **이 검사의 결론은 `structurally compatible`입니다.**
>
> 통과 메시지는 다음과 같이 기록됩니다.
>
> ```
> [OK] Resource bundle is structurally compatible
>      (contig names, lengths and coordinate ranges agree).
> [NOTE] Structural compatibility is not proof of shared build provenance;
>        that is asserted by the declared resource_bundle, not by these checks.
> ```
>
> `build verified`나 `same build confirmed`라고 쓰지 않습니다.
> 이유는 [4.4](#44-build가-안-맞으면-왜-위험한가)에 있습니다.

> **`$HOME` 경로 제한을 제거한 이유**
> 원본 코드에는 reference가 `$HOME/sideprojects/` 아래에 있어야 한다는 검사와
> 프로젝트 전용 subset 경로 가드가 있었습니다.
> 둘 다 **다른 사용자나 다른 서버에서는 무조건 실패**하게 만들었으므로 제거했습니다.
> 대신 위의 정합성 검사를 추가해, 경로가 아니라 **내용**으로 안전성을 확인합니다.

### 9.3 `validate_tools()`

필수 도구 목록을 `have_command`로 확인하고, 없는 것을 **한꺼번에** 보고합니다.
그리고 `logs/software_versions.txt`에 다음을 기록합니다.

```
pipeline_name, pipeline_version, run_id, host, user, conda_env,
bwa, samtools, gatk, bcftools, mosdepth, fastqc, fastp, multiqc, java, python
```

MultiQC만은 없어도 **warning**입니다. 어떤 분석 단계도 MultiQC 출력을 읽지 않기 때문입니다.

### 9.4 `validate_fastq_integrity()`

samplesheet 검증은 gzip **매직 넘버 2바이트**만 봅니다. 값싸지만
**잘린 파일은 탐지하지 못합니다.**

`verify_fastq_gzip: true`로 설정하면 `gzip -t`로 전체 스트림을 검사합니다.
전체 WES 입력을 끝까지 읽으므로 수 분이 걸립니다. 그래서 **기본은 꺼짐**이며,
껐을 때는 "매직 넘버만 확인했고 잘린 FASTQ는 정렬 단계에서 드러난다"는 사실을
검증 리포트에 남깁니다.

| 설정 | 기록되는 지표 |
|---|---|
| `false` (기본) | `fastq_gzip_verification = magic_only` |
| `true` | `fastq_gzip_verification = full_stream` |

`gzip` 명령 자체가 없으면 warning(`GZIP_MISSING`)을 남기고 넘어갑니다.

### 9.5 `validate_compute_resources()`

| 자원 | 검사 방법 | 판정 |
|---|---|---|
| 디스크 | manifest의 FASTQ 총 바이트 × 7 + 20 GB를 `df -Pk`의 여유와 비교 | 부족하면 **실패**, 측정 불가면 warning |
| RAM | `/proc/meminfo`의 `MemAvailable`을 `min_available_ram_gb`와 비교 | 미달이면 **실패**, 파일이 없으면 warning |
| CPU | `nproc`와 `threads`를 비교 | `threads`가 논리 코어 수를 넘으면 **실패** |

디스크 추정식 `(압축 FASTQ 바이트 × 7) + 20 GB`는 원본 Processing 스크립트의
보수적 휴리스틱을 그대로 가져온 것입니다.
lane BAM, merged BAM, markdup BAM, analysis-ready BAM, gVCF가 동시에 존재하는
최대 시점을 감안한 값입니다.

### 9.6 `validate_output_root()`

- run 디렉터리가 `output_root` **안에** 있는지 확인합니다 (`path_under`).
  심볼릭 링크를 따라간 실제 경로로 비교하므로, 링크를 이용해 밖으로 빠져나가는
  구성을 잡아냅니다.
- samplesheet가 run 디렉터리 **안에** 있으면 warning(`SAMPLESHEET_INSIDE_RUN`).
  run 디렉터리를 지우면 samplesheet까지 사라져 resume이 불가능해지기 때문입니다.

---

## 10. Raw QC

**위치: `script/main.sh > run_raw_qc()` — step `01_raw_qc`**

### `run_raw_qc()`

**한 줄 역할**
정렬 전 read의 품질을 lane별로 확인하고 리포트를 남깁니다.

**왜 필요한가**
분석 결과가 이상할 때 **"원본 데이터가 원래 나빴는가, 분석이 잘못됐는가"** 를
구분하려면 정렬 전 상태의 기록이 반드시 필요합니다.
나중에는 되돌아가 만들 수 없는 증거입니다.

**입력**
`00_input_validation/manifest.tsv`, 그리고 그 안에 적힌 원본 FASTQ

**주요 처리**
manifest를 한 줄씩 읽어 lane마다 FastQC를 돌리고, 마지막에 MultiQC로 집계합니다.

**사용하는 명령과 옵션**

| 도구 | 실제 명령 | 옵션 의미 |
|---|---|---|
| FastQC | `fastqc --threads "$qc_threads" --outdir "$unit_dir" "$fq1" "$fq2"` | `--threads`: 병렬 처리 (`fastqc_threads`와 `threads` 중 **작은 값**, 최소 1) / `--outdir`: **lane 전용 디렉터리** |
| MultiQC | `multiqc --force --outdir "$multiqc_dir" "$fastqc_dir"` | `--force`: 기존 리포트 덮어쓰기 허용 |

**FastQC가 확인하는 것** (초보자용)

- 위치별 품질 점수 — read 끝으로 갈수록 품질이 떨어지는 것은 정상입니다
- adapter 오염 — 실험용 인공 서열이 남아 있는지
- GC 비율 — 예상과 크게 다르면 오염 의심
- read 길이 분포, 중복 수준, 과대표현 서열

**왜 lane별로 실행하나**
lane마다 품질이 다를 수 있습니다. 합쳐 버리면 특정 lane만 이상한 상황을 놓칩니다.

**출력**

| 파일 | 설명 |
|---|---|
| `01_raw_qc/fastqc/<sample>.<lane>/<stem>_fastqc.html` | lane당 2개 (R1, R2) |
| `01_raw_qc/fastqc/<sample>.<lane>/<stem>_fastqc.zip` | lane당 2개 (원시 데이터) |
| `01_raw_qc/multiqc/multiqc_report.html` | MultiQC가 있을 때만 |

`<stem>`은 FASTQ 파일명에서 `.gz`와 `.fastq`/`.fq`를 떼어낸 이름입니다.
보조 함수 `fastqc_stem()`이 FastQC의 출력 파일명 규칙을 그대로 재현하므로,
**예상 출력 경로를 추측이 아니라 계산으로** 얻습니다.

**성공 판정**
lane마다 예상 출력 4개(HTML 2, ZIP 2)가 모두 존재하고 비어있지 않아야 합니다.

**실패 처리 — FastQC와 MultiQC를 구분합니다**

| 상황 | 처리 | 이유 |
|---|---|---|
| FastQC 실행 실패 | **step 실패** | 품질 근거는 core 리포트의 일부 |
| FastQC 출력 누락 | **step 실패** | 동일 |
| MultiQC 미설치 | warning (`MULTIQC_MISSING`) | 개별 FastQC 결과는 그대로 있음 |
| MultiQC 실행 실패 | warning (`MULTIQC_FAILED`) | 분석 결과를 바꾸지 않음 |
| MultiQC가 리포트 미생성 | warning (`MULTIQC_NO_REPORT`) | 동일 |

**핵심 판단**: MultiQC는 **사람이 보는 요약 리포트**일 뿐이고,
어떤 분석 단계도 그 출력을 읽지 않습니다.
없다고 변이 호출이 달라지지 않으므로 warning입니다.
FastQC 결과는 최종 보고서에 들어가는 근거이므로 실패로 처리합니다.

**다음 단계 전달**
없습니다. QC는 **관찰이지 변형이 아닙니다.**
다음 단계는 이 단계의 산출물을 읽지 않습니다.

**이렇게 구현한 이유**
"보고서용 도구가 없다고 분석이 멈추면 안 된다"와
"품질 근거가 없으면 결과를 신뢰할 수 없다"를 둘 다 지키기 위해,
두 도구의 실패 등급을 다르게 두었습니다.

**초보자가 헷갈릴 부분**
FastQC 결과가 나쁘다고 파이프라인이 자동으로 멈추거나 데이터를 고치지 않습니다.
**보여주기만 하고 판단은 사람이 합니다.**

**재실행 안전성**
같은 lane의 예상 출력 4개가 이미 다 있으면 `[SKIP]` 로그를 남기고 건너뜁니다.
하나라도 없으면 4개를 모두 지우고 다시 만듭니다.
부분적으로 남은 이전 출력이 섞이지 않게 하기 위함입니다.

---

## 11. preprocessing과 trimming 분기

**위치: `script/main.sh > run_preprocessing()` — step `02_preprocessing`**

### 11.1 trimming이란

시퀀싱 라이브러리를 만들 때 DNA 조각 양끝에 **adapter**라는 인공 서열을 붙입니다.
DNA 조각이 read 길이보다 짧으면 기계가 조각을 다 읽고 adapter까지 읽어 버립니다.
이 인공 서열과 품질이 나쁜 끝부분을 잘라내는 작업이 **trimming**입니다.

### 11.2 왜 항상 trimming하지 않는가

- BWA-MEM에는 **soft-clipping** 기능이 있어, 맞지 않는 read 끝부분을 정렬에서
  자동으로 제외합니다. adapter가 조금 남아도 정렬 자체는 견딥니다.
- trimming은 전체 FASTQ를 한 번 더 읽고 쓰므로 시간과 저장공간을 소비합니다.
- 무엇보다 **근거 없이 원본 데이터를 변형해서는 안 됩니다.**

### 11.3 왜 자동 trimming을 기본으로 두지 않는가

"adapter 비율이 N%를 넘으면 자동으로 자른다" 같은 규칙을 만들려면
그 N을 정당화할 근거가 필요합니다. 현재 그 근거가 확정되어 있지 않습니다.

그래서 `trim_mode`는 **`skip`과 `force` 두 값만** 허용하고,
다른 값이 들어오면 다음 메시지와 함께 즉시 중단합니다.

```
trim_mode must be 'skip' or 'force' (got '...').
An automatic threshold mode is not implemented.
```

근거 없는 임계값을 코드에 박아 넣는 대신, **사람이 선택하고 그 선택을 기록**하도록 했습니다.

### 11.4 `skip`도 의사결정 기록 단계인 이유

`skip`이어도 이 단계는 반드시 두 파일을 만듭니다.

- `02_preprocessing/fastq_manifest.tsv` — Alignment가 읽을 FASTQ 목록
- `02_preprocessing/preprocessing_decision.json` — 결정 내용과 이유

즉 **"자르지 않기로 했고, 그래서 이 파일들을 정렬에 쓴다"** 는 사실을 명시적으로 선언합니다.

덕분에 `run_alignment`는 `trim_mode`가 무엇이었는지 알 필요 없이
**항상 같은 8컬럼 형식의 manifest 하나만** 읽으면 됩니다.
두 모드에서 컬럼 구조가 동일합니다.

`preprocessing_decision.json`의 주요 필드:

| 필드 | `skip`일 때 | `force`일 때 |
|---|---|---|
| `mode` | `"skip"` | `"force"` |
| `decision` | `"not_trimmed"` | `"trimmed"` |
| `reason` | 설정에 따라 원본을 그대로 쓴다는 설명 | fastp를 모든 lane에 적용했다는 설명 |
| `automatic_threshold_decision` | `false` | `false` |
| `lanes[]` | lane별 입력/출력 FASTQ 쌍과 `trimmed` 여부 | 동일 |
| `fastp_output_dir` | `null` | fastp 리포트 디렉터리 |

> 직전 리비전에는 **fastp를 실제로 실행하면서 기록에는 "trimming 없음"이라고
> 적는** 모순이 있었습니다. 이제 결정을 내리는 함수가 그 결정을 한 번만 기록합니다.

### 11.5 `force`일 때의 fastp

**한 lane씩** 다음 명령을 실행합니다.

```bash
fastp -i "$fq1" -I "$fq2" -o "$r1_part" -O "$r2_part" \
      --detect_adapter_for_pe \
      --qualified_quality_phred 20 \
      --unqualified_percent_limit 40 \
      --length_required 50 \
      --thread "$THREADS" \
      --json "$fastp_json" --html "$fastp_html"
```

| Option | 실제 값 | 의미 | 선택 이유 | 변경 시 주의 |
|---|---|---|---|---|
| `-i` / `-I` | R1 / R2 | 입력 쌍 | — | — |
| `-o` / `-O` | `.part` 경로 | 출력 쌍 | 검증 전까지 최종 이름을 쓰지 않음 | — |
| `--detect_adapter_for_pe` | 사용 | paired-end adapter 자동 탐지 | adapter 서열을 수동 지정하지 않아도 됨 | 자동 탐지 결과는 fastp 리포트에서 확인 |
| `--qualified_quality_phred` | `20` | "양호"로 볼 품질 기준 | Phred 20 = 오류율 1% | 아래 주의 참고 |
| `--unqualified_percent_limit` | `40` | 저품질 염기 허용 비율(%) | 40% 초과면 read 폐기 | 동일 |
| `--length_required` | `50` | 최소 read 길이 | 너무 짧으면 정렬 위치가 모호해짐 | 동일 |
| `--thread` | config `threads` | 병렬 처리 | — | — |
| `--json` / `--html` | 리포트 경로 | 전후 read 수 확인용 | 지표로 기록됨 | — |

> [!NOTE]
> 위 세 threshold(20 / 40 / 50)는 **원 작성자의 값을 그대로 보존**한 것입니다.
> 현재 코드에서 값은 확인되지만, 이 값을 선택한 근거는 기존 자료에서
> 명확히 확인되지 않았습니다.
> Linux smoke test와 팀 합의를 거쳐 재검토가 필요합니다.
>
> `trim_mode` 기본값이 `skip`이므로, 기본 실행에서는 이 값들이 사용되지 않습니다.

**fastp 실행 후 검증**: 출력 두 파일이 모두 비어있지 않은지 확인한 뒤에만
`.part`에서 최종 이름으로 바꿉니다. 하나라도 비어 있으면 `.part`를 지우고 실패합니다.

**기록되는 지표**: lane마다 `reads_before_<unit>`, `reads_after_<unit>`을
fastp JSON에서 읽어 기록합니다.

### 11.6 fastp가 없으면

`trim_mode=force`인데 fastp가 설치되어 있지 않으면 **step이 실패**합니다.

```
trim_mode=force but fastp is not installed.
Install it before running; the pipeline never installs software.
```

**실행 도중 `conda install`로 설치하지 않는 이유:**

- 분석 도중 서버 환경을 바꾸면 같은 서버를 쓰는 다른 사람에게 영향을 줍니다
- 설치되는 버전이 실행할 때마다 달라져 **재현성이 깨집니다**
- provenance 기록(어떤 버전으로 만들었는가)이 무의미해집니다

직전 리비전에는 `conda install -c bioconda fastp -y`가 분석 경로 안에 있었고,
이번에 제거했습니다.

### 11.7 요약

| 항목 | 내용 |
|---|---|
| **입력** | `00_input_validation/manifest.tsv`, config `trim_mode` |
| **출력 (항상)** | `fastq_manifest.tsv`, `preprocessing_decision.json` |
| **출력 (`force`만)** | `fastq_clean/<sample>.<lane>_R1.clean.fastq.gz` 및 `_R2`, `fastp/<sample>.<lane>.fastp.json` / `.html` |
| **성공 판정** | lane 수 > 0, `force`면 trimmed FASTQ 양쪽 모두 비어있지 않음 |
| **실패** | manifest 없음/비어있음, fastp 미설치, fastp 비정상 종료, 빈 출력, lane 0개 |
| **다음 단계 전달** | `FASTQ_MANIFEST` 변수와 `fastq_manifest.tsv` 파일 |

**초보자가 헷갈릴 부분**
`skip` 모드인데 step 상태가 `skipped`가 아니라 `completed`입니다.
이건 **실제로 결정을 내리고 산출물을 만들었기 때문**입니다.
"안 했다"가 아니라 "안 하기로 결정했고 그 근거를 남겼다"입니다.

---

## 12. Alignment

**위치: `script/main.sh > run_alignment()` — step `03_alignment`**

### 12.1 정렬(alignment)이란

FASTQ 안의 read는 `ATCGGA…`라는 **글자열**일 뿐, 그것이 유전체의 어디인지는 모릅니다.
정렬은 이 짧은 글자열을 **표준 인간 유전체 위 가장 잘 맞는 자리에 붙이는** 작업입니다.

> 비유: 완성된 그림(reference)이 이미 있는 상태에서,
> 흩어진 퍼즐 조각(read)이 그림의 어디에 해당하는지 찾아 표시하는 것입니다.
> 다만 조각이 수억 개이고, 그림에는 비슷하게 생긴 부분이 많습니다.

### 12.2 데이터 흐름

```
R1 + R2
  → BWA-MEM              (reference 위 위치 찾기, SAM 스트림 생성)
  → samtools sort        (좌표 순서로 줄 세우기)
  → lane BAM             (lane 하나당 파일 하나)
  → merge                (여러 lane을 하나로)
  → sample BAM
  → index                (.bai 생성)
  → quickcheck / flagstat / stats  (구조와 통계 확인)
```

### 12.3 `run_alignment()`

**한 줄 역할**
lane별 FASTQ를 reference에 정렬해 coordinate-sorted BAM으로 만들고,
sample 단위 BAM 하나로 합칩니다.

**왜 필요한가**
서열만으로는 아무것도 할 수 없습니다.
"이 read가 7번 염색체 117,199,644번 위치에 붙는다"를 알아야
그 자리의 변이를 따질 수 있습니다.

**입력**
`02_preprocessing/fastq_manifest.tsv`, reference FASTA와 BWA index

**주요 처리 — lane 단위**

```bash
bwa mem -K 100000000 -Y -t "$THREADS" -R "$rg_string" "$REF_FASTA" "$fq1" "$fq2" \
  | samtools sort -@ "$SORT_THREADS" -m "$SORT_MEM" \
        -T "$tmp_dir/sort_${unit}" -O bam -o "$lane_part" -
```

BWA-MEM 옵션:

| Option | 실제 값 | 의미 | 선택 이유 | 변경 주의 |
|---|---|---|---|---|
| `-K` | `100000000` (1억) | 배치당 처리할 염기 수를 **고정** | BWA는 기본적으로 스레드 수에 따라 배치 크기가 달라져 **결과 BAM이 미세하게 달라집니다.** 이 값을 고정하면 스레드 수와 무관하게 동일한 BAM이 나옵니다 → 재현성 | 메모리를 조금 더 사용 |
| `-Y` | — | hard-clip 대신 **soft-clip** 사용 | soft-clip은 잘린 서열을 BAM에 그대로 남깁니다. 나중에 SV·breakpoint 분석 여지를 남김 | BAM 크기 소폭 증가 |
| `-t` | config `threads` | 병렬 스레드 | 서버 자원에 맞춤 | `-K` 덕분에 결과는 바뀌지 않음 |
| `-R` | `@RG\tID:…\tSM:…\tLB:…\tPL:…\tPU:…` | read group 태그 | GATK 필수. `SM`이 최종 VCF의 sample 이름 | samplesheet의 sample과 반드시 일치 |

`samtools sort` 옵션:

| Option | 실제 값 | 의미 | 변경 주의 |
|---|---|---|---|
| `-@` | config `sort_threads` | 정렬 스레드 | — |
| `-m` | config `sort_mem` (기본 `2G`) | **스레드당** 메모리 | **총 사용량 ≈ `sort_threads` × `sort_mem`.** 4 × 2G = 8G. 이걸 총량으로 착각하면 OOM |
| `-T` | `tmp/03_alignment/sort_<sample>.<lane>` | 임시 파일 접두사 | run 전용 경로. 다른 run과 충돌 방지 |
| `-O bam -o … -` | — | BAM으로 출력, stdin에서 입력 | 파이프 직결 |

**왜 파이프로 연결하나**
BWA의 출력(SAM)은 매우 큽니다. 디스크에 썼다가 다시 읽으면 시간과 공간이 크게 낭비됩니다.
파이프로 바로 넘기면 **중간 SAM 파일이 아예 생기지 않습니다.**

**파이프의 함정과 대응 (PIPESTATUS)**
파이프에서는 앞 명령(BWA)이 실패해도 뒤 명령(sort)이 성공하면 전체가 "성공"처럼 보입니다.
`set -o pipefail`이 켜져 있어도 **어느 쪽이 실패했는지**는 알 수 없습니다.

그래서 이 파이프라인은 파이프 실행 직후 `PIPESTATUS` 배열을 저장해
**각 요소의 종료 코드를 개별 확인**하고, 실패 시 두 코드를 함께 보고합니다.

```
bwa exit=1, samtools sort exit=0; see logs/03_alignment.bwa_HG002.L001.stderr.log
```

BWA가 중간에 죽었는데 잘린 BAM이 다음 단계로 넘어가는 사고를 막습니다.
이 안전 로직은 원본 Processing 스크립트에서 가져와 합친 부분입니다.

**merge 처리**

| lane 수 | 처리 | 이유 |
|---|---|---|
| 1개 | `ln`(하드 링크), 실패하면 `cp` | 단일 lane BAM은 이미 sample 단위 read group을 갖고 있습니다. 수십 GB 파일을 복제할 이유가 없습니다 |
| 2개 이상 | `samtools merge -@ "$THREADS" -f -o "$sample_part" "${lane_bams[@]}"` | — |

merge 전에 모든 lane BAM에 대해 존재 확인과 `samtools quickcheck`를 다시 수행합니다.

**출력**

| 경로 | 설명 |
|---|---|
| `03_alignment/lane_bam/<sample>.<lane>.sorted.bam` (+ `.bai`) | lane별 정렬 BAM |
| `03_alignment/lane_bam/<sample>.<lane>.done` | 재실행 시 완료 표시 |
| `03_alignment/lane_bam/<sample>.<lane>.{flagstat,idxstats,stats}.txt` | lane별 통계 |
| `03_alignment/sample_bam/<sample>.sorted.bam` (+ `.bai`) | **sample 단위 BAM** |
| `03_alignment/sample_bam/<sample>.done` | 완료 표시 |
| `03_alignment/sample_bam/<sample>.{flagstat,stats}.txt` | sample 통계 |
| `03_alignment/alignment_output.json` | 다음 단계가 읽는 계약 문서 |

**성공 판정 — 실제로 확인하는 것**

| 검사 | 대상 | 실패 시 |
|---|---|---|
| `PIPESTATUS` 두 요소 모두 0 | bwa \| sort | step 실패 |
| `samtools quickcheck -v` | `.part` BAM | `.part` 삭제 후 step 실패 |
| `@HD … SO:coordinate` 헤더 존재 | lane BAM, merged BAM | step 실패 |
| `SM:<sample>` 존재 | lane BAM | step 실패 |
| `SM` 값이 **정확히 하나**이고 sample과 같음 | merged BAM | step 실패 |
| `samtools idxstats` 실행 가능 | merged BAM | step 실패 |
| lane 수 > 0 | manifest | step 실패 |
| manifest 안의 sample이 하나 | manifest | step 실패 |

**기록되는 지표**: `lane_count`, `sample`, `total_alignment_records`,
`mapped_pct`, `properly_paired_pct`.

**실패 처리**
`.part` 파일을 제거하고 최종 이름을 만들지 않습니다.
실패한 step이 "완성된 것처럼 보이는 파일"을 남기지 않습니다.

**다음 단계 전달**
`SAMPLE_ID`, `LANE_COUNT`, `SAMPLE_BAM` 변수와 `alignment_output.json`.

**이렇게 구현한 이유**
두 사람이 작성한 정렬 코드가 있었습니다.
lane을 인지하는 쪽을 **기본 구현**으로 삼고 (samplesheet 계약과 맞기 때문),
다른 쪽에서는 **안전 로직만** 가져와 합쳤습니다
(`PIPESTATUS` 검사, `sort -T`/`-m`, 정렬 순서·`SM` 검증, 명령별 stderr 로그, 명령 기록).
다른 쪽의 BWA-MEM 호출 자체는 실행하지 않습니다.
그대로 두면 **같은 read를 두 번 정렬**하게 되기 때문입니다.

**재실행 안전성**
lane BAM은 `.bam` + `.bai` + `.done`이 모두 있고 `samtools quickcheck`를
통과할 때만 재사용합니다. quickcheck에 실패하면 경고를 남기고 다시 만듭니다.
sample BAM도 같은 규칙입니다. **`.done` 파일만으로는 절대 건너뛰지 않습니다.**

**초보자가 헷갈릴 부분**
"정렬"이라는 한국어 단어가 두 가지를 가리킵니다.

- **alignment(정렬)** = read를 유전체 위 제자리에 붙이는 것
- **sort(정렬)** = BAM 안의 read를 좌표 순서대로 줄 세우는 것

완전히 다른 작업이며, GATK는 후자(coordinate-sorted)를 요구합니다.
이 문서에서는 후자를 가리킬 때 "coordinate sort"라고 적습니다.

---

## 13. Processing

**위치: `script/main.sh > run_processing()` — step `04_processing`**

이 단계가 파이프라인에서 **가장 복잡**합니다.
정렬된 BAM을 "변이를 찾을 수 있는 상태"로 다듬는 일을 순서대로 합니다.

```
sample BAM
   ↓ ① MarkDuplicates       중복 read에 표시
   ↓ ② ValidateSamFile      BAM이 GATK 기준에 맞는지 검사
   ↓ ③ (조건부) samtools calmd   NM/MD 태그 재계산
   ↓ ④ BaseRecalibrator     오류 경향 모델 학습
   ↓ ⑤ ApplyBQSR            품질 점수 재기록
   ↓ ⑥ index → 검증 → 공개
analysis-ready BAM
```

### 13.1 MarkDuplicates

**중복(duplicate)이 왜 생기나**
라이브러리를 만들 때 PCR로 DNA를 증폭합니다.
이때 **같은 원본 분자에서 복사본이 여러 개** 생기고, 각각이 read로 읽힙니다.

**왜 문제인가**
같은 분자에서 나온 read 10개는 **독립적인 증거가 아닙니다.**
그런데 변이 호출 도구는 "10개 read가 지지한다"고 착각합니다.
증폭 과정에서 생긴 오류 하나가 10번 반복되면 **가짜 변이가 진짜처럼 보입니다.**

**실제 명령**

```bash
gatk --java-options "-Xmx${JAVA_MEM_GB}g -Djava.io.tmpdir=${tmp_dir}" MarkDuplicates \
    -I "$SAMPLE_BAM" -O "$markdup_part" -M "$markdup_metrics" \
    --REMOVE_DUPLICATES false --CREATE_INDEX false \
    [--READ_NAME_REGEX null] \
    --TMP_DIR "$tmp_dir"
```

| Option | 실제 값 | 의미 | 선택 이유 | 변경 주의 |
|---|---|---|---|---|
| `--REMOVE_DUPLICATES` | `false` | **표시만 하고 삭제하지 않음** | 지운 데이터는 되돌릴 수 없습니다. 변이 호출 도구는 flag를 보고 알아서 제외하므로 삭제할 이유가 없고, 나중에 중복 비율을 다시 계산할 수도 있습니다 | `true`로 바꾸면 원본 read가 사라짐 |
| `--CREATE_INDEX` | `false` | 인덱스는 `samtools index`로 별도 생성 | 인덱스 생성 실패를 **독립적으로 감지**하기 위함 | — |
| `--TMP_DIR` | `tmp/04_processing` | 임시 파일 위치 | 시스템 `/tmp`가 작으면 실패합니다. run 디렉터리 안으로 고정 | — |
| `--READ_NAME_REGEX` | 조건부 `null` | optical duplicate 판정용 정규식 | 아래 참고 | — |

**왜 duplicate를 삭제하지 않는가 (정책)**
이 파이프라인의 일관된 원칙은 **"판단은 기록하고, 데이터는 지우지 않는다"** 입니다.
duplicate flag는 BAM의 FLAG 필드 비트 하나이며, 모든 하위 도구가 이를 인식합니다.
삭제는 정보를 없애지만 flag는 정보를 더합니다.

**read name 형식 확인**
BAM의 **첫 read 이름**을 읽어 Illumina 표준 형식
(`:`로 구분된 7개 이상 필드에 좌표 포함)인지 판정합니다.

| 판정 | 기록되는 지표 | 동작 |
|---|---|---|
| 표준 형식 | `read_name_mode = illumina_coordinates` | Picard 기본 정규식 사용 |
| 다른 형식 | `read_name_mode = no_coordinates` | `--READ_NAME_REGEX null`을 넘겨 optical duplicate 판정 비활성화 |
| 읽지 못함 | `read_name_mode = unknown` | warning `READ_NAME_MODE_UNKNOWN` 후 Picard 기본값 사용 |

> **optical duplicate가 뭔가요?**
> PCR 중복과 달리, 시퀀싱 기계의 광학 인식 오류로 **한 클러스터가 두 개로 잘못 읽힌**
> 경우입니다. read 이름 안의 x/y 좌표로 판정하므로,
> 이름 형식이 다르면 판정 자체가 불가능합니다.
> 억지로 판정하면 잘못된 경고가 대량으로 나옵니다.

**중간 검증**: `samtools quickcheck -v` 실패 시 `.part`를 삭제하고 step 실패.
**기록되는 지표**: `percent_duplication` (Picard metrics 파일에서 파싱).

### 13.2 ValidateSamFile과 NM/MD 보정

**왜 검증하나**
GATK는 BAM 형식에 엄격합니다. 문제가 있으면 BQSR이나 HaplotypeCaller 도중에
실패하는데, 그때는 이미 오랜 시간을 쓴 뒤입니다. **먼저 검사해서 미리 알아냅니다.**

```bash
gatk --java-options "-Xmx4g" ValidateSamFile \
    -I "$markdup_bam" -R "$REF_FASTA" -MODE SUMMARY -O "$validate_1"
```

`-MODE SUMMARY`는 오류를 종류별로 집계해 보여줍니다.
전체 목록(`VERBOSE`)은 수백만 줄이 될 수 있어 요약을 씁니다.

**분류 함수 `classify_validation()`**

리포트를 읽어 네 값 중 하나를 반환합니다.

| 반환값 | 조건 | 처리 |
|---|---|---|
| `CLEAN` | `No errors found`가 있거나, `ERROR:` 항목이 없음 | 그대로 BQSR로 진행 |
| `ONLY_NM` | `ERROR:` 종류가 **오직 `INVALID_TAG_NM`** | `samtools calmd`로 복구 시도 |
| `OTHER:<종류들>` | 그 밖의 `ERROR:` 종류가 있음 | **step 실패** |
| `UNPARSEABLE` | 파일이 없거나 비어 있거나, `ERROR:`/`WARNING:` 어느 것도 인식되지 않음 | **step 실패** |

> [!IMPORTANT]
> `UNPARSEABLE`이 실패인 이유는 중요합니다.
> ValidateSamFile이 어떤 이유로든 리포트를 만들지 못했을 때,
> 파이프라인은 **"문제 없다"고 가정하지 않고 멈춥니다.**
> 분류할 수 없는 결과에 대해 조용히 복구를 적용하는 것이 가장 위험한 선택이기 때문입니다.

**NM / MD가 뭔가요?**
BAM의 각 read에 붙는 태그입니다.

- **NM** = 이 read가 reference와 **몇 글자** 다른가
- **MD** = **어디가 어떻게** 다른가

정렬 도구와 reference 처리 방식 사이에 미세한 불일치가 있으면 이 값이 어긋날 수 있습니다.

**복구 명령**

```bash
samtools calmd -@ "$THREADS" -b "$markdup_bam" "$REF_FASTA" > "$markdup_nm_part"
```

`-b`는 BAM 출력, `-@`는 스레드입니다.
calmd는 reference를 다시 읽어 **NM/MD를 처음부터 다시 계산**합니다.
**read 서열, CIGAR, 좌표, duplicate flag는 그대로 보존**되고 두 태그만 바뀝니다.

**복구 후 반드시 재검증**
calmd 후 `ValidateSamFile`을 **다시 실행**해
`qc/<sample>.markdup.validation.after_calmd.txt`에 남기고 다시 분류합니다.
`CLEAN`이 아니면 **step 실패**입니다.
"고쳤다고 주장"하지 않고 **고쳐졌는지 확인**합니다.
성공하면 warning `NM_MD_REPAIRED`를 남겨, 보정이 있었다는 사실이 기록에 남습니다.

**왜 다른 오류는 자동 복구하지 않나**
NM/MD는 **원본 정보를 잃지 않고 reference로부터 다시 계산할 수 있는** 유일한 항목입니다.
다른 오류(잘린 BAM, 잘못된 mate 정보 등)를 자동으로 "고치면"
데이터를 조용히 바꾸게 됩니다.
**원인을 모르는 채 데이터를 고치는 것보다 멈추는 것이 안전합니다.**

**왜 무조건 calmd를 돌리지 않는가**
calmd는 BAM 전체를 읽고 다시 씁니다. WES에서도 상당한 시간과 디스크를 씁니다.
태그 불일치를 일으키지 않는 reference에서까지 BAM을 새로 쓸 이유가 없습니다.

**이 단계가 남은 배경**
원 작성자가 실제로 MarkDuplicates BAM에서 `ERROR:INVALID_TAG_NM`을 관찰했고,
`calmd` 이후 `ValidateSamFile`이 `No errors found`를 반환한 사례가 있었습니다.
원본 스크립트의 v5.1이 v5.0과 다른 점이 사실상 이 단계의 추가였다는 점이 이를 뒷받침합니다.
그래서 삭제하지 않고 **"관찰된 경우에만 동작하는 조건부 단계"** 로 바꿨습니다.

### 13.3 BQSR (Base Quality Score Recalibration)

**염기 품질 점수가 뭔가요**
FASTQ의 각 염기에는 "이 글자가 맞을 확률"을 나타내는 Phred 점수가 붙어 있습니다.
Phred 30이면 오류 확률 1/1000입니다.

**왜 재보정이 필요한가**
시퀀싱 기계가 매기는 이 점수는 **체계적으로 편향**되어 있습니다.
"read의 특정 위치에서, 특정 염기 조합 뒤에서는 실제 오류율이 더 높다" 같은
경향이 있는데 기계는 이를 반영하지 못합니다.

**어떻게 재보정하나**

1. reference와 다른 자리를 전부 모읍니다.
2. 그중 **known-sites(이미 알려진 변이)** 를 제외합니다.
3. 남은 것은 대부분 **시퀀싱 오류**라고 가정합니다.
4. 이 오류들의 패턴(위치·염기 문맥·원래 점수별)을 학습해 점수를 다시 매깁니다.

**known-sites가 왜 필수인가**
빼지 않으면 **진짜 변이를 오류로 학습**해서, 진짜 변이 자리의 품질 점수를 낮춰 버립니다.
결과적으로 진짜 변이를 놓칩니다.
그래서 known-sites가 비어 있으면 preflight에서 아예 시작하지 않습니다.

```
known_sites is empty; BQSR is a core step and requires known sites
```

**BaseRecalibrator — 모델 학습**

```bash
gatk --java-options "$java_opts" BaseRecalibrator \
    -R "$REF_FASTA" -I "$markdup_bam" \
    --known-sites <파일1> --known-sites <파일2> … \
    [-L "$TARGET_BED" -ip "$INTERVAL_PADDING"] \
    -O "$recal_part" --tmp-dir "$tmp_dir"
```

| Option | 실제 값 | 의미 | 선택 이유 |
|---|---|---|---|
| `--known-sites` | bundle의 `known_sites` 배열 전부 | 학습에서 제외할 알려진 변이 | dbSNP + Mills indel + 1000G indel 조합이 일반적. **배열이라 개수 제한이 없음** |
| `-L` / `-ip` | 조건부 | target 영역으로 학습 제한 | `bqsr_target_only=true`일 때만 추가 |
| `-O` | `.part` 경로 | recalibration table | 검증 후 최종 이름으로 |
| `--tmp-dir` | run 전용 tmp | 임시 파일 | 시스템 tmp 부족 방지 |

**검증**: 생성된 table에 `RecalTable0` 문자열이 없으면 `.part`를 지우고 실패합니다.
GATK가 빈 껍데기 파일을 남긴 경우를 잡습니다.

**`bqsr_target_only` 선택**

| 값 | 동작 | 장점 | 단점 |
|---|---|---|---|
| `false` (기본) | 유전체 전체로 학습 | 학습 데이터가 많아 모델이 안정적. GATK 표준 예제에 가까움 | off-target read까지 포함 |
| `true` | target BED + padding 안에서만 학습 | WES 실제 관심 영역에 집중 | 데이터가 적어 모델이 불안정할 수 있음 |

**ApplyBQSR — 모델 적용**

```bash
gatk --java-options "$java_opts" ApplyBQSR \
    -R "$REF_FASTA" -I "$markdup_bam" --bqsr-recal-file "$recal_table" \
    -O "$final_part" --create-output-bam-index false --tmp-dir "$tmp_dir"
```

> [!IMPORTANT]
> **ApplyBQSR에는 `-L`을 주지 않습니다.**
> 이건 실수가 아니라 의도이며, 원본 코드의 주석과 함께 보존한 결정입니다.
>
> `-L`을 주면 ApplyBQSR이 **해당 구간에 걸치는 read만 출력**합니다.
> 그러면 analysis-ready BAM이 원본 BAM의 부분집합이 되어,
> off-target read를 이용한 이후 진단이 불가능해집니다.
> 학습은 제한할 수 있어도(`bqsr_target_only`), **적용은 전체 BAM에 합니다.**

`--create-output-bam-index false`인 이유는 MarkDuplicates와 같습니다 —
인덱스는 `samtools index`로 별도 생성해 실패를 독립적으로 감지합니다.

**record count preservation 검사**
ApplyBQSR은 품질 점수만 바꿔야 하며 read 수를 바꾸면 안 됩니다.
`flagstat` 첫 줄의 총 레코드 수를 **전후 비교**해 다르면 실패시킵니다.

```
record count changed across ApplyBQSR: before=123456789 after=123456700
```

이 검사가 실패하면 결과를 쓰면 안 됩니다. 원인 조사가 필요합니다.

**BQSR 진단 플롯 (`bqsr_diagnostics=true`)**
보정 후 BAM으로 BaseRecalibrator를 한 번 더 돌리고 `AnalyzeCovariates`로
전후 비교 플롯을 만듭니다. `Rscript`가 필요합니다.
**분석 결과 자체는 바뀌지 않으므로** 실패해도 warning입니다
(`BQSR_DIAG_FAILED`, `RSCRIPT_MISSING`).

### 13.4 최종 공개 순서

analysis-ready BAM은 **모든 검사를 통과한 뒤에야** 최종 이름을 얻습니다.

```
1. ApplyBQSR → <sample>.analysis_ready.part.bam
2. samtools quickcheck
3. samtools index          ← .part 이름 상태에서 인덱스 생성
4. flagstat / stats
5. ValidateSamFile → CLEAN 이어야 함
6. record count 전후 일치 확인
7. SM:<sample> 확인
8. 실패가 하나도 없을 때만:
     mv <...>.part.bam.bai → <sample>.analysis_ready.bam.bai
     mv <...>.part.bam     → <sample>.analysis_ready.bam
```

8번에서 실패가 있으면 다음 경고와 함께 `.part` 상태로 격리됩니다.

```
Analysis-ready BAM was not published; failed output is quarantined at <경로>
```

**최종 이름을 가진 analysis-ready BAM이 존재한다면,
그것은 위 검사를 전부 통과했다는 뜻입니다.**

### 13.5 `run_processing()` 요약

| 항목 | 내용 |
|---|---|
| **입력** | `03_alignment/alignment_output.json` → sample BAM, reference FASTA, known-sites, (조건부) target BED |
| **출력** | `04_processing/<sample>.markdup.bam` (+ `.bam.bai`), `.markdup.metrics.txt`, `.recal_data.table`, `<sample>.analysis_ready.bam` (+ `.bam.bai`), `processing_output.json` |
| **QC 출력** | `04_processing/qc/` 아래 `.markdup.validation.txt`, `.markdup.validation.after_calmd.txt`, `.markdup.flagstat.txt`, `.markdup.stats.txt`, `.analysis_ready.validation.txt`, `.analysis_ready.flagstat.txt`, `.analysis_ready.stats.txt`, (선택) `.bqsr_covariates.csv` / `.pdf` |
| **성공 판정** | quickcheck 통과 + 인덱스 생성 + ValidateSamFile `CLEAN` + record count 보존 + `SM` 일치 |
| **주요 실패** | 하드오프 문서 없음, 입력 BAM 없음, known-sites 없음, GATK 도구 비정상 종료, calmd 실패, 분류 불가 리포트, 복구 후에도 오류, record count 불일치 |
| **warning** | `READ_NAME_MODE_UNKNOWN`, `NM_MD_REPAIRED`, `BQSR_DIAG_FAILED`, `RSCRIPT_MISSING` |
| **다음 단계 전달** | `ANALYSIS_READY_BAM` 변수와 `processing_output.json` |

**초보자가 헷갈릴 부분 세 가지**

1. **duplicate는 삭제되지 않습니다.** BAM 크기가 거의 줄지 않는 것이 정상입니다.
2. **BQSR은 read를 지우거나 옮기지 않습니다.** 품질 점수 숫자만 바꿉니다.
   그래서 record count가 같아야 하고, 다르면 실패로 처리합니다.
3. `.markdup.bam`과 `.analysis_ready.bam`이 **둘 다 남습니다.**
   중간 파일을 지우지 않는 이유는 문제가 생겼을 때
   **어느 단계에서 생겼는지 추적**하기 위함입니다.
   `markdup.bam`은 artifact로 등록되지만 `downloadable=false`로 표시됩니다.

---

## 14. Coverage QC

**위치: `script/main.sh > run_coverage_qc()` — step `05_coverage_qc`**

### 14.1 coverage가 뭔가요

유전체의 특정 위치를 **read가 몇 번 덮었는가**입니다.
depth 30이면 그 자리를 read 30개가 지나갔다는 뜻입니다.

**왜 중요한가**
depth가 낮으면 변이를 놓칩니다.
사람은 각 위치에 유전자가 2벌(부모에게서 하나씩) 있는데,
depth 4에서 한쪽에만 변이가 있으면 그 변이를 지지하는 read가 2개뿐일 수 있고,
그 정도로는 시퀀싱 오류와 구분되지 않습니다.

주요 용어:

| 용어 | 의미 |
|---|---|
| **mean depth (평균 depth)** | target 영역 전체의 평균 읽힌 깊이 |
| **median depth (중앙값 depth)** | 깊이를 줄 세웠을 때 가운데 값. **이 파이프라인은 보고하지 않습니다** (아래 참고) |
| **breadth (폭)** | target 중 일정 depth 이상 읽힌 **비율** |
| **10× / 20× / 30×** | "depth가 10 이상인 target 염기의 비율" 같은 breadth 지표 |
| **low mean-depth 구간** | 구간의 **평균** depth가 `low_coverage_depth`(기본 20) 미만인 구간 |
| **fully uncovered 구간** | 구간의 **평균** depth가 정확히 0인 구간 — 구간 전체가 안 읽힘 |
| **zero-coverage 염기** | 1× 에도 도달하지 못한 **개별 염기**. 구간 단위 값과 다릅니다 |
| **MAPQ** | mapping quality. "이 read가 여기에 붙은 게 맞을 확률" |

> [!IMPORTANT]
> **"구간 단위"와 "염기 단위"를 섞어 읽으면 안 됩니다.**
>
> mosdepth 출력 두 개가 서로 다른 질문에 답합니다.
>
> | 출력 | 담는 값 | 유도되는 지표 |
> |---|---|---|
> | `regions.bed.gz` | 구간마다 **평균 depth 하나** | `low_mean_depth_*`, `fully_uncovered_*` (구간 단위) |
> | `thresholds.bed.gz` | 구간마다 **각 depth 이상인 실제 염기 수** | `target_bases_ge_*X_pct`, `zero_coverage_*` (염기 단위) |
>
> **절반만 덮인 구간**은 평균이 0보다 크므로 `fully_uncovered` 에 포함되지
> 않지만, 그 안의 안 덮인 염기는 `zero_coverage_bases` 에 포함됩니다.
> 따라서 항상
>
> ```
> bases_in_fully_uncovered_intervals_pct  ≤  zero_coverage_bases_pct
> ```
>
> 이고, 둘은 서로를 대신할 수 없습니다.
> "target의 몇 %가 안 읽혔나"의 정직한 답은 **염기 단위 쪽**입니다.

> [!IMPORTANT]
> **coverage QC는 변이 호출을 막지 않습니다.**
> 이 단계의 역할은 **"어느 영역의 결과를 신뢰할 수 있는지"** 를 알려주는 것입니다.
> "이 유전자에서 변이가 안 나왔다"는 결과를 봤을 때,
> 진짜 없는 것인지 **읽히지 않아서 못 본 것인지** 구분하려면 이 정보가 필요합니다.
>
> 참고로 `06_variant_calling`은 `05_coverage_qc`의 출력이 아니라
> `04_processing`의 출력을 직접 읽습니다.
> coverage QC가 변이 호출의 입력 경로에 끼어 있지 않다는 뜻입니다.

### 14.2 `run_coverage_qc()`

**한 줄 역할**
analysis-ready BAM이 target 영역을 얼마나 잘 덮었는지 측정해 지표로 남깁니다.

**입력**
`04_processing/processing_output.json` → analysis-ready BAM, target BED, reference `.fai`

**입력 검증**

| 검사 | 실패 시 |
|---|---|
| 하드오프 문서 존재 | step 실패 |
| BAM 존재 + `samtools quickcheck` | step 실패 |
| target BED 존재 | step 실패. **fallback target은 없습니다** |
| target BED 구조(컬럼·정수 좌표) | step 실패 |
| **target BED의 모든 contig가 BAM 헤더에 존재** | step 실패 |

BED와 BAM의 contig가 어긋나면 coverage가 조용히 0으로 계산되므로,
경고가 아니라 **실패**로 처리합니다.

**target BED merge**
target BED에는 겹치는 구간이 있을 수 있습니다.
그대로 쓰면 **같은 영역을 두 번 세어** 통계가 왜곡됩니다.
그래서 겹침을 제거한 `05_coverage_qc/target.nonoverlap.bed`를 만들어 사용합니다.

> merge는 **`main.sh` 안의 Python heredoc이 직접** 수행합니다.
> `bedtools`를 사용하지 않으므로, 서버에 `bedtools`가 있든 없든 결과가 동일합니다.
> 정렬 순서는 reference `.fai`의 contig 순서를 따릅니다.

**실행 명령**

```bash
mosdepth --threads "$THREADS" --no-per-base --mapq "$MOSDEPTH_MAPQ" \
    --by "$merged_bed" --thresholds 1,10,20,30,50,100 \
    "$prefix" "$ANALYSIS_READY_BAM"
```

| Option | 실제 값 | 의미 | 선택 이유 | 변경 주의 |
|---|---|---|---|---|
| `--threads` | config `threads` | 병렬 처리 | — | — |
| `--no-per-base` | — | 위치별 depth 파일을 만들지 않음 | WES에서도 수 GB가 됩니다. 영역별 요약이면 충분 | **per-base median을 계산할 수 없게 됨** |
| `--mapq` | config `mosdepth_mapq` (기본 `20`) | 최소 mapping quality | 낮은 MAPQ read를 세면 **반복 서열 영역의 depth가 부풀려집니다** | 값을 낮추면 coverage가 좋아 보이지만 신뢰도는 떨어짐 |
| `--by` | merge된 target BED | 영역별 집계 | 겹침 중복 계산 방지 | — |
| `--thresholds` | `1,10,20,30,50,100` | 각 depth 이상 비율 계산 | 임상 WES에서 20×와 30×가 흔한 기준선 | 값을 바꾸면 지표 이름도 바뀜 |

**출력**

| 파일 | 내용 |
|---|---|
| `05_coverage_qc/target.nonoverlap.bed` | 겹침 제거된 target |
| `05_coverage_qc/target_bed_check.txt` | BED/BAM contig 대조 결과 |
| `05_coverage_qc/<sample>.mosdepth.regions.bed.gz` | **영역별 평균 depth** |
| `05_coverage_qc/<sample>.mosdepth.thresholds.bed.gz` | 영역별 threshold 도달 염기 수 |
| `05_coverage_qc/<sample>.mosdepth.mosdepth.summary.txt` | mosdepth 요약표 (mosdepth가 접두사 뒤에 `.mosdepth.summary.txt`를 붙이므로 이름에 `mosdepth`가 두 번 들어갑니다) |
| `05_coverage_qc/coverage_metrics.json` | 파싱된 핵심 지표 |
| `05_coverage_qc/low_mean_depth_intervals.bed` | **평균** depth가 기준 미만인 구간 목록 (4번째 컬럼이 그 구간의 평균 depth). **0× 위치 목록이 아닙니다** |

**계산되는 지표**

| 지표 | 단위 | 의미 |
|---|---|---|
| `target_nonoverlap_bases` | — | 겹침 제거 후 target 총 염기 수 |
| `mean_target_depth` | — | 길이 가중 평균 depth |
| `target_bases_ge_1X_pct` … `ge_100X_pct` | **염기** | 각 depth 이상인 target 염기 비율(%) |
| `zero_coverage_bases` | **염기** | 1×에 도달하지 못한 염기 수 |
| `zero_coverage_bases_pct` | **염기** | 같은 값의 비율. `100 - target_bases_ge_1X_pct` 와 일치 |
| `low_mean_depth_intervals` | **구간** | 평균 depth가 `low_coverage_depth` 미만인 구간 수 |
| `bases_in_low_mean_depth_intervals` / `_pct` | **구간** | 그 구간들이 차지하는 target 길이 |
| `fully_uncovered_intervals` | **구간** | 평균 depth가 정확히 0인 구간 수 |
| `bases_in_fully_uncovered_intervals` / `_pct` | **구간** | 그 구간들이 차지하는 target 길이 |
| `low_mean_depth_threshold_x` | — | 사용한 기준값 |
| `median_target_depth` | — | **항상 `null`** |
| `median_note` | — | median을 계산하지 않은 이유 설명 |

`zero_coverage_*` 는 `thresholds.bed.gz` 의 1X 집계와 **같은 분모**로 계산합니다.
반올림된 비율을 다시 빼서 개수를 만들지 않습니다. mosdepth `--thresholds` 에
`1` 이 없으면 두 필드는 아예 기록하지 않습니다 — 없는 값을 추정하지 않습니다.

> [!NOTE]
> **legacy 필드 — 2026-09-07 이전 run의 `coverage_metrics.json`**
>
> 과거 run에는 아래 이름이 들어 있습니다. **값이 잘못된 것이 아니라 이름이
> 실제 측정 대상을 잘못 시사했습니다.** 모두 구간 단위였습니다.
>
> | 옛 이름 | 지금 이름 | 실제로 측정한 것 |
> |---|---|---|
> | `low_coverage_intervals` | `low_mean_depth_intervals` | 평균 depth 기준 미만 구간 수 |
> | `low_coverage_bases` | `bases_in_low_mean_depth_intervals` | 그 구간들의 총 길이 |
> | `low_coverage_bases_pct` | `bases_in_low_mean_depth_intervals_pct` | 그 비율 |
> | `uncovered_intervals` | `fully_uncovered_intervals` | 평균 depth 0인 구간 수 |
> | `uncovered_bases` | `bases_in_fully_uncovered_intervals` | 그 구간들의 총 길이 |
> | `uncovered_bases_pct` | `bases_in_fully_uncovered_intervals_pct` | 그 비율 |
> | `low_coverage_threshold_x` | `low_mean_depth_threshold_x` | 사용한 기준값 |
>
> **`uncovered_bases_pct` 를 "0× 염기의 비율"로 다시 해석하면 안 됩니다.**
> 그 값은 구간 단위이므로 실제 0× 염기 비율보다 작습니다. 옛 run에서 염기 단위
> 값이 필요하면 `target_bases_ge_1X_pct` 로부터 `100 - x` 로 **비율만** 복원할 수
> 있고, 개수는 복원할 수 없습니다(backend `result_reader._coverage` 가 그렇게
> 처리합니다).

> [!NOTE]
> **median을 보고하지 않는 이유.**
> mosdepth를 `--no-per-base`로 실행하므로 **위치별 depth가 애초에 만들어지지 않습니다.**
> 이 상태에서 median을 적으면 그건 계산이 아니라 지어낸 값입니다.
> 그래서 필드를 조용히 빼지 않고, `null`과 함께 이유를 명시적으로 남깁니다.

**성공 판정**
mosdepth가 정상 종료하고 `regions.bed.gz`와 `thresholds.bed.gz`가 존재하며,
그로부터 지표를 산출할 수 있어야 합니다.

**실패 처리와 warning 구분 — 여기가 핵심입니다**

| 상황 | 처리 | 이유 |
|---|---|---|
| BAM이 quickcheck 실패 | **step 실패** | 입력이 신뢰 불가 |
| target BED 구조 오류 또는 contig 불일치 | **step 실패** | 결과가 조용히 틀어짐 |
| mosdepth 비정상 종료 / 출력 누락 | **step 실패** | 지표를 만들지 못함 |
| 지표 산출 실패 | **step 실패** | 동일 |
| 평균 depth가 `coverage_min_mean_depth` 미만 | **warning** (`LOW_MEAN_COVERAGE`) | QC 관찰이지 오류가 아님 |
| `zero_coverage_bases_pct` > 0 | **warning** (`ZERO_COVERAGE_TARGET_BASES`) | 동일 |

> [!NOTE]
> **`UNCOVERED_TARGETS` → `ZERO_COVERAGE_TARGET_BASES` (2026-09-07)**
>
> 옛 warning은 **구간 단위** 값(`uncovered_bases_pct`)으로 판단하면서 메시지는
> `"X% of non-overlapping target bases have zero coverage"` 라고 **염기**를
> 말했습니다. 두 값이 다르므로 메시지가 실제보다 작은 수를 보고했습니다.
>
> 새 code는 염기 단위 `zero_coverage_bases_pct` 로 판단하고
> `"X% of non-overlapping target bases are at 0X coverage"` 라고 말합니다.
> 옛 run에 저장된 `UNCOVERED_TARGETS` 는 그대로 남으며 frontend registry가
> 계속 해석합니다 — 단, **그 run이 실제로 측정한 구간 단위 의미로** 설명합니다.

**왜 낮은 coverage로 실패시키지 않나**
"depth 30 미만이면 실패"는 **분석적 판단이 아니라 정책적 판단**입니다.
어떤 연구는 depth 20으로 충분하고, 어떤 임상 검사는 100을 요구합니다.
파이프라인이 임의 기준으로 데이터를 버리는 대신,
**숫자를 정확히 보고하고 판단은 사람에게** 맡깁니다.
`coverage_min_mean_depth` 기본값이 `0`(비활성화)인 이유도 같습니다.

> **80× 같은 값이 절대 기준이 아닌 이유.**
> 직전 리비전의 한 구현에는 평균 depth가 80× 미만이면 `exit 2`로 파이프라인을
> 중단시키는 코드가 있었습니다. 이 값은 근거가 기록되어 있지 않았고,
> **QC 관찰을 파이프라인 실패로 바꾸는** 결정이었습니다.
> 그 `exit`는 제거했고, 지금은 설정 가능한 참고값과 warning으로 대체되었습니다.
> WES의 적정 depth는 목적(연구/스크리닝/임상), capture kit, 관심 유전자에 따라
> 달라지므로 코드에 하나의 숫자를 박아 둘 수 없습니다.

**다음 단계 전달**
변이 호출로 넘기는 값은 없습니다.
`coverage_metrics.json`은 finalization의 최종 요약과 artifact 목록에 포함됩니다.

**초보자가 헷갈릴 부분**
평균 depth가 좋아도 **특정 유전자만 나쁠 수 있습니다.** 평균은 평균일 뿐입니다.
관심 유전자가 있다면 `regions.bed.gz`에서 그 영역을 직접 확인해야 합니다.

> **breast-cancer BED fallback을 제거한 이유**
> 직전 리비전의 다른 coverage 구현에는, target BED가 없으면
> BRCA1·BRCA2·PALB2·ATM·CHEK2·TP53·PTEN·CDH1 8개 유전자 구간으로 BED를 만들어
> **그것을 WES target으로 사용하는** 코드가 있었습니다.
> 수십 Mb짜리 전장 엑솜 target을 약 0.4 Mb의 유전자 구간으로 조용히 바꿔치기한 뒤
> 그 결과를 "엑솜 coverage"로 보고하게 됩니다.
> 알림은 stderr 한 줄뿐이었습니다. 이 fallback은 제거했고,
> 이제 target BED는 **fallback 없는 필수 resource**입니다.

---

## 15. Variant Calling

**위치: `script/main.sh > run_variant_calling()` — step `06_variant_calling`**

### 15.1 변이 호출이 무엇을 하는가

analysis-ready BAM에는 "각 위치를 어떤 read들이 어떻게 읽었는가"가 들어 있습니다.
변이 호출은 그 증거를 보고 **"이 사람의 유전형(genotype)이 무엇인가"** 를 판정합니다.

어떤 위치에서:

- read 30개가 전부 `A` → 양쪽 다 `A` (**homozygous reference**)
- read 15개 `A`, 15개 `G` → 한쪽은 `A`, 한쪽은 `G` (**heterozygous 변이**)
- read 30개가 전부 `G` → 양쪽 다 `G` (**homozygous 변이**)

실제로는 단순 개수 세기가 아니라 오류 확률을 반영한 통계 모델로 판정합니다.

### 15.2 데이터 흐름

```
analysis-ready BAM
   → HaplotypeCaller (-ERC GVCF)
   → gVCF
   → GenotypeGVCFs
   → raw VCF     ← 핵심 완료 지점
```

### 15.3 HaplotypeCaller → gVCF

```bash
gatk --java-options "$java_opts" HaplotypeCaller \
    -R "$REF_FASTA" -I "$ANALYSIS_READY_BAM" -ERC GVCF \
    -L "$TARGET_BED" -ip "$INTERVAL_PADDING" \
    --native-pair-hmm-threads "$PAIRHMM_THREADS" \
    -O "$gvcf_part" --tmp-dir "$tmp_dir"
```

| Option | 실제 값 | 의미 | 선택 이유 | 변경 주의 |
|---|---|---|---|---|
| `-R` | reference FASTA | 비교 기준 | — | — |
| `-I` | analysis-ready BAM | 입력 | `04_processing`의 하드오프 문서에서 읽음 | — |
| `-ERC GVCF` | — | **gVCF 모드** | 변이 자리뿐 아니라 "여기는 변이 없음"의 근거도 기록. 나중에 joint calling 가능 | 파일이 훨씬 커짐 |
| `-L` | target BED | 이 영역만 호출 | WES는 target 밖이 거의 읽히지 않음. 전체를 돌리면 시간만 낭비 | **BED가 틀리면 결과가 통째로 틀림** |
| `-ip` | config `interval_padding` (기본 `100`) | target 경계를 앞뒤로 확장 | 경계에 걸친 read와 indel 문맥을 놓치지 않기 위함 | 너무 크면 off-target 노이즈 증가 |
| `--native-pair-hmm-threads` | config `pairhmm_threads` (기본 `4`) | PairHMM 병렬 스레드 | PairHMM은 HaplotypeCaller에서 가장 무거운 연산 | 과하게 늘려도 이득이 적음 |
| `--tmp-dir` | run 전용 tmp | 임시 파일 | 시스템 tmp 부족 방지 | — |

> **HaplotypeCaller는 어떻게 동작하나요?** (개요)
> 각 위치를 따로 보지 않습니다. 변이가 의심되는 구역을 **active region**으로 잡고,
> 그 구역의 read를 전부 모아 **가능한 서열(haplotype)을 다시 조립(local assembly)** 한 뒤,
> 어떤 조합이 read들을 가장 잘 설명하는지 계산합니다.
> 그래서 indel 근처처럼 정렬이 헷갈리는 곳에서도 정확도가 높습니다.

**germline 전용입니다.** somatic(체세포 변이) 호출은 `Mutect2` 등 다른 도구를 쓰며,
이 파이프라인의 범위 밖입니다.

**gVCF와 VCF의 차이**

| | gVCF | VCF |
|---|---|---|
| 담는 것 | 변이 자리 + **"여기는 reference와 같다"는 구간(reference block)** | 변이 자리만 |
| 크기 | 훨씬 큼 | 작음 |
| 용도 | 나중에 여러 sample을 합칠 때의 **증거** | 이 sample의 **판정 결과** |
| "이 자리에 변이 없음" | **근거와 함께 기록됨** | 기록되지 않음 (없는 것과 못 본 것을 구분 못 함) |

**gVCF 인덱싱과 공개**
GATK가 `.tbi`를 만들지 않았으면 `tabix -p vcf`로 만듭니다.
그다음 `bcftools view -h`로 파싱되는지 확인하고,
**인덱스와 본체를 함께** 최종 이름으로 바꿉니다.

### 15.4 GenotypeGVCFs → raw VCF

```bash
gatk --java-options "$java_opts" GenotypeGVCFs \
    -R "$REF_FASTA" -V "$GVCF" \
    [--dbsnp "$DBSNP_VCF"] \
    -L "$TARGET_BED" -ip "$INTERVAL_PADDING" \
    -O "$raw_part" --tmp-dir "$tmp_dir"
```

| Option | 실제 값 | 의미 | 선택 이유 |
|---|---|---|---|
| `-V` | gVCF | 입력 | — |
| `--dbsnp` | 조건부 | 변이에 rsID를 붙임 | bundle이 `dbsnp_vcf`를 선언했고 실제로 읽을 수 있을 때만 추가 |
| `-L` / `-ip` | HaplotypeCaller와 **같은 값** | 호출 영역 | 두 단계의 영역이 달라지면 결과가 어긋남 |

**dbSNP를 bundle에 있을 때만 쓰는 이유**
`--dbsnp`는 **rsID를 붙이는 용도**일 뿐 변이 판정 자체를 바꾸지 않습니다.
직전 리비전은 known-sites 세 개 중 하나를 dbSNP로 **고정 지정**했는데,
어느 known-sites가 dbSNP인지는 bundle마다 다르므로 이는 가정입니다.
그래서 지금은 **명시적으로 선언된 경우에만** 사용하고,
없으면 warning 후 rsID 없이 진행합니다.

| 상황 | 처리 |
|---|---|
| `dbsnp_vcf` 선언 + 구조 검사 통과 | `--dbsnp` 추가 |
| **`dbsnp_vcf` 선언했지만 구조 검사 실패** | **`00_input_validation`에서 preflight 실패 — core 실행 전에 중단** |
| `dbsnp_vcf` 미선언 | warning `DBSNP_NOT_CONFIGURED`, rsID 없이 진행 |

> [!IMPORTANT]
> **dbSNP는 "선언하지 않을 자유"는 있어도 "잘못 선언할 자유"는 없습니다.**
>
> 선언하지 않으면 rsID만 안 붙고 변이 자체는 그대로이므로 warning 후 진행합니다.
> 하지만 일단 선언하면 그 파일은 **core 단계인 GenotypeGVCFs에 전달**되므로,
> `00_input_validation`에서 known-sites와 **똑같은 구조 검사**를 받습니다.
>
> | 검사 항목 |
> |---|
> | 파일 존재 및 non-empty |
> | `.tbi` 또는 `.csi` index 존재 |
> | `bcftools view -h`로 header 파싱 가능 |
> | tabix contig 목록이 reference contig의 부분집합 |
> | header에 contig 길이가 있으면 reference `.fai`와 일치 |
>
> 하나라도 실패하면 core가 시작되기 전에 멈춥니다.
> run이 몇 시간 진행된 뒤 rsID 단계에서 문제를 발견하는 것보다 낫기 때문입니다.
>
> `run_variant_calling()`의 `DBSNP_MISSING` warning은 그대로 남아 있지만,
> 이제는 preflight 이후 파일이 사라진 경우에만 도달하는 **2차 안전망**입니다.
>
> 이 검사도 **구조적 호환성만** 확인합니다. 같은 release에서 왔다는 보장은
> `resource_bundle` 계약이 담당합니다 ([4.4](#44-build가-안-맞으면-왜-위험한가) 참고).

**왜 single sample인데 두 단계로 나누나**
gVCF는 "증거", raw VCF는 "판정"입니다.
지금은 sample이 1개라 한 번에 해도 되지만, 나중에 여러 sample을 함께 분석하려면
각 sample의 gVCF가 필요합니다.
**나중에 구조를 갈아엎지 않으려고 지금부터 나눠 둡니다.**
cohort로 확장할 때는 `GenomicsDBImport` + cohort `GenotypeGVCFs`를
**추가**하면 되고, 앞 단계는 그대로 둡니다.

### 15.5 raw VCF가 core endpoint인 이유

이 파이프라인의 **핵심 완료 지점은 raw VCF**이며, 여기에는 **어떤 필터링도 적용하지 않습니다.**

이유:

- 필터 기준은 목적에 따라 달라집니다. 파이프라인이 미리 걸러 버리면
  **되돌릴 수 없습니다.**
- 검증되지 않은 임계값으로 변이를 버리는 것이 가장 위험한 형태의
  "조용히 틀린 답"입니다.
- raw VCF를 그대로 두면, 나중에 어떤 기준이 정해지든 **다시 필터링할 수 있습니다.**

`raw`는 **"아직 필터링하지 않았다"** 는 뜻이지 "품질이 나쁘다"는 뜻이 아닙니다.
GATK가 이미 상당한 통계적 판단을 거쳐 만든 결과입니다.

### 15.6 raw VCF 검증

파이프라인은 raw VCF를 만든 뒤 **실제로 검사**합니다.

| 검사 | 방법 | 실패 시 |
|---|---|---|
| gVCF·raw VCF 헤더 파싱 | `bcftools view -h` | **step 실패** |
| 인덱스 읽기 가능 | `tabix -l` | **step 실패** |
| sample 컬럼이 정확히 1개이고 `SM`과 같음 | `bcftools query -l` | **step 실패** |
| 변이 레코드 수 > 0 | `bcftools view -H \| wc -l` | **step 실패** |
| REF allele이 reference와 일치 | `bcftools norm -f "$REF_FASTA" -c e -Ou -o /dev/null` | **step 실패** |
| 변이 요약 통계 | `bcftools stats` | warning (`BCFTOOLS_STATS_FAILED`) |

> `bcftools norm -c e`의 `-c e`는 "REF가 reference와 다르면 error"를 뜻합니다.
> 출력은 `/dev/null`로 버리고 **검사 목적으로만** 실행합니다.
> 여기서 불일치가 나오면 **build mismatch의 강력한 신호**이며,
> 그런 결과는 쓰면 안 되므로 warning이 아니라 실패로 처리합니다.

`bcftools stats`에서 다음 지표를 뽑아 기록합니다:
`raw_records`, `raw_snps`, `raw_indels`, `raw_multiallelic_sites`, `raw_ts_tv`.

**출력**

| 파일 | 설명 |
|---|---|
| `06_variant_calling/<sample>.g.vcf.gz` (+ `.tbi`) | gVCF |
| `06_variant_calling/<sample>.raw.vcf.gz` (+ `.tbi`) | **핵심 산출물** |
| `06_variant_calling/<sample>.raw.bcftools.stats.txt` | 변이 요약 통계 |
| `06_variant_calling/variant_calling_output.json` | 다음 단계가 읽는 계약 문서 |

**다음 단계 전달**
`GVCF`, `RAW_VCF` 변수와 `variant_calling_output.json`
(`sample`, `assembly`, `gvcf`, `raw_vcf`, 상대 경로, `raw_variant_records`,
`filtering_applied: false`, `next_step_ready`).

**초보자가 헷갈릴 부분**
`05_coverage_qc`에서 낮은 coverage warning이 나와도 변이 호출은 그대로 진행됩니다.
반면 analysis-ready BAM이 `quickcheck`에 실패하면 이 단계는 **즉시 중단**합니다.
"관찰 결과가 나쁜 것"과 "입력을 신뢰할 수 없는 것"은 다르게 취급합니다.

---

## 16. Optional filtering

**위치: `script/main.sh > run_filtering()` — step `08_filtering` (기본 비활성화)**

### 16.1 기본 비활성화이며 raw VCF를 건드리지 않는다

- `optional_steps.filtering`이 `true`일 때만 실행 계획에 들어갑니다.
- 결과는 `optional/filtering/` 아래에만 씁니다.
- **raw VCF를 수정하거나 덮어쓰지 않습니다.** 새 파일을 만들 뿐입니다.
- 실패해도 run 전체는 실패하지 않습니다 ([23장](#23-core와-optional-상태-정책)).

### 16.2 세 가지 다른 "필터링"을 구분해야 합니다

혼동이 매우 잦은 지점이라 명확히 구분합니다.

| 종류 | 무엇을 보는가 | 이 파이프라인에서의 상태 |
|---|---|---|
| **genotype 품질 필터링** | `FORMAT`의 `DP`, `GQ`, `AD` — 개별 genotype이 얼마나 잘 지지되는가 | **구현됨. optional, 기본 꺼짐** |
| **GATK site-level hard filtering** | `INFO`의 `QD`, `FS`, `MQ`, `SOR` 등 — 그 자리 자체의 품질 | **구현되지 않음** |
| **MAF (population frequency) 필터링** | 인구집단 데이터베이스의 대립유전자 빈도 | **구현되지 않았고, 이전에도 구현된 적 없음** |

`run_filtering()`이 하는 것은 **첫 번째**뿐입니다.

### 16.3 preset과 임계값

| Preset | `min_dp` | `min_gq` | `min_alt_depth` | 성격 |
|---|---|---|---|---|
| `balanced` (기본) | 5 | 10 | 3 | 민감도와 특이도의 균형 |
| `strict` | 10 | 20 | 3 | 확실한 것만 |
| `pass-only` | — | — | — | `FILTER`만 보고 threshold 없음 |

preset을 고른 뒤 `filtering.min_dp` 등으로 **개별 값을 덮어쓸 수 있습니다.**
preset 이름이 셋 중 하나가 아니면 step이 실패합니다.

**만들어지는 표현식**

```
(FILTER="PASS" || FILTER=".") && FMT/DP>=5 && FMT/GQ>=10 && FMT/AD[0:1]>=3
```

| 조건 | 의미 |
|---|---|
| `FILTER="PASS" \|\| FILTER="."` | GATK가 문제 없다고 했거나, 판정 자체를 하지 않은 것 |
| `FMT/DP>=N` | 이 위치를 최소 N개 read가 덮었을 것 |
| `FMT/GQ>=N` | genotype 판정 신뢰도가 최소 N일 것 |
| `FMT/AD[0:1]>=N` | 변이(ALT)를 지지하는 read가 최소 N개일 것 |

`pass-only`는 세 threshold를 모두 비워 `(FILTER="PASS" || FILTER=".")`만 남깁니다.

### 16.4 실행

```bash
bcftools view -i "$expr" "$RAW_VCF" -Oz -o "$filtered_part"
bcftools index -f -t "$filtered"
```

> 표현식은 **argv 요소 하나로 전달**되며 셸이 다시 해석하지 않습니다.
> config 값이 셸 명령으로 실행되는 사고를 구조적으로 막습니다.

**출력**

| 파일 | 설명 |
|---|---|
| `optional/filtering/<sample>.filtered.vcf.gz` | 필터링 결과 |
| `optional/filtering/<sample>.filtered.vcf.gz.tbi` | 인덱스 |

**기록되는 지표**: `filter_preset`, `filter_expression`,
`records_before_filter`, `records_after_filter`.

**실패 조건**: 하드오프 문서 없음, raw VCF 없음, 잘못된 preset,
`bcftools` 비정상 종료, 빈 출력.

**warning**: 통과한 변이가 0개면 `NO_VARIANTS_PASSED`.
이건 **오류가 아니라 필터링 결과**이며, 원본 raw VCF는 그대로 남아 있습니다.

### 16.5 임계값이 검증되지 않았다는 사실

> [!WARNING]
> `balanced`(DP≥5, GQ≥10, AD≥3)와 `strict`(DP≥10, GQ≥20, AD≥3)는
> **원 작성자의 값을 그대로 보존**한 것입니다.
> 현재 코드에서 값은 확인되지만, 이 값을 선택한 근거는 기존 자료에서
> 명확히 확인되지 않았고, **이 프로젝트의 truth set으로 평가된 적이 없습니다.**
>
> 이것이 이 단계를 기본 비활성화로 둔 이유입니다.
>
> **기본 활성화로 바꾸는 조건**: 이 assay와 이 resource bundle에 대해
> 임계값을 benchmark로 평가하고, 선택한 값을 팀 결정으로 기록한 뒤에만.

### 16.6 MAF 필터링을 넣지 않은 이유

인구집단 빈도(MAF) 필터링은 **직전 리비전에도 구현되어 있지 않았습니다.**
제안 자료에만 등장했습니다.

"MAF 1% 이상은 제거" 같은 단일 기준을 모든 WES에 강제하지 않는 이유:

- 적정 임계값은 **질환, 유전 방식(우성/열성), 대상 집단**에 따라 달라집니다
- 어떤 데이터베이스의 어떤 릴리스, 어떤 population 필드를 쓸지가 결정되어야 합니다
- genome build와 allele 표기법이 callset과 맞아야 합니다
- **제거할 것인지 순위만 낮출 것인지**가 별개의 결정입니다

이 결정들이 내려지기 전에 코드에 숫자를 박아 넣으면,
근거 없는 기준으로 변이를 조용히 버리게 됩니다.

### 16.7 현재 한계 — optional artifact 검증이 약함

> [!NOTE]
> resume 시 optional step의 artifact 검증은
> **`status/steps/08_filtering.json`에 기록된 출력 파일이 존재하고
> 비어 있지 않은지 확인하는 수준**입니다.
>
> core step처럼 VCF를 파싱하거나 인덱스를 읽어 보거나 sample 컬럼을
> 대조하지 않습니다 (`validate_step_artifacts`의 `08_filtering|10_annotation|11_intervar`
> 분기가 추가 검사를 하지 않음).
>
> 근거는 "optional 결과는 다시 만들기 싸고, core 결과의 전제 조건이 아니다"입니다.
> 다만 **잘린 filtered VCF가 재사용될 수 있다**는 뜻이므로,
> optional 결과를 중요하게 쓸 계획이라면 새 `run_id`로 다시 만드는 편이 확실합니다.

---

## 17. Optional annotation

**위치: `script/main.sh > run_annotation()` — step `10_annotation` (기본 비활성화)**

### 17.1 variant calling과 annotation의 차이

| | variant calling | annotation |
|---|---|---|
| 답하는 질문 | "표준과 **어디가** 다른가?" | "그 차이가 **무슨 의미**인가?" |
| 근거 | 이 sample의 read | 외부 데이터베이스와 예측 모델 |
| 결과 | 좌표·REF·ALT·genotype | 유전자 이름, 임상 보고 이력, 기능 예측 |
| 실패해도 | core 산출물이 없음 | **raw VCF는 그대로 유효** |

### 17.2 입력 선택

filtering이 켜져 있고 filtered VCF가 실제로 있으면 그것을,
아니면 raw VCF를 입력으로 씁니다.
어느 쪽을 썼는지 `annotation_input` 지표(`filtered` / `raw`)에 기록합니다.

### 17.3 처리 순서

**① 정규화 (항상 수행)**

```bash
bcftools norm -m -any [-f "$REF_FASTA"] "$input_vcf" -Oz -o "$norm_part"
bcftools index -f -t "$normalized"
```

- `-m -any` — 한 줄에 여러 ALT가 있으면 **각각 별도 줄로 분리**
- `-f` — reference 기준으로 indel 표기를 왼쪽 정렬(left-align).
  reference FASTA가 있을 때만 추가

**왜 먼저 해야 하나**: 같은 변이가 표기 방식에 따라 다르게 적힐 수 있습니다.
정규화하지 않으면 데이터베이스와 대조할 때 **같은 변이를 못 찾습니다.**

> core raw VCF는 일부러 정규화하지 않고 둡니다.
> `GenotypeGVCFs`가 만든 그대로를 유지하기 위함입니다.
> 정규화는 이 optional 단계 안에서만 일어납니다.

**② 로컬 ClinVar 주석 (`clinvar_vcf`가 있을 때)**

```bash
bcftools annotate -a "$CLINVAR_VCF" \
    -c 'ID,INFO/CLNSIG,INFO/CLNDN,INFO/CLNREVSTAT,INFO/CLNHGVS,INFO/GENEINFO' \
    "$normalized" -Oz -o "$clinvar_part"
```

| 필드 | 의미 |
|---|---|
| `CLNSIG` | 임상적 의미 (Pathogenic / Benign / VUS 등) |
| `CLNDN` | 관련 질환명 |
| `CLNREVSTAT` | 그 판정의 **근거 수준** (몇 개 기관이 제출했는가 등) |
| `CLNHGVS` | HGVS 표준 표기 |
| `GENEINFO` | 유전자 정보 |

매칭은 **CHROM+POS+REF+ALT 정확 일치**입니다.

> [!WARNING]
> **build가 다르면 엉뚱한 변이에 임상 해석이 붙습니다.**
> 에러 없이 조용히 일어나므로 가장 위험합니다.
>
> 그래서 주석을 붙이기 **전에** ClinVar VCF를 reference와 대조합니다
> (`check_vcf_against_reference()`).
>
> | 검사 항목 | 실패 예 |
> |---|---|
> | 파일 존재 및 non-empty | 경로 오타 |
> | `.tbi`/`.csi` index 존재 | 인덱스를 만들지 않음 |
> | header 파싱 가능 | 손상된 파일 |
> | header의 contig 길이가 reference `.fai`와 일치 | **다른 build의 ClinVar** |
> | tabix contig가 reference의 부분집합 | reference에 없는 contig 포함 |
> | contig 명명 규칙이 reference와 동일 | `chr1` vs `1` |
>
> 하나라도 어긋나면 주석을 **건너뛰고** warning `CLINVAR_INCOMPATIBLE`을 남깁니다.
> 틀린 결과를 만드는 것보다 만들지 않는 편이 안전하기 때문입니다.
>
> **core 정책은 그대로입니다.** ClinVar가 호환되지 않아도
> raw VCF와 normalized VCF는 그대로 유효하며, run 전체가 실패하지 않습니다.

> [!IMPORTANT]
> **contig 명명 규칙 비교만으로는 build 검증이 되지 않습니다.**
>
> 위 검사는 **구조적 호환성**을 확인할 뿐입니다.
> 같은 GRCh38이라도 ClinVar release가 다르면 주요 염색체 이름과 길이는
> 똑같으면서 내용은 다를 수 있고, 이 검사는 그것을 잡아내지 못합니다.
>
> ClinVar가 선언한 assembly의 것이라는 보장은 **`resource_bundle` 계약**에서 나옵니다 —
> bundle 안의 모든 resource는 `resource_bundle.assembly`의 것이어야 합니다.
> **정확한 release와 출처는 run config 또는 bundle provenance에 사람이 기록해야 합니다.**
>
> 이 때문에 resource마다 별도의 assembly key를 추가하지 않았습니다.
> key를 늘려도 값의 진위는 여전히 사람이 보증해야 하므로,
> **계약을 문서로 명확히 하는 쪽**을 택했습니다.

**③ VEP — 현재 상태를 정확히**

| 상황 | 실제 동작 |
|---|---|
| `vep_cache` 미설정 | 아무것도 하지 않음 |
| `vep_cache` 설정 + `vep` 미설치 | warning `VEP_MISSING` |
| `vep_cache` 설정 + `vep` 설치됨 | warning `VEP_NOT_WIRED` — **실제 VEP 호출은 구현되어 있지 않습니다** |

> [!IMPORTANT]
> **현재 offline VEP 주석은 배선되어 있지 않습니다.**
> 캐시와 실행 파일이 둘 다 있어도 VEP는 실행되지 않고,
> "구현되지 않았다"고 명시하는 warning만 남깁니다.
>
> 없는 기능을 있는 척하지 않기 위한 선택입니다.
> 실제 구현에는 캐시 버전, 종(species), transcript set을 정하는 결정이 필요합니다.

**④ 변이 TSV**

```bash
bcftools query --allow-undef-tags \
    -f '%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%QUAL\t%INFO/GENEINFO\t%INFO/CLNSIG\t%INFO/CLNDN\t%INFO/CLNREVSTAT[\t%GT\t%AD\t%DP\t%GQ]\n' \
    "$annotated"
```

`--allow-undef-tags`는 ClinVar 주석이 붙지 않은 경우에도
빈 값으로 출력되게 합니다. 실패하면 warning `TSV_FAILED`.

### 17.4 로컬·오프라인을 우선하는 이유

직전 리비전에는 Ensembl VEP **REST API**와 PanelApp **REST API**를
분석 도중 호출하는 코드가 있었습니다. 이 경로들은 가져오지 않았습니다.

| 이유 | 설명 |
|---|---|
| **재현성** | 원격 서비스는 같은 입력에 대해 날짜가 다르면 다른 결과를 줄 수 있습니다. 파이프라인이 기록하는 provenance와 근본적으로 충돌합니다 |
| **데이터 전송** | 변이 데이터를 제3자 서비스로 보내게 됩니다 |
| **애초에 동작 불가** | 원본 코드는 `--max-rest-variants 2000`을 넘으면 중단했습니다. 전장 엑솜은 그 수를 훨씬 넘습니다 |
| **입력 검증 부재** | PanelApp 코드는 `PANEL_ID`를 형식 검증 없이 URL에 그대로 넣었습니다 |

그래서 기본 동작은 **로컬 리소스만 사용**하며, REST 호출은 하지 않습니다.

### 17.5 일반 WES 기능과 질환 특화 기능의 구분

| 기능 | 성격 | 현재 상태 |
|---|---|---|
| 정규화 | 일반 WES | **구현됨** |
| 로컬 ClinVar 주석 | 일반 WES | **구현됨** |
| 변이 TSV 추출 | 일반 WES | **구현됨** |
| offline VEP | 일반 WES | **미배선** (경고만) |
| VEP REST | 일반 WES지만 원격 | **미이관** |
| **PanelApp** | 질환 특화 (원본은 유전성 유방·난소암 패널 635번) | **미이관** |
| **BRCA Exchange** | 질환 특화 | **코드에 존재한 적 없음** |
| **REVEL** | 예측 점수 | **코드에 존재한 적 없음** |
| **SpliceAI** | 예측 점수 | **코드에 존재한 적 없음** |

BRCA Exchange, REVEL, SpliceAI는 제안 자료에만 있었고 구현된 적이 없습니다.
**흉내 낸 구현도 만들지 않았습니다.**
질환 특화 패널과 예측 점수는 일반 germline WES 파이프라인의 기본 단계가 아니며,
도입하려면 리소스 릴리스 고정, transcript set 결정,
그리고 예측 점수를 **판정이 아니라 보조 근거로** 제시하는 표기 원칙이 필요합니다.

### 17.6 요약

| 항목 | 내용 |
|---|---|
| **출력** | `optional/annotation/<sample>.normalized.vcf.gz` (+`.tbi`), `<sample>.clinvar.vcf.gz` (+`.tbi`), `<sample>.variants.tsv` |
| **실패 조건** | 하드오프 문서 없음, 입력 VCF 없음, `bcftools norm` 비정상 종료 또는 빈 출력, 정규화 인덱스 생성 실패 |
| **warning** | `CLINVAR_NOT_CONFIGURED`, `CLINVAR_MISSING`, `CLINVAR_INCOMPATIBLE`, `CLINVAR_ANNOTATE_FAILED`, `VEP_MISSING`, `VEP_NOT_WIRED`, `TSV_FAILED` |
| **core 보존** | 실패해도 raw VCF와 core artifact는 그대로 유효 |

변이 TSV에는 다음 문구가 artifact 설명으로 붙습니다:
"연구·교육용. ClinVar에 없다는 것이 benign을 뜻하지 않습니다."

---

## 18. Optional InterVar

**위치: `script/main.sh > run_intervar()` — step `11_intervar` (기본 비활성화)**

### 18.1 InterVar가 하는 일

ACMG/AMP 가이드라인은 변이의 임상적 의미를 판정할 때
`PVS1`, `PS1`, `PM2` 같은 **근거 항목(evidence code)** 을 조합하도록 규정합니다.
InterVar는 이 중 **자동으로 계산할 수 있는 근거 항목**을 산출합니다.

### 18.2 자동 근거와 최종 임상 판정의 차이

> [!CAUTION]
> **InterVar 결과는 "자동 계산된 ACMG 근거"이지 최종 임상 판정이 아닙니다.**
>
> InterVar 자체 문서도 이 도구를 **2단계 과정**으로 설명합니다.
> ① 근거 항목의 자동 해석, ② 사용자의 수동 조정.
> 이 파이프라인이 산출하는 것은 **①번뿐**입니다.
>
> 실제 임상 판정에는 가족력, 표현형, 기능 연구, 분리 분석,
> 전문가 검토가 필요합니다.
> **이 결과를 진단으로 사용해서는 안 됩니다.**

이 원칙은 문서에만 적힌 것이 아니라 **산출물 자체에 기록**됩니다.

```json
{
  "interpretation_status": "automated_evidence_only",
  "requires_manual_review": true,
  "is_final_clinical_classification": false,
  "intended_use": "research and education only",
  "limitations": [ "…", "…", "…" ]
}
```

그리고 step은 항상 warning `AUTOMATED_EVIDENCE_ONLY`를 남깁니다.

### 18.3 사전 설치가 필수인 이유

InterVar와 ANNOVAR humandb는 **미리 설치되어 있어야 합니다.**
파이프라인은 실행 중에 clone·설치·다운로드를 하지 않습니다.

| 설정 | 없으면 |
|---|---|
| `intervar.install_dir` | step 실패. `InterVar.py`가 그 안에 있어야 함 |
| `intervar.build` | step 실패. **추정하지 않음.** 또한 `resource_bundle.assembly`와 대응해야 함 |
| `intervar.humandb_dir` | step 실패 |

#### assembly와 build의 대응 검사

`intervar.build`가 채워져 있기만 하면 되는 것이 아니라,
선언한 assembly에 **실제로 대응하는 값**이어야 합니다.

```bash
# main.sh 상단 — 확장 가능한 매핑표
declare -A INTERVAR_BUILD_FOR_ASSEMBLY=(
    [grch38]=hg38
)
```

| 실패 코드 | 언제 | 메시지가 알려 주는 것 |
|---|---|---|
| `intervar_build_not_set` | `intervar.build`가 비어 있음 | 추정하지 않는다는 사실 |
| `intervar_build_mismatch` | 예: assembly=`GRCh38`인데 build=`hg19` | 현재 assembly, 입력된 build, **기대되는 build** |
| `intervar_assembly_unmapped` | assembly가 매핑표에 없음 | 현재 assembly, 입력된 build, **등록된 매핑 목록 전체** |

세 메시지 모두 첫 문장이 다음으로 시작합니다.

```
Optional InterVar step configuration problem — the CORE pipeline and the raw VCF are unaffected.
```

즉 **core 파이프라인이 실패한 것이 아니라 optional 설정이 어긋난 것**임을 분명히 합니다.

> [!NOTE]
> 이 검사는 **optional InterVar step 안에서만** 수행됩니다.
> core preflight에서는 하지 않습니다.
> 매핑이 없는 assembly라도 QC부터 raw VCF까지는 정상적으로 완주해야 하기 때문입니다.
>
> 새 assembly를 지원하려면 해당 build의 ANNOVAR humandb를 준비한 뒤
> 매핑표에 한 줄을 추가하세요. 다른 코드는 바꿀 필요가 없습니다.

직전 리비전에서 제거한 것:

| 제거한 코드 | 이유 |
|---|---|
| `git clone https://github.com/WGLab/InterVar.git` | 분석 도중 소프트웨어 설치 |
| `pip install -r requirements.txt --break-system-packages` | 시스템 패키지 관리자의 보호를 의도적으로 무력화 |
| `python InterVar.py --download_db -d humandb/` | run이 수십 GB 데이터베이스 다운로드를 유발 |
| `-b` build 하드코딩 | config에서 읽지 않으므로 **나머지 파이프라인이 쓰는 resource의 reference build와 모순**될 수 있음. 좌표계가 어긋나 결과가 무의미해짐 |
| `find … -name "*.annotated.vcf" \| head -1` | 다른 run이나 다른 사용자의 파일을 집어올 수 있음 |

**build 하드코딩 제거가 특히 중요한 이유**: `-b`가 틀리면 도구는 정상 종료하지만
좌표 해석이 통째로 어긋납니다. 조용히 틀린 결과가 나오는 전형적인 경우입니다.
그래서 지금은 config에서 **반드시 명시**해야 하고, 비어 있으면 다음 메시지로 중단합니다.

```
intervar.build is not set. The build must match the resource bundle
(assembly=GRCh38); it is never assumed.
```

현재 기준인 GRCh38 bundle에서는 `intervar.build`를 `hg38`로 지정하고,
ANNOVAR humandb도 같은 build로 준비한 것을 사용해야 합니다.

### 18.4 입력 선택

우선순위대로 존재하는 첫 번째 파일을 씁니다.

1. `optional/annotation/<sample>.clinvar.vcf.gz`
2. `optional/annotation/<sample>.normalized.vcf.gz`
3. `variant_calling_output.json`의 `raw_vcf`

파일을 **찾아 헤매지 않고** 정해진 경로만 확인합니다.

### 18.5 실행

```bash
(
  cd "$intervar_dir" || exit 1
  "$py" ./InterVar.py \
      -i "$input_vcf" --input_type VCF \
      -o "$out_prefix" -b "$intervar_build" -t intervardb \
      --table_annovar=./table_annovar.pl \
      --convert2annovar=./convert2annovar.pl \
      --annotate_variation=./annotate_variation.pl \
      -d "$humandb"
)
```

`cd`가 **서브셸 안에서만** 일어나므로 파이프라인 자신의 작업 디렉터리는 바뀌지 않습니다.
InterVar가 헬퍼 스크립트를 상대 경로로 찾기 때문에 필요한 조치입니다.

**출력**

| 파일 | 설명 |
|---|---|
| `optional/intervar/<sample>_intervar.<build>_multianno.txt.intervar` | InterVar 결과표 |
| `optional/intervar/<sample>_intervar_summary.json` | 집계 요약 + 명시적 한계 기술 |

요약 JSON에 담기는 값:
`total_variants`, `automated_evidence_counts`(판정 문자열별 개수),
`automated_pathogenic_or_likely_pathogenic`, `gene_counts_for_pathogenic`,
그리고 위의 한계 필드들.

> 필드 이름이 `automated_pathogenic_or_likely_pathogenic`인 것에 유의하세요.
> `pathogenic_count` 같은 이름을 쓰지 않은 이유는,
> **이 숫자가 최종 판정 개수가 아니라 자동 근거 집계**이기 때문입니다.

**실패 조건**: 설치 경로·build·humandb 미설정, `InterVar.py` 없음,
하드오프 문서 없음, 입력 VCF 없음, InterVar 비정상 종료, 결과 파일 미생성.

**core 보존**: 위 어느 것으로 실패해도 raw VCF와 core artifact는 그대로 유효하며,
run은 `RUN_COMPLETED_WITH_WARNINGS`로 끝납니다.

---

## 19. 함수 간 handoff

### 19.1 왜 전역 변수만으로는 부족한가

Bash에서 함수끼리 값을 넘기는 가장 쉬운 방법은 전역 변수입니다.
`main.sh`도 `SAMPLE_ID`, `SAMPLE_BAM`, `ANALYSIS_READY_BAM`, `RAW_VCF` 같은
전역 변수를 씁니다. 하지만 그것만으로는 두 가지 문제가 있습니다.

1. **`--from-step 06_variant_calling`으로 시작하면** 앞 단계가 이번 프로세스에서
   실행되지 않았으므로 전역 변수가 비어 있습니다.
2. **재현과 감사가 안 됩니다.** 어떤 값이 어디서 왔는지 나중에 확인할 수 없습니다.

### 19.2 해결 — 디스크의 계약 문서

각 주요 단계는 **다음 단계가 읽을 파일**을 남깁니다.

| 생산 함수 | handoff 파일 | 주요 필드 | 소비 함수 | 소비 측 validation |
|---|---|---|---|---|
| `run_input_validation` | `00_input_validation/manifest.tsv` | 8컬럼: sample, lane, rg_id, library, platform, platform_unit, fastq_1, fastq_2 | `run_raw_qc`, `run_preprocessing` | 존재·비어있지 않음 |
| `run_input_validation` | `config/normalized_manifest.json` | `sample`, `library`, `platform`, `lane_count`, `lanes[]` | `run_input_validation` 자신(지표 산출), resume 검증 | `json_get sample`이 성공해야 함 |
| `run_preprocessing` | `02_preprocessing/fastq_manifest.tsv` | manifest와 동일한 8컬럼. 정렬에 실제로 쓸 FASTQ 경로 | `run_alignment` | 존재·비어있지 않음. resume 시 **선언된 FASTQ가 실제로 존재**하는지 확인 |
| `run_preprocessing` | `02_preprocessing/preprocessing_decision.json` | `mode`, `decision`, `reason`, `lanes[]`, `fastq_manifest` | (기록용) | artifact 등록 시 checksum 계산 |
| `run_alignment` | `03_alignment/alignment_output.json` | `sample`, `lane_count`, `sample_bam`, `sample_bai`, 상대 경로, `sort_order`, `next_step_ready` | `run_processing` | 문서 존재 + BAM/BAI 존재 + `validate_bam_artifact` |
| `run_processing` | `04_processing/processing_output.json` | `sample`, `analysis_ready_bam`, `analysis_ready_bai`, `nm_md_repaired`, `duplicates_removed`, `next_step_ready` | `run_coverage_qc`, `run_variant_calling` | 문서 존재 + BAM 존재 + quickcheck + `validate_bam_artifact` |
| `run_coverage_qc` | `05_coverage_qc/coverage_metrics.json` | 평균 depth, breadth, low/uncovered 지표 | `run_finalization` (요약 집계) | 존재 확인 |
| `run_variant_calling` | `06_variant_calling/variant_calling_output.json` | `sample`, `assembly`, `gvcf`, `raw_vcf`, 상대 경로, `raw_variant_records`, `filtering_applied`, `next_step_ready` | `run_filtering`, `run_annotation`, `run_intervar`, `run_finalization` | 문서 존재 + `validate_vcf_artifact` (gVCF, raw VCF 둘 다) |

### 19.3 계약이 지켜지는 방식

`--from-step`으로 중간부터 시작해도, 각 단계는 **전역 변수가 아니라 JSON을 읽어**
자기 입력을 복원합니다.

```bash
local vc_json="$RUN_DIR/06_variant_calling/variant_calling_output.json"
[[ -s "$vc_json" ]] || { fail_step "missing_variant_calling_output" "…"; return 1; }
SAMPLE_ID=$(json_get "$vc_json" sample)
RAW_VCF=$(json_get "$vc_json" raw_vcf)
```

문서가 없으면 **추측하지 않고 실패**합니다.
"아마 이 경로일 것이다"로 진행하다가 엉뚱한 파일을 쓰는 사고를 막습니다.

### 19.4 glob으로 최신 파일을 찾지 않는 이유

> [!IMPORTANT]
> **어떤 함수도 glob이나 `find`로 자기 입력을 발견하지 않습니다.**

직전 리비전에는 다음과 같은 패턴이 세 곳 있었습니다.

```bash
find "${BASE_DIR}/samples" -maxdepth 3 -name "*.recal.bam" | head -1
find "${BASE_DIR}/samples" -maxdepth 4 -name "*.annotated.vcf" | head -1
# FASTQ도 UPLOAD_DIR 또는 $HOME/giab_wes/fastq를 뒤져 첫 결과를 사용
```

이 방식의 문제:

| 문제 | 결과 |
|---|---|
| **다른 run의 파일을 집을 수 있음** | 같은 서버에서 여러 run이 돌면 남의 결과로 분석하게 됨 |
| **다른 사용자의 파일을 집을 수 있음** | 공유 서버에서 심각한 문제 |
| **`find` 순서는 결정적이지 않음** | 같은 명령이 실행할 때마다 다른 파일을 고를 수 있음 |
| **에러가 나지 않음** | 파일을 찾긴 했으므로 파이프라인은 성공한 것처럼 진행 |
| **`.part` 파일을 집을 수 있음** | 아직 완성되지 않은 파일을 입력으로 사용 |

그래서 지금은 **앞 단계가 명시적으로 발행한 경로만** 사용합니다.
경로가 없으면 진행하지 않습니다.

### 19.5 `fastq_manifest.tsv`의 형식 고정

`fastq_manifest.tsv`는 trimming을 했든 안 했든 **같은 8컬럼**입니다.
바뀌는 것은 마지막 두 컬럼(FASTQ 경로)의 값뿐입니다.

덕분에 `run_alignment`는 `trim_mode`를 알 필요도, 분기할 필요도 없습니다.
**전처리 정책의 변화가 정렬 코드에 전파되지 않습니다.**

### 19.6 계약 문서의 공통 필드

핵심 handoff 문서에는 공통으로 다음이 들어갑니다.

```json
{
  "sample": "...",
  "next_step_ready": true
}
```

`next_step_ready`는 **"이 단계는 다음 단계가 소비해도 될 만큼 완결되었다"** 는 선언입니다.
파일이 존재하는 것과, 그 파일을 써도 되는 것은 다른 문제입니다.

한편 `status/`, `metrics/`, `artifacts/` 아래의 문서와 `run_status.json`에는
`schema_version` 필드가 들어갑니다. 나중에 백엔드가 이 JSON을 읽을 때
형식 변화를 감지할 수 있게 하기 위함입니다.

---

## 20. 상태, 로그, metrics, artifact, provenance

이 다섯 가지는 이름이 비슷하지만 **역할이 다릅니다.** 구분해서 봐야 합니다.

| 종류 | 무엇인가 | 누가 읽나 | 형식 |
|---|---|---|---|
| **Status** | 지금 어떤 단계가 어떤 상태인가 | 프로그램(백엔드, resume 로직) | JSON |
| **Log** | 무슨 일이 있었는가 | 사람 | 텍스트·TSV |
| **Metrics** | 품질 지표 숫자 | 사람·프로그램 | JSON |
| **Artifact** | 검증된 산출물 목록 | 프로그램 | JSON |
| **Provenance** | 이 결과를 어떻게 만들었는가 | 사람·프로그램 | JSON |

### 20.1 run 디렉터리 구조

```
<output_root>/<run_id>/
├── .run.lock/                        동시 실행 방지 (디렉터리)
│   └── owner                         pid, host, 시작 시각
├── config/
│   ├── run_config.snapshot.json      실행 시점 설정 전체 + identity 해시
│   ├── normalized_manifest.json      sample/lane 구조화 정보
│   ├── run_config.resume_request.json    (resume 성공 시 감사 사본)
│   └── run_config.rejected_resume.json   (resume 거부 시 보존본)
├── status/
│   ├── run_status.json               run 전체 상태
│   └── steps/<step_id>.json          step별 기계 계약
├── logs/
│   ├── pipeline.log                  사람이 읽는 전체 로그
│   ├── stage_status.tsv              step 상태 변화 이력 (append)
│   ├── execution_trace.tsv           step별 소요 시간 (append)
│   ├── commands.sh                   실행된 모든 명령
│   ├── software_versions.txt         도구 버전
│   ├── resource_sha256.txt           resource 해시
│   └── <step>.<label>.stderr.log     명령별 원본 stderr
├── metrics/<step_id>.json
├── artifacts/<step_id>.json
├── tmp/                              run 전용 임시 (도구에 --tmp-dir로 지정)
├── 00_input_validation/ … 06_variant_calling/    core 결과
├── optional/
│   ├── filtering/  annotation/  intervar/        optional 결과
├── artifact_manifest.json
├── provenance.json
├── final_validation.tsv
├── core_summary.json
├── methods.md
└── RUN_COMPLETED | RUN_COMPLETED_WITH_WARNINGS | RUN_FAILED | RUN_CANCELLED
```

**지켜지는 규칙:**

- 이미 존재하는 `run_id` 디렉터리는 `--resume` 없이는 **하드 실패**입니다
  (단, 직전 실행이 `--check-only`였던 경우는 예외)
- `run_id`가 다르면 같은 sample이라도 결과가 완전히 분리됩니다
- 선언된 입력 FASTQ와 읽기 전용 resource를 빼면,
  **현재 run 디렉터리 밖을 읽거나 쓰지 않습니다**
- 공유되는 `latest` 심볼릭 링크는 없습니다
- `RUN_*` marker는 **항상 정확히 하나**만 존재합니다

> **`latest` 심볼릭 링크를 없앤 이유**
> 직전 리비전에는 `ln -sfn "$LOG_DIR" "$PROJECT/logs/full/latest_v5"`가 있었습니다.
> 공유되는 가변 심볼릭 링크는 **마지막으로 끝난 run이 덮어씁니다.**
> 결과적으로 어떤 사용자가 다른 사용자의 로그를 보게 될 수 있습니다.

### 20.2 Status

**run 상태 (`status/run_status.json`의 `status` 필드)**

| 값 | 의미 |
|---|---|
| `running` | 실행 중 |
| `check_only` | `--check-only` 실행이 끝남 |
| `completed` | 정상 완료 |
| `completed_with_warnings` | 완료했으나 warning 또는 optional 실패가 있음 |
| `failed` | core 단계 실패 |
| `cancelled` | 신호를 받아 중단됨 |
| `resume_refused` | config가 달라 resume을 거부함 |
| `stopped_at_requested_step` | `--to-step`으로 의도적으로 멈춤 |

`run_status.json`은 `status/steps/*.json`을 매번 다시 읽어 재구성되며,
`completed_steps`와 `failed_steps` 목록을 함께 담습니다.

**step 상태 (`status/steps/<step_id>.json`의 `status` 필드)**

| 값 | 의미 | 현재 코드에서 기록되는가 |
|---|---|---|
| `completed` | 실패도 warning도 없이 성공 | 예 |
| `warning` | 성공했으나 warning이 있음 | 예 |
| `failed` | 실패 | 예 |
| `cancelled` | 실행 중 신호를 받아 중단 | 예 (`on_signal`) |
| `skipped` | 의도적으로 건너뜀 | **아니오** — `skip_step()`이 정의만 되어 있고 호출되지 않음 |
| `pending` | 아직 시작하지 않음 | **아니오** — 상태 문서가 아직 없는 상태를 가리키는 개념적 표현 |

> 비활성화된 optional step은 실행 계획에 아예 들어가지 않으므로
> **상태 문서 자체가 만들어지지 않습니다.** `skipped`로 기록되는 것이 아닙니다.
> `step_is_reusable`, `gate_next_step`, `run_final_validation`은 `skipped`를
> 정상 상태로 취급하도록 이미 작성되어 있어, 나중에 쓰이더라도 로직 변경이 필요 없습니다.

**next step ready**

`next_step_ready`는 다음을 **모두** 만족할 때만 `true`입니다.

- 상태가 `completed`, `warning`, `skipped` 중 하나
- 기록된 실패가 0건
- `can_continue=false`인 warning이 없음

`gate_next_step()`은 다음 step으로 넘어가기 전에 이 값을 확인합니다.
**함수의 종료 코드 0만으로는 절대 충분하지 않습니다.**
`run_optional_cmd`가 실패한 optional 명령 뒤에도 0을 반환하도록 일부러 만들어져 있어서,
"종료 코드"와 "올바름"은 다른 질문이기 때문입니다.

**step 상태 문서의 구조**

```json
{
  "schema_version": "1.0",
  "run_id": "...",
  "step_id": "04_processing",
  "status": "completed",
  "exit_code": 0,
  "started_at": "...", "finished_at": "...", "elapsed_seconds": 1234,
  "inputs":  [ { "type": "sample_bam", "path": "03_alignment/..." } ],
  "outputs": [ { "type": "analysis_ready_bam", "path": "04_processing/..." } ],
  "validation": { "status": "pass", "checks": 9, "warnings": 0,
                  "failures": 0, "results": [ … ] },
  "warnings": [ { "code": "...", "message": "...", "impact": "...",
                  "can_continue": true } ],
  "failures": [],
  "metrics_file":   "metrics/04_processing.json",
  "artifacts_file": "artifacts/04_processing.json",
  "next_step_ready": true
}
```

`inputs`와 `outputs`의 경로는 **run 디렉터리 기준 상대 경로**로 저장됩니다.

### 20.3 Log

| 파일 | 내용 | 언제 보나 |
|---|---|---|
| `logs/pipeline.log` | 표준 출력과 표준 오류를 합쳐 기록한 전체 로그 | 전체 흐름을 훑을 때 |
| `logs/stage_status.tsv` | `timestamp / step / status / exit_code` (append) | 어느 단계에서 멈췄는지 |
| `logs/execution_trace.tsv` | `step / seconds / finished_at` (append) | 각 단계가 얼마나 걸렸는지 |
| `logs/commands.sh` | 실행된 모든 명령을 순서대로, 셸 인용까지 적용해 기록 | 손으로 재현하거나 명령을 검토할 때 |
| `logs/software_versions.txt` | 도구 버전, 호스트, 사용자, conda 환경 | 재현성 대조 |
| `logs/resource_sha256.txt` | reference·BED·known-sites의 SHA-256 | resource 동일성 확인 |
| `logs/<step>.<label>.stderr.log` | **각 명령의 원본 stderr** | 도구가 정확히 뭐라고 했는지 |

**표준 오류를 명령별로 분리 저장하는 이유**
도구가 실패했을 때 **가장 정확한 정보는 그 도구 자신의 메시지**입니다.
전체 로그에 섞이면 찾기 어렵고 앞뒤 맥락이 잘립니다.
분리해 두면 문제가 생긴 도구의 출력만 온전히 볼 수 있습니다.

**TSV가 append인 이유**
덮어쓰지 않고 계속 추가하므로, resume을 여러 번 해도 **전체 이력이 남습니다.**

**JSON과 TSV를 함께 두는 이유**

| | JSON (`status/`, `metrics/`, `artifacts/`) | TSV·로그 (`logs/`) |
|---|---|---|
| 대상 | 프로그램 | 사람 |
| 성격 | 기계 계약. 형식이 고정되고 `schema_version`이 붙음 | 감사 기록. 사람이 읽기 좋은 형태 |
| 파싱 필요성 | 필요 | 불필요 (`column -t`로 바로 봄) |
| 안정성 | 도구가 바뀌어도 필드가 유지됨 | 도구 메시지가 바뀌면 내용도 바뀜 |

**중요한 점은 둘을 같은 helper가 쓴다는 것입니다.**
`finish_step()`이 JSON을 쓰면서 `append_status_tsv`와 `append_trace_tsv`를 함께 호출하므로,
**JSON과 TSV가 서로 다른 상태를 보고할 수 없습니다.**

또한 **run의 상태를 알기 위해 `pipeline.log`를 파싱할 필요가 전혀 없습니다.**
로그 문구는 도구 버전이 바뀌면 달라지지만, 상태 문서는 그렇지 않습니다.

### 20.4 Metrics

`metrics/<step_id>.json`에 step별 지표가 모입니다.

| 단계 | 주요 지표 |
|---|---|
| `00_input_validation` | `sample`, `lane_count`, `target_rows`, `target_merged_rows`, `target_merged_bases`, `assembly`, `contig_style`, `bundle_id`, `input_fastq_bytes`, `required_disk_gb`, `available_disk_gb`, `available_ram_gb`, `logical_cores`, `fastq_gzip_verification` |
| `01_raw_qc` | `lanes_total`, `lanes_with_fastqc` |
| `02_preprocessing` | `trim_mode`, `lanes`, (force일 때) lane별 `reads_before_*` / `reads_after_*` |
| `03_alignment` | `lane_count`, `sample`, `total_alignment_records`, `mapped_pct`, `properly_paired_pct` |
| `04_processing` | `read_name_mode`, `percent_duplication`, `markdup_validation`, `markdup_validation_after_calmd`, `nm_md_repaired`, `analysis_ready_records` |
| `05_coverage_qc` | `mean_target_depth`, `target_bases_ge_*X_pct`, `zero_coverage_*`(염기), `low_mean_depth_*`·`fully_uncovered_*`(구간), `target_nonoverlap_bases` |
| `06_variant_calling` | `raw_variant_records`, `raw_records`, `raw_snps`, `raw_indels`, `raw_multiallelic_sites`, `raw_ts_tv` |
| `08_filtering` | `filter_preset`, `filter_expression`, `records_before_filter`, `records_after_filter` |
| `10_annotation` | `annotation_input`, `clinvar_matched_records` |
| `11_intervar` | `intervar_build` |
| `99_finalization` | `validation_pass`, `validation_warn`, `validation_fail`, `artifact_count`, (있으면) `optional_failed_steps` |

### 20.5 Artifact

artifact는 **검증을 통과한 산출물**입니다.
`add_artifact`는 파일이 비어 있으면 등록하지 않고, `finish_step`은 실제로
존재하는 파일만 최종 목록에 넣습니다.
`.part` 파일은 **절대 등록되지 않습니다.** 검증 후에만 최종 이름을 얻기 때문입니다.

`artifacts/<step_id>.json`의 각 항목:

| 필드 | 의미 |
|---|---|
| `file_id` | `f_` + `sha256("<run_id>:<step_id>:<상대경로>")`의 앞 16자리 |
| `step_id` | 이 파일을 만든 step |
| `kind` | 종류 태그 (`raw_vcf`, `analysis_ready_bam`, `fastqc_html` 등) |
| `display_name` | 사람이 읽는 이름 |
| `relative_path` | **run 디렉터리 기준 상대 경로** (절대 경로는 공개하지 않음) |
| `size_bytes` | 크기 |
| `sha256` | 요청된 경우에만 계산, 아니면 `null` |
| `downloadable` | 제공 가능 여부 (중간 markdup BAM은 `false`) |
| `description` | 설명. 한계가 있으면 여기에 함께 기록됨 |

finalization이 이들을 모아 `artifact_manifest.json` 하나로 만듭니다.

**절대 경로 대신 상대 경로를 쓰는 이유**: 나중에 API가 artifact를 제공할 때
서버 디렉터리 구조를 노출하지 않기 위함입니다.
백엔드는 `file_id`로 파일을 제공하면 됩니다.

### 20.6 Provenance

`provenance.json`은 **"이 결과를 어떻게 만들었는가"** 를 담습니다.

| 필드 | 내용 |
|---|---|
| `pipeline_name`, `pipeline_version`, `run_id` | 파이프라인 식별 |
| `run_config` | `config/run_config.snapshot.json` 전체 내용 |
| `config_identity_sha256` | 설정 identity 해시 |
| `software_versions` | `logs/software_versions.txt`를 key=value로 파싱한 것 |
| `resource_checksums` | reference·BED·known-sites의 sha256과 경로 |
| `steps` | step별 상태·종료 코드·소요 시간 |
| `commands`, `stage_status_tsv`, `execution_trace_tsv`, `pipeline_log`, `final_validation`, `artifact_manifest` | 관련 파일의 상대 경로 |
| `intended_use` | `"research and education only; not a diagnostic result"` |

**왜 재현성의 핵심인가**
같은 FASTQ를 같은 파이프라인으로 돌려도 결과가 달라질 수 있습니다.

| 원인 | 어떻게 확인하나 |
|---|---|
| 도구 버전이 다름 (GATK 4.2 vs 4.4) | `software_versions.txt` |
| reference 파일이 다름 (같은 이름, 다른 내용) | `resource_sha256.txt` |
| 설정값이 다름 (`interval_padding` 100 vs 50) | `run_config.snapshot.json` |
| 스레드 수가 다름 | BWA의 `-K` 고정으로 결과에는 영향 없음 |

세 파일이 있으면 위 요인을 **추측이 아니라 기록으로** 대조할 수 있습니다.
6개월 뒤 "결과가 왜 다르지?"라는 질문에 답할 수 있는 최소 조건입니다.

### 20.7 finalization의 나머지 산출물

| 파일 | 내용 |
|---|---|
| `final_validation.tsv` | `check / status / detail` 3컬럼. 전체 run에 대한 하나의 pass/warn/fail 표 |
| `core_summary.json` | 기계가 읽는 요약. sample, assembly, `core_complete`, `raw_variant_records`, `nm_md_repaired`, step 목록, 모든 warning, 전체 지표 |
| `methods.md` | 사람이 읽는 방법 기술. 논문 Methods 절의 초안으로 쓸 수 있음 |

`methods.md`에는 실행된 step 표, 도구 버전, resource 체크섬,
그리고 다음 한계 기술이 항상 포함됩니다.

- 연구·교육용이며 진단 결과가 아님
- raw VCF는 **필터링되지 않음.** 변이 수준·genotype 수준 필터링은 별도의 optional 단계
- coverage 지표는 평균 depth만으로 pass/fail 판정을 내리지 않음
- 이 run에서 truth set 대비 benchmark를 수행하지 않음

---

## 21. resume와 멱등성

### 21.1 왜 필요한가

**멱등성(idempotency)** 은 "같은 명령을 여러 번 실행해도 결과가 같다"는 성질입니다.

WES 전체 실행은 몇 시간이 걸립니다.
그리고 몇 시간짜리 작업은 **반드시 중간에 죽습니다.**
서버 재부팅, 디스크 부족, 세션 끊김, 실수로 누른 Ctrl+C.
그때마다 처음부터 다시 돌리는 것은 현실적이지 않습니다.

### 21.2 순진한 resume이 위험한 이유

가장 흔한 구현은 "출력 파일이 있으면 건너뛴다"입니다. **이건 위험합니다.**

| 상황 | 순진한 방식의 동작 | 실제로 일어나는 일 |
|---|---|---|
| BAM을 쓰는 중에 프로세스가 죽음 | 파일이 있으니 건너뜀 | **잘린 BAM으로 계속 진행** |
| config를 바꾸고 resume | 파일이 있으니 건너뜀 | **옛 설정 결과와 새 설정 결과가 한 run에 섞임** |
| reference 파일을 교체 | 파일이 있으니 건너뜀 | **다른 reference 기준으로 만든 BAM에서 변이 호출** |
| `.tbi` 인덱스만 삭제됨 | VCF가 있으니 건너뜀 | 다음 단계에서 뒤늦게 실패 |
| 앞 단계를 다시 돌림 | 뒤 단계는 파일이 있으니 건너뜀 | **입력은 새것, 결과는 옛것** |

전부 **에러 없이 틀린 답**으로 이어집니다.
그래서 이 파이프라인은 세 겹의 확인을 둡니다.

### 21.3 ① config identity 비교

`config_identity_sha256`은 다음을 정렬된 JSON으로 만들어 해시한 값입니다.

- `run_id`
- 분석에 영향을 주는 설정값: `samplesheet` 경로, `trim_mode`, `interval_padding`,
  `mosdepth_mapq`, `pairhmm_threads`, `bqsr_target_only`, `resource_bundle` 전체
- **resource 파일의 내용 해시**: samplesheet, reference FASTA, target BED,
  known-sites 각각, dbSNP
- **lane별 FASTQ 지문**

**resource 내용까지 해시하는 이유**
경로는 그대로인데 파일만 바꿔치기하는 경우를 잡기 위함입니다.
이게 없으면 "같은 `/ref/reference.fa` 경로"인데 내용이 다른 상황을 탐지할 수 없습니다.

**FASTQ 지문 정책**

| 설정 | 지문 방식 | 이유 |
|---|---|---|
| 기본 | `크기:수정시각` | 전체 WES FASTQ를 해시하면 수 분이 걸립니다 |
| `resume_strict_checksums: true` | SHA-256 | 내용 변경까지 확실히 탐지 |

reference·BED·known-sites·samplesheet는 **항상 내용 해시**입니다.
FASTQ에 비해 작고, 바뀌면 결과가 조용히 달라지기 때문입니다.

**비교 순서가 결정적입니다**

```
1. 기존 snapshot을 읽는다              ← 절대 먼저 덮어쓰지 않음
2. 새 요청으로 identity를 계산해 임시 파일에 쓴다
3. 두 identity를 비교한다
4. 다르면 중단. 원본 snapshot 보존, 거부된 요청은 별도 보관
5. 같으면 진행. snapshot은 여전히 다시 쓰지 않음
```

> 초기 구현은 snapshot을 **먼저 쓴 뒤** 자기가 방금 쓴 값과 비교했습니다.
> 항상 일치할 수밖에 없는 무의미한 비교였고, 설정 변경을 절대 감지하지 못했습니다.
> 이것이 감사에서 BLOCKER로 지적되어, `render_config_snapshot`이
> **쓸 위치를 인자로 받는** 형태로 분리되었습니다.

거부되면 `report_identity_diff`가 **달라진 필드만** 출력합니다.

```
  differences:
    - settings.trim_mode: recorded='skip' requested='force'
    - resource_content.target_bed: recorded='a1b2…' requested='c3d4…'
```

### 21.4 ② artifact 무결성 검증

identity가 같아도, 파일 존재만으로는 재사용하지 않습니다.
`validate_step_artifacts()`가 **실제로 검사**합니다.

공통 검사:

| 검사 | 내용 |
|---|---|
| 기록된 모든 출력 | 존재하고 크기가 0이 아님 |
| 상태 문서 | 파싱되고, `run_id`가 이 run이며, `step_id`가 이 step임 |

step별 검사:

| Step | 실제로 확인하는 것 |
|---|---|
| `00_input_validation` | `manifest.tsv`가 비어있지 않음, `normalized_manifest.json`에서 `sample`을 읽을 수 있음 |
| `01_raw_qc` | 기록된 출력 존재 확인만 |
| `02_preprocessing` | `fastq_manifest.tsv`가 비어있지 않고, **거기 선언된 모든 FASTQ가 실제로 존재하고 비어있지 않음** |
| `03_alignment` | `alignment_output.json` 존재, sample BAM과 BAI 존재, `validate_bam_artifact` |
| `04_processing` | `processing_output.json` 존재, analysis-ready BAM과 `.bai` 존재, `validate_bam_artifact` |
| `05_coverage_qc` | `coverage_metrics.json` 존재 |
| `06_variant_calling` | `variant_calling_output.json` 존재, gVCF `validate_vcf_artifact`, raw VCF `validate_vcf_artifact`(sample 컬럼까지 대조) |
| `08_filtering` / `10_annotation` / `11_intervar` | **공통 존재 확인만** |

`validate_bam_artifact`가 확인하는 것:
`samtools quickcheck` 통과 → 인덱스 존재 → `samtools idxstats` 실행 가능 →
`@HD … SO:coordinate` → 기대하는 `SM` 태그.

`validate_vcf_artifact`가 확인하는 것:
비어있지 않음 → `bcftools view -h` 파싱 → `.tbi`/`.csi` 존재 →
`tabix -l` 실행 가능 → 기대하는 sample 컬럼.

### 21.5 ③ downstream 무효화

`STEP_DEPENDS`에 각 단계의 의존 관계가 선언되어 있습니다.

```
00_input_validation  →  01_raw_qc, 02_preprocessing
02_preprocessing     →  03_alignment
03_alignment         →  04_processing
04_processing        →  05_coverage_qc, 06_variant_calling
06_variant_calling   →  08_filtering, 10_annotation, 11_intervar, 99_finalization
```

어떤 step이 재실행되면 `mark_step_invalidated()`가 그것을 기록하고,
그 step에 의존하는 step은 `step_is_reusable()`에서 즉시 재사용 불가로 판정됩니다.
step을 **실행 계획 순서대로** 검사하므로 이 무효화는 자동으로 **전이(transitive)** 됩니다.

```
[RESUME] 06_variant_calling cannot be reused: VCF index missing for S.raw.vcf.gz
[RESUME] 99_finalization cannot be reused: its dependency 06_variant_calling was invalidated
```

### 21.6 step 재사용 조건 — 전부 만족해야 함

| 조건 | 확인하는 함수 |
|---|---|
| 상태가 `completed` / `warning` / `skipped` | `step_is_reusable` |
| `next_step_ready`가 `true` | `step_is_reusable` |
| 의존하는 upstream step이 무효화되지 않음 | `step_is_reusable` |
| 기록된 `config_identity_sha256`이 일치 | `main` (아무것도 쓰기 전에 한 번) |
| 상태 문서가 이 run·이 step의 것임 | `validate_step_artifacts` |
| 기록된 모든 출력이 존재하고 비어있지 않음 | `validate_step_artifacts` |
| step별 무결성 검사 통과 | `validate_step_artifacts` |

**`.done` 파일 하나로 건너뛰는 일은 없습니다.**
`03_alignment` 안의 `.done` marker는 **같은 run 안에서의 재진입**을 빠르게 하기 위한
보조 표시일 뿐이고, 그것조차 `samtools quickcheck`과 함께 확인됩니다.

### 21.7 `--from-step`의 upstream 검증

`--from-step`으로 중간부터 시작하면 앞 단계는 아예 실행되지 않습니다.
그래서 `assert_from_step_inputs()`가 그 step의 `STEP_DEPENDS` 항목마다
상태 문서 존재와 artifact 유효성을 확인하고, 실패하면 시작 자체를 거부합니다.

```
--from-step 06_variant_calling cannot start: its input from 04_processing is not valid.
Reason: samtools quickcheck failed on HG002.analysis_ready.bam
Re-run from 04_processing (or earlier) instead.
```

검증되지 않은 입력을 소비하느니 시작하지 않는 편이 낫다는 판단입니다.

### 21.8 멱등성을 지키는 다른 장치들

| 장치 | 막는 사고 |
|---|---|
| 같은 `run_id` 디렉터리 존재 시 `--resume` 없으면 실패 | 이전 run 위에 덮어쓰기 |
| `run_id`가 다르면 결과가 완전히 분리 | 서로 다른 실행의 결과 혼합 |
| run 디렉터리가 `output_root` 안에 있는지 확인 | 의도치 않은 위치 오염 |
| run lock | 같은 run 디렉터리에 두 프로세스가 동시에 쓰기 |
| `.part` → 검증 → rename | 잘린 파일이 최종 이름을 갖는 것 |

`--check-only`가 남긴 디렉터리는 예외입니다.
분석 산출물이 없으므로, 이후 실제 실행이 `--resume` 없이 그대로 진행됩니다.

### 21.9 현재 한계 — 숨기지 않고 적습니다

> [!NOTE]
> **① FASTQ 크기+수정시각 방식의 한계.**
> 기본 설정에서는 FASTQ의 내용 변경을 완벽히 탐지하지 못합니다.
> 크기가 같고 수정시각이 유지되도록 파일을 바꿔치기하면 identity가 동일하게 나옵니다.
> 확실히 하려면 `resume_strict_checksums: true`를 쓰세요. 대신 느려집니다.
>
> **② optional subconfig가 identity에 약하게 반영됨.**
> `filtering.preset`, `filtering.min_dp`, `intervar.build`, `intervar.humandb_dir` 등은
> `load_config`가 읽지 않고 각 optional 함수가 실행 시점에 직접 읽으므로
> **identity 해시에 포함되지 않습니다.**
> filtering 기준만 바꾸고 `--resume` 하면 기존 결과가 재사용될 수 있습니다.
> `optional_steps.*` 토글 자체도 identity에 들어가지 않습니다.
>
> **③ optional artifact validator가 core보다 약함.**
> optional step의 재사용 검증은 **파일 존재 확인 수준**이며,
> core step처럼 VCF 파싱·인덱스 검사·sample 대조를 하지 않습니다.
>
> ②와 ③ 모두 **core raw VCF에는 영향이 없습니다.**
> optional 결과를 새 기준으로 다시 만들려면 새 `run_id`를 쓰는 것이 확실합니다.

---

## 22. part 파일, atomic rename, lock, marker

### 22.1 `.part` — 완성되지 않은 파일을 최종 산출물로 오인하지 않게 하는 장치

**문제:** 도구가 BAM을 쓰는 도중에 죽으면, **최종 이름을 가진 잘린 파일**이 남습니다.
다음 실행은 그것을 "완성된 결과"로 착각합니다.

**해결:** 완성 전에는 최종 이름을 주지 않습니다.

```
1. 임시 이름으로 쓴다              <sample>.analysis_ready.part.bam
2. 구조를 검증한다                 samtools quickcheck
3. 인덱스를 만들고 검증한다         (여전히 .part 이름 상태에서)
4. 모든 검사를 통과하면 최종 이름으로 바꾼다
5. 실패하면 .part를 지우거나 격리 상태로 남긴다
```

**핵심 원칙: 최종 이름이 존재한다면, 그 파일은 검증을 통과한 것입니다.**

적용 대상:

| 산출물 | 최종 이름을 받는 시점 |
|---|---|
| lane BAM | quickcheck 통과 후 rename, 그다음 인덱스 생성 |
| merged sample BAM | quickcheck 통과 후 rename, 그다음 인덱스 생성 |
| markdup BAM | quickcheck 통과 후 rename |
| calmd 출력 | quickcheck 통과 후 markdup BAM 자리로 rename |
| recalibration table | `RecalTable0` 문자열 확인 후 rename |
| **analysis-ready BAM** | 인덱스·flagstat·ValidateSamFile·record count·`SM` 검사를 전부 통과한 뒤 **본체와 인덱스를 함께** rename |
| **gVCF, raw VCF** | `.part` 상태에서 인덱스를 만들고 헤더 파싱을 확인한 뒤 **본체와 인덱스를 함께** rename |
| filtered / normalized / ClinVar VCF | 출력이 비어있지 않음을 확인한 뒤 rename |
| 모든 상태·지표·artifact JSON | Python이 `.part`에 쓴 뒤 `os.replace` |

### 22.2 atomic rename

`mv`(그리고 Python의 `os.replace`)는 **같은 파일시스템 안에서 원자적**입니다.
파일 이름은 **바뀌었거나 안 바뀌었거나**, 중간 상태가 없습니다.
읽는 쪽이 반쯤 쓰인 파일을 보는 일이 발생하지 않습니다.

**BAM/BAI와 VCF/index는 한 쌍입니다**

본체를 먼저 공개하고 인덱스를 나중에 만들면, 그 사이에 프로세스가 죽었을 때
**인덱스 없는 완성 파일**이 남습니다.
다음 단계는 그것을 완성품으로 보고 읽으려다 실패합니다.

그래서 analysis-ready BAM, gVCF, raw VCF는
**`.part` 이름일 때 인덱스까지 만들고 검증한 뒤 둘을 함께 공개**합니다.

```bash
# analysis-ready BAM
mv -f -- "${final_part}.bai" "${ANALYSIS_READY_BAM}.bai"
mv -f -- "$final_part"       "$ANALYSIS_READY_BAM"

# raw VCF
mv -f -- "${raw_part}.tbi" "${RAW_VCF}.tbi"
mv -f -- "$raw_part"       "$RAW_VCF"
```

> [!WARNING]
> **이 부분은 Linux smoke test에서 반드시 실제 도구로 확인해야 합니다.**
>
> 코드는 `samtools index <파일>.part.bam`이 `<파일>.part.bam.bai`를 만들고,
> GATK가 `<파일>.part.vcf.gz`에 대해 `<파일>.part.vcf.gz.tbi`를 만든다고 가정합니다.
> 이 가정이 실제 도구 버전에서도 성립하는지는 **정적 검토로 확인할 수 없습니다.**
> smoke test에서 `mv` 대상 파일이 실제로 존재하는지 확인해야 합니다.

### 22.3 Lock — 동시 실행 방지

**문제:** 같은 run 디렉터리에 두 프로세스가 동시에 쓰면 결과가 섞입니다.

**해결:** `mkdir`을 lock으로 사용합니다.

```bash
if mkdir "$RUN_DIR/.run.lock" 2>/dev/null; then
    printf 'pid=%s\nhost=%s\nstarted=%s\n' \
        "$$" "$(hostname)" "$(iso_now)" > "$RUN_LOCK_DIR/owner"
    RUN_LOCK_HELD=1
fi
```

**왜 `mkdir`인가**
`mkdir`은 POSIX에서 **원자적**입니다.
디렉터리가 이미 있으면 실패하고, 없으면 만들면서 성공합니다.
두 프로세스가 동시에 시도해도 **정확히 하나만 성공**합니다.

`if [ ! -d lock ]; then mkdir lock; fi` 같은 방식은 검사와 생성 사이에 틈이 있어
둘 다 성공할 수 있습니다.

**`flock`을 쓰지 않은 이유**
`flock`은 사용할 수 없거나 신뢰하기 어려운 환경(일부 NFS 구성)이 있습니다.
그런 곳에서는 어차피 `mkdir` 방식의 대체 경로가 필요합니다.
그러면 **추론해야 할 메커니즘이 둘**이 됩니다. 하나로 통일하는 편이 낫다고 판단했습니다.

**owner 파일에 pid·host·시작 시각을 남기는 이유**
lock이 잡혀 있을 때 사용자에게 판단 근거를 주기 위함입니다.

| 상황 | 파이프라인이 알려 주는 것 |
|---|---|
| **active lock** — 같은 호스트, pid가 살아 있음 | "pid N이 이 호스트에서 아직 실행 중입니다. 끝나기를 기다리거나 의도적으로 중지하세요." |
| **stale lock 의심** — 같은 호스트, pid가 없음 | "pid N이 이 호스트에 없으므로 **아마도** 죽은 run이 남긴 stale lock입니다. **자동으로 지우지 않습니다.** pid는 재사용될 수 있습니다. 확실하다면 직접 지우고 다시 시도하세요." |
| 다른 호스트 | "lock이 호스트 X에서 잡혔습니다. 여기서는 확인할 수 없습니다. 그쪽에서 실행 중이 아님을 확인한 뒤 지우세요." |

**lock을 자동으로 지우지 않는 이유**
"죽은 프로세스의 lock"과 "다른 호스트에서 실행 중인 lock"을
**확실하게 구분할 수 없습니다.**
게다가 pid는 재사용됩니다. 잘못 지우면 두 프로세스가 같은 디렉터리를 동시에 쓰게 되고,
그것이 lock으로 막으려던 바로 그 사고입니다.

**SIGKILL의 한계**
`mkdir` lock은 **살아 있는 소유자와 SIGKILL로 죽은 소유자를 구분할 수 없습니다.**
`kill -9`, OOM killer, 노드 장애로 죽으면 lock 디렉터리가 그대로 남고,
마지막 step은 상태 문서 없이 남거나 `running` 상태로 남습니다.
프로세스가 자기 죽음을 기록할 수는 없기 때문에, 이는 구조적 한계입니다.
사람이 확인하고 정리해야 합니다.

**해제**: `EXIT` trap의 `on_exit`가 `release_run_lock`을 호출하므로
정상 종료·실패·Ctrl+C 모두 해제됩니다.

### 22.4 Trap — 중단 처리

```bash
set -Eeuo pipefail
```

| 옵션 | 의미 |
|---|---|
| `-e` | 명령이 실패하면 즉시 중단 |
| `-E` | 함수와 서브셸 안에서도 `ERR` trap이 동작 |
| `-u` | 정의되지 않은 변수를 쓰면 오류 |
| `-o pipefail` | 파이프 중 하나라도 실패하면 파이프 전체가 실패 |

| Trap | 함수 | 하는 일 |
|---|---|---|
| `INT` / `TERM` | `on_signal` | trap 해제 → 자식 프로세스에 `TERM` → 진행 중 step을 `cancelled`로 마감 → run 상태 `cancelled` → `RUN_CANCELLED` marker → lock 해제 → exit 130 |
| `ERR` | `on_error` | 오류가 난 줄 번호·명령·종료 코드를 경고로 출력 → 진행 중 step을 `failed`로 마감 → run 상태 `failed` → `RUN_FAILED` marker → lock 해제 |
| `EXIT` | `on_exit` | **lock 해제만** |

> **취소는 직접 자식까지만 닿습니다.**
> `on_signal`은 `pkill -TERM -P $$`를 실행합니다.
> 부모에서 분리된 손자 프로세스나 스케줄러에 제출된 작업은 Bash에서 닿을 수 없습니다.
> 긴 GATK 단계를 취소했다면 `ps`로 남은 프로세스가 없는지 확인하세요.

> **`pipeline.log`의 마지막 줄이 잘릴 수 있습니다.**
> 로그 캡처는 프로세스 치환(`tee`)을 사용합니다.
> 갑작스러운 종료 시 마지막 몇 줄이 유실될 수 있습니다.
> **믿을 수 있는 기록은 상태 JSON과 `RUN_*` marker입니다.**

### 22.5 Marker — 결과를 한눈에

run 디렉터리 최상위에 파일 하나만 보면 결과를 알 수 있습니다.

| Marker | 의미 |
|---|---|
| `RUN_COMPLETED` | core 성공, warning 없음, optional 실패 없음 |
| `RUN_COMPLETED_WITH_WARNINGS` | core 성공, warning이 있거나 optional 단계가 실패함 |
| `RUN_FAILED` | core 단계 실패 또는 예상치 못한 오류 |
| `RUN_CANCELLED` | `INT`/`TERM` 신호를 받아 중단 |

marker 파일 내용은 3줄입니다: marker 이름, 시각, 상세 설명.

**marker가 하나만 남아야 하는 이유**
두 개가 동시에 있으면 어느 것이 이번 결과인지 알 수 없습니다.
그래서 `set_run_marker()`는 쓰기 전에 항상 `clear_run_markers()`를 호출해
기존 marker 4종을 모두 지웁니다. **정확히 하나만 존재합니다.**

또한 `main()`은 실제 실행을 시작하기 직전에도 `clear_run_markers()`를 호출합니다.
이전 run의 marker가 새 실행 중에 남아 있지 않게 하기 위함입니다.

**marker를 남기지 않는 경우**

| 상황 | 이유 |
|---|---|
| `--check-only` | 분석 산출물이 없으므로, 시작한 적 없는 run을 설명하는 marker를 남기면 안 됨 |
| `--to-step`으로 중단 | 부분 실행을 완료로 오인하지 않기 위함. run 상태는 `stopped_at_requested_step` |
| resume 거부 | 아무것도 실행하지 않음. run 상태는 `resume_refused` |

**활용 예시**

```bash
for d in /data/runs/*/; do
  if   [[ -f "$d/RUN_COMPLETED" ]];               then echo "OK    $d"
  elif [[ -f "$d/RUN_COMPLETED_WITH_WARNINGS" ]]; then echo "WARN  $d"
  elif [[ -f "$d/RUN_FAILED" ]];                  then echo "FAIL  $d"
  elif [[ -f "$d/RUN_CANCELLED" ]];               then echo "CANCEL $d"
  fi
done
```

JSON을 파싱할 필요가 없어 셸 스크립트와 배치 처리에서 쓰기 편합니다.

---

## 23. core와 optional 상태 정책

### 23.1 종류는 추론하지 않고 선언한다

`main.sh` 상단에 두 개의 표가 **한 번만** 선언되어 있습니다.

```bash
declare -A STEP_KIND=(
    [00_input_validation]=core   [01_raw_qc]=core
    [02_preprocessing]=core      [03_alignment]=core
    [04_processing]=core         [05_coverage_qc]=core
    [06_variant_calling]=core    [08_filtering]=optional
    [10_annotation]=optional     [11_intervar]=optional
    [99_finalization]=core
)

declare -A STEP_DEPENDS=( … )
```

`build_step_plan`, `should_run_step`, `step_is_reusable`,
`run_final_validation`, `run_pipeline`이 **모두 이 표를 읽습니다.**

**함수 이름이나 ID 접두사로 core/optional을 추측하는 코드는 없습니다.**
그래서 resume 로직의 판단과 보고 로직의 판단이 서로 어긋날 수 없습니다.

### 23.2 step 전체 표

| Step | 종류 | 기본 활성 | 실패 시 run 영향 | warning 가능 | 의존 |
|---|---|---|---|---|---|
| `00_input_validation` | core | 항상 | `RUN_FAILED` | 예 | — |
| `01_raw_qc` | core | 항상 | `RUN_FAILED` | 예 | `00` |
| `02_preprocessing` | core | 항상 | `RUN_FAILED` | 예 | `00` |
| `03_alignment` | core | 항상 | `RUN_FAILED` | 예 | `02` |
| `04_processing` | core | 항상 | `RUN_FAILED` | 예 | `03` |
| `05_coverage_qc` | core | 항상 | `RUN_FAILED` | 예 | `04` |
| `06_variant_calling` | core | 항상 | `RUN_FAILED` | 예 | `04` |
| `08_filtering` | **optional** | **꺼짐** | **없음** — warning으로 기록 | 예 | `06` |
| `10_annotation` | **optional** | **꺼짐** | **없음** — warning으로 기록 | 예 | `06` |
| `11_intervar` | **optional** | **꺼짐** | **없음** — warning으로 기록 | 예 | `06` |
| `99_finalization` | core | 항상 | `RUN_FAILED` | 예 | `06` |

> `05_coverage_qc`와 `06_variant_calling`이 **둘 다 `04_processing`에 의존**한다는 점에 유의하세요.
> 변이 호출은 coverage QC의 결과를 소비하지 않습니다.

### 23.3 상태 결정 규칙

| 상황 | run 상태 | marker |
|---|---|---|
| core 전부 성공, warning 없음, optional 실패 없음 | `completed` | `RUN_COMPLETED` |
| core 전부 성공 + warning 있음 | `completed_with_warnings` | `RUN_COMPLETED_WITH_WARNINGS` |
| core 전부 성공 + optional 일부 실패 | `completed_with_warnings` | `RUN_COMPLETED_WITH_WARNINGS` |
| core 하나라도 실패 | `failed` | `RUN_FAILED` |
| 신호로 중단 | `cancelled` | `RUN_CANCELLED` |
| `--to-step` 도달 | `stopped_at_requested_step` | 없음 |

### 23.4 왜 optional 실패를 전체 실패로 만들지 않는가

이 파이프라인의 **핵심 산출물은 raw VCF**입니다.

raw VCF가 정상적으로 나왔는데 ClinVar 파일 경로가 틀렸다는 이유로
전체를 `RUN_FAILED`로 표시하면:

- 몇 시간짜리 정상 결과를 **실패로 오인**하게 됩니다
- 완전히 유효한 raw VCF를 다시 만드는 낭비가 생깁니다
- 상태 표시가 **사실과 다릅니다.** core는 실제로 성공했습니다

optional 실패는 대신 이렇게 처리됩니다.

| 처리 위치 | 동작 |
|---|---|
| `run_pipeline` | 경고 로그를 남기고 `OPTIONAL_FAILED_STEPS`에 추가한 뒤 **계속 진행** |
| `run_final_validation` | `final_validation.tsv`에 `WARN`으로 기록: `OPTIONAL step failed; core results are unaffected and remain valid` |
| `run_final_validation` | 실패한 optional step 이름을 warning `OPTIONAL_STEPS_FAILED`와 지표 `optional_failed_steps`로 남김 |
| `set_run_marker` | marker 상세 줄에 실패한 step 이름을 기재 |

**raw VCF와 모든 core artifact는 유효하고 그대로 제공 가능한 상태로 남습니다.**

> 이 정책이 처음부터 있었던 것은 아닙니다.
> 초기 구현에서는 `run_final_validation`이 실패한 step을 종류 구분 없이 처리해서,
> `08_filtering` 하나가 실패하면 finalization이 실패하고 결과적으로
> raw VCF가 온전한데도 `RUN_FAILED`가 되었습니다.
> 이는 optional 격리 원칙과 정면으로 모순되었고,
> 이제는 문서가 아니라 **코드에서** 그 원칙이 강제됩니다.

### 23.5 optional 결과의 물리적 격리

optional step의 결과는 전부 `optional/` 아래에만 씁니다.

```
optional/filtering/    optional/annotation/    optional/intervar/
```

core 결과(`06_variant_calling/` 등)와 **디렉터리 수준에서 분리**되어 있어,
optional이 실패하더라도 core 산출물이 섞이거나 훼손될 수 없습니다.

**어떤 optional step도 raw VCF를 수정하거나 덮어쓰지 않습니다.**
filtering은 새 파일을 만들고, annotation은 정규화본을 따로 만들며,
InterVar는 읽기만 합니다.

### 23.6 finalization이 실패하는 조건

`99_finalization`은 **항상 실행됩니다.** 부분적으로 성공한 run이라도
완전한 기록을 남기기 위함입니다. 다음 경우에만 실패합니다.

- analysis-ready BAM이 없음
- gVCF가 없음
- raw VCF 또는 그 인덱스가 없음
- **core** step 중 상태가 `failed`인 것이 있음

**optional step의 실패는 finalization을 실패시키지 않습니다.**

---

## 24. 조원 코드 통합 판단

### 24.1 배경

직전 리비전의 `script/main.sh`(커밋 `a0c9927`, 2,323줄)는
**서로 다른 사람이 각자 작성한 다섯 개의 독립 스크립트를 이어 붙인 파일**이었습니다.
각 블록은 자기 안에서는 동작하도록 작성되었지만, 서로 연결된 적이 없었습니다.

이 장은 각 블록이 어떻게 처리되었는지, 그리고 **제거한 것에 대해서는
그것이 취향 문제가 아니라 확인된 오류라는 근거**를 기록합니다.

> 아래에서 언급하는 줄 번호는 전부 **직전 리비전** 기준이며, 현재 파일과 무관합니다.

### 24.2 분석 코드의 출처

지시에 따라 두 곳만 사용했습니다.

1. 커밋 `a0c9927` 시점의 작업 트리 `script/main.sh`
2. 원 작성자의 완전한 독립 스크립트
   `run_wes_processing_variantcall_full_v5_1.sh` — **읽기 전용 참조**.
   이 저장소에 복사한 적이 없으며, 아래에 명시한 로직만 함수로 옮겼습니다.

**git 히스토리에서 복원한 파일은 없습니다.**
삭제된 스크립트, 삭제된 Python 주석 코드, 삭제된 테스트, 삭제된 `docs/*.md`는
구현 출처로 사용하지 않았습니다.
히스토리는 각 블록이 언제 어느 커밋으로 추가되었는지 확인하는 데만 참조했습니다.

### 24.3 처리 방식 분류

| 분류 | 의미 |
|---|---|
| **그대로 유지** | 분석 로직과 인터페이스 모두 변경 없음 |
| **interface만 수정** | 분석 로직은 그대로. 입출력 경로·변수·상태 기록만 맞춤 |
| **두 구현 장점 통합** | 같은 일을 하는 구현이 둘 있었고, 더 나은 쪽을 기본으로 삼고 다른 쪽의 장점을 합침 |
| **optional로 보존** | 코드를 유지하되 기본 비활성화 |
| **문서 참고만 유지** | 실행하지 않고 지식으로만 기록 |
| **명백한 오류로 제거** | 근거와 함께 제거 |

### 24.4 블록별 처리 표

| 기존 코드 영역 | 최종 위치 | 처리 방식 | 이유 |
|---|---|---|---|
| **samplesheet validation** (432–669행) | `validate_samplesheet()` | interface만 수정 | 236줄짜리 Python 검증기의 규칙을 전부 보존. read group 컬럼과 "한 run 한 sample" 규칙만 추가하고, `normalized_manifest.json` 출력을 더함 |
| **FastQC (lane별)** (776–810행) | `run_raw_qc()` | 두 구현 장점 통합 (기본 구현) | lane 인지 구현이 samplesheet 계약과 맞고 자기 출력을 검증함 |
| **FastQC (중복 호출)** (1061행) | 제거 | 명백한 오류로 제거 | Processing 스크립트에서 온 사본으로, `$FQ1`·`$FQ2`·`$FASTQC_THREADS`·`run_cmd` 등 **이 파일에 존재하지 않는 심볼**을 참조. 같은 read를 두 번 QC하게 됨 |
| **MultiQC** (1013–1027행) | `run_raw_qc()` 후반 | interface만 수정 | `multiqc --force --outdir` 유지 + 리포트 생성 확인 추가. **report-only 정책**을 명시적으로 정함 |
| **fastp** (253–399행) | `run_preprocessing()` | interface만 수정 | 옵션 세트를 그대로 보존. 입력은 검증된 manifest에서, 출력은 `.part` → 검증 → rename |
| **BWA Alignment (lane별)** (812–870행) | `run_alignment()` | 두 구현 장점 통합 (기본 구현) | lane 인지 + `-K`/`-Y` + read group + atomic rename + quickcheck + `.done` 재진입 |
| **BWA Alignment (Processing 사본)** | 실행하지 않음 | 문서 참고만 유지 | 안전 로직만 병합. **호출 자체를 실행하면 같은 read를 두 번 정렬**하게 됨 |
| **lane merge** (878–967행) | `run_alignment()` 후반 | 그대로 유지 + 검사 1개 추가 | `samtools merge`, 단일 lane 하드 링크 경로, quickcheck, `.done` 보존. merged BAM의 `SM`이 정확히 하나인지 확인을 추가 |
| **MarkDuplicates** (1097–1103행) | `run_processing()` | interface만 수정 | `--REMOVE_DUPLICATES false --CREATE_INDEX false`와 metrics 보존. optical duplicate 모드 판정만 BAM 첫 read 이름 기반으로 변경 |
| **calmd (NM/MD)** (1110–1141행) | `run_processing()` | interface만 수정 | 명령과 주석을 보존하되, **무조건 실행에서 근거 기반 조건부 실행으로** 변경 |
| **ValidateSamFile** (1149–1150, 1175–1176행) | `run_processing()` | interface만 수정 | `-MODE SUMMARY` 검증 2회 유지. analysis-ready BAM이 `CLEAN`이어야 한다는 조건 추가 |
| **BQSR** (1152–1170행) | `run_processing()` | interface만 수정 | `--known-sites`를 고정 변수 3개에서 bundle 배열로. **`ApplyBQSR`에 `-L`을 주지 않는 결정과 그 주석을 그대로 보존.** record count 보존 검사 유지 |
| **Coverage (thresholds 방식)** (1191–1193행) | `run_coverage_qc()` | 두 구현 장점 통합 (기본 구현) | `>=Nx` 비율이 지표 계약에 직접 대응하고, **이 방식만 MAPQ 필터를 적용**함 |
| **Coverage (quantize 방식)** (1403–1565행) | 채택하지 않음 | 두 구현 장점 통합 | 비겹침 target 유도와 depth 가중 평균 계산 방식은 가져옴 |
| **HaplotypeCaller** (1195–1203행) | `run_variant_calling()` | interface만 수정 | `-ERC GVCF`, `-L`/`-ip`, `--native-pair-hmm-threads`, `.part` + `.tbi` 처리, tabix fallback 보존 |
| **GenotypeGVCFs** (1205–1212행) | `run_variant_calling()` | interface만 수정 | 동일 영역·padding, `.part` 처리 보존. `--dbsnp`만 bundle 선언 기반 조건부로 변경 |
| **hard filtering (genotype 품질)** (1794–1812, 1944–1946행) | `run_filtering()` | optional로 보존 | 표현식과 preset을 그대로 보존. **임계값이 truth set으로 평가된 적이 없어** 기본 비활성화 |
| **MAF filtering** | 해당 없음 | — | **코드에 존재한 적 없음.** 제안 자료에만 있었음 |
| **VCF normalization** (1948–1953행) | `run_annotation()` | interface만 수정 (optional 안에서) | `bcftools norm -m -any [-f]` 보존. core raw VCF는 일부러 정규화하지 않음 |
| **ClinVar annotation** (1955–1959행) | `run_annotation()` | optional로 보존 | `bcftools annotate` 필드 목록 보존 + 원본의 build 안전 확인 습관을 contig style 대조로 구현 |
| **VEP (REST)** (1974–2017행) | 실행하지 않음 | 문서 참고만 유지 | 원격 의존으로 재현 불가, 제3자 데이터 전송, 그리고 **원본 코드 자체가 2000개 초과 시 중단**해 전장 엑솜 처리 불가 |
| **PanelApp (REST)** (1859–1920행) | 실행하지 않음 | 문서 참고만 유지 | 위와 같은 원격 의존 문제 + `PANEL_ID`를 형식 검증 없이 URL에 삽입. 패널 635는 유전성 유방·난소암 패널로 **질환 특화 기능**이지 일반 WES 단계가 아님 |
| **BRCA Exchange / REVEL / SpliceAI** | 해당 없음 | — | **코드에 존재한 적 없음.** 흉내 낸 구현도 만들지 않음 |
| **InterVar** (2161–2323행) | `run_intervar()` | optional로 보존 | 호출과 결과 집계 보존. 설치·다운로드·build 하드코딩 제거 |
| **runtime install** (371, 1519, 2213–2217행) | 제거 | 명백한 오류로 제거 | 아래 24.5 |
| **`latest_v5` symlink** (1386행) | 제거 | 명백한 오류로 제거 | 공유 가변 심볼릭 링크는 마지막으로 끝난 run이 덮어씀. 한 사용자가 다른 사용자의 로그를 보게 됨 |
| **glob 자동 탐색** (301–314, 1448, 2192행) | 제거 | 명백한 오류로 제거 | 다른 run·다른 사용자의 파일을 집을 수 있고 `find` 순서가 결정적이지 않음. [19.4](#194-glob으로-최신-파일을-찾지-않는-이유) |
| **reference build 혼용** (2295행) | 제거 | 명백한 오류로 제거 | InterVar build가 하드코딩되어 나머지 파이프라인 리소스의 reference build와 어긋날 수 있었음. build는 이제 config에서 명시 |
| **유방암 BED fallback** (1461–1479행) | 제거 | 명백한 오류로 제거 | 전장 엑솜 target을 8개 유전자 약 0.4 Mb로 조용히 대체한 뒤 결과를 엑솜 coverage로 보고 |
| **여러 top-level `main "$@"`** (399, 1565, 2323행) | 제거 | 명백한 오류로 제거 | 각 블록이 자기 자신을 실행. 이제 파일 맨 끝에 정확히 하나 |
| **중간 `exit 0`** (1397행) | 제거 | 명백한 오류로 제거 | 이후 926줄(파일의 40%)이 **도달 불가능**. 게다가 그 앞에서 성공 메시지를 출력해 부분 실행이 완료처럼 보였음 |
| **고립 backtick** (2153행) | 제거 | 명백한 오류로 제거 | `bash -n`이 통과하지 못함. **파일 전체가 파싱되지 않아 어떤 줄도 실행될 수 없었음** |
| **`exit 2` on low depth** (1562행) | 제거 | 명백한 오류로 제거 | QC 관찰을 파이프라인 실패로 바꿈. 설정 가능한 warning으로 대체 |
| **개인 디렉터리 경로 제한** | 제거 | 명백한 오류로 제거 | `$HOME/sideprojects/` 전제. 다른 사용자·다른 서버에서 무조건 실패 |
| **trim 결정 모순** (375 vs 1063행) | 수정 | interface만 수정 | fastp를 실제로 실행하면서 기록에는 `trim_mode=none`으로 적었음. 이제 결정을 내리는 함수가 한 번만 기록 |
| **status·metrics·artifact·provenance** (1218–1396행 등) | step 생명주기 helper 전체 | interface만 수정 | TSV·`commands.sh`·버전·체크섬·metrics·manifest·provenance·marker를 전부 보존. artifact manifest만 절대 경로 대신 `file_id` + 상대 경로로 변경 |

### 24.5 runtime install을 제거한 이유

제거한 명령:

```bash
conda install -c bioconda fastp -y            # 371행
conda install -c bioconda mosdepth -y         # 1519행
git clone https://github.com/WGLab/InterVar.git   # 2213행
pip install -r requirements.txt --break-system-packages   # 2215행
python InterVar.py --download_db -d humandb/              # 2217행
```

| 문제 | 설명 |
|---|---|
| **재현성 파괴** | 설치되는 버전이 실행할 때마다 다를 수 있어, provenance 기록이 무의미해집니다 |
| **공유 환경 오염** | 분석 도중 서버 환경을 바꾸면 같은 서버를 쓰는 다른 사람에게 영향을 줍니다 |
| **보호 장치 무력화** | `--break-system-packages`는 시스템 패키지 관리자의 보호를 의도적으로 우회합니다 |
| **자원 소모** | `--download_db`는 run 하나가 수십 GB 다운로드를 유발합니다 |
| **build 모순** | 하드코딩된 `-b` 값은 나머지 파이프라인 리소스의 reference build와 충돌할 수 있습니다 |

**지식은 잃지 않았습니다.** 설치 절차는 [6.7](#67-실행-전-준비물)에 기록되어 있으며,
**사람이 한 번 수행하는 준비 작업**으로 위치가 바뀌었을 뿐입니다.

**제거하지 않은 것**: `command -v` 탐지, 버전 기록, conda 환경 이름 기록,
resource 존재 확인, resource 체크섬 기록. 이들은 설치가 아니라 확인입니다.

### 24.6 "누락처럼 보인 것"에 대한 기록

초기 감사에서 "Processing 코드가 통째로 누락되었다"는 BLOCKER 판정이 있었습니다.
확인 결과 **의도적으로 잘라 둔 것**이었고 원본은 온전히 존재했습니다.

원본과 당시 코드를 대조한 결과 **바이트 단위로 동일**했습니다.
따라서 이 사안은 "코드 손실"이 아니라 **"연결(merge) 문제"** 로 재분류되었고,
"보관 후 재작성"이라는 초기 권고는 철회되었습니다.

이 사례의 교훈: **누락처럼 보이는 것을 누락이라고 단정하기 전에 원본과 대조해야 합니다.**

### 24.7 통합 원칙

> **동작하는 분석 코드는 임의로 지우지 않는다. 인터페이스만 맞춘다.**

"내가 다시 짜면 더 깔끔하겠다"는 이유로 남의 코드를 바꾸지 않았습니다.
바꾼 것은 (1) 근거와 함께 확인된 오류, (2) 다른 단계와 연결하기 위한 인터페이스,
이 두 가지뿐입니다.

**제거한 항목은 전부 분석 로직이 아니라 구조·환경 관련 코드입니다.**
분석 결과를 만들어 내는 코드는 하나도 제거하지 않았습니다.

각자 독립적으로 작성된 코드를 **하나의 실행 흐름**으로 합치는 과정에서,
같은 일을 하는 구현이 둘 있으면 계약에 맞는 쪽을 기본으로 삼고
다른 쪽의 안전 로직을 합쳤습니다. 어느 쪽도 "더 못 쓴 코드"가 아니라,
**서로 다른 전제 위에서 작성된 코드**였습니다.

---

## 25. 옵션과 파라미터 선택 이유

앞 장들에 흩어져 있던 옵션 설명을 도구별로 한 번에 모읍니다.
**여기 있는 옵션은 전부 현재 코드에 실제로 존재합니다.**

### 25.1 도구별 전체 표

| 단계 | 도구 | Option | 현재 값/변수 | 의미 | 선택 이유 | 변경 주의 |
|---|---|---|---|---|---|---|
| 01 | FastQC | `--threads` | `min(fastqc_threads, threads)` | 병렬 처리 | FastQC는 스레드를 많이 줘도 이득이 적음 | 최소 1 보장 |
| 01 | FastQC | `--outdir` | `01_raw_qc/fastqc/<sample>.<lane>` | 출력 디렉터리 | **lane 전용 디렉터리**로 결과 섞임 방지 | — |
| 01 | MultiQC | `--force` | — | 기존 리포트 덮어쓰기 허용 | 재실행 시 중단되지 않게 | — |
| 01 | MultiQC | `--outdir` | `01_raw_qc/multiqc` | 출력 디렉터리 | — | — |
| 02 | fastp | `--detect_adapter_for_pe` | 사용 | paired-end adapter 자동 탐지 | adapter 서열 수동 지정 불필요 | 탐지 결과는 fastp 리포트로 확인 |
| 02 | fastp | `--qualified_quality_phred` | `20` | 양호 판정 품질 기준 | Phred 20 = 오류율 1% | **근거 미기록** (아래 25.6) |
| 02 | fastp | `--unqualified_percent_limit` | `40` | 저품질 염기 허용 비율(%) | 초과 시 read 폐기 | **근거 미기록** |
| 02 | fastp | `--length_required` | `50` | 최소 read 길이 | 짧으면 정렬 위치가 모호 | **근거 미기록** |
| 02 | fastp | `--thread` | config `threads` | 병렬 처리 | — | — |
| 02 | fastp | `--json` / `--html` | `02_preprocessing/fastp/` | 리포트 | 전후 read 수를 지표로 기록 | — |
| 03 | BWA-MEM | `-K` | `100000000` | 배치당 염기 수 고정 | 스레드 수와 무관하게 **동일한 BAM** 생성 → 재현성 | 메모리를 조금 더 사용 |
| 03 | BWA-MEM | `-Y` | — | hard-clip 대신 soft-clip | 잘린 서열을 BAM에 보존 | BAM 크기 소폭 증가 |
| 03 | BWA-MEM | `-t` | config `threads` | 병렬 스레드 | 서버 자원에 맞춤 | `-K` 덕분에 결과 불변 |
| 03 | BWA-MEM | `-R` | `@RG\tID:…\tSM:…\tLB:…\tPL:…\tPU:…` | read group | GATK 필수. `SM`이 VCF sample 이름 | samplesheet와 일치 필수 |
| 03 | samtools sort | `-@` | config `sort_threads` | 정렬 스레드 | — | — |
| 03 | samtools sort | `-m` | config `sort_mem` (`2G`) | **스레드당** 메모리 | 총량 = threads × 이 값 | 총량으로 착각하면 OOM |
| 03 | samtools sort | `-T` | `tmp/03_alignment/sort_<unit>` | 임시 파일 접두사 | run 전용 경로로 충돌 방지 | — |
| 03 | samtools sort | `-O bam -o … -` | — | BAM 출력, stdin 입력 | 중간 SAM 파일 없이 파이프 직결 | — |
| 03 | samtools merge | `-@` / `-f` / `-o` | threads / 덮어쓰기 / 출력 | lane BAM 합치기 | lane 2개 이상일 때만 | 1개면 하드 링크 |
| 03 | samtools index | `-@` | config `threads` | 인덱스 생성 | GATK가 인덱스를 요구 | — |
| 03 | samtools quickcheck | `-q` / `-v` | — | BAM 구조 확인 | 잘린 BAM 조기 탐지 | 내용 검증은 아님 |
| 03 | samtools flagstat / idxstats / stats | `-@` | config `threads` | 정렬 통계 | 지표 산출용 | 실패해도 step은 진행 |
| 04 | MarkDuplicates | `--REMOVE_DUPLICATES` | `false` | 표시만 하고 삭제 안 함 | 지운 데이터는 복구 불가. 하위 도구가 flag를 인식 | `true`면 원본 read 소실 |
| 04 | MarkDuplicates | `--CREATE_INDEX` | `false` | 인덱스 별도 생성 | 인덱스 실패를 독립 감지 | — |
| 04 | MarkDuplicates | `--READ_NAME_REGEX` | 조건부 `null` | optical duplicate 판정 | read 이름이 Illumina 좌표 형식이 아닐 때만 비활성화 | — |
| 04 | MarkDuplicates | `--TMP_DIR` | `tmp/04_processing` | 임시 파일 | 시스템 `/tmp` 부족 방지 | — |
| 04 | ValidateSamFile | `-MODE SUMMARY` | — | 오류 종류별 집계 | 전체 목록은 수백만 줄이 될 수 있음 | — |
| 04 | ValidateSamFile | `--java-options` | `-Xmx4g` | 힙 크기 | 검증은 상대적으로 가벼움 | 고정값 |
| 04 | samtools calmd | `-b` / `-@` | BAM 출력 / threads | NM·MD 재계산 | reference 기준으로 다시 계산 | **`ONLY_NM`일 때만 실행** |
| 04 | BaseRecalibrator | `--known-sites` | bundle 배열 전부 | 학습 제외 변이 | 진짜 변이를 오류로 학습하지 않게 | 배열이라 개수 제한 없음 |
| 04 | BaseRecalibrator | `-L` / `-ip` | 조건부 | 학습 영역 제한 | `bqsr_target_only=true`일 때만 | 데이터가 줄어 모델이 불안정할 수 있음 |
| 04 | BaseRecalibrator | `--tmp-dir` | run 전용 tmp | 임시 파일 | — | — |
| 04 | ApplyBQSR | `--bqsr-recal-file` | recal table | 학습된 모델 | — | — |
| 04 | ApplyBQSR | **`-L` 없음** | — | 전체 BAM에 적용 | **target 밖 read를 버리지 않기 위함** | `-L`을 추가하면 BAM이 부분집합이 됨 |
| 04 | ApplyBQSR | `--create-output-bam-index` | `false` | 인덱스 별도 생성 | 실패를 독립 감지 | — |
| 04 | AnalyzeCovariates | `-before` / `-after` / `-csv` / `-plots` | 진단 파일 | 보정 전후 비교 | `bqsr_diagnostics=true`일 때만. Rscript 필요 | 실패해도 warning |
| 04 | GATK 공통 | `--java-options` | `-Xmx<java_mem_gb>g -Djava.io.tmpdir=<tmp>` | 힙과 Java 임시 경로 | 시스템 tmp 부족 방지 | 최소 4 GB 강제 |
| 05 | mosdepth | `--threads` | config `threads` | 병렬 처리 | — | — |
| 05 | mosdepth | `--no-per-base` | — | 위치별 depth 파일 생성 안 함 | WES에서도 수 GB. 영역별 요약이면 충분 | **median을 계산할 수 없게 됨** |
| 05 | mosdepth | `--mapq` | config `mosdepth_mapq` (`20`) | 최소 mapping quality | 낮은 MAPQ read가 반복 영역 depth를 부풀리는 것 방지 | 낮추면 좋아 보이지만 신뢰도 하락 |
| 05 | mosdepth | `--by` | `target.nonoverlap.bed` | 영역별 집계 | 겹침 중복 계산 방지 | — |
| 05 | mosdepth | `--thresholds` | `1,10,20,30,50,100` | 각 depth 이상 비율 | 임상 WES에서 20×·30×가 흔한 기준선 | 바꾸면 지표 이름도 바뀜 |
| 06 | HaplotypeCaller | `-ERC GVCF` | — | gVCF 모드 | 변이 없음의 근거도 기록. joint calling 확장 대비 | 파일이 훨씬 커짐 |
| 06 | HaplotypeCaller | `-L` | target BED | 호출 영역 | WES는 target 밖이 거의 안 읽힘 | BED가 틀리면 결과가 통째로 틀림 |
| 06 | HaplotypeCaller | `-ip` | config `interval_padding` (`100`) | 경계 확장 bp | 경계 read와 indel 문맥 보존 | 크면 off-target 노이즈 |
| 06 | HaplotypeCaller | `--native-pair-hmm-threads` | config `pairhmm_threads` (`4`) | PairHMM 스레드 | 가장 무거운 연산 | 과하게 늘려도 이득 적음 |
| 06 | GenotypeGVCFs | `-V` | gVCF | 입력 | — | — |
| 06 | GenotypeGVCFs | `--dbsnp` | 조건부 | rsID 부여 | bundle이 선언했고 읽을 수 있을 때만 | 변이 판정 자체는 불변 |
| 06 | GenotypeGVCFs | `-L` / `-ip` | HaplotypeCaller와 동일 | 호출 영역 | 두 단계 영역이 다르면 결과 어긋남 | 반드시 동일 값 |
| 06 | bcftools view | `-h` / `-H` | 헤더만 / 헤더 제외 | 파싱 확인, 레코드 수 세기 | — | — |
| 06 | bcftools query | `-l` | — | sample 목록 | `SM` 대조 | — |
| 06 | bcftools norm | `-f <ref> -c e -Ou -o /dev/null` | — | **REF allele 검사 전용** | `-c e` = REF 불일치 시 error. 출력은 버림 | 불일치는 **build mismatch 신호** |
| 06 | bcftools stats | — | — | 변이 요약 통계 | Ti/Tv, SNP/indel 수 | 실패해도 warning |
| 06 | tabix | `-p vcf` | — | VCF 인덱스 생성 | GATK가 만들지 않았을 때의 fallback | — |
| 06 | tabix | `-l` | — | contig 목록 | 인덱스 읽기 가능 확인 | — |
| 08 | bcftools view | `-i "<expr>"` | preset 기반 표현식 | genotype 품질 필터 | argv 한 요소로 전달되어 셸이 재해석하지 않음 | **임계값 미검증** |
| 08 | bcftools view | `-Oz -o` | gzip VCF 출력 | — | — | — |
| 08 | bcftools index | `-f -t` | 강제, tabix 형식 | 인덱스 생성 | — | — |
| 10 | bcftools norm | `-m -any` | — | 다중 ALT를 각각 별도 줄로 분리 | DB 대조 전에 표기를 통일 | — |
| 10 | bcftools norm | `-f <ref>` | 조건부 | indel 왼쪽 정렬 | reference가 있을 때만 | — |
| 10 | bcftools annotate | `-a <clinvar>` | ClinVar VCF | 주석 원본 | 로컬 파일만 사용 | build 일치 필수 |
| 10 | bcftools annotate | `-c` | `ID,INFO/CLNSIG,INFO/CLNDN,INFO/CLNREVSTAT,INFO/CLNHGVS,INFO/GENEINFO` | 가져올 필드 | 임상 의미·질환·근거수준·표기·유전자 | — |
| 10 | bcftools query | `--allow-undef-tags -f '<format>'` | 15컬럼 | 변이 TSV 추출 | 주석이 없는 변이도 빈 값으로 출력 | — |
| 11 | InterVar.py | `-i --input_type VCF -o -b -t intervardb -d` | config 값 | ACMG 근거 산출 | build는 반드시 명시 | 자동 최종 판정 아님 |
| 11 | InterVar.py | `--table_annovar` / `--convert2annovar` / `--annotate_variation` | `./` 상대 경로 | ANNOVAR 헬퍼 | 서브셸에서 `cd` 후 실행 | 파이프라인 작업 디렉터리는 불변 |
| 00 | gzip | `-t` | 조건부 | FASTQ 전체 스트림 검사 | `verify_fastq_gzip=true`일 때만 | 전체 WES에서 수 분 |

### 25.2 재현성을 위한 선택

| 선택 | 이유 |
|---|---|
| `bwa mem -K 100000000` | 스레드 수가 달라도 **동일한 BAM** |
| `--tmp-dir` / `--TMP_DIR` / `-T`를 run 전용 경로로 | 시스템 tmp 부족과 run 간 충돌 방지 |
| `logs/commands.sh`에 전 명령 기록 | 손으로 재현 가능 |
| resource SHA-256 기록 | 파일 바꿔치기 탐지 |
| 도구 버전 기록 | 버전 차이로 인한 결과 차이 추적 |
| config snapshot 보존 | 어떤 설정으로 만든 결과인지 확정 |

### 25.3 데이터를 보존하기 위한 선택

| 선택 | 이유 |
|---|---|
| `MarkDuplicates --REMOVE_DUPLICATES false` | 지운 데이터는 복구 불가. flag로 충분 |
| `bwa mem -Y` (soft-clip) | 잘린 서열을 BAM에 남김 |
| `ApplyBQSR`에 `-L` 없음 | target 밖 read를 버리지 않음 |
| `trim_mode` 기본 `skip` | 근거 없는 데이터 변형 금지 |
| filtering 출력을 별도 파일로 | raw VCF를 덮어쓰지 않음 |
| 중간 markdup BAM 유지 | 문제 발생 단계 추적 |
| core raw VCF를 정규화하지 않음 | `GenotypeGVCFs`가 만든 그대로 보존 |

### 25.4 실패를 정확히 감지하기 위한 선택

| 선택 | 이유 |
|---|---|
| GATK `--CREATE_INDEX false` / `--create-output-bam-index false` | 인덱스 생성 실패를 독립적으로 감지 |
| `PIPESTATUS` 개별 확인 | 파이프 앞단 실패가 뒷단 성공에 가려지지 않게 |
| `.part` → 검증 → rename | 잘린 파일이 최종 이름을 갖지 못하게 |
| 인덱스를 `.part` 상태에서 생성 | 본체와 인덱스가 항상 짝을 이루게 |
| `set -Eeuo pipefail` | 조용한 실패 제거 |
| `next_step_ready` 게이트 | 종료 코드 0만으로 다음 단계로 넘어가지 않게 |
| ApplyBQSR record count 비교 | 품질 보정이 read를 잃지 않았는지 확인 |
| `bcftools norm -c e` | REF allele 불일치로 build mismatch 탐지 |
| 명령을 argv 배열로 실행 | config 값이 셸 문법으로 재해석되지 않게 |

### 25.5 품질 기준선

| 값 | 현재 값 | 근거 |
|---|---|---|
| `mosdepth --mapq` | `20` | 애매한 정렬이 depth를 부풀리지 않게 |
| `-ip` (interval padding) | `100` | 경계 read와 indel 문맥 보존 |
| `--thresholds` | `1,10,20,30,50,100` | 임상 WES에서 20×·30×가 흔한 기준선 |
| `low_coverage_depth` | `20` | **보고용 기준**. 실패 판정과 무관 |
| `coverage_min_mean_depth` | `0` | **비활성화가 기본.** 임의 기준으로 데이터를 버리지 않음 |
| `java_mem_gb` 하한 | `4` | 그 이하에서는 GATK가 사실상 동작하지 않음 |

### 25.6 선택 근거가 확인되지 않은 값

정직하게 적습니다.

> 현재 코드에서 값은 확인되지만,
> 이 값을 선택한 근거는 기존 자료에서 명확히 확인되지 않았습니다.
> Linux smoke test와 팀 합의를 거쳐 재검토가 필요합니다.

| 옵션 | 값 | 현재 사용 여부 |
|---|---|---|
| `fastp --qualified_quality_phred` | `20` | `trim_mode=skip`이 기본이라 **기본 실행에서 미사용** |
| `fastp --unqualified_percent_limit` | `40` | 동일 |
| `fastp --length_required` | `50` | 동일 |
| `filtering balanced` DP/GQ/AD | `5` / `10` / `3` | filtering이 기본 꺼짐이라 **기본 실행에서 미사용** |
| `filtering strict` DP/GQ/AD | `10` / `20` / `3` | 동일 |
| 디스크 추정 계수 | FASTQ 바이트 × 7 + 20 GB | preflight에서 **항상 사용됨**. 보수적 휴리스틱 |

### 25.7 자원 관련 값

| 값 | 기본값 | 주의 |
|---|---|---|
| `threads` | `4` | 공유 서버 기준 보수적 값. **논리 코어 수를 넘으면 preflight 실패** |
| `sort_threads` | `threads`와 동일 | — |
| `sort_mem` | `2G` | **스레드당.** 총량 = `sort_threads` × 이 값 |
| `java_mem_gb` | `8` | 최소 4 강제. 너무 작으면 GATK OOM |
| `min_available_ram_gb` | `8` | preflight 하한 |
| `fastqc_threads` | `2` | 실제로는 `threads`와 비교해 작은 값 사용 |
| `pairhmm_threads` | `4` | — |

> **총 메모리 계산 예시**
> `sort_threads: 4` + `sort_mem: "2G"` → samtools sort가 최대 약 8 GB.
> 여기에 `java_mem_gb: 16`이 더해지면, 두 단계가 동시에 돌지 않더라도
> 서버 RAM이 최소 16 GB 이상이어야 합니다.
> 실측값은 Linux smoke test에서 확인해야 합니다.

---

## 26. 결과 파일 읽는 방법

### 26.1 어디부터 보나

```
1. RUN_* marker              결과가 뭔가?
2. core_summary.json         핵심 지표 요약
3. final_validation.tsv      무엇이 pass/warn/fail 인가
4. logs/stage_status.tsv     각 단계가 어떻게 끝났나
5. 05_coverage_qc/           결과를 얼마나 믿을 수 있나
6. 06_variant_calling/       변이 목록
7. methods.md                무엇을 어떻게 했나
```

### 26.2 파일별 안내

아래 `$RUN`은 `<output_root>/<run_id>`입니다.

#### 상태와 로그

| 파일 | 의미 | 정상일 때 확인할 것 | 오류가 있을 때 볼 것 | 다음 단계에서의 쓰임 |
|---|---|---|---|---|
| `RUN_*` marker | run의 최종 상태 | `RUN_COMPLETED` 또는 `RUN_COMPLETED_WITH_WARNINGS` | `RUN_FAILED`면 상세 줄에 실패 step이 적혀 있음 | 배치 처리에서 결과 분류 |
| `status/run_status.json` | run 전체 상태 | `status`, `completed_steps` 길이 | `failed_steps` 배열 | 백엔드가 진행 상황 조회 |
| `status/steps/<step>.json` | step별 기계 계약 | `status`, `next_step_ready: true` | `failures[]`, `warnings[]` | resume 판정의 근거 |
| `logs/pipeline.log` | 전체 실행 로그 | 마지막의 `RUN …` 요약 블록 | `[WARN]`, `[ERROR]` 줄 | 사람이 흐름 파악 |
| `logs/stage_status.tsv` | 단계 상태 이력 | 모든 step이 `COMPLETED`/`WARNING` | 첫 `FAILED` 행 | 어느 단계에서 멈췄는지 |
| `logs/execution_trace.tsv` | 단계별 소요 시간 | 예상 범위 안인가 | 비정상적으로 짧으면 조기 종료 의심 | 자원 계획 |
| `logs/commands.sh` | 실행된 모든 명령 | 옵션이 의도대로인가 | 실패한 명령을 손으로 재현 | 재현·검토 |
| `logs/<step>.<label>.stderr.log` | 도구 원본 stderr | 대개 비어 있음 | **도구가 정확히 뭐라고 했는지** | 원인 진단의 1순위 |
| `logs/software_versions.txt` | 도구 버전 | 기대한 버전인가 | 버전 차이로 인한 동작 차이 | 재현성 대조 |

#### 입력 검증

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `00_input_validation/manifest.tsv` | 정규화된 8컬럼 lane 목록 | FASTQ 경로가 의도한 파일인가 |
| `config/normalized_manifest.json` | sample/lane 구조 | `lane_count`가 맞는가 |
| `00_input_validation/samplesheet_validation.txt` | samplesheet 검증 결과 | `[OK] Validated N lane row(s)` |
| `00_input_validation/resource_validation.txt` | resource 검증 결과 | `[NOTE] reference contigs:`, `target BED:` 줄 |
| `logs/resource_sha256.txt` | resource 해시 | 다른 run과 같은 resource를 썼는지 대조 |

#### QC

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `01_raw_qc/multiqc/multiqc_report.html` | 전체 QC 한눈에 | lane 간 편차 |
| `01_raw_qc/fastqc/<sample>.<lane>/*.html` | lane별 상세 | 위치별 품질, adapter 함량 |
| `02_preprocessing/preprocessing_decision.json` | trimming 결정 기록 | `decision`이 의도와 맞는가 |
| `02_preprocessing/fastp/*.fastp.html` | trimming 전후 (force일 때만) | 몇 %가 버려졌는가 |

#### 정렬과 processing

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `03_alignment/lane_bam/*.sorted.bam` | lane별 정렬 BAM | 중간 산출물 |
| `03_alignment/sample_bam/<sample>.sorted.bam` (+`.bai`) | merge된 sample BAM | 다음 단계 입력 |
| `03_alignment/sample_bam/<sample>.flagstat.txt` | 정렬 통계 | **mapped %, properly paired %** |
| `04_processing/<sample>.markdup.metrics.txt` | Picard 중복 지표 | `PERCENT_DUPLICATION` |
| `04_processing/<sample>.recal_data.table` | BQSR 모델 | `RecalTable0` 존재 |
| `04_processing/<sample>.analysis_ready.bam` (+`.bam.bai`) | **변이 호출 입력 BAM** | 존재 자체가 검증 통과의 증거 |
| `04_processing/qc/*.validation.txt` | ValidateSamFile 결과 | `No errors found` |
| `04_processing/qc/*.analysis_ready.flagstat.txt` | 최종 정렬 통계 | markdup 시점과 총 레코드 수가 같은가 |

**duplicate 비율 읽는 법**: WES에서 10~20%는 흔합니다.
40%를 넘으면 라이브러리 복잡도가 낮았을 가능성이 있습니다.
다만 **capture kit과 depth에 따라 달라지므로** 절대 기준으로 보면 안 됩니다.

#### Coverage QC 결과

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `05_coverage_qc/coverage_metrics.json` | 핵심 지표 | `mean_target_depth`, `target_bases_ge_20X_pct`, `zero_coverage_bases_pct`(염기 단위) |
| `05_coverage_qc/<sample>.mosdepth.mosdepth.summary.txt` | mosdepth 요약표 | contig별 요약 |
| `05_coverage_qc/<sample>.mosdepth.regions.bed.gz` | **영역별 평균 depth** | 관심 유전자 영역을 직접 조회 |
| `05_coverage_qc/<sample>.mosdepth.thresholds.bed.gz` | 영역별 threshold 도달 염기 수 | breadth 상세 |
| `05_coverage_qc/low_mean_depth_intervals.bed` | 평균 depth 기준 미만 구간 | **관심 유전자가 여기 있는지** |
| `05_coverage_qc/target.nonoverlap.bed` | 겹침 제거 target | 집계 기준 확인 |

> **가장 중요한 해석**: 관심 유전자가 low-coverage 목록에 있다면,
> 그 유전자에서 "변이 없음"은 **"변이가 없다"가 아니라 "확인할 수 없었다"** 입니다.

#### 변이

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `06_variant_calling/<sample>.g.vcf.gz` (+`.tbi`) | gVCF | 나중에 joint calling 할 때의 입력 |
| `06_variant_calling/<sample>.raw.vcf.gz` (+`.tbi`) | **핵심 산출물** | 변이 목록 |
| `06_variant_calling/<sample>.raw.bcftools.stats.txt` | 요약 통계 | 총 변이 수, SNP/indel 비, **Ti/Tv** |
| `06_variant_calling/variant_calling_output.json` | 계약 문서 | `raw_variant_records`, `filtering_applied: false` |

```bash
# 전체 변이 수
bcftools view -H $RUN/06_variant_calling/*.raw.vcf.gz | wc -l

# 요약 통계
less $RUN/06_variant_calling/*.raw.bcftools.stats.txt

# 특정 영역
# 좌표와 contig 이름은 사용한 GRCh38 bundle의 contig_style에 맞춰 적으세요.
# chr 접두사를 쓰는 bundle이면 chr7:..., 쓰지 않으면 7:... 형식입니다.
bcftools view $RUN/06_variant_calling/*.raw.vcf.gz <contig>:<start>-<end>

# sample 이름 확인
bcftools query -l $RUN/06_variant_calling/*.raw.vcf.gz
```

**Ti/Tv 비율**: transition/transversion 비율입니다.
WES에서 보통 2.8~3.3 범위입니다. 크게 벗어나면 위양성이 많다는 신호일 수 있습니다.

#### optional 단계 결과

| 파일 | 의미 |
|---|---|
| `optional/filtering/<sample>.filtered.vcf.gz` | genotype 품질 필터 결과 |
| `optional/annotation/<sample>.normalized.vcf.gz` | 정규화된 VCF |
| `optional/annotation/<sample>.clinvar.vcf.gz` | ClinVar 주석 VCF |
| `optional/annotation/<sample>.variants.tsv` | 사람이 보기 쉬운 변이 표 |
| `optional/intervar/<sample>_intervar.<build>_multianno.txt.intervar` | InterVar 결과표 |
| `optional/intervar/<sample>_intervar_summary.json` | 집계 + **명시적 한계 기술** |

#### 최종 정리

| 파일 | 의미 | 볼 것 |
|---|---|---|
| `final_validation.tsv` | 전체 pass/warn/fail 표 | `FAIL` 행이 없는가 |
| `artifact_manifest.json` | 모든 산출물 목록 | `file_id`, `relative_path`, `sha256` |
| `provenance.json` | 재현 정보 | 설정·버전·체크섬 |
| `core_summary.json` | 기계용 요약 | `core_complete: true` |
| `methods.md` | 사람용 방법 기술 | 논문 Methods 초안 |

### 26.3 VCF 한 줄 읽는 법

아래는 **컬럼 구조를 보여 주기 위한 예시**입니다.
contig 이름과 좌표는 실제로 사용한 GRCh38 bundle에 따라 달라지므로
이 숫자를 특정 변이의 GRCh38 좌표로 인용하지 마세요.

```
#CHROM POS        ID          REF ALT QUAL   FILTER INFO        FORMAT      HG002
chr7   <POSITION> rs113993960 CTT C   1250.5 PASS   AC=1;AF=0.5 GT:AD:DP:GQ 0/1:15,18:33:99
```

| 컬럼 | 의미 |
|---|---|
| `CHROM` | 염색체 이름. bundle의 `contig_style`에 따라 `chr7`(chr/ucsc) 또는 `7`(plain/nochr/ensembl) |
| `POS` | 그 염색체 위의 위치 (1부터 시작) |
| `ID` | 변이 식별자. dbSNP를 넣었으면 `rs…`, 없으면 `.` |
| `REF` | reference의 서열 |
| `ALT` | 이 sample에서 발견된 다른 서열. 여러 개면 쉼표로 구분 |
| `QUAL` | 이 자리에 변이가 존재한다는 확신도. 높을수록 확실 |
| `FILTER` | `PASS` = 문제 없음, `.` = 판정하지 않음, 그 외 = 걸러진 이유 |
| `INFO` | 이 자리 전체에 대한 정보 (`AC`=ALT 개수, `AF`=빈도 등) |
| `FORMAT` | 아래 sample 컬럼 값들의 **순서 정의** |
| sample genotype | `FORMAT` 순서대로의 값 |

위 예시의 sample 컬럼 `0/1:15,18:33:99`:

| 항목 | 값 | 의미 |
|---|---|---|
| `GT` | `0/1` | genotype. `0`=REF, `1`=첫 ALT. 한쪽만 변이 → **heterozygous** |
| `AD` | `15,18` | REF를 지지하는 read 15개, ALT를 지지하는 read 18개 |
| `DP` | `33` | 이 위치의 총 depth |
| `GQ` | `99` | genotype 판정의 신뢰도 (99가 최대) |

읽으면: 33개 read 중 15개가 REF, 18개가 ALT →
**heterozygous 변이로 판정, 신뢰도 최상.**

genotype 표기:

| `GT` | 의미 |
|---|---|
| `0/0` | 양쪽 다 reference (변이 없음). raw VCF에는 보통 나타나지 않음 |
| `0/1` | 한쪽만 변이 (heterozygous) |
| `1/1` | 양쪽 다 변이 (homozygous alternate) |
| `1/2` | 양쪽이 서로 다른 변이 |
| `./.` | 판정할 수 없음 (대개 depth 부족) |

### 26.4 재현·추적용 파일 모음

| 파일 | 용도 |
|---|---|
| `logs/commands.sh` | 그대로 다시 실행하거나 명령을 검토 |
| `logs/software_versions.txt` | 도구 버전 대조 |
| `logs/resource_sha256.txt` | resource 동일성 확인 |
| `config/run_config.snapshot.json` | 설정 전체 + identity 해시 |
| `artifact_manifest.json` | 산출물 목록·크기·해시 |
| `provenance.json` | 위 전부를 하나로 묶은 문서 |
| `methods.md` | 논문 Methods 초안 |

---

## 27. 오류가 났을 때 확인 순서

### 27.1 순서대로 확인하기

```
 1. RUN_* marker            어떤 결과인가?
 2. status/run_status.json  run 상태와 failed_steps
 3. failed step 찾기        logs/stage_status.tsv의 첫 FAILED 행
 4. 그 step의 stderr        logs/<step>.<label>.stderr.log   ← 가장 중요
 5. logs/pipeline.log       실패 전후 맥락
 6. logs/commands.sh        실제로 어떤 명령이 실행됐나
 7. 입력 경로 확인          manifest.tsv의 FASTQ 경로
 8. resource 경로 확인      config/run_config.snapshot.json
 9. 도구 버전               logs/software_versions.txt
10. 디스크 / RAM / tmp      df -h, free -g, run 디렉터리의 tmp/ 크기
11. artifact 검증 결과      status/steps/<step>.json의 failures[]
12. resume 가능 여부        config가 그대로면 --resume, 아니면 새 run_id
```

**4번이 가장 중요합니다.** 도구 자신의 메시지가 가장 정확합니다.

### 27.2 증상별 표

| 증상 | 가능한 원인 | 먼저 볼 파일 | 해결 방향 |
|---|---|---|---|
| `Required command not found in PATH: X` | 도구 미설치 또는 환경 미활성화 | `logs/software_versions.txt` | 설치하거나 conda 환경 활성화. **파이프라인은 설치하지 않습니다** |
| `cannot read JSON …` / `Refusing to publish invalid JSON` | config JSON 문법 오류 | config 파일 | `python -m json.tool cfg.json`으로 검사 |
| `is not gzip-compressed` | FASTQ가 압축되지 않았거나 손상 | `00_input_validation/samplesheet_validation.txt` | 원본 다시 받기 |
| `gzip integrity test failed (truncated or corrupt)` | FASTQ가 잘림 | 동일 | 원본 다시 받기 |
| `fastq_2 is empty (paired-end input is required)` | R2 컬럼 누락 | samplesheet | R2 경로 추가 |
| `fastq_1 and fastq_2 are the same file` | R1/R2에 같은 파일 지정 | samplesheet | 경로 수정 |
| `FASTQ re-used` | 같은 FASTQ가 두 행에 등장 | samplesheet | 중복 행 제거 |
| `reference FASTA index (.fai) missing` | reference 준비 미완 | `resource_validation.txt` | `samtools faidx <ref>` |
| `reference sequence dictionary (.dict) missing` | 동일 | 동일 | `gatk CreateSequenceDictionary -R <ref>` |
| `BWA index (.bwt) missing` | 동일 | 동일 | `bwa index <ref>` (WES reference는 수십 분) |
| `reference .fai and .dict disagree` | 서로 다른 시점에 만든 인덱스 | 동일 | 인덱스를 모두 다시 생성 |
| `contig_style='plain' declares no 'chr' prefix but the reference uses 'chr'` | bundle 메타데이터와 실제 reference 불일치 | config `resource_bundle` | `contig_style`을 고치거나(이 경우 `chr`) 맞는 reference 지정 |
| `contig_style='chr' declares a 'chr' prefix but the reference does not use it` | 위와 반대 방향의 불일치 | 동일 | `contig_style`을 `plain`으로 고치거나 맞는 reference 지정 |
| `resource_bundle.assembly is required` | `assembly` 미선언·`null`·공백 | config `resource_bundle` | 이 bundle의 assembly 이름을 적으세요 (권장 profile은 `GRCh38`). **특정 값으로 제한되지 않습니다** |
| `resource_bundle.assembly is still a template placeholder` | `TODO_...` 값을 그대로 둠 | 동일 | 실제 assembly 이름으로 교체 |
| `resource_bundle.contig_style is required` | `contig_style` 미선언·`null`·공백 | 동일 | `.fai` 첫 열을 확인하고 `chr` 또는 `plain` 선언 |
| `resource_bundle.contig_style is still a template placeholder` | `TODO_...` 값을 그대로 둠 | 동일 | 동일 |
| `resource_bundle.contig_style must be one of: plain nochr ensembl chr ucsc` | 오타이거나 **assembly/build 이름을 contig_style에 적음** (`GRCh38`, `hg38` 등) | 동일 | assembly는 `assembly` key에, 이름 표기 방식은 `contig_style` key에 |
| `contig_style='…' is not a recognised chromosome naming convention` | 위와 같은 값이 preflight까지 도달한 경우 | `resource_validation.txt` | 동일 |
| `dbsnp_vcf index missing (.tbi or .csi)` | 선언한 dbSNP에 인덱스 없음 | `resource_validation.txt` | `tabix -p vcf <file>` |
| `dbsnp_vcf contigs absent from the reference` | dbSNP의 build가 다름 | 동일 | 같은 build의 dbSNP 사용, 또는 선언 자체를 제거 |
| `… declares contig lengths that differ from the reference` | known-sites/dbSNP header의 contig 길이가 reference `.fai`와 다름 | 동일 | **다른 build입니다.** 같은 build의 파일로 교체 |
| `BED line N: contig absent from reference` | BED와 reference의 build 불일치 | `resource_validation.txt` | 같은 build의 BED 사용 |
| `BED line N: interval out of range` | 동일 | 동일 | 동일 |
| `target BED contigs absent from the BAM header` | BED와 정렬 reference 불일치 | `05_coverage_qc/target_bed_check.txt` | build 통일 후 정렬부터 다시 |
| `known-sites contigs absent from the reference` | known-sites의 build가 다름 | `resource_validation.txt` | 같은 build의 known-sites 사용 |
| `known_sites index missing (.tbi or .csi)` | 인덱스 미생성 | 동일 | `tabix -p vcf <file>` |
| `known_sites is empty; BQSR is a core step` | `known_sites` 배열이 빔 | config | 최소 1개 지정. **BQSR은 선택이 아님** |
| `bwa exit=N, samtools sort exit=M` | BWA 파이프 실패 | `logs/03_alignment.bwa_*.stderr.log` | BWA index 확인, 메모리 확인, FASTQ 손상 확인 |
| samtools sort 실패 / `No space left` | 정렬 임시 파일용 디스크 부족 | `df -h`, run의 `tmp/` | 여유 확보, `sort_threads`×`sort_mem` 축소 |
| `ValidateSamFile reported error types that NM/MD repair cannot fix` | 실제 BAM 문제 | `04_processing/qc/*.validation.txt` | 리포트의 오류 종류 확인. 정렬부터 다시 |
| `Could not classify the ValidateSamFile output` | 리포트를 만들지 못했거나 형식 미인식 | 동일 + `logs/04_processing.validate_markdup.stderr.log` | **의도적 정지**입니다. 조용한 복구를 하지 않습니다 |
| `samtools calmd exited with code N` | calmd 실패 | `logs/04_processing.calmd.stderr.log` | reference 일치 여부, 디스크 확인 |
| `BaseRecalibrator output does not contain RecalTable0` | 학습 데이터 부족 또는 known-sites 문제 | `logs/04_processing.base_recalibrator.stderr.log` | known-sites build 확인 |
| `record count changed across ApplyBQSR` | 보정 중 read 손실 | `04_processing/qc/*.flagstat.txt` | **결과를 쓰지 마세요.** 원인 조사 필요 |
| `Java heap space` / GATK OOM | `java_mem_gb` 부족 | 해당 stderr 로그 | 값을 늘리되 서버 RAM 한도 안에서 |
| mosdepth 실패 | BAM 인덱스 없음, BED 문제 | `logs/05_coverage_qc.mosdepth.stderr.log` | BAM 인덱스와 BED contig 확인 |
| `HaplotypeCaller produced no gVCF` | 도구 실패 또는 target 영역에 read 없음 | 해당 stderr 로그 | target BED와 정렬 결과 확인 |
| `the produced gVCF cannot be parsed` / 인덱스 없음 | 도구가 중간에 죽음 | 해당 stderr 로그 | 디스크·메모리 확인 후 재실행 |
| `expected exactly one sample column named 'X'` | BAM `SM`과 sample 이름 불일치 | `03_alignment` 검사 결과 | 정렬부터 다시. **손으로 만든 BAM을 넣지 마세요** |
| `the raw VCF contains no variant records` | target 영역에 변이가 하나도 없음 | coverage 지표 | BED·정렬·depth 확인. subset 입력에서는 정상일 수 있음 |
| `REF allele mismatch against the … reference` | **build mismatch** | `logs/06_variant_calling.ref_allele_check.log` | **반드시 원인을 찾으세요.** reference·BED·known-sites의 build 통일 |
| `RESUME REFUSED` | config 또는 resource 파일이 바뀜 | 출력된 differences 목록 | 설정을 되돌리거나 새 `run_id` |
| `The existing run has no recorded configuration identity` | snapshot에 identity가 없음 | `config/run_config.snapshot.json` | 새 `run_id`로 시작 |
| `Run directory already exists` | 같은 `run_id` 재사용 | — | 새 `run_id` 또는 `--resume`. **`--check-only`가 남긴 디렉터리는 실제 실행을 막지 않습니다** |
| `This run is already locked` | 다른 프로세스가 실행 중이거나 stale lock | `.run.lock/owner` | pid·host 확인. **확실할 때만** `.run.lock` 삭제 |
| stale lock 의심 (pid 없음) | SIGKILL/OOM으로 죽은 run | `.run.lock/owner` | `ps`로 확인 후 사람이 직접 `rm -rf .run.lock` |
| `--from-step X cannot start: its input from Y is not valid` | upstream artifact 없음/손상 | 메시지의 Reason | `Y` 또는 그 이전부터 재실행 |
| `--from-step X comes after --to-step Y` | 범위가 비었음 | — | 순서 수정 |
| `Unknown step id: X` | step ID 오타 | `--help`의 목록 | 정확한 ID 사용 |
| `supports exactly one biological sample per run` | samplesheet에 sample이 2개 이상 | samplesheet | run을 나누기 |
| `threads=N exceeds logical cores=M` | `threads` 과다 | `nproc` | `threads`를 줄이기 |
| `available RAM … is below the configured minimum` | RAM 부족 | `free -g` | 다른 작업 종료 또는 `min_available_ram_gb` 조정 |
| `need about N GB, available M GB` | 디스크 부족 | `df -h` | 여유 확보. FASTQ의 5~10배 필요 |
| optional step 실패 | 외부 리소스 문제 | `optional/` + 해당 stderr | **raw VCF는 정상입니다.** `RUN_COMPLETED_WITH_WARNINGS`가 정상 결과 |
| `RUN_COMPLETED_WITH_WARNINGS` | warning이 있거나 optional이 실패함 | `final_validation.tsv`의 `WARN` 행 | **실패가 아닙니다.** warning 내용을 확인하고 판단 |
| MultiQC 관련 warning | MultiQC 미설치/실패 | — | **무시해도 됩니다.** 분석 결과에 영향 없음 |
| `DBSNP_NOT_CONFIGURED` | bundle에 dbSNP 미선언 | — | rsID만 없습니다. 변이 자체는 동일 |
| `CLINVAR_INCOMPATIBLE` | ClinVar가 reference와 구조적으로 불일치 (index·header·contig·길이·명명 규칙 중 하나) | warning 메시지의 상세 사유 | ClinVar를 같은 build로 교체. **raw VCF는 정상입니다** |
| `Optional InterVar step configuration problem … expects intervar.build='…'` | assembly와 `intervar.build` 불일치 | config `intervar` | 메시지가 알려 주는 기대값으로 수정. **core 결과는 무사합니다** |
| `Optional InterVar step configuration problem … has no InterVar/ANNOVAR build mapping` | 매핑표에 없는 assembly | `main.sh`의 `INTERVAR_BUILD_FOR_ASSEMBLY` | 매핑 한 줄 추가, 또는 `optional_steps.intervar`를 끄기 |
| `VEP_NOT_WIRED` | VEP 캐시는 있으나 호출 미구현 | — | 현재 알려진 한계입니다 |
| `AUTOMATED_EVIDENCE_ONLY` | InterVar 결과의 성격 안내 | — | **항상 나옵니다.** 수동 검토 필요를 알리는 것 |

### 27.3 특히 조심할 것

> [!CAUTION]
> **에러가 안 났다고 결과가 맞는 것은 아닙니다.**
>
> build mismatch, 잘못된 target BED, ClinVar build 불일치는
> **경고 없이 조용히 틀린 답**을 만듭니다.
>
> - preflight 검증을 건너뛰지 마세요
> - `bcftools norm -c e` 실패가 나오면 반드시 원인을 찾으세요
> - `RUN_COMPLETED`가 나왔어도 `final_validation.tsv`의 `WARN` 행을 읽으세요
> - coverage가 0에 가까운 영역이 많다면 BED와 reference의 build를 의심하세요

### 27.4 도움을 요청할 때 첨부할 것

1. `logs/pipeline.log`의 마지막 100줄
2. `logs/stage_status.tsv` 전체
3. 실패한 step의 `logs/<step>.<label>.stderr.log`
4. `status/steps/<실패한 step>.json`
5. `config/run_config.snapshot.json`
6. `logs/software_versions.txt`

---

## 28. 현재 한계

**한계와 코드 버그를 구분합니다.**

- **한계** = 코드가 의도대로 동작하지만 아직 확인되지 않았거나, 의도적으로 범위 밖인 것
- **버그** = 코드가 의도와 다르게 동작하는 것

아래는 전부 **한계**입니다. 현재 알려진 코드 버그는 없습니다
(BLOCKER 0건, HIGH 0건). 다만 "코드에 결함이 발견되지 않았다"와
"실행이 성공한다"는 다른 명제입니다.

### 28.1 실행 검증이 되지 않은 항목

검증 단계별 현재 위치입니다.

| 단계 | 상태 | 무엇을 확인했는가 |
|---|---|---|
| **static validation** | **완료** | `bash -n`, `--help`, 코드↔문서 정합성 |
| **resource validation** (`--check-only`) | **미완료** | 실제 config·resource가 없어 수행 불가 |
| **execution validation** | **미완료** | subset/full WES 실행 없음 |

> [!WARNING]
> static validation은 **문법과 문서 정합성만** 말해 줍니다.
> 특정 bundle이 실제로 동작하는지에 대해서는 **아무것도 증명하지 않습니다.**

| 항목 | 상태 | 왜 중요한가 |
|---|---|---|
| **GRCh38 resource bundle 확정** | 미확정 | 권장 profile은 GRCh38이지만, 어떤 GRCh38 배포본(primary assembly / analysis set / ALT·decoy 포함 여부)과 어떤 target BED·known-sites·dbSNP·ClinVar·truth set을 쓸지 아직 정해지지 않았습니다. 7장 config 예시의 경로가 `TODO_GRCH38_*` placeholder인 이유입니다 |
| **GRCh38 `contig_style`** | 미확정 | 실제 FASTA의 `.fai`를 확인하기 전에는 `chr`인지 `plain`인지 단정할 수 없습니다. 7장 예시의 `"chr"`은 **예시 값이며 확정 값이 아닙니다** |
| **GRCh38 profile `--check-only`** | 미완료 | 위 두 항목이 정해지기 전에는 수행할 수 없습니다. **따라서 "GRCh38 profile이 검증되었다"고 말할 수 없습니다** |
| **build provenance 확인 수단** | 구조 검사까지만 구현 | preflight는 contig 이름·길이·좌표 범위만 확인합니다. 같은 release에서 왔는지는 **사람이 보증**해야 합니다 ([4.4](#44-build가-안-맞으면-왜-위험한가)) |
| **GRCh38 외 assembly 실사용** | 미검증 | 엔진은 assembly를 제한하지 않지만, GRCh38 외의 bundle로 실행해 본 적은 없습니다. InterVar를 쓰려면 매핑표 추가도 필요합니다 |
| **Linux 서버 실제 실행** | 미완료 | 실제 도구를 사용한 실행이 한 번도 없었습니다 |
| **subset smoke test** | 미완료 | 배선이 실제로 이어지는지 확인되지 않았습니다 |
| **full WES 실행** | 미완료 | 완주 여부, 소요 시간, 자원 사용량이 미확정입니다 |
| **optional 단계 실제 실행** | 미완료 | filtering·annotation·InterVar가 실제 리소스와 동작한 적 없습니다 |
| **실제 도구 버전 조합** | 미확정 | 어떤 GATK/samtools/BWA 버전 조합으로 검증할지 정해지지 않았습니다 |
| **tool version constraint** | 미확정 | 최소 지원 버전을 코드가 확인하지 않습니다. 버전을 기록만 합니다 |
| **자원 모델** | 실측 필요 | 디스크 추정식(FASTQ × 7 + 20 GB)과 메모리 기본값이 실제와 맞는지 확인되지 않았습니다 |

### 28.2 `.part` 인덱스 파일명 가정

> [!WARNING]
> analysis-ready BAM, gVCF, raw VCF는 `.part` 이름 상태에서 인덱스를 만들고
> **본체와 인덱스를 함께** rename합니다.
>
> 이때 코드는 다음을 가정합니다.
>
> - `samtools index <파일>.part.bam` → `<파일>.part.bam.bai`
> - GATK/`tabix` → `<파일>.part.vcf.gz.tbi`
>
> 이 가정이 실제 도구 버전에서도 성립하는지는 **정적 검토로 확인할 수 없습니다.**
> smoke test에서 `mv` 대상 파일이 실제로 존재하는지 반드시 확인해야 합니다.

### 28.3 `--check-only`의 부작용

`--check-only`는 완전한 무부작용 dry-run이 아닙니다.
run 디렉터리, lock, config snapshot, status JSON, `pipeline.log`를 만듭니다.
분석 도구는 실행하지 않고 `RUN_*` marker도 남기지 않으며,
이후 같은 `run_id`로 `--resume` 없이 실제 실행이 가능합니다.
자세한 내용은 [6.3](#63---check-only의-실제-동작)에 있습니다.

### 28.4 resume 관련 한계

| 한계 | 내용 |
|---|---|
| **FASTQ size+mtime identity** | 기본 설정에서 FASTQ 내용 변경을 완벽히 탐지하지 못합니다. 크기와 수정시각이 같으면 동일하다고 판정합니다. `resume_strict_checksums: true`로 강화할 수 있지만 느려집니다 |
| **optional subconfig identity** | `filtering.*`, `intervar.*`, `optional_steps.*`가 identity 해시에 포함되지 않습니다. filtering 기준만 바꾸고 `--resume` 하면 기존 결과가 재사용될 수 있습니다 |
| **optional artifact validator** | optional step의 재사용 검증이 **파일 존재 확인 수준**이며, core처럼 VCF 파싱·인덱스·sample 대조를 하지 않습니다 |
| **`verify_fastq_gzip`이 identity에 미포함** | 이 설정은 `load_config`가 아니라 검증 함수가 직접 읽으므로 snapshot에 들어가지 않습니다 |

세 번째까지 모두 **core raw VCF에는 영향이 없습니다.**

### 28.5 lock과 취소의 한계

| 한계 | 내용 |
|---|---|
| **SIGKILL은 처리할 수 없음** | `kill -9`, OOM killer, 노드 장애로 죽으면 lock 디렉터리가 남고 마지막 step은 상태 문서 없이 남습니다. 프로세스가 자기 죽음을 기록할 수 없기 때문입니다 |
| **stale lock 수동 처리** | lock을 자동으로 지우지 않습니다. pid는 재사용될 수 있고 다른 호스트의 lock은 확인할 수 없기 때문입니다. **사람이 확인하고 지워야 합니다** |
| **취소는 직접 자식까지만** | `pkill -TERM -P $$`는 부모에서 분리된 손자 프로세스에 닿지 않습니다. 긴 GATK 단계를 취소했다면 `ps`로 확인하세요 |
| **로그 마지막 줄 유실 가능** | `tee` 프로세스 치환을 쓰므로 갑작스러운 종료 시 마지막 몇 줄이 유실될 수 있습니다. 믿을 수 있는 기록은 상태 JSON과 marker입니다 |

### 28.6 분석 범위의 한계

| 한계 | 내용 |
|---|---|
| **한 run에 sample 하나** | 현재 검증 profile. 구조적 제약이 아니라 범위 선언입니다. 여러 sample은 `GenomicsDBImport` + cohort `GenotypeGVCFs` **추가**로 지원 가능 |
| **benchmark 미구현** | `truth_vcf`/`truth_bed` config key만 있고 비교 로직이 없습니다. 정확도를 측정하는 단계가 존재하지 않습니다 |
| **자동 최종 ACMG 판정은 범위 밖** | InterVar 출력은 **자동 근거**이며 최종 임상 판정이 아닙니다 |
| **GATK site-level hard filtering 미구현** | `QD`, `FS`, `MQ`, `SOR` 등을 이용한 site 수준 필터가 없습니다 |
| **MAF 필터링 미구현** | 인구집단 빈도 필터가 없습니다. 이전에도 없었습니다 |
| **offline VEP 미배선** | 캐시와 실행 파일이 있어도 호출되지 않고 경고만 남깁니다 |
| **PanelApp / BRCA Exchange / REVEL / SpliceAI 미구현** | 질환 특화·예측 점수 기능. 흉내 낸 구현도 만들지 않았습니다 |
| **somatic, CNV, SV, fusion, RNA-seq** | 범위 밖 |

### 28.7 benchmark를 만들지 않은 이유

benchmark step(`09_benchmark` 같은)은 **자리표시자조차 만들지 않았습니다.**

나중에 추가하려면 다음이 필요합니다.

- GIAB truth VCF와 confident-region BED
- 둘 다 callset의 reference build와 일치해야 함
  (그렇지 않으면 파이프라인의 contig/assembly 검사를 중복 구현해야 함)
- 어떤 GIAB 릴리스를 쓸지에 대한 결정
- SNV와 indel의 분리 보고
- **HG002 같은 benchmark 검체에만 적용된다**는 이해
  (임의의 사용자 검체에는 정답이 없습니다)

truth set과 build 호환성 검사가 없는 상태에서 benchmark를 만들면
**의미를 방어할 수 없는 숫자**가 나오므로 만들지 않았습니다.

### 28.8 코드에 존재하지만 현재 호출되지 않는 것

| 항목 | 내용 |
|---|---|
| `atomic_write_json()` | 정의만 존재. JSON 작성은 각 Python heredoc이 직접 수행 |
| `require_command()` | 정의만 존재. 도구 확인은 `have_command`로 수행 |
| `skip_step()` | 정의만 존재. **어떤 step도 `skipped` 상태를 기록하지 않음** |
| `bgzip` | 필수 도구 목록에 있으나 직접 호출되지 않음 |
| `truth_vcf` / `truth_bed` | 읽고 snapshot에 기록하지만 사용하는 로직이 없음 |

기능상 문제를 일으키지는 않지만, 문서와 코드가 어긋나지 않도록 기록합니다.

---

## 29. Linux smoke test 절차

### 29.1 순서

```
1. Linux 서버로 저장소 복사
2. bash -n script/main.sh          (구문 검사)
3. 도구 버전 확인
4. resource / config 작성
5. --check-only 통과
6. subset smoke test 실행
7. raw VCF 완주 확인
8. resume / 실패 복구 검증
9. full WES 실행
10. optional 단계 개별 검증
```

### 29.2 1~3단계: 준비

```bash
# 2. 구문 검사 — 아무것도 실행하지 않음
bash -n script/main.sh && echo "syntax OK"

# 3. 도구 확인
for t in bwa samtools gatk bcftools tabix bgzip mosdepth fastqc python3; do
  printf '%-10s %s\n' "$t" "$(command -v $t || echo '=== MISSING ===')"
done

bwa 2>&1 | head -3
samtools --version | head -1
gatk --version 2>&1 | head -1
bcftools --version | head -1
mosdepth --version
fastqc --version
```

**여기서 확인한 버전을 기록해 두세요.** 나중에 결과 차이를 추적할 때 필요합니다.

### 29.3 4단계: resource config 작성

```bash
# 준비한 GRCh38 reference 경로로 바꿔서 실행하세요.
REF=TODO_GRCH38_REFERENCE_FASTA
REF_DIR=$(dirname "$REF")

# reference 인덱스가 다 있는지 확인
ls -l $REF $REF.fai ${REF%.fa}.dict $REF.amb $REF.ann $REF.bwt $REF.pac $REF.sa

# known-sites 인덱스 확인
for v in "$REF_DIR"/*.vcf.gz; do
  ls -l "$v" "$v.tbi" 2>/dev/null || echo "인덱스 없음: $v"
done

# contig_style은 추정하지 말고 .fai에서 직접 확인하세요.
#   chr1 형식이면 contig_style="chr", 1 형식이면 "plain"
cut -f1 "$REF.fai" | head -5
```

[7장](#7-config-전체-설명)의 예시를 바탕으로 `run_config.json`을 만듭니다.
`output_root`는 **미리 존재하고 쓰기 가능**해야 합니다.

### 29.4 5단계: `--check-only`

```bash
bash script/main.sh --config /data/runs/smoke_cfg.json --check-only
```

성공하면 다음이 출력됩니다.

```
PRECHECK PASSED — no analysis output was produced.
```

실패하면 `<run_dir>/status/steps/00_input_validation.json`의
`failures[]`를 확인하세요.

### 29.5 6단계: subset smoke test

전체 데이터로 몇 시간을 쓰기 전에, 작은 입력으로 **배선이 이어지는지** 확인합니다.

```bash
mkdir -p /data/runs/smoke/fastq

# 400,000줄 = read 100,000개
zcat /data/fastq/HG002_L001_R1.fastq.gz | head -n 400000 | gzip \
    > /data/runs/smoke/fastq/S_R1.fastq.gz
zcat /data/fastq/HG002_L001_R2.fastq.gz | head -n 400000 | gzip \
    > /data/runs/smoke/fastq/S_R2.fastq.gz

cat > /data/runs/smoke/samplesheet.csv <<'CSV'
sample,lane,fastq_1,fastq_2
SMOKE,L001,/data/runs/smoke/fastq/S_R1.fastq.gz,/data/runs/smoke/fastq/S_R2.fastq.gz
CSV
```

**같은 resource bundle**을 쓰고 `run_id`만 `smoke_001` 같은 값으로 바꿉니다.

```bash
bash script/main.sh --config /data/runs/smoke/cfg.json --check-only
bash script/main.sh --config /data/runs/smoke/cfg.json
```

### 29.6 7단계: raw VCF 완주 확인

```bash
RUN=/data/runs/smoke_001

ls $RUN/RUN_*
cat $RUN/final_validation.tsv | column -t -s$'\t'
ls -l $RUN/06_variant_calling/*.raw.vcf.gz*
bcftools view -H $RUN/06_variant_calling/*.raw.vcf.gz | wc -l
bcftools query -l $RUN/06_variant_calling/*.raw.vcf.gz
```

**성공 기준:**

- `RUN_COMPLETED` 또는 `RUN_COMPLETED_WITH_WARNINGS`가 존재
- `final_validation.tsv`에 `FAIL` 행이 없음
- `<sample>.raw.vcf.gz`와 `.tbi`가 존재
- `status/steps/06_variant_calling.json`에서
  VCF 파싱·인덱스 읽기·sample 컬럼 일치·레코드 수 > 0·REF allele 일치가 모두 pass

**반드시 함께 확인할 것 (28.2의 가정 검증):**

```bash
ls -l $RUN/04_processing/*.analysis_ready.bam*
ls -l $RUN/06_variant_calling/*.g.vcf.gz*
ls -l $RUN/06_variant_calling/*.raw.vcf.gz*
# .part 파일이 남아 있지 않아야 합니다
find $RUN -name '*.part*' -o -name '*.part'
```

> subset 입력은 **당연히 warning을 만듭니다.** 낮은 coverage, 적은 변이 수 등은
> 관찰 결과이지 실패가 아닙니다. 여기서 중요한 것은
> **배선이 끊기지 않고 raw VCF까지 도달하는지**입니다.

### 29.7 8단계: resume / 실패 복구 검증

```bash
# ① 중간에 Ctrl+C 후 재개
bash script/main.sh --config /data/runs/smoke/cfg.json   # 실행 중 Ctrl+C
ls $RUN/RUN_CANCELLED
bash script/main.sh --config /data/runs/smoke/cfg.json --resume
# → 완료된 step이 [SKIP] 되는지 로그 확인

# ② config를 바꾸고 resume → 거부되어야 함
#    (예: trim_mode를 skip에서 force로)
bash script/main.sh --config /data/runs/smoke/cfg_modified.json --resume
# → RESUME REFUSED와 달라진 필드 목록이 출력되어야 함
ls $RUN/config/run_config.rejected_resume.json

# ③ artifact를 손상시키고 resume → 그 step부터 재실행되어야 함
rm $RUN/06_variant_calling/*.raw.vcf.gz.tbi
bash script/main.sh --config /data/runs/smoke/cfg.json --resume
# → [RESUME] 06_variant_calling cannot be reused: … 가 나와야 함
# → 99_finalization도 dependency 무효화로 재실행되어야 함
```

### 29.8 9단계: full WES 실행

subset이 통과한 뒤에만 진행합니다.

```bash
bash script/main.sh --config /data/runs/full_cfg.json --check-only

nohup bash script/main.sh --config /data/runs/full_cfg.json \
    > /data/runs/full_driver.log 2>&1 &
echo $! > /data/runs/full_run.pid
```

진행 확인:

```bash
tail -f /data/runs/<run_id>/logs/pipeline.log
column -t -s$'\t' /data/runs/<run_id>/logs/execution_trace.tsv
```

**기록해야 할 것:**

- 단계별 소요 시간 (`logs/execution_trace.tsv`)
- 최대 디스크 사용량
- 최대 메모리 사용량
- 실제 도구 버전 (`logs/software_versions.txt`)

이 값들이 [28.1](#281-실행-검증이-되지-않은-항목)의 "미확정" 항목을 채웁니다.

### 29.9 10단계: optional 단계 개별 검증

core가 완주한 뒤, optional을 **하나씩** 켜서 확인합니다.

```bash
# filtering만
#   "optional_steps": { "filtering": true, "annotation": false, "intervar": false }

# annotation만 (clinvar_vcf 필요)
# intervar만 (install_dir, build, humandb_dir 필요)
```

optional 세부 설정은 resume identity에 포함되지 않으므로
([28.4](#284-resume-관련-한계)), 각각 **새 `run_id`** 로 실행하는 편이 확실합니다.

확인할 것:

- optional이 실패해도 run이 `RUN_COMPLETED_WITH_WARNINGS`로 끝나는가
- raw VCF와 그 인덱스가 손상 없이 남아 있는가
- `final_validation.tsv`에 실패한 optional step이 `WARN`으로 기록되는가

---

## 30. 향후 단계 분리와 백엔드 연동 계획

### 30.1 현재 상태를 명확히

> [!IMPORTANT]
> **현재는 단계 분리를 구현한 상태가 아닙니다.**
> `script/stages/`, `script/lib/`, `script/optional/` 같은 디렉터리는 존재하지 않고,
> 만들 계획이 지금 실행되고 있지도 않습니다.
> 실행 코드는 `script/main.sh` 한 파일뿐이며, FastAPI 코드도 없습니다.

### 30.2 왜 아직 나누지 않는가

- 파이프라인이 아직 처음부터 끝까지 한 번도 돌아 본 적이 없습니다
- 파일을 나누는 것은 정리 문제를 해결하지만, 지금 필요한 것은 **연결 검증**입니다
- **함수 경계는 실행해 보면 검증되고, 파일 경계는 그렇지 않습니다**
- 실제로 raw VCF까지 나온 뒤에야 어디가 진짜 경계인지 알 수 있습니다

### 30.3 분리 순서

full 실행이 완료되고 검토가 끝난 뒤:

1. 실제로 실행된 내용을 기준으로 **step 경계를 확인**합니다
2. 각 `run_*` 함수를 **함수 본문과 상태 계약을 바꾸지 않은 채** 별도 파일로 옮깁니다
3. 이 작업은 **별도 branch**에서 진행하고, 분리 전후의 run 디렉터리를 비교합니다

계약이 이미 파일 기반이고 기계가 읽을 수 있는 형태이므로,
이 분리는 분석 동작을 바꾸지 않아야 합니다.
현재 run 디렉터리 구조가 **비교 기준선(baseline)** 이 됩니다.

### 30.4 FastAPI 연동은 그 뒤에

**지금 만들지 않는 이유:**

- 백엔드는 파이프라인을 **호출하는 계층**입니다.
  호출 대상이 검증되지 않은 상태에서 호출 계층을 만들면,
  문제가 생겼을 때 **어느 쪽 문제인지 구분할 수 없습니다**
- 실제 실행 후에야 진짜 API 요구사항을 알 수 있습니다
  (실행 시간이 얼마인지, 어떤 중간 상태 조회가 필요한지 등)

**다만 준비는 이미 되어 있습니다:**

| 준비된 것 | 백엔드가 어떻게 쓰나 |
|---|---|
| `status/run_status.json`, `status/steps/*.json` | 진행 상황 조회 |
| 모든 문서의 `schema_version` | 형식 변화 감지 |
| `artifact_manifest.json`의 `file_id` + 상대 경로 | **파일을 다시 스캔하지 않고** 목록 제공. 절대 경로를 노출하지 않음 |
| `metrics/*.json` | 품질 지표 API |
| `provenance.json` | 재현 정보 제공 |
| run lock | 중복 실행 방지 |
| `--from-step` / `--to-step` | 부분 재실행 API |

**백엔드가 지켜야 할 제약:**

- 한 run에는 **오케스트레이터가 정확히 하나**여야 합니다.
  run lock이 강제하지만, 백엔드도 이미 존재하는 run 디렉터리로
  새 실행을 시작해서는 안 됩니다
- artifact는 **`file_id`로 제공**해야 하고 절대 경로로 제공하면 안 됩니다
- run 상태는 `pipeline.log`를 파싱하지 말고 **상태 JSON에서** 읽어야 합니다

### 30.5 전체 로드맵

```
[현재]  단일 main.sh, 코드 감사 완료
   ↓
1. Linux 서버 복사
2. bash -n
3. tool version 확인
4. resource config 작성
5. --check-only
6. subset smoke test
7. raw VCF 완주 확인
8. resume / failure recovery 검증
9. full WES
10. optional 단계 개별 검증
   ↓
11. 별도 branch에서 stage script 분리
   ↓
12. FastAPI 연동
```

benchmark 구현은 truth set과 build 호환 검사에 대한 결정이 선행되어야 하며,
현재 로드맵에서는 optional 검증 이후의 별도 과제입니다.

---

## 31. 전체 과정 요약

### 31.1 한 문단 요약

> 이 파이프라인은 사람의 엑솜 시퀀싱 FASTQ를 받아, 입력과 reference의 정합성을
> 먼저 검증하고, read 품질을 lane별로 기록하고, trimming 여부를 명시적으로 결정한 뒤,
> BWA-MEM으로 표준 유전체에 정렬해 coordinate-sorted BAM을 만들고,
> PCR 중복을 표시하고, 필요한 경우에만 NM/MD 태그를 보정하고,
> 염기 품질 점수를 재보정해 analysis-ready BAM을 만듭니다.
> 그다음 target 영역의 coverage를 측정해 신뢰 범위를 기록하고,
> HaplotypeCaller로 gVCF를, GenotypeGVCFs로 raw VCF를 산출합니다.
> raw VCF가 핵심 완료 지점이며 어떤 필터링도 적용되지 않습니다.
> 그 뒤 선택적으로 genotype 품질 필터링, 로컬 ClinVar 주석,
> InterVar 자동 근거 산출을 수행하고,
> 마지막으로 산출물 목록·품질 지표·명령 이력·도구 버전·resource 체크섬을
> 재현 가능한 형태로 정리합니다.

### 31.2 단계 요약표

| Step | 종류 | 핵심 도구 | 입력 | 핵심 출력 | 실패 시 run |
|---|---|---|---|---|---|
| `00_input_validation` | core | (검증 전용) | samplesheet, config, resource | `manifest.tsv` | 실패 |
| `01_raw_qc` | core | FastQC, MultiQC | FASTQ | FastQC 리포트 | 실패 (MultiQC는 warning) |
| `02_preprocessing` | core | fastp (`force`일 때만) | manifest | `fastq_manifest.tsv`, 결정 문서 | 실패 |
| `03_alignment` | core | BWA-MEM, samtools | FASTQ, reference | sample BAM | 실패 |
| `04_processing` | core | GATK, samtools | sample BAM | **analysis-ready BAM** | 실패 |
| `05_coverage_qc` | core | mosdepth | ready BAM, target BED | coverage 지표 | 실패 (낮은 depth는 warning) |
| `06_variant_calling` | core | GATK, bcftools, tabix | ready BAM | **raw VCF** | 실패 |
| `08_filtering` | optional | bcftools | raw VCF | filtered VCF | **실패 아님** |
| `10_annotation` | optional | bcftools | raw/filtered VCF | 정규화·주석 VCF, 변이 TSV | **실패 아님** |
| `11_intervar` | optional | InterVar | 주석/raw VCF | ACMG 자동 근거 | **실패 아님** |
| `99_finalization` | core | (정리 전용) | 전체 기록 | manifest, provenance, methods | 실패 |

### 31.3 기억할 여덟 가지

1. **핵심 완료 지점은 raw VCF입니다.** optional이 실패해도 run은 성공입니다.
2. **raw VCF에는 어떤 필터링도 적용되지 않았습니다.** `raw`는 "필터링 안 함"이지
   "품질 나쁨"이 아닙니다.
3. **`--check-only`는 파일을 만듭니다.** 순수 dry-run이 아닙니다.
   다만 분석 도구는 실행하지 않고 marker도 남기지 않습니다.
4. **`--resume`은 config나 resource가 바뀌면 거부합니다.**
   버그가 아니라 안전장치입니다.
5. **파일 존재는 유효성의 증거가 아닙니다.** resume은 BAM/VCF를 실제로 검증합니다.
6. **build mismatch는 에러 없이 틀린 답을 만듭니다.** preflight를 건너뛰지 마세요.
7. **최종 이름을 가진 산출물은 검증을 통과한 것입니다.**
   실패한 출력은 `.part`로 남고 artifact에 등록되지 않습니다.
8. **Linux 실제 실행은 아직 검증되지 않았습니다.** subset부터 시작하세요.

### 31.4 이 문서를 검증한 방법

이 문서에 적힌 함수 이름, CLI 옵션, config key, 도구 옵션, 파일 경로,
marker 이름, 상태값, 기본값은 **모두 현재 `script/main.sh`에서 직접 확인**했습니다.
추측으로 채운 항목은 없습니다.

| 항목 | 확인 방법 |
|---|---|
| 함수 이름 | 함수 정의 전수 추출 (91개) |
| CLI 옵션 | `parse_args`의 `case` 분기 전수 (6개) |
| config key | `json_get` / `json_list` 호출 전수 (40개) |
| `DEFAULT_*` 상수 | 선언부 원문 |
| 도구 옵션 | 실제 명령 호출부 원문 |
| 출력 경로 | `$RUN_DIR` 하위 경로 문자열 전수 |
| marker / 상태값 | `set_run_marker`, `write_run_status` 호출 전수 |
| `STEP_KIND` / `STEP_DEPENDS` | 선언부 원문 |
| 호출되지 않는 helper | 함수명 전체 검색으로 호출부 부재 확인 |

**확인하지 않은 것** (그래서 단정으로 쓰지 않은 것):

- 실제 Linux 실행 시의 동작
- 실제 도구 버전에서의 옵션 호환성과 인덱스 파일명 생성 방식
- 실행 시간·메모리·디스크 실측값
- fastp / filtering threshold의 선택 근거 (기존 자료에 기록이 없음)

---

## 32. 용어 사전

### 데이터 형식

| 용어 | 설명 |
|---|---|
| **FASTQ** | 염기서열과 각 염기의 품질 점수를 담은 텍스트 파일. 시퀀싱 기계의 출력. read 하나당 4줄 |
| **SAM** | 정렬 결과를 담은 텍스트 형식 |
| **BAM** | SAM의 압축 바이너리 형식. 실무에서는 거의 BAM만 사용 |
| **BAI** | BAM 인덱스. 특정 좌표를 빠르게 찾기 위한 파일. BAM과 **한 쌍** |
| **CSI** | BAI의 대체 인덱스 형식. 아주 긴 contig를 지원 |
| **VCF** | 변이 목록 형식 (Variant Call Format) |
| **gVCF** | VCF의 확장. 변이가 없는 구간의 근거(reference block)까지 포함 |
| **BED** | 유전체 구간 목록. `염색체 시작 끝` 형식. 시작은 0부터, 끝은 포함하지 않음 |
| **TBI** | bgzip 압축 VCF의 tabix 인덱스 |

### 실험·시퀀싱

| 용어 | 설명 |
|---|---|
| **DNA** | 생물의 설계도. `A`, `T`, `G`, `C` 네 글자로 이루어진 긴 사슬 |
| **염기서열** | DNA를 이루는 글자의 나열 |
| **유전체(genome)** | 한 사람이 가진 DNA 전체. 사람은 약 30억 글자 |
| **엑손(exon)** | 유전체 중 단백질을 만드는 데 쓰이는 구간 |
| **WES** | 전장 엑솜 시퀀싱. 엑손만 골라 읽음. 전체의 1~2% |
| **WGS** | 전장 유전체 시퀀싱. 전체를 읽음 |
| **read** | 기계가 한 번에 읽은 짧은 DNA 조각 (보통 100~150 글자) |
| **paired-end** | DNA 조각의 양쪽 끝을 각각 읽는 방식. R1(앞), R2(뒤) 두 파일이 한 쌍 |
| **lane** | 시퀀싱 기계 안의 물리적 통로. 같은 검체를 여러 lane에 나눠 넣을 수 있음 |
| **library** | 시퀀싱용으로 준비한 DNA 집합 |
| **capture kit** | 엑손 영역만 골라내는 실험 키트. kit마다 잡는 영역이 다름 |
| **target region** | capture kit이 실제로 잡아내는 영역. BED로 표현 |
| **target BED** | 위 영역을 적어 둔 BED 파일. WES 분석의 범위를 결정 |
| **adapter** | 시퀀싱을 위해 DNA 양끝에 붙이는 인공 서열 |
| **read group (RG)** | BAM 안에 기록하는 출처 정보. `ID`, `SM`, `LB`, `PL`, `PU` |
| **SM 태그** | read group의 sample 이름. **최종 VCF의 sample 컬럼 이름이 됨** |

### 정렬과 BAM 처리

| 용어 | 설명 |
|---|---|
| **alignment (정렬)** | read를 표준 유전체 위 제자리에 붙이는 것 |
| **reference genome** | 비교 기준이 되는 표준 유전체 서열 |
| **coordinate sort** | BAM 안의 read를 **좌표 순서로 줄 세우는 것.** alignment와 다른 작업 |
| **soft-clip** | 맞지 않는 read 끝부분을 정렬에서 제외하되 **서열은 BAM에 남김** |
| **hard-clip** | 위와 같지만 서열을 **잘라 버림** |
| **duplicate** | PCR 증폭으로 생긴 같은 원본 분자의 복사본. 독립적 증거가 아님 |
| **optical duplicate** | 기계의 광학 인식 오류로 하나가 둘로 잘못 읽힌 read |
| **MarkDuplicates** | duplicate를 찾아 **flag로 표시**하는 Picard/GATK 도구. 이 파이프라인은 삭제하지 않음 |
| **MAPQ** | mapping quality. 이 read가 이 자리에 붙은 것이 맞을 확률 |
| **NM** | BAM 태그. 이 read가 reference와 **몇 글자** 다른가 |
| **MD** | BAM 태그. **어디가 어떻게** 다른가 |
| **samtools calmd** | NM/MD를 reference 기준으로 다시 계산하는 명령 |
| **BQSR** | Base Quality Score Recalibration. 염기 품질 점수 재보정 |
| **known-sites** | 이미 알려진 변이 목록. BQSR 학습에서 제외해야 진짜 변이를 오류로 배우지 않음 |
| **analysis-ready BAM** | 중복 표시와 품질 보정이 끝나 변이 호출에 바로 쓸 수 있는 BAM |
| **coverage / depth** | 특정 위치를 덮은 read의 수 |
| **breadth** | target 중 일정 depth 이상 읽힌 비율 |

### 변이 호출과 변이

| 용어 | 설명 |
|---|---|
| **variant (변이)** | 표준 유전체와 다른 부분 |
| **germline** | 부모에게 물려받아 모든 세포가 가진 변이 |
| **somatic** | 특정 세포에서 후천적으로 생긴 변이 (이 파이프라인의 범위 밖) |
| **SNV** | 한 글자만 바뀐 변이 |
| **short Indel** | 짧은 삽입(insertion) 또는 결실(deletion) |
| **HaplotypeCaller** | GATK의 germline 변이 호출 도구. active region을 재조립해 판정 |
| **active region** | HaplotypeCaller가 변이를 의심해 재조립하는 구역 |
| **local assembly** | 그 구역의 read를 모아 가능한 서열을 다시 조립하는 것 |
| **haplotype** | 한 염색체 위에서 함께 유전되는 서열 조합 |
| **PairHMM** | read와 haplotype을 대조할 때 쓰는 알고리즘. 가장 무거운 연산 |
| **GenotypeGVCFs** | gVCF에서 genotype을 확정해 VCF를 만드는 GATK 도구 |
| **joint calling** | 여러 sample의 gVCF를 함께 분석해 genotype을 확정 (현재 범위 밖) |
| **genotype (GT)** | 양쪽 염색체의 조합. `0/0`, `0/1`, `1/1` 등 |
| **heterozygous** | 한쪽만 변이 (`0/1`) |
| **homozygous** | 양쪽이 같음 (`0/0` 또는 `1/1`) |
| **allele** | 같은 위치에 올 수 있는 서로 다른 서열 |
| **AD** | allele depth. REF와 ALT 각각을 지지하는 read 수 |
| **DP** | 그 위치의 총 depth |
| **GQ** | genotype 판정의 신뢰도 |
| **QUAL** | 그 자리에 변이가 존재한다는 확신도 |
| **FILTER** | 그 변이가 필터를 통과했는지. `PASS`, `.`, 또는 걸러진 이유 |
| **Ti/Tv** | transition/transversion 비율. WES에서 보통 2.8~3.3 |
| **normalization** | 같은 변이가 여러 방식으로 표기되지 않도록 표준형으로 맞추는 것 |
| **rsID** | dbSNP가 부여한 변이 식별자 (`rs113993960` 등) |

### 유전체 좌표

| 용어 | 설명 |
|---|---|
| **assembly / build** | reference 유전체의 판본. **이 프로젝트의 현행 기준은 `GRCh38` 하나입니다.** |
| **GRCh38** | 현재 사용하는 인간 reference 판본. config의 `resource_bundle.assembly`에 적습니다 |
| **hg38** | GRCh38에 대해 **도구(InterVar/ANNOVAR 등)가 요구하는 build 이름**. `intervar.build`에 씁니다 |
| **contig** | reference를 구성하는 연속 서열 단위 (염색체 포함) |
| **contig style** | contig **이름 표기 규칙**. `1` 방식(`plain`/`nochr`/`ensembl`)인가 `chr1` 방식(`chr`/`ucsc`)인가. **assembly와는 별개의 개념**이며, GRCh38이라고 해서 자동으로 `chr` 방식인 것은 아닙니다 |
| **primary assembly / analysis set / ALT·decoy 포함 여부** | 같은 GRCh38이라도 배포본마다 포함된 contig 집합이 다릅니다. 이름이 같다고 서로 호환된다고 가정하면 안 됩니다 |
| **interval padding** | 지정한 영역을 앞뒤로 확장하는 길이 |

### 데이터베이스와 도구

| 용어 | 설명 |
|---|---|
| **dbSNP** | 알려진 변이 식별자(rsID) 데이터베이스 |
| **ClinVar** | 임상적 의미가 보고된 변이 데이터베이스 |
| **CLNSIG** | ClinVar의 임상적 의미 필드 (Pathogenic / Benign / VUS 등) |
| **annotation (주석)** | 변이에 "어떤 유전자의 어떤 변화이고 알려진 의미가 있는가"를 붙이는 것 |
| **VEP** | Variant Effect Predictor. 변이의 기능적 영향 예측 도구 |
| **ANNOVAR** | 변이 주석 도구 |
| **InterVar** | ACMG/AMP 근거 항목을 자동 산출하는 도구 |
| **ACMG/AMP** | 변이의 임상적 의미를 판정하는 국제 가이드라인 |
| **GIAB** | Genome in a Bottle. 정답이 알려진 표준 검체 (HG002 등) |
| **truth set** | 정답 변이 목록. benchmark용 |
| **BWA-MEM** | 짧은 read 정렬 도구 |
| **samtools / bcftools** | BAM / VCF 처리 도구 모음 |
| **GATK** | Broad Institute의 변이 분석 도구 모음 |
| **Picard** | GATK에 통합된 BAM 처리 도구 (MarkDuplicates, ValidateSamFile 등) |
| **mosdepth** | 빠른 coverage 계산 도구 |
| **FastQC / MultiQC** | QC 리포트 도구 / 여러 리포트를 합치는 도구 |
| **fastp** | FASTQ trimming·필터링 도구 |
| **tabix / bgzip** | 압축 파일 인덱싱 / 블록 gzip 압축 도구 |

### 파이프라인과 소프트웨어

| 용어 | 설명 |
|---|---|
| **pipeline (파이프라인)** | 여러 분석 단계를 정해진 순서로 이어 실행하는 프로그램 |
| **step (단계)** | 파이프라인을 구성하는 하나의 작업 단위 |
| **core / optional** | 핵심 단계 / 선택 단계. optional 실패는 run을 실패시키지 않음 |
| **preflight** | 본 작업 전에 수행하는 사전 검증 |
| **samplesheet** | 무엇을 분석할지 적은 CSV 표 |
| **manifest** | 검증을 마친 목록 문서 |
| **run** | 한 번의 파이프라인 실행. `run_id`로 식별되고 디렉터리 하나에 격리됨 |
| **artifact** | 파이프라인이 만들어 낸 **검증된 산출물** |
| **provenance** | 이 결과를 어떻게 만들었는지의 기록 (설정·버전·체크섬·명령) |
| **checksum** | 파일 내용을 요약한 고정 길이 값. 여기서는 SHA-256. 내용이 1바이트만 달라도 값이 바뀜 |
| **resume** | 중단된 지점부터 이어서 실행하는 기능 |
| **멱등성 (idempotency)** | 같은 명령을 여러 번 실행해도 결과가 같은 성질 |
| **atomic operation (원자적 연산)** | 중간 상태 없이 성공 또는 실패만 있는 연산 |
| **atomic rename** | 검증을 마친 파일을 최종 이름으로 바꾸는 것. 중간 상태가 없음 |
| **`.part` 파일** | 아직 완성되지 않은 파일의 임시 이름. 최종 산출물로 오인되지 않게 함 |
| **lock** | 같은 run을 두 프로세스가 동시에 실행하지 못하게 막는 장치 |
| **stale lock** | 죽은 프로세스가 남긴 lock. 자동으로 지우지 않음 |
| **marker** | run의 최종 상태를 나타내는 표식 파일 (`RUN_COMPLETED` 등) |
| **trap** | 오류나 신호가 발생했을 때 실행되는 처리기 |
| **heredoc** | 셸에서 여러 줄 문자열을 프로그램에 넘기는 문법 |
| **PIPESTATUS** | 파이프 각 단계의 종료 코드를 담은 Bash 배열 |
| **schema version** | 데이터 형식의 판본. 형식이 바뀌었는지 판단하는 근거 |
| **`file_id`** | artifact의 고유 식별자. 절대 경로를 노출하지 않고 파일을 지칭하기 위함 |
| **dry-run** | 실제 작업 없이 검증만 하는 실행. `--check-only`는 **완전한 dry-run이 아님** |
