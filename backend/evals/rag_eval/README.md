# 공식 문서 검색 오프라인 평가 (rag_eval)

모델·네트워크·DB 없이 공식 문서 검색(`app/services/doc_search/engine.run_search`)의 품질을 잽니다.

각 사례는 다음 순서로 평가합니다.
1. 사례를 main.sh가 쓰는 실행 기록으로 만듭니다.
   - 단계 문서
   - `resource_validation.txt` 보고서
2. 임시 폴더에서 실제 검색 경로가 그 기록을 읽게 합니다.
3. 돌려받은 문서의 순위를 채점합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `cases.public.json` | 공개·합성 사례 23개. 문장은 `script/main.sh`의 메시지 형식(줄 번호는 `basis`)에 가짜 경로를 넣은 것 |
| `metrics.py` | Recall@k, MRR, abstain 정확도(순수 함수) |
| `run.py` | 사례 → 실행 기록 → 검색 → 채점 |
| `../test_rag_eval.py` | 지표 단위 테스트, 사례 파일 검사, 합성 baseline 회귀 검사(CI의 `pytest evals`에 포함) |

```
cd backend
.venv/Scripts/python.exe -m evals.rag_eval.run                  # 공개 합성 코퍼스
.venv/Scripts/python.exe -m evals.rag_eval.run --corpus local   # 로컬 비공개 발췌로 순위까지(로컬 전용)
.venv/Scripts/python.exe -m evals.rag_eval.run --json           # 사례별 결과
```

## 지표

| 지표 | 정의 | 대상 |
|---|---|---|
| Recall@k | 첫 관련 문서가 상위 k개 안에 있는 질의의 비율 | positive 사례의 질의(기록된 원인 1개 = 질의 1개) |
| MRR | 1 / 첫 관련 문서 순위의 평균. 못 찾으면 0 | 동일 |
| Abstain 정확도 | 아무 문서도 돌려주지 않은 사례의 비율 | coverage_gap + negative 사례 |
| inputKindAccuracy | 기록에서 만든 질의 종류가 기대와 정확히 같은 사례 비율 | 전체 |
| wrongKindHits | 기대 원인과 다른 원인으로 분류된 문서를 돌려준 건수 | 전체 |

**관련 문서의 정의**
- 돌려받은 문서가 기대 원인 종류(`relevant_kinds`) 아래 등록돼 있으면 관련 문서입니다.
- 분모가 0이면 `null`입니다. "측정 안 함"을 0이나 1로 쓰지 않습니다.

## 사례 구성 (46개, 모두 `unreviewed`; log 62에서 held-out 14개 추가)

`design`은 그 사례가 무엇을 재는지입니다.

| design | 사례 | 재는 것 |
|---|---|---|
| `rule_replicating` | 14 | main.sh 템플릿 문장 → 규칙표 → 원인 종류. 종류가 맞으면 결과가 하나로 정해지므로 **규칙을 반복 확인할 뿐 검색 품질은 재지 못함** |
| `independent_ranking` | 12 | 같은 원인 종류에 문서가 여럿일 때 어느 것이 더 도움이 되는지. `grades_local`(0~2)과 근거(`grade_basis`)는 AI가 제안한 **잠정값** |
| `phrasing_variant` | 20 | 같은 뜻을 main.sh가 쓰지 않는 표현으로(약어, 셸 메시지, 도구 자체 메시지, 다른 어순). `split`: dev 6 / heldout 14(양성 8·음성 6) |

`category`는 기대 출력입니다.
- positive: 관련 문서가 돌아와야 함
- coverage_gap: 분류되지만 등록 문서가 없어 "없음"이 맞음
- negative: 아무것도 돌아오면 안 됨

`ind-bed-contig-absent`는 negative입니다. "BED에 참조에 없는 contig" 오류인데, 그 원인 종류에 등록된 BED 문서는 모두 열 수·좌표에 관한 것입니다. 그래서 **잘못된 문서가 검색되는 사례**입니다.

## 결과 (2026-11-23, 같은 평가셋 32사례)

**공개 합성 코퍼스**(자리표시 본문이라 원인 안 순위는 재지 않음)

| design | 질의 | Recall@1 = @5 | MRR | Abstain | 질의 종류 일치 |
|---|---|---|---|---|---|
| rule_replicating | 5 | 1.0 | 1.0 | 1.0 (10) | 1.0 |
| independent_ranking | 11 | 1.0 | 1.0 | 0.0 (1: contig 사례) | 1.0 |
| phrasing_variant | 7 | 0.0 | 0.0 | — | 0.0 |

**로컬 비공개 코퍼스**(21발췌, 로컬 전용, 등급은 잠정)
- Recall·abstain은 위와 같습니다.
- 원인 안 순위(독립 사례 11질의): nDCG@3 **0.934**, 최상(2등급) 문서 1위 비율 **0.8**(10질의), MRR(2등급) **0.9**
- 놓친 순위 2건
  - `pos-bwa-not-found`: bwtsw가 2위
  - `ind-bed-out-of-range`: 좌표 문서가 2위
  - 둘 다 오류 문장과 문서에 겹치는 단어가 없습니다.

**경로 안정성**(경로에 문서 단어로 된 폴더명을 넣어도 순위가 같은 비율): 11질의 1.0. 두 코퍼스 모두 같습니다.

## 검색 개선과 효과 (log 61)

변경: `doc_retrieval.query_words()`. 원인 문장에서 다음을 빼고 메시지 단어로만 순위를 매깁니다.
- 경로
- 파일명
- 따옴표 값
- 목록
- `key=value`
- digest
- 가림 표시(`<path>` 등)

| 측정 | 개선 전 | 개선 후 |
|---|---|---|
| 위 평가셋의 모든 지표(합성·로컬) | 위 표와 같음 | **변화 없음**(바뀐 순위 0건) |
| `retrieve()` 직접 호출의 경로 의존 | `bgzip_sorted_input/` 폴더가 순위를 뒤집음(RED 테스트) | 경로·파일명과 무관(`test_doc_retrieval.py`) |

평가셋에서 변화가 없는 이유:
- 운영 경로(문서 검색 API, Agent 도구)는 문장을 이미 가린 뒤 검색합니다(`resource_bundle_diagnosis`).
- 그래서 경로 단어가 원래 들어가지 않았습니다.
- 이 변경은 **방어적 일관성 수정**이며, 측정된 순위 향상으로 주장하지 않습니다.

## 표현 변형 보완: 표현 사전 추정 (log 62, 2026-11-23)

### 실제 원인

표현 변형 질의는 **검색이나 순위가 아니라 분류 단계**에서 전부 탈락했습니다.

- 규칙표(`resource_bundle_causes.py`)는 main.sh 템플릿만 정확히 맞춥니다. 다른 표현은 `unknown`이 됩니다.
- 등록 발췌는 원인 종류 키로만 고르므로, `unknown`이면 후보가 0개입니다.
- 질의어·후보·순위 문제는 그다음 단계여서 원인이 아닙니다.
- 실측: dev 6개, held-out 8개 모두 `inputKinds=["unknown"]`, hit 0.

### 선택한 방법

`services/doc_search/lexicon.py`가 `unknown` 문장에만 원인 종류를 **추정**합니다.

- 한 규칙의 개념(예: VCF 도구 + "command not found")이 모두 있어야 추정합니다.
- 두 종류가 동시에 맞으면 추정하지 않습니다.
- 원인 종류는 바꾸지 않고 `unknown`으로 둡니다.
- 결과는 별도 관계 `suggestedByWording`으로 표시하고, 최대 3개입니다. Agent 입력에서는 제외됩니다.

### 평가 분리

| 집합 | 내용 |
|---|---|
| dev | 기존 phrasing 6사례(만들 때 봄) + `experiments/retrieval_queries.json` split=dev |
| heldout | 구현 전에 작성·고정한 14사례(양성 8, 음성 6, 해시를 테스트로 고정) + `retrieval_queries.json` split=heldout |

held-out 14사례는 코드와 같은 AI가 썼습니다. 그래서 **코드로부터는 독립이지만 작성자의 어휘로부터는 독립이 아닙니다.** held-out에만 나오는 식별자(`bns_restore`, `hts_idx_load3` 등)는 사전에 넣지 않았습니다.

### 결과 (같은 평가셋, 전후)

**구조 지표**(기존 `queries`·`byDesign`, 합성·로컬)
- 모든 design에서 변화 0, 순위 변화 0, 경로 안정성 1.0 유지.
- 분류 자체는 바뀌지 않았으므로 phrasing의 구조 Recall은 여전히 0입니다.

**표현 사전 결과**(`wordingBySplit`, 합성·로컬 동일)

| split | 양성 found@1 | 다른 종류 문서 | 음성 기권 | 놓친 사례 |
|---|---|---|---|---|
| dev | 0 → 1.0 (6) | 0 | — | — |
| heldout | 0 → 0.75 (8) | 0 | 1.0 (6) | `ho-htslib-index-retrieve`, `ho-bedtools-invalid-record` |

놓친 2건은 파일 종류를 알려 주는 단어(`.vcf.gz`, `.bed`)가 경로 가림(`<path>`)으로 사라진 경우입니다. 사례나 사전을 고쳐 맞추지 않았습니다.

**기각한 대안과 비교**(`experiments/retrieval_queries.json`의 `unknown` 질의, top-1 문서의 원인 종류 기준. 이 질의 파일은 gitignore된 **로컬 전용**이라 CI에서는 해당 테스트가 건너뛰어집니다)

| 방법 | 코퍼스 | dev 맞음/틀림/기권 | heldout 맞음/틀림/기권 | 음성 오검출 |
|---|---|---|---|---|
| 자유 BM25 | 로컬 | 3 / 8 / 2 | 4 / 3 / 1 | 2 / 8 |
| 표현 사전 | 로컬 | 7 / 0 / 6 | 4 / 0 / 4 | 0 / 8 |
| 자유 BM25 | 합성 | 5 / 2 / 6 | 3 / 3 / 2 | 1 / 8 |
| 표현 사전 | 합성 | 7 / 0 / 6 | 4 / 0 / 4 | 0 / 8 |

벡터·하이브리드 검색과 재순위는 고르지 않았습니다.
- 원인이 순위가 아니라 분류 탈락이라, 재순위할 후보가 0개였습니다.
- 의미 검색은 자유 검색과 같은 "원인 단정" 위험을 가집니다. 새 의존성도 필요합니다.
- 다시 검토할 조건은 셋입니다: 사전이 못 다루는 표현이 실제 운영 입력에서 확인될 때, 검토된 정답이 늘었을 때, 의존성 설치가 승인됐을 때.

## 하지 않은 것과 이유

| 후보 | 판단 |
|---|---|
| 표현 변형 분류(퍼지 매칭) | (log 61 당시) recall 0을 그대로 기록했습니다. 규칙표 분류는 여전히 바꾸지 않았고, log 62에서 검색 전용 추정으로만 보완했습니다(위 절). 운영 입력은 항상 main.sh 템플릿입니다. 자유 검색은 잘못된 원인을 단정했습니다(48질의 중 8회, log 17.2). 표현이 다른 입력 경로가 생길 때 다시 봅니다 |
| 원인 안 순위용 동의어·키워드 메타데이터 | 놓친 2건을 고칠 수 있지만, 그 정답을 같은 AI가 제안했습니다. 사용자 검토로 등급이 확정된 뒤에 해야 과적합이 아닙니다 |
| contig 사례의 잘못된 문서 | 규칙표의 한 종류(`bed_content_invalid`)가 하위 변형 5개를 묶습니다. 문서에 "어느 하위 변형에 해당하는지" 메타데이터가 필요합니다. 로컬 발췌 파일(사용자 큐레이션)을 고쳐야 해서 승인 대상입니다 |
| 벡터·하이브리드·재순위 | 원인당 후보가 5개 이하이고, 놓친 2건은 어휘 차이입니다. 임베딩이 도울 수는 있지만 새 의존성이 필요하고, 검토된 등급 없이는 비교 근거가 없습니다 |

## CI와 검토

| 구분 | 내용 |
|---|---|
| CI(`pytest evals`) | 지표 단위 테스트(Recall·MRR·nDCG), 사례 파일 형식·개인정보, 템플릿 사례 회귀 하한, 알려진 공백이 그대로 보고되는지, 경로 안정성 |
| 사용자 검토 | `review.status`, `grades_local` 등급과 근거, coverage_gap을 "문서가 있어야 함"으로 바꿀지 |
| 로컬 전용 | `--corpus local` 결과(비공개 발췌) |

## 분석 단계 실패의 검색 입력 (log 65, 2026-11-23)

### 문제와 원인
- 01~06 단계의 도구 실패(예: `samtools index`, `gatk MarkDuplicates`)는 검색 입력이 되지 않고 "이 검사에 연결된 도구 명령이 파이프라인 코드에 없음"으로 제외됐습니다.
- main.sh는 이 실패를 `require_cmd_ok <label> <argv...>`로 기록합니다. 그래서 label마다 실행한 명령은 하나로 정해져 있습니다.
- 몇몇 `fail_step` 코드도 바로 앞의 명령 하나의 결과를 보고합니다.
- 그런데도 `commands.py`의 명령 표에는 VCF 검사 6종만 있었습니다.

### 바꾼 것
- `commands._ANALYSIS_FAMILIES`에 label·code 28종을 명령에 연결했습니다. 연결이 main.sh와 일치하는지는 테스트(`app/tests/test_doc_analysis_steps.py`)가 문자열로 확인합니다.
- 명령을 지어내게 되는 검사는 연결하지 않았습니다.
  - 존재·크기 검사: `fastp_missing`, `norm_empty`, `filter_empty`
  - grep·Python 검사: `recal_table`, `coverage_metrics`
  - 두 명령 파이프: `alignment_<lane>`
  - 여러 명령이 같은 이름을 쓰는 검사: `bam_validation`
  - ERR trap: `unexpected_error`
- lane 이름이 붙은 검사(`index_<lane>`, `fastqc_<lane>`, `fastp_<lane>`)는 family만 남깁니다. lane 이름에 시료명이 들어갈 수 있기 때문입니다.
- 원인 종류 발췌(curated)에는 연결하지 않았습니다. 발췌는 리소스 원인 종류로만 분류돼 있고, 새 분류를 만들지 않습니다. 같은 도구의 매뉴얼이 설정된 경우에만 그 명령 절을 검색합니다.

### 평가 (`analysis.py`, `cases.analysis.public.json`, 27사례 모두 `unreviewed`)
- 코퍼스는 합성 매뉴얼 2종(samtools, bcftools)입니다. 실제 문서 문장은 없습니다. 서버당 매뉴얼은 하나이므로 각 사례를 매뉴얼마다 한 번씩, 54회 실행했습니다.
- `--ablate`는 새 연결만 끈 상태, 즉 변경 전입니다.

| 지표 | 변경 전 | 변경 후 |
|---|---|---|
| inputAccuracy | 0.185 | 1.0 |
| 명령 절 Recall@1 / @3 / MRR (17질의) | 0 / 0 / 0 | 1.0 / 1.0 / 1.0 |
| abstain 정확도 (37회: 명령 없음·매뉴얼 없음·다른 도구 매뉴얼) | 1.0 | 1.0 |
| 다른 도구 매뉴얼에서 나온 문서 | 0 | 0 |
| curated hit | 0 | 0 |
| 명령 절 밖의 Agent 입력 후보 | 0 | 0 |
| 시료명 노출 | 0 | 0 |

- 합성 매뉴얼에서는 첫 hit이 구조적으로 명령 절에 놓입니다(옵션 조회·절 첫 단락이 먼저). 그래서 Recall은 **경로가 맞는지에 대한 회귀 방지**이고 순위 품질 주장이 아닙니다.
- 실제 매뉴얼 본문에서의 순위는 재지 않았습니다.
- 기존 평가셋(`cases.public.json`)의 결과는 합성·로컬 코퍼스 모두 변경 전과 바이트 단위로 같습니다.
