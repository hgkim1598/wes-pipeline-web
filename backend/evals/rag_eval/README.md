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

## 사례 구성 (32개, 모두 `unreviewed`)

`design`은 그 사례가 무엇을 재는지입니다.

| design | 사례 | 재는 것 |
|---|---|---|
| `rule_replicating` | 14 | main.sh 템플릿 문장 → 규칙표 → 원인 종류. 종류가 맞으면 결과가 하나로 정해지므로 **규칙을 반복 확인할 뿐 검색 품질은 재지 못함** |
| `independent_ranking` | 12 | 같은 원인 종류에 문서가 여럿일 때 어느 것이 더 도움이 되는지. `grades_local`(0~2)과 근거(`grade_basis`)는 AI가 제안한 **잠정값** |
| `phrasing_variant` | 6 | 같은 뜻을 main.sh가 쓰지 않는 표현으로(약어, 셸 메시지, 다른 어순). 표현 변화에 대한 견고성 |

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

## 하지 않은 것과 이유

| 후보 | 판단 |
|---|---|
| 표현 변형 분류(퍼지 매칭) | recall 0을 그대로 기록했습니다. 운영 입력은 항상 main.sh 템플릿입니다. 자유 검색은 잘못된 원인을 단정했습니다(48질의 중 8회, log 17.2). 표현이 다른 입력 경로가 생길 때 다시 봅니다 |
| 원인 안 순위용 동의어·키워드 메타데이터 | 놓친 2건을 고칠 수 있지만, 그 정답을 같은 AI가 제안했습니다. 사용자 검토로 등급이 확정된 뒤에 해야 과적합이 아닙니다 |
| contig 사례의 잘못된 문서 | 규칙표의 한 종류(`bed_content_invalid`)가 하위 변형 5개를 묶습니다. 문서에 "어느 하위 변형에 해당하는지" 메타데이터가 필요합니다. 로컬 발췌 파일(사용자 큐레이션)을 고쳐야 해서 승인 대상입니다 |
| 벡터·하이브리드·재순위 | 원인당 후보가 5개 이하이고, 놓친 2건은 어휘 차이입니다. 임베딩이 도울 수는 있지만 새 의존성이 필요하고, 검토된 등급 없이는 비교 근거가 없습니다 |

## CI와 검토

| 구분 | 내용 |
|---|---|
| CI(`pytest evals`) | 지표 단위 테스트(Recall·MRR·nDCG), 사례 파일 형식·개인정보, 템플릿 사례 회귀 하한, 알려진 공백이 그대로 보고되는지, 경로 안정성 |
| 사용자 검토 | `review.status`, `grades_local` 등급과 근거, coverage_gap을 "문서가 있어야 함"으로 바꿀지 |
| 로컬 전용 | `--corpus local` 결과(비공개 발췌) |
