# ADR-001. 리소스 검사 실패 원인: 내부 분석과 외부 제공의 경계

ADR(Architecture Decision Record)은 설계 결정을 이유와 함께 남기는 기록이다.

- **상태:** 채택 (Accepted) — 기본 설계(B)는 사용자가 수용. **구현됨, 로컬 자동 테스트 통과(§10). 보안 검토 완료나 사용자 최종 승인을 뜻하지 않음.** Ubuntu 서버와 실제 LLM 호출로는 검증하지 않음
- **작성일:** 2026-11-13
- **기준 코드:** `main` @ `4822b41` (작업 트리 미커밋 변경은 이 결정과 무관)
- **관련 명세:** [P0-1 명세 v3](../specs/P0-1_resource_bundle_causes.md) (이하 "명세")
- **형식:** [AGENT_PLAN.md §7](../AGENT_PLAN.md)의 ADR 형식(상태 / 맥락 / 결정 / 대안 / 결과 / 재검토 조건)을 따르고, 요청된 항목을 더했다. 저장소에 독립 ADR 파일 규칙은 없었다. 번호는 `docs/adr/`의 첫 문서라서 001이다. AGENT_PLAN 안의 `ADR-01`–`ADR-08`과는 별개의 번호 체계다.

근거 표기:

| 표기 | 의미 |
|---|---|
| [코드] | 저장소 코드나 테스트로 확인 |
| [명세] | P0-1 명세 v3의 합의 사항 |
| [제안] | 이 ADR이 제안하는 결정. 승인 전 |

---

## 1. 맥락: 해결하려는 문제

### 1.1 문제

- `00_input_validation`의 `resource_bundle` 검사가 실패해도 step 문서에는 고정 문장 하나만 남는다. 세부 원인 문장은 보고서 `resource_validation.txt`와 `pipeline.log`에만 있다 [명세 §1, §2].
- 실제 사례:
  - `3a22c5`: BED 2개 누락
  - `b94559`: BED 2개 누락 + `bcftools` 없음 2건
  - Agent는 이 원인들을 구분할 수 없다.
- 명세는 Backend가 이 기록을 규칙으로 분류해 공개 API와 Agent 양쪽에 같은 정보 보호 규칙으로 제공하라고 정했다 [명세 FR-11·12·15, NFR-2].

이 ADR이 정하는 것은 **분석 코드와 정보 보호 코드를 어디에 두고, 둘 사이의 경계를 어떻게 지킬지**다.

### 1.2 코드에서 확인한 사실

**F1. `step_reader`는 직접 읽지 않는다 [코드]**
- [step_reader.py:1-22](../../backend/app/services/step_reader.py#L1-L22)의 docstring은 "This module reads nothing itself"라고 밝힌다.
- 이 모듈은 기존 reader 세 개를 한 step 기준으로 조합할 뿐이다.

**F2. `step_reader.read()`의 dict는 공개 응답으로 그대로 펼쳐진다 [코드]**
- [steps.py:60](../../backend/app/api/steps.py#L60): `StepDetailResponse(jobId=..., runId=..., **payload)`
- 따라서 이 dict에 원문 필드가 들어가고 응답 모델에 같은 이름의 필드가 있으면, **가리지 않은 원문이 공개 응답으로 나간다.**
- `StepDetailResponse`는 별도 `model_config`가 없는 `BaseModel`이다 [schemas.py:359](../../backend/app/schemas.py#L359). 선언되지 않은 키는 버려진다(Pydantic 기본 동작).

**F3. Agent 쪽은 같은 dict를 받아 허용 필드만 다시 고른다 [코드]**
- `step_evidence.read_step_evidence()`가 `step_reader.read()`를 호출하고, `_project()`로 허용된 필드만 고른다. 남은 문자열은 모두 `redactor.text()`를 거친다 [step_evidence.py:152-221](../../backend/app/services/agent/step_evidence.py#L152-L221).

**F4. `Redactor`가 무엇을 가리는지 [코드]**
- [privacy.py:127-152](../../backend/app/services/agent/privacy.py#L127-L152)에 있다.
- 형태 규칙으로 가리는 것: Windows·POSIX·상대 경로, 데이터 파일명, 32자 이상 hex
- literal(서버가 아는 식별자 값)로 가리는 것: sample·run·job id
- 1000자(`MAX_TEXT`)를 넘으면 ` ...(truncated)`를 붙인다.
- 제어 문자는 제거하지 않는다.

**F5. Job별 `Redactor`는 Agent 쪽에서만 만든다 [코드]**
- literal 목록을 조립하는 곳은 `run_scope.for_job()` 내부 한 곳뿐이다 [run_scope.py:69-112](../../backend/app/services/agent/run_scope.py#L69-L112).
- 이 함수는 DB를 직접 조회하고, Agent 전용 `RunScope`(sink, 예산 포함)를 만든다.
- **공개 API 경로에는 `Redactor`를 만드는 코드가 없다.**
- `app/api/*`는 현재 `services.agent`를 import하지 않는다.

**F6. 공개 API의 기존 보호 방식은 Agent와 다르다 [코드]**
- `step_reader._io()`는 절대경로 입력·출력을 응답에서 뺀다 [step_reader.py:62-88](../../backend/app/services/step_reader.py#L62-L88).
- check `detail`과 failure `message`는 가리지 않고 그대로 낸다.
- polling 응답 `logTail`은 서버 경로를 그대로 노출한다 [run_context.py:41-44](../../backend/app/services/explanation/run_context.py#L41-L44).

**F7. `StepEvidence` 필드는 테스트로 고정되어 있다 [코드]**
- [test_agent_step_tool.py:402-422](../../backend/app/tests/test_agent_step_tool.py#L402-L422) `test_step_evidence_fields_are_pinned`
- docstring: "adding a field must be a decision"
- 필드를 추가하면 이 테스트는 **의도적으로** 실패한다.

**F8. Agent가 받은 결과는 통째로 검증 근거가 된다 [코드]**
- `tools.credit()`은 tool이 반환한 dict 전체를 guardrail(LLM 출력 검증)의 fact 집합에 넣는다 [tools.py:173-192](../../backend/app/services/explanation/llm/tools.py#L173-L192).
- 따라서 새 필드에 들어간 문자열과 숫자는 모델이 인용할 수 있는 "확인된 사실"이 된다.

**F9. 샘플 식별자가 비어 있는 행이 있을 수 있다 [코드]**
- `jobs.sample_id`는 nullable이다 [db.py:36](../../backend/app/db.py#L36).
- privacy.py docstring은 이 컬럼이 생기기 전에 쓰인 행에서 값이 null이라고 밝힌다.
- 반면 00 단계는 `step_metric sample "$SAMPLE_ID"`를 기록한다 [main.sh:1853](../../script/main.sh#L1853).
- 로그에는 `sample 'DEMO_WES'` 같은 줄이 있다 [명세 AS-IS 14].

**F10. 재사용할 테스트 자산이 있다 [코드]**
- `conftest.RunBuilder`
  - `step()`, `metrics()`, `raw()`로 run 디렉터리를 합성한다.
  - `as_failing_precheck()`는 `required_tools` FAIL만 있고 `resource_bundle` 행은 없다.
- `test_reference_bundle_validation.py`
  - main.sh에서 `PYBUNDLE` heredoc을 추출해 실행하는 fixture가 있다 (22-34행).
- `test_step_detail.py`
  - 24개 테스트. 절대경로 미노출, 계획 밖 step 404 등을 검증한다.

### 1.3 명세와 코드가 충돌하거나 명세에 없는 점

**C1. 고정 테스트 수정이 필요하다**
- 명세 T-11은 "기존 필드 동일"만 요구하고, `test_agent_step_tool.py`의 무수정 통과는 요구하지 않는다.
- 하지만 F7 때문에 고정 테스트는 **반드시 갱신**해야 한다.
- 이것은 명세 위반이 아니다. 고정 테스트가 요구하는 "명시적 결정"이며, 이 ADR이 그 결정 근거다.

**C2. "기존 Job별 `Redactor` 재사용"을 그대로 하기 어렵다**
- 명세 NFR-2는 이 재사용을 요구한다.
- 그러나 공개 API에서 재사용할 생성 함수가 없다 (F5).
- 구현할 때 기존 코드(`run_scope.py`)를 동작을 바꾸지 않는 범위에서 조금 고쳐야 한다 (§3.2 D4).

**C3. 샘플 식별자 노출 가능성 (명세 미반영)**
- 명세 FR-7·NFR-2는 출력에 샘플 식별자가 0회 나와야 한다고 요구한다.
- `sample_id`가 null인 행에서는 literal이 없어 이를 보장할 수 없다 (F9).
- 명세는 이 경우를 다루지 않는다. **§6 Q-A로 사용자 결정을 요청한다.** 이 ADR은 임의로 확정하지 않는다.

**C4. 제어 문자 제거 기능이 없다**
- 명세 NFR-10은 제어 문자 제거를 요구한다.
- `Redactor`에는 이 기능이 없다 (F4). 새 코드가 필요하다.

---

## 2. 검토한 대안

| | A. 하나의 모듈 | **B. 내부 분석과 외부 제공 분리 (선택)** |
|---|---|---|
| 구조 | 한 모듈이 파일 읽기, 분류, 정보 가리기, 응답 모델 생성을 모두 한다. 가린 결과만 밖으로 낸다 | 분석 모듈은 원문을 담은 **내부 값**을 만든다. 별도 투영(projection) 함수가 이를 가려 **외부 응답 모델**로 바꾼다 |
| 장점 | 파일 수가 적다. 원문이 모듈 밖으로 나가지 않는다 | 기존 코드의 역할 분리와 일치한다: `step_reader`(조합)와 `step_evidence`·`privacy`(투영·가리기), F1·F3. 분류 규칙을 정보 보호 없이 원문 그대로 테스트할 수 있다(NFR-9 heredoc 계약 테스트). 향후 방법 B(구조화 JSON 보고서)로 출처를 바꿔도 투영 코드는 그대로다(NFR-8) |
| 단점 | 분석 모듈이 `Redactor`(Agent 패키지)에 의존한다. 분류 테스트에도 가리기가 섞여, 규칙 오류와 가리기 오류를 구분하기 어렵다. 출처를 JSON으로 바꿀 때 정보 보호 코드도 함께 건드린다. 나중에 내부용 원문이 필요한 소비자(예: 복구 전 조건 확인)가 생기면 다시 쪼개야 한다 | 원문을 담은 내부 값이 실수로 응답에 실릴 위험이 생긴다(F2 경로). 이 위험은 §3.3의 경계 규칙과 테스트로 막아야 한다. 파일이 하나 늘어난다 |
| 명세 적합성 | FR-15(공통 분석) 충족. NFR-8(출처·분류 분리)이 약함 | FR-15, NFR-8 충족 |

검토했으나 제외한 변형:

| 변형 | 제외 이유 |
|---|---|
| B-1. `step_reader.read()`가 분석 결과(원문)를 dict에 넣고 두 소비자가 각자 가리기 | F2 때문에 공개 응답 모델에 필드가 선언되는 순간 원문이 그대로 나간다. 또 `step_reader`가 "직접 읽지 않는다"는 역할(F1)이 깨진다 |
| B-2. 두 소비자가 각자 투영 함수를 가짐 | Q8로 정보 보호 규칙이 같으므로 투영 함수가 둘이면 서로 어긋날 수 있다(FR-15 위반 위험) |

---

## 3. 결정 [제안]

### 3.1 구조

```
                        ┌──────────────── 내부 (원문 있음) ────────────────┐
 step_reader.read()     │                                                 │
 (변경 없음) ──────────▶ │  validation.results                             │
                        │        │                                        │
 Job 행(run_dir) ─────▶ │  resource_bundle_causes.analyze()               │
                        │   ├ 출처 읽기 (보고서 → 로그, 끝 256 KiB, 구간)    │
                        │   ├ 블록 추출                                    │
                        │   └ 규칙표 분류                                  │
                        │        │                                        │
                        │  ResourceBundleAnalysis (frozen dataclass)      │
                        └────────┼────────────────────────────────────────┘
                                 │  ← 경계: 이 지점을 넘는 길은 투영 함수 하나뿐
                        resource_bundle_diagnosis.project(analysis, redactor)
                                 │
                        ResourceBundleDiagnosis (Pydantic, 가린 값만)
                          ┌──────┴───────┐
              api/steps.py           step_evidence._project()
       StepDetailResponse          StepEvidence
       .resourceBundleDiagnosis    .resourceBundleDiagnosis
```

### 3.2 구현 위치

모듈 이름은 제안이다.

**D1. 내부 분석 — 새 모듈 `backend/app/services/resource_bundle_causes.py`**
- 입력:
  - `run_dir`
  - `step_id`
  - `step_reader.read()`가 이미 만든 `validation.results`
- 입력 방식의 이유:
  - step 문서를 다시 읽지 않는다.
  - 해당 check가 FAIL이 아니면 파일을 열지 않는다 (FR-1·2).
- 출력: `ResourceBundleAnalysis | None`
  - 00 이외 step이면 `None`
  - 원문 문장(`raw_text`), 분류 결과, 상태, 출처, 잘림 여부, 원문 발췌를 담는다.
- 형식:
  - `@dataclass(frozen=True)`로 만들고 Pydantic 모델로 만들지 않는다.
  - 그래서 `response_model`이나 `StepDetailResponse(**...)`에 실수로 넣어도 직렬화 대상이 되지 않는다. FastAPI·Pydantic이 임의 dataclass를 응답 필드로 받는 경로를 원천적으로 만들지 않기 위해서다.
- 내부 구성: 출처 읽기, 블록·구간 추출, 규칙 분류를 함수 단위로 나눈다.
  - 규칙표는 이 모듈 안에 데이터(튜플 목록)로 둔다 (NFR-8).
  - 출처 읽기는 "출처 → 줄 목록" 형태의 작은 함수로 둔다. 방법 B가 생기면 그 앞에 끼울 수 있다.
- step id `00_input_validation`과 check 이름 `resource_bundle`은 **이 모듈의 상수로만** 둔다. 소비자는 step id를 비교하지 않는다.
- import 제한:
  - `privacy`, `schemas`, `services.agent`를 import하지 않는다.
  - 원문을 서버 로그(`logging`)에 쓰지 않는다 (NFR-2).

**D2. 외부 투영 — 새 모듈 `backend/app/services/resource_bundle_diagnosis.py`**
- `project(analysis: ResourceBundleAnalysis | None, redactor: Redactor) -> ResourceBundleDiagnosis | None`
- 문자열 처리 순서: 제어 문자 제거(NFR-10) → `redactor.text()`(F4) → **공개 조건 검사** (v4 추가).
- 공개 조건 (fail-closed, 명세 NFR-2 v4):
  - Job의 `Redactor`에 샘플 literal이 있어야 한다. 이는 `run_scope.SAMPLE_PLACEHOLDER`로 확인한다.
  - 가린 뒤에 경로 흔적, 32자 이상 hex, 식별자 literal이 남지 않아야 한다.
  - 둘 중 하나라도 못 넘으면 그 문자열은 `null`이 되고 `withheldTextCount`에 센다.
- 분류 필드(`kind`, `resourceRole`, `tool`, `ruleId`)는 규칙표의 고정 어휘이므로 그대로 복사한다. 공개 조건과 무관하게 유지된다.
- **두 소비자가 함께 쓰는 유일한 투영 함수다** (B-2 제외 이유). 구현에서는 `diagnose(run_dir, step_id, checks, redactor)`가 `analyze()`와 `project()`를 묶는다. 두 소비자는 이 함수만 호출한다 (REFACTOR 단계에서 중복 제거).

**D3. 외부 응답 모델 — `ResourceBundleDiagnosis`, `ResourceBundleCause` (Pydantic)**
- `backend/app/schemas.py`에 둔다.
- 이유:
  - API 응답 모델이 모두 여기 있다.
  - `StepEvidence`도 이 모델을 그대로 필드 타입으로 쓰면 두 소비자의 모양이 구조적으로 같아진다 (FR-15).
- `StepDetailResponse`에 `resourceBundleDiagnosis: ResourceBundleDiagnosis | None = None`을 **최상위**에 추가한다 (FR-12).
- `CheckResult`는 바꾸지 않는다.

**D4. 공개 API용 `Redactor` 생성**
- `run_scope.for_job()` 안의 literal 조립 부분(86-99행)을 Job 행을 받는 순수 함수로 분리한다.
- `for_job()`과 `api/steps.py`가 이 함수를 함께 쓴다.
- `for_job()`의 동작은 바뀌지 않는 리팩터링이다. 기존 Agent 테스트가 이를 확인한다.
- 이 경우 `app/api/steps.py`가 `services.agent.privacy`를 import하는 첫 API 모듈이 된다 (F5). 이 의존 방향은 §5와 §8 재검토 조건에 기록한다.
- `privacy.py`를 옮기는 것은 이번 범위가 아니다.

**D5. 소비자 연결**
- `api/steps.py`
  1. `step_reader.read()` 호출 (변경 없음)
  2. `analyze()` 호출
  3. 이미 읽은 `row`로 `Redactor` 생성
  4. `project()` 호출
  5. 결과를 `StepDetailResponse(..., resourceBundleDiagnosis=...)`에 **명시적 키워드**로 넣는다.
  - `payload` dict에 섞지 않는다.
  - DB 조회는 늘지 않는다 (`_load_job`이 이미 행 전체를 읽음).
- `step_evidence.read_step_evidence()`
  - `step_reader.read()` 다음에 같은 두 함수를 `scope.redactor`로 호출하고 `_project()`에 넘긴다.
  - `StepEvidence`에 같은 필드를 추가하고, 고정 테스트(F7)를 갱신한다.
- MCP 서버(`agent_mcp/server.py`)와 tool 이름, 예산은 바꾸지 않는다.
  - 새 필드는 기존 `get_step_detail` 반환값 안에 실린다.
  - 출력 schema 테스트(`test_output_schema_is_the_projection`)는 `model_fields`를 비교하므로 자동으로 따라온다.

**D6. 바꾸지 않는 모듈:** `step_reader.py`, `run_status_reader.py`(기존 `read_log_tail` 포함), `result_reader.py`, `artifact_reader.py`, `privacy.py`, `agent_mcp/server.py`, `main.sh`

### 3.3 내부와 외부의 경계 규칙

| # | 규칙 | 지키는 방법 |
|---|---|---|
| E1 | 원문(`raw_text`, 원문 발췌)은 `ResourceBundleAnalysis` 밖으로 나가지 않는다. 밖으로 나가는 길은 `project()` 하나다 | 내부 값은 dataclass, 외부 값은 Pydantic으로 타입을 분리. 소비자는 `project()` 결과만 응답에 넣음 |
| E2 | 분석 결과를 `step_reader.read()`의 dict에 넣지 않는다 | F2의 `**payload` 경로 차단. 경계 테스트(§7 V3) |
| E3 | 분석 모듈은 정보 보호 코드를 모르고, 투영 모듈은 파일을 모른다 | import 방향: 분석 ← 투영 ← 소비자. 분석 모듈은 `privacy`·`schemas`를 import하지 않음 |
| E4 | 두 소비자는 같은 `project()`와 같은 literal 규칙을 쓴다 | D4의 공용 생성 함수. 일관성 테스트(§7 V5) |
| E5 | 원문은 서버 로그, 예외 메시지, HTTP 오류 본문에 들어가지 않는다 | 분석 모듈의 예외는 내부에서 상태값으로 바꿈(NFR-5). 테스트에서 로그 출력 확인 |

---

## 4. 결과: 장점과 단점

**장점**
- 기존 역할 분리를 그대로 따른다 (`step_reader`는 조합, `step_evidence`·`privacy`는 투영). 기존 모듈 대부분을 고치지 않는다.
- 분류 규칙은 정보 보호와 섞이지 않은 원문 기준으로 테스트할 수 있다. main.sh 문구가 바뀌면 heredoc 계약 테스트가 바로 잡아낸다.
- 두 소비자가 같은 모델과 같은 투영 함수를 쓰므로 FR-15(값 전체 동일)가 구조적으로 보장된다.
- 출처가 구조화 JSON으로 바뀌어도 바뀌는 곳은 분석 모듈의 출처 읽기뿐이다.
- 공개 API 쪽 DB 조회 횟수는 늘지 않는다. polling 경로는 바뀌지 않는다.

**단점**
- 새 파일 2개, 기존 파일 4개를 수정해야 한다: `schemas.py`, `api/steps.py`, `step_evidence.py`, `run_scope.py`(D4).
- 원문을 담은 내부 값이 존재하는 한, 실수로 응답에 실릴 가능성은 테스트와 리뷰로만 막을 수 있다. 타입 분리는 실수를 줄일 뿐 불가능하게 만들지는 않는다.
- 공개 API가 Agent 패키지(`services.agent.privacy`)에 처음으로 의존한다.
- 고정 테스트 하나를 의도적으로 갱신해야 한다 (C1).

---

## 5. 위험

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| K1 | **샘플 식별자 노출.** `sample_id`가 null인 오래된 행은 literal이 없다. 로그의 `sample 'XXX'` 같은 문장이 참고 로그(`unparsedExcerpt`)나 `evidenceText`에 남을 수 있다 (F9) | FR-7 위반. 공개 API로 노출 | §6 Q-A 결정 전까지는 명세상 미해결. 테스트에서 `sample_id` null 행을 반드시 포함 (§7 V4) |
| K2 | **원문이 공개 응답으로 샘.** 누군가 분석 결과를 `payload` dict에 넣거나 내부 값을 직접 응답에 쓸 수 있다 (F2) | 서버 경로·파일명 노출 | E1–E2, 경계 테스트 V3, 공개 응답 전체 문자열 검사 V4 |
| K3 | **Agent 검증 근거가 넓어짐.** 새 필드의 문자열·숫자가 fact 집합에 들어간다 (F8). 원인 문장의 숫자(줄 번호, contig 길이 등)를 모델이 "확인된 사실"로 인용할 수 있다. 사용자 파일 내용(contig 이름)도 섞인다 | 근거 범위 확대. 지시처럼 보이는 문자열이 들어갈 여지 | 문자열 1000자 제한, 원인 50개 제한, 제어 문자 제거(NFR-10). 영향은 기존 A/B 평가로 측정. 기존 check `detail`도 같은 경로로 들어가므로 새 유형의 위험은 아님 |
| K4 | **기존 기능 회귀.** `run_scope.for_job()` 리팩터링(D4)이 Agent의 literal 순서(긴 것 먼저)를 바꿀 수 있다 | Agent 응답의 부분 치환 | 기존 `test_agent_step_tool.py`의 정보 보호 테스트(354-390행)를 수정 없이 통과해야 함 |
| K5 | **응답 지연.** 00 step 상세 조회마다 최대 256 KiB × 2를 읽는다 | 경미 | FR-1 조건(끝난 step의 FAIL)일 때만 읽음. 실행 중 polling에서는 해당 없음 (명세 NFR-7) |
| K6 | **새 import 방향.** `api` → `services.agent` | 패키지 경계가 흐려짐 | §8 재검토 조건 |

---

## 6. 사용자 결정이 필요한 사항

> **해소 (2026-11-13, 사용자 정책 P4·P5):**
> - b안을 넓혀 적용했다. `sample_id`가 없으면 **참고 로그와 `evidenceText`를 모두** 내보내지 않는다(`null`).
> - 구조화된 원인(분류 필드)은 남긴다.
> - b안의 "template에 샘플 이름이 없다"는 근거는 코드로 증명된 것이 아니어서, fail-closed 원칙에 따라 `evidenceText`도 제한했다.
> - a안(00 metrics `sample`을 literal로 추가)은 후속 개선 후보로 남긴다. 이를 쓰면 오래된 Job에서도 원문을 보여 줄 수 있다.
> - 아래는 결정 전 검토 기록이다.

**Q-A. `sample_id`가 null인 행의 샘플 식별자 처리 (K1, C3)**

선택지:
- a) 00 step metrics의 `sample` 값(F9)을 literal 후보에 추가한다.
  - 문제: 이 경우에만 Agent의 literal 규칙도 함께 바뀐다(E4 유지를 위해). 기존 Agent 동작을 바꾸는 것이라 명세 범위를 넘는다.
- b) literal이 없으면 `unparsedExcerpt`를 제공하지 않는다. `evidenceText`는 원인 문장 template에 샘플 이름이 들어가지 않으므로 그대로 둔다.
  - 근거: 경로·파일명은 형태 규칙으로 가려진다.
  - 단, 이 근거는 [코드]로 확인한 것은 아니고 [명세 §7.3]의 template 목록에 기반한다.
- c) 현재 명세대로 두고, 위험으로만 기록한다.

추천: **b**. 명세를 넓히지 않으면서 노출 가능성이 가장 큰 경로(로그 발췌)만 닫는다. 결정에 따라 명세 FR-9를 수정해야 할 수 있다.

---

## 7. 검증 방법 (TDD로 옮길 항목)

| # | 검증 | 대상 | 재사용 자산 |
|---|---|---|---|
| V1 | 분석 모듈 단위 테스트: 상태 6종, 출처 선택, 구간, 상한, 규칙 분류 (명세 T-01–T-07, T-13, T-14, T-16) | D1 | `conftest.RunBuilder.raw()` (보고서·로그 합성), 합성 문자열 |
| V2 | heredoc 계약: 원본 `PYBUNDLE` 출력을 분석 모듈이 기대한 `kind`로 분류 (명세 T-09) | D1 규칙표 | `test_reference_bundle_validation.py`의 추출 fixture |
| V3 | 경계: `step_reader.read()` 결과 키에 새 필드가 없음. `StepDetailResponse`·`StepEvidence`의 새 필드 타입이 Pydantic 투영 모델임 | E1–E2 | — |
| V4 | 정보 보호: S1·S2·S8 입력으로 공개 API 응답 JSON 전체와 `StepEvidence` JSON 전체에 경로·64자 hex·`sample_id`가 0회. `sample_id` null 행 포함 (명세 T-08) | D2, D4 | `test_agent_step_tool.py`의 "누출할 것이 있는 fixture" 방식(326행) |
| V5 | 소비자 일관성: 같은 run의 공개 API 필드와 `StepEvidence` 필드가 값 전체로 같음 (명세 T-15) | E4 | `client`, `make_job`, `scope` fixture |
| V6 | 하위 호환: `test_step_detail.py` 24개를 수정 없이 통과. 다른 step은 `null`. `CheckResult` 모양 불변 (명세 T-10) | D3, D5 | 기존 테스트 |
| V7 | Agent 회귀: `test_agent_step_tool.py`에서 고정 필드 테스트 **하나만** 갱신하고 나머지는 수정 없이 통과 (C1, K4) | D4, D5 | 기존 테스트 |
| V8 | 파일 접근: FR-1 조건이 아니면(PASS, 다른 step, 실행 중) 두 출처를 열지 않음 (명세 T-03, T-18) | D1 | monkeypatch로 열기 감시 |
| V9 | 원본 불변, 서버 로그에 원문 없음 (명세 T-12, E5) | D1 | `caplog` |

---

## 8. 변경하지 않을 기존 동작

- `step_reader.read()`의 입력, 출력 키, 동작
- `run_status_reader.read_log_tail()`과 polling 응답 `logTail` (경로 노출 개선은 별도 과제)
- `StepDetailResponse`·`StepEvidence`·`CheckResult`의 기존 필드 이름·타입·의미
- `Redactor`의 규칙과 `MAX_TEXT`
- `run_scope.for_job()`의 외부 동작 (D4는 내부 분리만)
- MCP tool 이름, 입력 schema(stepId만), 예산 `DEFAULT_MAX_DISTINCT_STEPS = 2`, sink 기록 방식
- main.sh, step 판정, 실패 코드, 원본 Run 파일

---

## 9. 재검토 조건

- **방법 B 도입:** main.sh가 구조화 JSON 오류 보고서를 쓰기 시작하면 D1의 출처 읽기를 교체한다. 규칙표 문장 일치를 계속 유지할지 다시 판단한다.
- **원문이 필요한 내부 소비자 등장:** 예를 들어 복구 전 조건 확인. 그때 내부 값을 공개 범위로 바꾸지 말고, 원문 접근을 그 소비자로만 제한하는 방안을 검토한다.
- **두 소비자의 정보 보호 규칙이 갈라질 때:** Q8이 바뀌는 경우다. B-2(소비자별 투영)를 다시 검토하고 FR-15를 고친다.
- **`api` → `services.agent` 의존이 늘어날 때:** 두 번째 API 모듈이 `privacy`를 쓰게 되면 `privacy.py`를 공용 위치(`services/` 바로 아래)로 옮기는 것을 검토한다.
- **운영 측정 결과:** 256 KiB·50개·1000자 상한을 넘는 실제 기록이 관측되거나, `unknown` 비율이 높게 나오면 명세 NFR-6과 규칙표를 재검토한다.
- **K3 측정:** A/B 평가에서 새 필드 때문에 잘못된 인용이나 근거 오남용이 늘면 Agent 쪽 투영 범위(예: `evidenceText` 제외)를 재검토한다.

---

## 10. 구현과 검증 결과 (2026-11-13)

### 10.1 구현 위치 (계획 대비)

| 계획 | 실제 | 차이 |
|---|---|---|
| D1 `services/resource_bundle_causes.py` | 같음. `analyze()`, `classify()`, frozen dataclass `RawCause`·`ResourceBundleAnalysis`, 규칙표 17개 | 없음 |
| D2 `services/resource_bundle_diagnosis.py` | 같음. `project()` + 공개 조건 + `diagnose()` | `diagnose()` 추가 (REFACTOR) |
| D3 `schemas.py` | `ResourceBundleCause`, `ResourceBundleDiagnosis`, `StepDetailResponse.resourceBundleDiagnosis` | `withheldTextCount` 필드 추가 (v4 정책) |
| D4 `run_scope.redactor_for_row()` | 같음. `for_job()`이 이 함수를 호출. `SAMPLE_PLACEHOLDER` 상수 추가 | 상수 추가 |
| D5 `api/steps.py`, `step_evidence.py` | 둘 다 `diagnose()` 호출, 키워드로 전달 | 없음 |
| C1 고정 테스트 | `test_step_evidence_fields_are_pinned`에 필드 1개 추가 | 없음 |

### 10.2 TDD 실행 기록

명령은 `backend/`에서 `.venv/Scripts/python.exe -m pytest -p no:cacheprovider ...`로 실행했다. Python 3.12.3, Windows.

| 단계 | 대상 | 결과 |
|---|---|---|
| 기준선 | 전체 `app/tests` | 687 passed, 1 skipped (Windows symlink 권한, 기존) |
| RED | 새 테스트 2개 파일 | 80 failed, 8 passed. 실패 원인: `'NoneType' object has no attribute ...` 63건, `KeyError: 'resourceBundleDiagnosis'` 10건, `assert None is not None` 4건, 골격 함수의 `NotImplementedError` 1건 등. 모두 미구현 때문이며 ImportError·환경 오류는 0건. 통과 8건은 "없어야 하는 것" 검사(파일을 읽지 않음, 원문 미노출 등)로, 구현 전에도 참인 것이 정상 |
| GREEN | 새 테스트 + `test_agent_step_tool.py` + `test_step_detail.py` | 187 passed |
| GREEN 회귀 | 전체 `app/tests` | 775 passed, 1 skipped |
| REFACTOR (`diagnose()`) | 전체 `app/tests` | 775 passed, 1 skipped |
| 추가 회귀 | `evals/test_real_runs.py` (보존된 실제 Run cba73e의 StepEvidence 누출 검사 포함) | 31 passed |
| 추가 회귀 | `evals/` 순수 테스트 4개 파일 | 211 passed, 3 skipped (기록된 모델 답변 없음, 기존) |
| 변이 검사 | 핵심 규칙을 일부러 망가뜨림 → 새 테스트가 잡는지 | 공개 조건 끔: 3 fail. 보고서 → 로그 전환 오류: 4 fail. START 구간 무시: 2 fail. 잔여 검사 끔: 1 fail. 원복 후 88 passed |

### 10.3 새 테스트 88개의 근거 구분

| 구분 | 개수 | 내용 |
|---|---|---|
| 실제 Run (아카이브, 읽기 전용 임시 추출) | 7 | 3a22c5 원인 2개, b94559 원인 4개(bcftools 2개 role `unknown`), 68aa20 `not_applicable` + 파일 미접근, 원본 불변. API·Agent 경유 2건 + 68aa20 API 1건 |
| heredoc (main.sh 원본 `PYBUNDLE` 실행) | 4 | 빈 PATH로 bcftools 부재 재현 포함. 출력된 모든 원인 줄이 규칙에 일치 |
| 합성 | 77 | 규칙표 26, 상태·출처·구간·상한, 정보 보호, API·Agent 일치, 경계 |

아카이브가 없는 환경에서는 실제 Run 7개가 skip으로 표시된다.

### 10.4 검증하지 못한 것

- frontend Zod 파싱
  - 코드만 확인했다: `z.object`이고 `.strict()`가 없다.
  - frontend 테스트 환경이 없고 이번 범위에서 frontend 변경이 금지되어 실행하지 않았다.
- 실제 Claude CLI·MCP stdio를 통한 end-to-end 호출과 guardrail 결과 (K3). fact gate 기존 테스트는 통과했다.
- Ubuntu 서버의 실제 파일 권한, 대용량 운영 로그.
- 명세 U5: 알려진 형태 외의 식별정보.

## 부록. 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-11-13 | 제안 작성. 구현·테스트 없음 |
| 2026-11-13 | 사용자가 B 수용. 정책 P1–P6 반영(D2 공개 조건, §6 Q-A 해소). 구현·로컬 검증 결과 §10 추가. 상태를 채택(구현됨, 최종 승인 대기)으로 변경 |
