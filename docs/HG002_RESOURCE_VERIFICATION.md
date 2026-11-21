# HG002 리소스 검증 기록

> 목적: 개발 검증에 쓴 HG002 입력(SRR2962669)과 분석 리소스(capture BED, reference)가
> 실제로 맞는지에 대한 근거를 한곳에 누적한다. 같은 조사를 반복하지 않기 위한 정본이다.
>
> - 최초 작성: 2026-11-10
> - 기준 코드: `main` @ `4822b41` (`script/main.sh` v1.2.0)
> - 갱신 방법: 기존 행을 지우지 않는다. 새 사실은 §11 검증 로그에 날짜와 함께 추가하고,
>   해당 항목의 등급을 바꾼 경우 그 행에 `(→ YYYY-MM-DD 갱신, §11 참조)`를 붙인다.

## 증거 등급

| 등급 | 의미 |
|---|---|
| **CONFIRMED** | 이 문서 작성자가 1차 자료(공식 기록 원문, 저장소 코드, 로컬에 남은 실행 기록)를 직접 읽어 확인함 |
| **DOCUMENTED** | 프로젝트 문서·운영자 기록·제3자 자료에만 있고 이번에 1차 자료로 재확인하지 못함 |
| **UNVERIFIED** | 추정이거나 확인 수단이 아직 실행되지 않음 |

로컬 실행 기록 위치(`.gitignore`의 `/runs/`, 저장소에 커밋되지 않음):
`runs/dev_real_cba73e/runs/wes-20260918-222933-cba73e/` — metrics·status·config·logs JSON/텍스트만 있고
BAM·VCF·FASTQ는 없다. 이하 `RUN/`으로 줄인다.

---

## 1. 결론 요약

1. **SRR2962669는 Agilent SureSelect Human All Exon V5로 capture된 HG002(NA24385) WES다.** — CONFIRMED (NCBI SRA·ENA 원문, §2)
2. 개발 검증 Run은 **Twist Exome 2.0 BED**로, 그 이전 Run 하나는 **IDT xGen v2 BED**로 분석됐다. **둘 다 실제 kit와 다르다.** — CONFIRMED(cba73e) / DOCUMENTED(fcb1c2, 97ea7b)
3. 따라서 기존 Run의 커버리지·breadth·0x 수치와 변이 호출 영역은 **실제 capture 영역이 아닌 Twist 영역 기준**이다. 해석에 쓰면 안 된다.
4. **새 발견:** reference는 3,366 contig이고 BWA는 실행 시 `read 0 ALT contigs`를 출력했다. **ALT-aware 정렬이 아니었을 가능성이 높다.** — 로그는 CONFIRMED, 의미는 UNVERIFIED (§5)
5. GIAB HG002 small-variant benchmark는 v4.2.1(GRCh38)과 그 후속 v5.0q(draft)가 공개돼 있다. 저장소와 Run 어디에도 truth 비교는 없다. — CONFIRMED (§8)

---

## 2. 원본 실험과 Run ID

출처(모두 2026-11-10 조회, HTTP 200):
- NCBI SRA: <https://www.ncbi.nlm.nih.gov/sra/SRX1453593>
- NCBI E-utilities efetch (SRA UID 2055308): <https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id=2055308>
- ENA XML: <https://www.ebi.ac.uk/ena/browser/api/xml/SRX1453593>
- ENA filereport: <https://www.ebi.ac.uk/ena/portal/api/filereport?accession=SRR2962669&result=read_run&format=tsv>

| 항목 | 값 | 등급 |
|---|---|---|
| Experiment | SRX1453593, alias/library name `HG002_WES_OUS` | CONFIRMED |
| Run | SRR2962669 (해당 experiment의 run) | CONFIRMED |
| Study / BioProject | SRP047086 / PRJNA200694 (GIAB, NIST 주관) | CONFIRMED |
| Sample | SRS1181267 / BioSample SAMN04299540, sample name `HG002`, isolate `NA24385`, male | CONFIRMED |
| 제출 기관 | Oslo University Hospital, Department of medical genetics | CONFIRMED |
| Library | WXS · GENOMIC · Hybrid Selection · PAIRED | CONFIRMED |
| **Capture kit** | DESIGN_DESCRIPTION 원문: *"The coding exons were captured by Agilent SureSelect Human All Exon V5 kit."* | CONFIRMED |
| 보조 근거 | NCBI에 등록된 원본 FASTQ 파일명 `HG002-KIT-Av5_AGATGTAC_L008_R{1,2}_001.fastq.gz` | CONFIRMED |
| 장비 | Illumina HiSeq 2500 | CONFIRMED |
| Spots / bases | 75,193,388 / 18,948,733,776 | CONFIRMED |
| Read 길이 | NCBI 통계는 read당 평균 126 (stdev 0). design description은 "2x125bp"라고 적음. 로컬 tail subset header `length=126`과 일치 | CONFIRMED (불일치 자체도 사실로 기록) |
| 공개일 | 2015-12-01 (NCBI) / 2015-12-02 (ENA) | CONFIRMED |
| FASTQ checksum | ENA와 NCBI가 서로 다른 md5·크기를 제시함(다른 파일 표현으로 보임). 로컬 subset은 SRA에서 `fastq-dump`로 만들었으므로 둘 다 직접 비교 대상이 아님 | CONFIRMED (차이 존재) |

GIAB FTP의 관련 자료:
- `giab/data/AshkenazimTrio/HG002_NA24385_son/OsloUniversityHospital_Exome/`에는 **GRCh37 BAM/BAI 두 파일만** 있다. README도 BED도 없다. 파일명에 `KIT-Av5`가 있다. — CONFIRMED
  (<https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data/AshkenazimTrio/HG002_NA24385_son/OsloUniversityHospital_Exome/>)
- `giab_data_indexes`는 이 데이터를 `bwamem:hg19` 정렬로만 색인한다. SRR2962669 표기와 kit 표기는 없다. — CONFIRMED
  (<https://github.com/genome-in-a-bottle/giab_data_indexes>)
- **결론: GIAB가 이 exome용 GRCh38 capture BED를 제공하지 않는다.** BED는 Agilent에서 따로 확보해야 한다.

---

## 3. 기존 Run의 실제 설정과 체크섬

| 항목 | `wes-20260918-222933-cba73e` | `wes-20260907-014650-fcb1c2` | `wes-20260904-201711-97ea7b` |
|---|---|---|---|
| 입력 | SRR2962669 **뒤쪽** 5,000,000 spots (`tail_5M`, spot 70,193,389–75,193,388) | SRR2962669 **앞쪽** 5M (`subset_5M`) | `subset_5M` |
| capture kit id | `twist_exome_2_0` | `twist_exome_2_0` | `idt_xgen_exome_hyb_panel_v2` |
| BED design | `hg38-exome-v2.0.2-targets`, 283,942 구간, 36,458,262 bp | 같음 | IDT hg38 targets/probes |
| target = coverage BED sha256 | `8fa8f1a9fd5d2dcbefa2b48713e8b242065eb60bef0f9b8482322246ed4d5a77` | 사용자 보고상 같음 | 레지스트리상 `9b18f157…`(target) / `3934ebff…`(probes) |
| Reference FASTA sha256 | `93157a161863464c9435062fd67c173fdaf99cb8b32f1455018361387ffa5564` (`Homo_sapiens_assembly38.fasta`) | 사용자 보고상 같음 | 기록 없음 |
| known sites sha256 | known_indels `c0c400cf…`, Mills `e11195ef…` (indel 세트만, SNP 세트 없음) | — | — |
| dbSNP / ClinVar / truth | 모두 미설정 | 미설정 | 미설정 |
| 주요 설정 | padding 100, mosdepth MAPQ 20, trim skip, `bqsr_target_only=false`, optional 08/10/11 꺼짐 | 같음 | — |
| 도구 버전 | bwa 0.7.19-r1273, samtools 1.24, GATK 4.7.0.0, bcftools 1.24, mosdepth 0.3.14 | — | — |
| 결과 | completed_with_warnings 8/8, raw records 52,294 | completed_with_warnings 8/8, raw records 52,379 | completed_with_warnings |
| 근거 등급 | **CONFIRMED** (`RUN/logs/resource_sha256.txt`, `RUN/config/run_config.snapshot.json`, `RUN/logs/software_versions.txt`) | **DOCUMENTED** (`README.md` Validation 표, `backend/evals/fixtures/full_completed_with_warnings.json`, 로컬 개발 기록 §52) | **DOCUMENTED** (로컬 개발 기록 §29) |

- 두 Twist Run은 **서로 다른 FASTQ 구간**이다. 동일 입력 반복 실행이 아니고 독립 sample도 아니다.
- 97ea7b는 같은 `subset_5M`을 다른 BED로 분석한 사례다. 지금 시점에서 그 의미는 "kit 선택이 run마다 달랐다"는 것뿐이다.

---

## 4. 결과 파일 보존 현황

| 대상 | 상태 | 등급 |
|---|---|---|
| cba73e 메타데이터 (metrics, status, config snapshot, logs) | Windows 로컬 `RUN/`에 복사본 있음 | CONFIRMED |
| cba73e BAM·VCF·gVCF | 로컬에 없음. VM run 디렉터리에 있다고 기록됨 | 현재 상태 UNVERIFIED |
| fcb1c2 run 디렉터리 전체 | 2026-09-17 정리 때 삭제 목록(97ea7b, eed8e3)에 없었음 | 현재 상태 UNVERIFIED |
| 97ea7b run 디렉터리 | 2026-09-17 삭제됨 (로컬 개발 기록 §57-2) | DOCUMENTED |
| head `subset_5M` FASTQ | VM upload 사본은 삭제됨. Windows에 보존본이 있다고 기록됨 (§29) | DOCUMENTED |
| tail `tail_5M` FASTQ | Windows 임시 위치와 VM upload에 있다고 기록됨 (§57-1) | DOCUMENTED |
| GIAB 원본 GRCh37 BAM | GIAB FTP에 공개 (9.6 GB) | CONFIRMED |

---

## 5. Reference FASTA의 종류 — ALT-aware 정렬 여부

| 사실 | 근거 | 등급 |
|---|---|---|
| FASTA 파일명 `Homo_sapiens_assembly38.fasta`, 출처는 Broad의 public GRCh38 resource bucket | 로컬 개발 기록 §11 | DOCUMENTED |
| reference contig **3,366개**, 그중 `chr` 접두 2,841개 | `RUN/logs/pipeline.log` 15–16행 | CONFIRMED |
| BWA index는 `.64.{amb,ann,bwt,pac,sa}` 5종만 기록됨. `.64.alt`는 목록에 없음 | 로컬 개발 기록 §11, §57-6 | DOCUMENTED |
| BWA stderr 첫 줄 `[M::bwa_idx_load_from_disk] read 0 ALT contigs` | `RUN/logs/03_alignment.bwa_*.stderr.log` 1행 | CONFIRMED |
| bwa 명령에 별도 postalt 처리 없음 (`bwa mem -K 100000000 -Y … \| samtools sort`) | `RUN/logs/commands.sh`, `script/main.sh` run_alignment | CONFIRMED |
| BWA는 ALT contig 목록을 `idxbase.alt`에서 읽는다. ALT를 모르는 채 GRCh38+ALT에 정렬하면 MAPQ 0 read가 많이 늘고 변이를 놓친다 | bwa `README-alt.md` (<https://github.com/lh3/bwa/blob/master/README-alt.md>) | CONFIRMED (문서 원문) |
| 3,366 contig = primary + unlocalized/unplaced + EBV + ALT + decoy + HLA 구성이라는 해석 | 제3자 자료와 일반 지식. GATK 공식 문서는 이번에 403으로 읽지 못함 | UNVERIFIED |
| **이번 Run이 non-ALT-aware 정렬이었다**는 결론 | 위 두 CONFIRMED 사실에서 나온 추론. `.fai`의 `_alt` 개수 확인 전에는 단정하지 않음 | UNVERIFIED |

**영향 (UNVERIFIED):** ALT haplotype이 있는 영역(예: HLA, KIR 주변, 일부 유전자군)에서 read가 primary와 ALT로 나뉘어 MAPQ가 0이 된다.
- mosdepth(`--mapq 20`)에서 해당 영역 깊이가 0으로 집계된다.
- HaplotypeCaller는 기본 MAPQ 필터로 그 read를 제외해 변이를 놓친다.

**확인 방법:** §9의 명령 R1–R4. `.fai`에서 `_alt` 개수를 세고 `.64.alt` 존재를 확인한다. 공식 bucket의 md5와 로컬 FASTA를 비교한다.

---

## 6. Capture kit 불일치 — 과학적 영향

| 비교 | Twist Exome 2.0 (사용됨) | Agilent SureSelect Human All Exon V5 (실제) |
|---|---|---|
| target 규모 | 36,458,262 bp / 283,942 구간 (CONFIRMED, cba73e) | 약 50 Mb (DOCUMENTED, 출시 당시 보도. Agilent 공식 페이지는 이번에 403) |
| 설계 기관 / 연도 | Twist, v2.0.2 hg38 | Agilent, 2012년경 출시 (DOCUMENTED) |
| design ID | `hg38-exome-v2.0.2-targets` | `S04380110`로 알려져 있음 (UNVERIFIED, SureDesign에서 확인 필요) |
| GRCh38 BED | 공식 제공, 레지스트리 checksum 있음 | SureDesign 로그인 후 다운로드. hg38 제공 여부는 UNVERIFIED |

**영향:**
- **커버리지 지표 무효 (CONFIRMED 논리):**
  - 평균 깊이, breadth(1/10/20/30X), 0x 비율, low-coverage 구간은 모두 Twist BED로 계산됐다.
  - V5 라이브러리를 Twist 영역으로 평가한 값이므로 capture 효율이나 품질 지표로 해석하면 안 된다.
  - cba73e의 0x 9.29% 중 얼마가 "V5가 capture하지 않는 Twist 영역" 때문인지는 UNVERIFIED다.
- **변이 호출 영역 (CONFIRMED 코드):**
  - HaplotypeCaller와 GenotypeGVCFs는 `-L TARGET_BED -ip 100`으로 실행된다.
  - V5에만 있는 영역의 변이는 호출되지 않았다.
  - V5에 없는 Twist 영역에서는 off-target read로 저품질 호출이 생겼을 수 있다 (UNVERIFIED).
  - raw record 수(52,294 / 52,379)는 "V5 라이브러리를 Twist 영역 ±100bp에서 호출한 결과"다.
- **BQSR (CONFIRMED 코드):**
  - `bqsr_target_only=false`라 genome 전체에서 학습한다. BED 선택의 영향을 받지 않는다.
  - 대신 indel known sites만 쓴 점은 별도 위험으로 남는다 (감사 4).
- **정렬·중복 표시 (CONFIRMED 코드):** BWA와 MarkDuplicates는 BED를 쓰지 않는다. kit 불일치의 영향이 없다.

---

## 7. 재사용 가능 범위와 재실행이 필요한 범위

| 산출물 | Agilent BED로 바꿀 때 | ALT-aware 정렬을 도입할 때 | 근거 |
|---|---|---|---|
| FASTQ subset | 재사용 | 재사용 | 입력 데이터 |
| 03 sorted BAM | 재사용 가능 | **재실행** | BWA가 BED를 쓰지 않음 / `.alt` 필요 |
| 04 analysis-ready BAM | 재사용 가능 (BQSR genome-wide, ApplyBQSR `-L` 없음) | **재실행** | `main.sh` BQSR 블록 |
| 05 coverage | **재계산** (BED 의존) | 재계산 | mosdepth `--by` BED |
| 06 gVCF / raw VCF | **재실행** (`-L TARGET_BED`) | 재실행 | HaplotypeCaller `-L` |
| 99 provenance·methods | 재생성 | 재생성 | 설정 snapshot 의존 |

**실행 방식 주의:**
- `main.sh --resume`은 config identity가 달라지면 거부한다 (`main.sh` 1407–1433, 5329–).
- 따라서 BED를 바꾸면 새 run_id로 처음부터 실행해야 한다.
- 기존 BAM에서 05·06만 다시 돌리는 경로는 파이프라인에 없다. 수동 실행은 Web 결과 계약 밖의 실험이 된다. — 경로 부재는 CONFIRMED, BED 변경이 identity에 포함되는지는 UNVERIFIED

**권장 판단 순서:**
1. §5의 ALT 여부를 먼저 확인한다. ALT-aware로 바꾼다면 03부터 다시 해야 한다.
2. 그 다음 BED를 교체한다.

순서를 반대로 하면 재실행을 두 번 하게 된다.

---

## 8. GIAB benchmark 선행 조건

공개 자료 (2026-11-10 조회):
- `NISTv4.2.1/GRCh38/`: `HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz`(+`.tbi`), `HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed`. 이 폴더에는 README가 없다. — CONFIRMED
- `v5.0q/`: `HG002_GRCh38_v5.0q_smvar.vcf.gz`, `HG002_GRCh38_v5.0q_smvar.benchmark.bed`. README는 이 버전을 "draft", "under active development"라고 하고, small variant 비교에 rtg vcfeval과 `--gender male` 사용을 권장한다. — CONFIRMED
- NIST 페이지는 HG002의 v4.2.1을 "deprecated … by v5.0q"라고 적는다 (<https://www.nist.gov/programs-projects/genome-bottle>). — CONFIRMED
- GA4GH benchmarking: hap.py가 기준 구현이고 vcfeval 엔진을 권장한다 (<https://github.com/ga4gh/benchmarking-tools>). — CONFIRMED

**선행 조건 (모두 미충족):**

| # | 조건 | 상태 |
|---|---|---|
| B1 | 실제 kit(V5)의 GRCh38 BED 확보와 checksum 기록 | 미충족 |
| B2 | reference 종류 확정 (ALT 포함 여부, 공식 md5와 일치 여부) | 미충족 (§5) |
| B3 | GIAB 버전 결정 (v4.2.1 안정판 vs v5.0q draft). checksum 기록 | 미결정 (`docs/MAIN_SH_COMPLETE_GUIDE.md` §28.7) |
| B4 | 평가 영역 정의: truth BED ∩ V5 BED. padding 포함 여부 결정 | 미정 |
| B5 | 비교 도구 선택: hap.py(vcfeval 엔진) 또는 rtg vcfeval 단독. vcfeval은 reference SDF 필요. **대안 제안일 뿐 사용 결정 아님** | 미설치 여부 UNVERIFIED |
| B6 | 해석 범위 명시: 5M subset(약 11x)의 결과는 "이 깊이의 subset" 성능이다. SNV와 indel을 분리하고 영역 stratification을 함께 보고 | 원칙만 정함 |
| B7 | 동일 입력 2회 실행 (반복 일관성) | 없음 |

정확도 수치는 이 문서에서 추정하지 않는다.

---

## 9. Ubuntu 읽기 전용 점검 명령 (계획, 미실행)

이 저장소 작업 환경(Windows)에서는 Ubuntu VM에 접근하지 않았다. 아래는 운영자가 VM에서 **한 번에** 실행할 읽기 전용 점검이다.
- 파일을 만들거나 바꾸지 않는다. 출력은 터미널로만 나온다.
- read 서열이나 변이 내용은 출력하지 않는다.
- `md5sum`/`sha256sum`은 큰 파일을 끝까지 읽으므로 시간이 걸린다.

```bash
# 경로는 운영자가 채운다 (backend/.env의 WES_REFERENCE_FASTA, WES_RUNS_ROOT 값)
REF="<WES_REFERENCE_FASTA>"
RUNS="<WES_RUNS_ROOT>"

echo "== R1 reference index files"; ls -la "${REF}".* 2>&1 | awk '{print $5, $NF}' | sed 's|.*/||'
echo "== R2 .alt present?"; for f in "${REF}.64.alt" "${REF}.alt"; do [ -e "$f" ] && echo "present: ${f##*/} ($(wc -l < "$f") lines)" || echo "absent: ${f##*/}"; done
echo "== R3 contig composition (.fai)"
echo "total $(wc -l < "${REF}.fai")"; echo "alt $(grep -c '_alt\b' "${REF}.fai")"
echo "decoy $(grep -c '_decoy\b' "${REF}.fai")"; echo "HLA $(grep -c '^HLA-' "${REF}.fai")"; echo "EBV $(grep -c '^chrEBV\b' "${REF}.fai")"
echo "== R4 FASTA md5 (Broad bucket md5와 비교용)"; md5sum "$REF" | awk '{print $1}'

echo "== A1 Agilent BED 후보 (파일명만)"
find / -xdev -type f \( -iname '*S04380110*' -o -iname '*sureselect*' -o -iname '*agilent*' -o -iname '*all*exon*v5*' \) \
  \( -iname '*.bed' -o -iname '*.bed.gz' -o -iname '*.zip' \) 2>/dev/null | head -50

echo "== P1 run 디렉터리 보존 상태"
for r in fcb1c2 cba73e; do d=$(ls -d "$RUNS"/wes-*-"$r" 2>/dev/null); echo "-- $r: ${d:-MISSING}"; [ -n "$d" ] && du -sh "$d" | awk '{print $1}' && \
  ls -la "$d"/04_processing/*.analysis_ready.ba* "$d"/06_variant_calling/*.vcf.gz* 2>/dev/null | awk '{print $5, $NF}' | sed 's|.*/||'; done

echo "== P2 정렬 명령 이력 (BAM header @PG, 서열 없음)"
for r in fcb1c2 cba73e; do b=$(ls "$RUNS"/wes-*-"$r"/04_processing/*.analysis_ready.bam 2>/dev/null | head -1); [ -n "$b" ] && \
  samtools view -H "$b" | grep -E '^@PG' | grep -E 'ID:bwa' | cut -c1-200; done

echo "== T1 benchmark 도구·truth 존재 여부"
for t in hap.py rtg bedtools bcftools; do printf '%s: ' "$t"; command -v "$t" || echo absent; done
find / -xdev -type f -iname 'HG002_GRCh38*' 2>/dev/null | head -20

echo "== D1 disk"; df -h "$RUNS" | tail -1
```

| ID | 확인하는 것 | 결과 기록 위치 |
|---|---|---|
| R1–R3 | `.alt` 존재와 contig 구성 → §5 확정 | §11 |
| R4 | 공식 md5와 일치 여부 → 정확한 reference 판본 확정 | §11 |
| A1 | VM 어딘가에 Agilent BED가 이미 있는지 (전체 파일시스템, `-xdev` 범위) | §11 |
| P1–P2 | BAM·VCF 보존 여부와 실제 정렬 명령 | §4, §11 |
| T1 | benchmark 도구·truth 보유 여부 | §8, §11 |

---

## 10. 다음 단계와 승인 필요 작업

| # | 작업 | 성격 | 승인 |
|---|---|---|---|
| N1 | §9 명령을 VM에서 실행하고 결과를 §11에 기록 | 읽기 전용 | 운영자 실행 |
| N2 | SureDesign에서 V5 design의 GRCh38 Regions/Covered BED 존재 확인. GRCh37만 있다면 liftover를 할지 결정 (기존 정책 `docs/CAPTURE_BED_RESOURCES.md`는 GRCh37 BED에 `chr`만 붙이는 변환을 금지함) | 외부 계정, 소용량 다운로드 | **사용자 승인** |
| N3 | V5 kit를 `config/capture_kits.grch38.json`에 추가 (`unconfirmed`로 시작해 checksum 확인 후 `confirmed`) | 설정 변경 | **사용자 승인** |
| N4 | ALT-aware 정렬 도입 여부 결정 (`.64.alt` 배치 + postalt 처리) | 분석 방법 변경 | **사용자 판단** |
| N5 | BQSR known sites에 SNP 세트(dbSNP 등) 추가 여부 | 분석 방법 변경 | **사용자 판단** |
| N6 | GIAB 버전 선택과 truth 파일 다운로드 (수백 MB) | 대용량 다운로드 | **사용자 승인** |
| N7 | N2–N5 반영 후 새 run_id로 동일 입력 2회 full 실행 | 파이프라인 실행 | **사용자 승인** |
| N8 | README Validation 표의 "Capture kit: Twist Exome 2.0" 문구에 불일치 주석 추가 | 문서 수정 | **사용자 승인** (이번 작업에서는 수정하지 않음) |

---

## 11. 검증 로그 (누적)

| 날짜 | 수행자 | 환경 | 수행 내용 | 결과 |
|---|---|---|---|---|
| 2026-11-10 | Claude Code | Windows 저장소 (읽기 전용) | NCBI SRA·ENA·GIAB FTP·NIST·GA4GH·bwa README 조회. 로컬 `RUN/` 메타데이터와 `main.sh` 확인 | §2·§3·§5·§8의 CONFIRMED 항목 |
| 2026-11-10 | Claude Code | Windows | GATK Reference Genome Components 문서, Broad GCS bucket 목록, Agilent V5 제품 페이지 조회 시도 | **실패** (403/401). 해당 항목은 UNVERIFIED 유지 |
| (이전) | 운영자 | Ubuntu | 일부 경로에서 Agilent BED 검색 | 결과 없음. 전체 파일시스템 부재는 미확인 (사용자 보고) |

### 이번에 실행한 조사 명령 (Windows, 읽기 전용)

```text
grep -n "reference contigs\|contig style"  RUN/logs/pipeline.log
head -1                                    RUN/logs/03_alignment.bwa_*.stderr.log
grep "bwa mem"                             RUN/logs/commands.sh
cat                                        RUN/logs/resource_sha256.txt   (경로 부분 제거 후 열람)
cat                                        RUN/logs/software_versions.txt
grep -o '"bqsr_target_only"…'              RUN/config/run_config.snapshot.json
sed -n 3300,3330p                          script/main.sh                 (BQSR -L 조건)
GET  ebi.ac.uk/ena/browser/api/xml/SRX1453593
GET  ebi.ac.uk/ena/portal/api/filereport?accession=SRR2962669…
GET  eutils.ncbi.nlm.nih.gov/…/esearch.fcgi?db=sra&term=SRX1453593 → efetch id=2055308
GET  ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data/AshkenazimTrio/HG002_NA24385_son/OsloUniversityHospital_Exome/
GET  ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/{,NISTv4.2.1/GRCh38/,v5.0q/}
GET  github.com/lh3/bwa/blob/master/README-alt.md
```

---

## 관련 문서

- `docs/CAPTURE_BED_RESOURCES.md`: kit 레지스트리 정책. V5는 아직 없고 V8만 `unconfirmed`로 있다.
- `docs/MAIN_SH_COMPLETE_GUIDE.md` §28.7: benchmark를 만들지 않은 이유.
- `README.md` Validation: 두 Run 수치. **capture kit 불일치 주석이 아직 없음 (N8).**
- 로컬 개발 기록 (`local-context/`, Git 추적 제외): Run 경위의 서사 기록. 이 문서는 그 기록의 리소스 근거만 정본화한다.
