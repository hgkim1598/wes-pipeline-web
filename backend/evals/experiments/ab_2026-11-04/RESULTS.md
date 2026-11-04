# A/B 비교 실험 — real_cba73e, 2026-11-04

## 무엇을 비교했나

| | A (기존) | B (개선) |
|---|---|---|
| 코드 | `ed12c18` (git worktree, detached) | `600cca4` (main) |
| promptHash | 08c1f9035445420a | 4a4f2d9ddf604ce8 |
| knowledgeHash | 448e9866a674441d | 1ab94103bca81358 |

두 커밋 사이에서 모델 입력을 바꾸는 파일은 `prompt.py`, `wes_diagnostics.json`, `wes_failures.json` 셋뿐이다.
payload 생성(contract), provider, MCP 서버, 나머지 Knowledge, `real_runs.py`는 두 커밋에서 같다(`git diff`로 확인).
**프롬프트와 Knowledge를 함께 바꿨으므로, 결과 차이를 둘 중 하나의 효과로 나눌 수 없다.**

## 실행 조건

- **데이터**: 같은 실제 Run `real_cba73e`, 같은 capture(manifest `8f54e06e88d5…`). 6회 모두 `captureUnchanged: true`.
- **모델**: 설정은 양쪽 모두 `sonnet` alias다. 기록된 모델도 6회 모두 `claude-haiku-5-5`, `claude-sonnet-5-5`로 같다.
  - Haiku가 함께 기록된 것은 CLI(2.1.316) 동작이다.
  - Day 3(2026-11-02) 기록에는 Sonnet만 있다. 그래서 오늘 A를 다시 생성해 비교했다.
- **variant와 설정**: variant v3(MCP Tool 제공). CLI는 `--setting-sources ""`로 사용자 설정을 읽지 않는다.
- **인증**: `claude auth status`의 authMethod는 `claude.ai`(구독)다. `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN`은 없고, `--bare`는 쓰지 않는다.
- **실행 순서**: A1 → B1 → A2 → B2 → A3 → B3를 교차로 실행했다(2026-11-04 02:59–03:02 UTC).
- **실행 방법**: `run_eval.evaluate_real("real_cba73e", variant="v3")`을 scratchpad의 얇은 wrapper로 호출하고, 기록을 이 폴더에 새 파일로 저장했다.
  - wrapper가 필요했던 이유: 기존 `--record-baseline` 파일 이름에는 날짜만 들어가서, 같은 날 같은 버전의 두 번째 실행은 저장되지 않는다(`FileExistsError`).
  - 저장은 `write_baseline`(mode "x", 덮어쓰기 불가)로 했다.

## 실행 결과 (6회 중 5회 답변 확보)

| 실행 | 답변 | 결정론 평가 | 비고 |
|---|---|---|---|
| A1 | 있음 | 통과 | |
| A2 | **없음** | 실패 | 런타임 gate가 거부: 없는 근거 ID `dx:NM_MD_REPAIED`(오타)를 인용해 `unknownEvidenceRef` |
| A3 | 있음 | 통과 | |
| B1 | 있음 | 통과 | |
| B2 | 있음 | **실패** | `variant-count-carries-unfiltered-qualification`: uncertainties의 "52,294개 후보 기록 중…" 문장이 `lim:UNFILTERED_VARIANTS`를 인용하지 않음. 평가 단계 검사이며, 런타임에서는 답변이 그대로 나간다 |
| B3 | 있음 | 통과 | |

- MCP Tool 호출: 6회 모두 0회다(`toolUsed: false`). 호출하지 않은 이유는 기록되지 않는다.
- 숫자 보존(`numbers-preserved`)과 내부 필드 이름 검사는 답변이 있는 5회 모두 통과했다.

## 공통 기준 재채점 (`compare_versions.py`, 답변별)

| | A1 | A3 | B1 | B2 | B3 |
|---|---|---|---|---|---|
| 글자 수 | 1602 | 1647 | 1387 | 1636 | 1724 |
| 문장 수 | 20 | 18 | 17 | 19 | 21 |
| 응답 시간(ms) | 15375 | 14049 | 13619 | 14560 | 19353 |
| v1 용어 FAIL | 8 | 11 | 3 | 1 | 0 |
| v1 내부 표현 FAIL | 2 | 3 | 0 | 0 | 0 |
| v2 용어 FAIL | 8 | 11 | 2 | 0 | 0 |
| v2 내부 표현 FAIL | 2 | 3 | 0 | 0 | 0 |
| v2 경고 단계 수 | not_found | not_found | stated | stated | stated |
| v2 경고 단계 이름 | not_named | not_named | all_named | all_named | all_named |
| v2 평균 깊이 뜻·범위 | no_meaning_no_scope | no_meaning_no_scope | PASS | PASS | PASS |
| v2 0x 비율 뜻·범위 | no_scope | split | no_scope | PASS | no_scope |

- **응답 시간 평균**: A 14.7초(n=2), B 15.8초(n=3). 표본이 작아 차이를 말할 수 없다.
- **토큰 사용량**: 기록되지 않는다.
- **용어 FAIL의 내용**
  - A: depth와 read를 어디에서도 설명하지 않았다. A3는 dbsnp-rsid도 설명하지 않았다.
  - B1: dbsnp-rsid만 설명하지 않았다.
- **내부 표현 FAIL의 내용**
  - A: `resource bundle`, `dbsnp_vcf`(A1·A3), 서버 경로 `00_input_validation/resource_validation.txt`(A3)
  - B: 없음

## 문자열로 직접 확인한 것

| 표현 | A1 | A3 | B1 | B2 | B3 |
|---|---|---|---|---|---|
| resource bundle / dbsnp_vcf | 1 / 1 | 2 / 2 | 0 | 0 | 0 |
| `[NOTE]` | 0 | 1 | 0 | 0 | 0 |
| "겹치지 않" | 0 | 1 | 0 | 0 | 1 |
| "염기 단위" | 3 | 2 | 2 | 4 | 2 |
| "read에 덮이다"(수동형) | 0 | 0 | 0 | 0 | 0 |

- B의 "충분/부족" 표현은 모두 "충분한지는 … 판단할 수 없습니다" 형태다. 기준 없이 좋다/나쁘다를 판정한 문장은 없다.
- "근거가 부족"은 A와 B 모두에 있다. 검출 근거를 말하는 것이며 품질 판정이 아니다.

## 대표 문장 (같은 사실, 전후)

**평균 깊이**
- A1: "target 전체의 평균 깊이는 11.0116배이며, 평균이 0보다 커도 한 번도 읽히지 않은 위치가 있을 수 있습니다."
- B1: "target 한 위치를 평균 몇 번 읽었는지를 나타내는 평균 깊이는 11.0116배입니다. 이 프로젝트에는 합격 기준이 없어 충분한지는 이 값으로 판단할 수 없습니다."

**경고**
- A1 summary: "이번 실행은 끝까지 진행됐고, 경고와 함께 완료됐습니다." 단계 수와 이름이 없다.
- B1: "실행은 경고와 함께 완료됐고, 경고가 기록된 단계는 BAM 정리·보정, 커버리지 검사, 변이 검출의 3단계입니다."

**dbSNP 다음 확인**
- A3: "…resource bundle 검증 보고서(00_input_validation/resource_validation.txt)에서 dbsnp_vcf가 선언되지 않았다는 [NOTE] 항목을 보면 됩니다."
- B1: "dbSNP 파일이 지정되지 않았다는 기록을 확인하려면, 실행 산출물 목록의 'Resource validation report'를 보세요."

## 해석과 한계

**관찰된 개선** (이 Run, 이 표본에서)
- 경고 단계 수와 이름: B는 3/3, A는 0/2.
- 평균 깊이의 뜻과 판단 기준: B는 3/3, A는 0/2.
- 내부 설정 이름과 서버 경로: B는 0회, A는 2/2 답변에서 노출.
- 용어 FAIL은 v2뿐 아니라, 개선 전에 만든 v1 규칙으로 채점해도 줄었다.

**나빠졌거나 그대로인 것**
- "염기 단위"는 줄지 않았다(A 2~3회, B 2~4회). 설명 없이 남은 경우가 B1 1회, B2 3회다.
- 0x 비율의 해석 범위는 B에서도 3회 중 1회만 PASS다.
- "겹치지 않는 염기"는 B3에 한 번 남았다.
- B2는 변이 후보 수 문장에서 한계 근거 인용을 빠뜨려 결정론 평가를 하나 실패했다. A에는 이런 사례가 없지만, A는 답변이 2개뿐이고 A2는 다른 이유로 거부됐다.
- 응답 시간 차이는 판단할 수 없다. 프롬프트는 약 25% 길어졌다.

**한계**
- 표본이 작다(A 답변 2, B 답변 3). Run도 하나뿐이고, 개발에 쓴 Run(split dev)이다. 다른 Run에서도 같은 결과가 나오는지는 모른다.
- v2 검사기 규칙과 B 프롬프트는 같은 Day 2·Day 3 사례를 보고 만들었다. 그래서 v2 점수는 B에 유리하게 기울 수 있다. v1에서도 같은 방향이 나왔다는 것만이 이를 약하게 보완한다.
- 새 답변을 사람이 평가하지 않았다. HR01~HR04는 이전 답변에 대한 사용자 판단이다.
- 검사기는 문자열 규칙이다. 설명이 과학적으로 정확한지, 초보자가 실제로 이해하는지는 판정하지 않는다.
  - 예: B의 "한 위치를 평균 몇 번 읽었는지"는 depth의 accept 단서에 맞아 PASS다. 하지만 정의가 정확한지는 사람이 확인해야 한다.

## 파일

- `A_r*.json`, `B_r*.json`: 실행 기록 원문 6개 (모델 답변 `output` 포함)
- `compare_v1_v2.json`: `compare_versions.py` 출력
- `blind_sheet.md`: 라벨을 섞은 답변 5개 (사람 검토용)
- `blind_key_DO_NOT_OPEN_BEFORE_REVIEW.json`: 라벨과 A/B 대응표. 검토를 마친 뒤에 연다
