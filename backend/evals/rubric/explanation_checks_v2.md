# 설명 품질 검사 규칙 v2

`explanation_checks_v2.json`과 `evals/explanation_quality.py`의 `rules="2"` 경로를 설명한다.
v1(`explanation_checks_v1.json`)은 고치지 않고 남겨 둔다. v1 라벨 세트는 v1으로만 채점한다.
A/B 비교 때는 양쪽 답변을 v1과 v2 **둘 다로** 다시 채점한다(`evals/compare_versions.py`).

이 검사기는 평가 전용이다. `affectsDeterministic: false`이고 앱 코드는 이것을 import하지 않는다.
v2에서 새로 추가한 검사는 **모두 REVIEW까지만 낸다.** FAIL은 v1에 있던 규칙에서만 나온다.

## 근거 표기

| 표기 | 뜻 |
|---|---|
| 사용자 판단 | `human_review_v1/responses.json` HR01~HR04. 사용자가 직접 적은 판단 |
| AI 검토 | `human_review_v1/ai_review_v1.json` HR05~HR20. 사람 판정이 아니다 |
| 코드 사실 | 저장소 코드·실행 기록에서 확인한 것 |

## A. 어려운 표현 (`hardPhrases`, category internal)

| id | 잡는 표현 | 근거 |
|---|---|---|
| `nonoverlap-bases` (field-translation) | 겹치지 않는 염기, 겹치지 않게 센 (target/목표) 염기 | 사용자 판단 HR01·HR04. 코드 사실: payload `targetNonoverlapBases`의 직역 |
| `covered-by-read-passive` (hard-wording) | read에 (한 번도) 덮이다/덮인 | 사용자 판단 HR01. 같은 메모가 능동형은 상대적으로 쉽다고 해서 **수동형만** 잡는다 |
| `per-base-level` (hard-wording) | 염기 단위 | 사용자 판단 HR01("A/T/G/C 각각인가?"). 코드 사실: `prompt._HEAD`가 이 표기를 쓰라고 지시한다 |

- 같은 항목에 `explainedBy` 표현이 있으면 판정하지 않는다. 그런 표현의 예: "겹치는 구간을 합쳐 한 번만", "위치 하나하나".
- 없으면 REVIEW다. 표현 자체가 틀린 것은 아니므로 FAIL로 두지 않는다.
- 쉬운 문장(예: "DNA를 읽은 기록이 한 번도 없는 위치")이 잡히지 않는지 테스트로 확인한다.

**한계:** 관찰된 표현만 잡는다. 필드 이름 직역 전반을 찾아내지는 못한다. 새 표현이 보이면 근거와 함께 이 목록에 추가한다.

## B. 경고 사실 (category fact)

v1의 `warning-count-or-steps`는 수나 단계 이름 중 하나만 있어도, 위치와 상관없이 PASS를 냈다.
AI 검토 HR20은 Day 2가 경고 단계 수를 `uncertainties`에만 적었는데 PASS가 나왔다고 지적했다.

v2는 이것을 두 검사로 나눈다.

| 검사 | PASS | REVIEW |
|---|---|---|
| `warning-step-count` | summary·importantFindings 항목에 경고(또는 주의)라는 말과 정확한 단계 수가 함께 있음 (`stated`) | 수가 단계 수인지 불분명(`count_unit_unclear`) / 다른 그룹에만 있음(`secondary_only`) / 없음(`not_found`) |
| `warning-steps-named` | 경고 단계 이름이 모두 주요 위치에 있음 (`all_named`) | `secondary_only` / `partially_named` / `not_named` / 단계 이름을 알 수 없음(`labels_unknown`) |

- 경고 **단계 수**와 경고 **개수**를 섞지 않는다. 기준은 실행 기록의 `steps` 중 status가 warning인 단계 수다.
- `steps`가 없으면 `checkSummary.notable`의 WARN 행 중 `step_<id>`인 것을 쓴다.
- 실행 기록에 경고 단계가 없으면 이 두 검사는 내지 않는다. 기록에 없는 사실을 요구하지 않기 위해서다.
- 다른 수를 적으면 v1 규칙과 같이 따로 기록된다(수치 보존 검사는 결정론 평가가 맡는다).

## C. 용어 정책

1. **항목 단위와 답변 단위를 따로 기록한다.** 항목마다의 판정은 v1과 같다. 거기에 더해
   `terms[].explainedInAnswer`가 "답변 어딘가에서 한 번이라도 설명했는가"를 기록한다. 답변이
   그 용어를 쓰지 않았으면 null이다.
2. **모든 등장마다 같은 괄호 설명을 요구하지 않는다.** 다른 항목에서 설명한 용어는 v1과 같이
   `explained_elsewhere` REVIEW다. FAIL이 아니다.
3. **쉬운 말 대체를 인정한다** (`plainSubstitutes`). v2에서 추가한 표현:
   - read: "DNA를 읽은 기록/조각"
   - target: "분석하려고 정해 둔 위치/구간"
   - zero-coverage: "읽은 기록이 한 번도 없"
   - depth accept: "몇 번 겹치는". 근거는 AI 검토 HR09다.
4. **단계 이름 속 용어는 개념 설명이 필요한 용어와 구분한다** (`stepNameVariants`).
   - "BAM 처리/정리" 속의 BAM은 단계 이름을 바꿔 쓴 것이다. v2는 이것을 REVIEW `step_name_variant`로 둔다.
   - v1은 같은 경우를 never_explained FAIL로 셌다. 근거: AI 검토 HR05.
   - 정확한 단계 이름은 v1부터 판정에서 제외(mask)한다.
5. **정의의 정확성은 초보자 이해만으로 정하지 않는다.**
   - 쉬운 말 대체가 맞는지는 `wes_terms.json`의 definition·misreadings를 기준으로 사람이 본다.
   - 다른 곳에 검증되지 않은 정의가 있으면 v1과 같이 never_explained를 막는다.

## D. 수치의 뜻과 해석 범위 (`measurement-meaning:<metric>`, category fact)

- 대상: payload `coverage`의 `meanTargetDepth`, `zeroCoverageBasesPct`. 이 수를 적은 답변만 본다.
- PASS(`meaning_and_scope`): 같은 항목에서 무엇을 잰 값인지(뜻)와, 판단 기준이 없다는 것 또는 무엇을 판단할 수 없는지(범위)를 함께 말한다.
- REVIEW: 뜻과 범위가 다른 항목에 나뉨(`split`) / 범위 없음(`no_scope`) / 뜻 없음(`no_meaning`) / 둘 다 없음(`no_meaning_no_scope`).
- 근거: 사용자 판단 HR03 메모("평균 깊이 11배가 높은지 낮은지, 어떤 의미인지 판단하기 어려움").
- 이 검사는 "좋다/나쁘다"를 요구하지 않는다. 기준값 없이 좋고 나쁨을 말하는 답변을 잡는 검사도 아니다. 그것은 사람이 본다.

## beginner_v2.md와 다른 점

| 주제 | beginner_v2 (사람 채점) | 검사기 v2 |
|---|---|---|
| 다른 항목에서만 설명한 용어 | B2 1점(감점) | REVIEW `explained_elsewhere` (FAIL 아님) |
| 쓰지 않은 필수 용어 | 같은 사실을 전달했으면 충족 | 판정 없음. 사실 전달은 fact 검사가 본다 |
| 단계 이름 속 용어 | 필수 용어가 아니면 B2 감점 없음 | REVIEW `step_name_variant` |
| 정의 정확성 | `wes_terms.json` 기준으로 사람이 본다 | 문자열 신호만 본다. 정확성은 판정하지 않는다 |

## 한계

- 모든 검사는 문자열 패턴이다. 문장 뜻을 이해하지 못한다. REVIEW는 "사람이 볼 곳"이지 "나쁜 답"이 아니다.
- 경고 단계 수는 숫자와 한글 수사 1~8("세 단계")까지만 찾는다(`_KOREAN_COUNT`). "모두 3곳에서" 같은 다른 말로 바꿔 쓰면 `not_found`로 보일 수 있다. 측정값은 기록된 값의 문자열 그대로만 찾는다.
- 이 규칙들의 근거 사례 중 사람이 직접 판단한 것은 HR01~HR04뿐이다. 나머지 근거는 AI 검토다.
- 검사기의 정확도(정밀도·재현율)는 측정되지 않았다.
