# A/B 평가 프로토콜

이 디렉터리의 각 JSON은 실험 하나의 조건을 **호출 전에** 고정한다. 실행기는
`../runner.py`이다. 이 문서에서는 다음을 다룬다.

- 프로토콜이 무엇을 잠그는지
- 두 arm의 코드가 어디서 오는지
- 파일 분류 검사가 실패했을 때 어떻게 하는지
- 버전 이력

## 1. 무엇을 잠그는가

- `prepare`는 프로토콜 파일 바이트의 sha256(`protocolSha256`)을 실험 기록에 남긴다.
- 호출할 때마다 `verify_integrity`가 이 값을 다시 계산한다. 값이 달라졌으면 호출하지 않는다.
- 따라서 **고정된 프로토콜 파일은 한 바이트도 고치지 않는다.**
  - 고치면 그 파일로 만든 실험이 모두 멈춘다. 모의 실험도 마찬가지다.
  - `evals/test_ab_protocol_sources.py`가 v1–v4의 해시를 고정해 둔다.
- 바꿔야 할 것이 생기면 **새 버전 파일**을 만든다.
  - 새 파일의 `supersedes`에는 `id`, `why`, `changed`, `unchanged`를 적는다.
- 같은 질문(가설·사례·지표·성공 기준)의 비교 가능성은 새 버전에서도 유지해야 한다.
  - 따라서 `unchanged`에 적은 항목은 실제로도 같아야 한다.
  - 테스트 `test_v4_changes_only_what_it_says_it_changes`가 이를 확인한다.

## 2. arm의 출처 (`arms.<arm>.source`)

| source | 의미 |
|---|---|
| `{"kind": "git", "commit": C}` | `git archive C`. arm A는 항상 이 형태다. |
| `{"kind": "workingTree"}` | arm B에만 쓸 수 있다. `prepare` 시점 작업 트리의 tracked + untracked-not-ignored 파일을 쓴다. |

- 실행기는 그 밖의 출처를 거부하고, 기본값으로 대신하지 않는다.
- 2026-11-23 이전의 실행기는 arm B의 source를 읽지 않고 항상 작업 트리를 복사했다.
  - v1–v3는 모두 `workingTree`였으므로 이미 만든 실험의 의미는 바뀌지 않는다.
- `evals/ab_compare/`, `ab_store/`, `experiments/`는 스냅샷에 들어가지 않는다(`STORE_EXCLUDE`).

**`workingTree`의 결과.** B가 계속 움직인다(v1–v3).

- 실험 전에 제품 코드를 고치면, 그 변경이 모두 B에 들어갈 후보가 된다.
- 그때 CI의 분류 검사(당시 이름 `test_the_current_working_tree_difference_is_fully_classified`)가 실패했다. 그 실패는 정상 동작이었다.
- v4부터 B는 커밋이다. 현재 검사 `test_the_default_protocol_explains_every_arm_difference`는 작업 트리와 무관하게 기본 프로토콜의 두 커밋 차이를 판정한다.
- 어느 경우든 검사를 건너뛰거나, 파일을 제외하거나, 분류를 대충 붙여 초록으로 만들지 않는다.

## 3. 파일 분류 (`diffClassification`)

A와 B에서 다른 파일은 모두 아래 세 분류 중 하나를 받아야 한다. 하나라도 빠지면 `prepare`와 `run`이 멈춘다.

| 분류 | 주장 | 확인 방법 |
|---|---|---|
| `intended` | 이 실험이 측정하려는 변경이다. | `intendedDifference`의 설명과 맞는지 사람이 검토한다. |
| `inertInCallPath` | import는 되지만, 바뀐 부분이 호출 중에 **실행되지 않는다.** | 바뀐 함수나 route가 호출 경로에서 불리지 않음을 코드로 보인다. 근거는 `reason`에 적는다. |
| `notInCallPath` | 호출 중에 import되지 않는다. | 실행기가 기계로 확인한다. worker가 기록한 import 목록에 있으면 실패한다. |

주의할 점이 세 가지 있다.

- **분류는 경로 단위다.**
  - 이미 분류된 파일을 나중에 또 고치면 검사는 통과한다.
  - 그러므로 분류된 파일을 고칠 때도 그 변경이 원래 주장 안에 있는지 다시 본다.
- **"사례가 다 끝났다"는 근거가 아니다.**
  - 실행은 되지만 출력이 같은 변경(예: 보존 Run에서 일어날 수 없는 상태를 다루는 규칙)은 `inertInCallPath`의 정의에 맞지 않는다.
  - 이런 변경을 받아들이려면 출력이 같다는 것을 보여야 한다. 받아들인 뒤에도 B가 바뀌었다는 사실은 남는다.
- **출력이 같다는 주장은 확인한다.** 아래 도구가 합성 사례에서 그것을 비교한다.

```
cd backend
python -m evals.ab_compare.equivalence --base <commit> [--head <commit>]
```

- 두 트리를 따로 준비하고, 각 트리마다 따로 띄운 Python에서 합성 agent 사례를 만든다.
- 그다음 다섯 가지를 digest로 비교한다.
  - 모델 입력(payload)
  - 허용 근거 id
  - 결정적 설명
  - Run 문맥
  - 각 단계의 Tool 결과
- 모델·CLI 호출은 막혀 있다.
  - provider 진입점이 예외를 던진다.
  - real-CLI guard가 `deny` 모드로 켜진다.
- 보존된 실제 Run 사례는 비교하지 않는다. 로컬 비공개 자료가 필요하기 때문이다.
  - 실제 사례의 동등성은 실험의 `payloads` 단계에서 확인한다. 이 단계에서는 모델을 부르지 않는다.

## 4. 분류 검사가 실패했을 때

실패 메시지에는 분류되지 않은 파일이 모두 나온다(`runner.unclassified_message`). 아래 순서로 처리한다.

1. **먼저 묻는다: 이 변경이 B에 들어가야 하는가?**
   - 측정할 변경과 무관한 제품 수정이라면, B를 이미 검토한 커밋에 고정하는 것이 맞다.
   - 그러면 이후의 무관한 수정이 실험을 건드리지 않는다. v4 초안이 이 방식이다.
2. B에 들어가야 한다면 **파일마다** 분류를 정하고 근거를 적는다.
   - `notInCallPath`라고 주장했다면 모의 실험의 import 목록으로 확인한다.
   - `inertInCallPath`라고 주장했다면 바뀐 코드가 실행되지 않음을 보인다.
   - 실행은 되지만 출력이 같다면, 3절의 도구 결과를 근거로 남긴다.
   - 이때 "이 변경이 B의 의미를 바꾸는가"는 사람이 결정한다.
3. 결과를 **새 버전 파일**로 쓴다.
   - `"draft": true`와 `draftNote`를 단다. `prepare`는 draft를 거부한다.
4. 사용자가 승인하면 다음을 한다.
   - `draft`와 `draftNote`를 지운다.
   - `fixedAt`을 채운다.
   - `test_ab_protocol_sources.py`의 `FIXED_PROTOCOL_SHA256`에 새 해시를 추가한다.
   - `runner.DEFAULT_PROTOCOL`을 새 버전으로 바꾼다.
   - CI의 분류 검사는 이때부터 새 버전으로 판정한다.
5. 이전 버전으로 만든 실험은 이전 버전으로 남긴다.
   - 결과를 새 버전 실험과 합치지 않는다. 버전이 다르면 다른 실험이다.

## 5. 버전 이력

| 버전 | 고정일 | arm B | 바꾼 것 | 만든 실험 |
|---|---|---|---|---|
| v1 | 2026-11-21 | workingTree | 최초 | 모의 실험만 |
| v2 | 2026-11-21 | workingTree | 파일 분류(`diffClassification`) 도입 | 모의 실험만 |
| v3 | 2026-11-22 | workingTree | Tool 결과(step_evidence·run_scope)에도 적용 판정 적용. 이 둘을 intended로 추가 | 모의 실험만 |
| v4 | 2026-11-23 (사용자 승인) | git `91ffab6` | B를 v3 분류가 CI에서 통과한 커밋에 고정. 나머지는 v3와 같다. **현재 기본값** | 없음 |

- v2와 v3는 모두 실제 호출 전에 B가 바뀌어서 생겼다.
- v4는 그 반복의 원인인 "움직이는 B"를 없앤다.
  - 근거와 기각한 대안은 v4의 `supersedes`에 있다.
  - 승인 전 확인: 고정 B의 차이 파일은 작업 트리 B의 진부분집합(run-state 변경만 빠짐), 하네스·게이트 코드 동일, scratch 저장소의 mock prepare + payloads에서 3사례 모두 검사 통과(모델 호출 없음).
- 제품 수정을 실험에 넣으려면 B 커밋을 바꾼 새 버전(v5)을 만든다. 그 자체가 검토 대상이다.
- 실제 모델로 비교한 실험은 아직 없다.
