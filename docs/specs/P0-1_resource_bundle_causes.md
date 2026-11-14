# P0-1 요구사항 명세 — 리소스 검사 실패의 세부 원인 제공

> SDD(Spec-Driven Development, 요구사항 명세를 먼저 쓰고 그 명세에 맞춰 테스트와 구현을 진행하는 방식) 문서
>
> - 상태: **v4 (구현 반영 중 정책 보완)**. 구현과 자동 테스트 결과는 [ADR-001](../adr/ADR-001-resource-cause-boundary.md) §10에 기록. 최종 승인은 사용자가 판단
> - 작성일: 2026-11-12 (Specify), 같은 날 Clarify·최종 결정 반영
> - 기준 코드: `main` @ `4822b41` (작업 트리에 미커밋 변경이 있으며, 이 명세와 관련된 파일은 아님)
> - 범위: Backend가 **이미 기록된** 오류 문서를 읽어 구조화하는 **방법 A**
> - 관련 문서:
>   - 직전 감사 결과(터미널 보고): P0-1 선정 근거
>   - `docs/HG002_RESOURCE_VERIFICATION.md`

## 0. 표기 규칙

모든 요구사항과 판단에 근거의 종류를 붙인다.

| 표기 | 의미 |
|---|---|
| **[코드]** | 저장소 코드나 실제 실패 Run 원본 기록으로 확인한 사실 |
| **[합의]** | 사용자와 합의한 결정 (Clarify 단계 결정 포함) |
| **[제안]** | 아직 확정하지 않은 제안. 구현 전에 확정해야 함 |
| **[미결정]** | 근거가 부족해 사용자 판단을 기다리는 항목. v3 기준 요구사항에는 없음 (남은 문제는 §10.3) |

실제 실패 Run 원본은 `wes_failure_evidence_20261112.tar.gz`(Git에 넣지 않음)에서 읽었다. 이하 Run은 끝 6자리로 부른다.

---

## 1. 문제 정의와 실제 실패 사례

### 1.1 문제

`00_input_validation`의 리소스 검사(`resource_bundle`)는 reference FASTA, BWA index, capture BED, known sites VCF 등을 한꺼번에 검사한다. 원인 문장의 template(문장 틀)은 약 20종이다 (§7.3).

그런데 단계 상태 문서(step JSON)에는 원인과 상관없이 다음 한 문장만 남는다.

```
resource_bundle  FAIL  "validation failed; see 00_input_validation/resource_validation.txt"
```

구체적인 원인 문장은 보고서 파일(`resource_validation.txt`)과 실행 로그(`pipeline.log`)에만 있다. Agent가 근거로 쓸 수 있는 유일한 경로(`get_step_detail`)로는 이 내용을 볼 수 없다.

그 결과 Agent는 다음을 할 수 없다.
- 실패 원인 식별: "BED 파일이 없다"인지 "reference 색인이 어긋났다"인지
- 복구 후 재검증 시 판정: "BED는 해결됐지만 다른 원인이 남았다"와 "BED가 해결되지 않았다"를 구분하는 것

근본 원인과 파생 증상(다른 문제 때문에 덩달아 생긴 오류)을 구분하는 일은 Agent에게 필요하다. 다만 **이 기능의 책임은 아니다** (FR-10). 이 기능은 그 판단에 쓸 재료만 제공한다.

### 1.2 실제 사례

| Run | 실제 기록 (원본) | 이 명세가 다뤄야 하는 이유 |
|---|---|---|
| `3a22c5` | `pipeline.log` 20–22행: `target_bed missing or empty: …`, `coverage_bed missing or empty: …` | 원인 2개를 각각 식별해야 함 |
| `b94559` | `pipeline.log` 20–24행: BED 누락 2건 + `bcftools unavailable for …: [Errno 2] No such file or directory: 'bcftools'` 2건. 같은 step에 `required_tools` FAIL (`missing from PATH: bwa samtools gatk bcftools …`) | 4개 원인을 각각 추출하고, `required_tools` 결과와 함께 볼 수 있어야 함. 둘 사이의 관계 판단은 범위 밖 |
| `68aa20` | 00 단계 PASS. `pipeline.log` 17·19행 `SHA-256 verified`, 24행 `[OK] Resource bundle is structurally compatible` | 통과한 검사에서 원인을 만들어내면 안 됨 |
| (합성) 알 수 없는 오류 | 실제 Run 없음. 코드상 `errors.append(str(exc))`가 존재 | 분류하지 못한 원문을 버리지도, 추측하지도 않아야 함 |

`d87484`는 00 단계가 PASS이므로(실패는 04 단계) 이 기능의 대상이 아니다. `68aa20`과 같은 `not_applicable` 사례로만 쓴다.

---

## 2. 현재 동작 (AS-IS) — 모두 [코드]

1. **검사 실행:** `validate_reference_bundle()`가 Python heredoc(셸 스크립트 안에 넣은 Python 코드 블록) `PYBUNDLE`을 실행한다. 출력은 `> "$report" 2>&1`로 `$RUN_DIR/00_input_validation/resource_validation.txt`에 보낸다. `>`이므로 **실행할 때마다 보고서를 덮어쓴다** ([main.sh:1891-1898](../../script/main.sh#L1891-L1898)).
2. **원인 수집:** `PYBUNDLE`은 원인을 `errors.append(...)`로 모은다. 실패하면 아래 형식으로 출력하고 종료 코드 2로 끝낸다 ([main.sh:2174-2179](../../script/main.sh#L2174-L2179)).
   ```
   [NOTE] …            (0줄 이상)
   [ERROR] Resource bundle validation failed:
     - <원인 문장>      (1줄 이상)
   ```
3. **로그 기록과 판정:** 셸은 `cat "$report"`로 보고서를 `pipeline.log`에도 복사한다. 종료 코드가 0이 아니면 `step_check_fail "resource_bundle" "validation failed; see …"`를 기록한다 ([main.sh:2193-2198](../../script/main.sh#L2193-L2198)).
4. **로그 누적:** `pipeline.log`는 `tee -a`(이어쓰기)로 기록된다 ([main.sh:1393](../../script/main.sh#L1393)). 같은 run 디렉터리를 다시 실행하면 이전 기록 뒤에 새 기록이 붙는다. 다시 실행하는 경우는 두 가지다.
   - `--resume`
   - `check_only` 결과 위에서 실제 실행을 시작하는 경우 ([main.sh:1374-1376](../../script/main.sh#L1374-L1376))
5. **Backend의 재실행:** Backend는 `--resume`을 넘기지 않고, 제출마다 새 run_id를 만든다 ([pipeline_executor.py:41-46](../../backend/app/services/pipeline_executor.py#L41-L46)). 따라서 **웹 제출 경로에서는 로그에 블록이 여러 개 생기지 않는다.** 운영자가 CLI로 직접 다시 실행할 때만 생긴다.
6. **원인 문장 template:** 고정 문장 약 20종과 자유 텍스트 1종이 있다 (`PYBUNDLE` 내부, [main.sh:1900-2186](../../script/main.sh#L1900-L2186)). §7.3에 목록을 정리했다. 일부 문장에는 사용자가 올린 파일 내용에서 온 값이 들어간다. 예: BED의 contig 이름 `contig absent from reference: {chrom}` ([main.sh:2065](../../script/main.sh#L2065)).
7. **Backend 읽기:** `step_reader.read()`는 step JSON, metrics, artifacts만 읽는다. 보고서와 로그는 읽지 않는다 ([step_reader.py:125-174](../../backend/app/services/step_reader.py#L125-L174)).
8. **기존 로그 읽기 방식:**
   - `run_status_reader.read_log_tail()`은 `pipeline.log` **전체**를 `read_text(encoding="utf-8", errors="replace")`로 메모리에 읽은 뒤, 마지막 200줄만 남긴다. 읽는 바이트 수에는 상한이 없다 ([run_status_reader.py:82-91](../../backend/app/services/run_status_reader.py#L82-L91)).
   - 이 결과는 polling 응답 `logTail`로 **경로를 지우지 않은 채** 공개된다 ([run_context.py:41-44](../../backend/app/services/explanation/run_context.py#L41-L44)의 주석이 이를 인정함).
9. **Agent 근거:** `step_evidence._project()`가 Agent에 넘기는 것은 check의 `name`·`status`·`detail`, failures의 `code`·`message`, metrics, 개수 필드뿐이다 ([step_evidence.py:178-221](../../backend/app/services/agent/step_evidence.py#L178-L221)). 문자열은 Job별 `Redactor`(경로·해시값·샘플 식별자를 지우는 기존 도구)를 거친다.
10. **API 응답:** `GET /api/jobs/{id}/steps/{step_id}`의 `StepDetailResponse`에는 원인 목록 필드가 없다. check 표 `validation.results[]`의 `CheckResult`는 이 응답 외에 `/results`의 `checks`와 explanation의 `checkSummary.notable`에서도 쓰인다 ([schemas.py:165-171, 359-393](../../backend/app/schemas.py#L359-L393)).
11. **Frontend 파싱:** frontend Zod 스키마는 `z.object`를 쓰며 `.strict()`(모르는 키가 있으면 실패하는 옵션)를 쓰지 않는다. 그래서 모르는 필드는 무시된다 ([api.ts:140, 190](../../front/src/features/run-detail/api.ts#L190)).
12. **Step 상세 polling:** frontend는 step 상세를 **그 step이 실행 중일 때만** 주기적으로 다시 요청한다 ([queries.ts:80-94](../../front/src/features/run-detail/queries.ts#L80-L94)).
13. **보고서 등록:** `resource_validation.txt`는 artifact로 등록되지 않는다. 00 단계의 `validation_report` artifact는 samplesheet 보고서다 ([main.sh:1858](../../script/main.sh#L1858)).
14. **로그의 줄 형식:**
    - step 시작 기록은 `log "START $CURRENT_STEP"`이다. 로그에는 `[<시각>] START 00_input_validation` 형태로 남는다 ([main.sh:293, 679](../../script/main.sh#L679)).
    - 반면 `cat "$report"`로 복사된 보고서 내용은 시각 접두어가 없다. `[ERROR] Resource bundle validation failed:`와 `  - …` 줄이 줄 맨 앞에서 시작한다.
    - `die()`가 남기는 `[<시각>] [ERROR] …` 줄은 원인 블록이 아니다 ([main.sh:295](../../script/main.sh#L295)).
    - [기록] 아카이브 4건과 로컬 성공 Run 1건의 로그는 모두 이 형식이다. `START 00_input_validation`은 각각 정확히 1회, 줄바꿈은 LF(CR 없음)다.
    - 로그에는 `sample 'DEMO_WES'`처럼 샘플 식별자가 포함된 줄도 있다.

---

## 3. 목표 동작 (TO-BE)

`resource_bundle` 검사가 FAIL인 Run에 대해, Backend가 이미 존재하는 기록만 읽는다. **정해진 규칙**(LLM이 아닌 결정적 코드)으로 개별 원인을 추출하고 분류한다.

구조:

```
              ┌─ Agent 근거 (StepEvidence)    ← 정보 보호 규칙(NFR-2)을 거쳐 투영
공통 해석 기능 ┤
              └─ 공개 API (StepDetailResponse) ← 같은 정보 보호 규칙을 거쳐 투영
```

- **공통 해석 기능은 하나다.** 분류 규칙과 상태 판정은 두 소비자(결과를 받아 쓰는 쪽)에서 같다.
- 공통 해석 결과는 내부 값이다. 소비자는 그것을 그대로 내보내지 않고, 투영(정보 보호 규칙을 적용해 필요한 필드만 골라내는 변환)을 거쳐 내보낸다. 새 필드에 적용하는 정보 보호 규칙은 두 소비자가 같다 (Q8). 두 소비자의 기존 필드는 각자의 기존 정책을 그대로 따른다.
- 원인마다 **분류 결과**(종류, 대상 리소스 역할, 관련 도구)와 **원문 근거**(경로를 지운 문장)를 구분해서 제공한다.
- **분류하지 못한 문장은 `unknown`으로 보존한다.**
- **"원인을 읽을 수 없음", "실패 기록은 있으나 원인 문장이 없음", "원인 문장을 읽었으나 분류 못 함", "현재 실행의 기록인지 확정할 수 없음"을 서로 다른 상태로 구분한다** (FR-8).
- 크기 제한으로 기록이 잘렸으면 원인 목록을 완전한 목록으로 내보내지 않는다 (NFR-6).
- 원인 사이의 관계(어느 것이 근본 원인인지)는 판단하지 않는다.
- 기존 판정, 실패 코드, API 필드, 원본 파일은 바꾸지 않는다.

---

## 4. 기능 요구사항 (FR)

| ID | 요구사항 | 근거 |
|---|---|---|
| **FR-1** | `00_input_validation` step 문서의 `validation.results`에 `name == "resource_bundle"`이고 `status == "FAIL"`인 항목이 있을 때만 세부 원인 해석을 수행한다 | [코드] check 이름과 상태 기록 방식 (`step_check_fail`). [합의] 기존 판정 유지 |
| **FR-2** | step이 `00_input_validation`이지만 FR-1 조건이 아니면 기록 파일을 **읽지 않고** `state: "not_applicable"`과 빈 원인 목록을 반환한다. 여기에는 PASS, WARN, 해당 check 없음, step 문서 없음(대기·실행 중)이 모두 포함된다. 다른 step의 처리는 FR-12·FR-11을 따른다 | [합의] 존재하지 않는 오류 생성 금지 (68aa20) |
| **FR-3** | 원인 문장의 출처는 두 가지로 고정한다.<br>① `<run_dir>/00_input_validation/resource_validation.txt`(보고서)<br>② `<run_dir>/logs/pipeline.log`(로그)<br>②는 ①이 **존재하지 않거나 열거나 읽는 중 OS 오류가 날 때만** 쓴다. ①을 읽었는데 원인 블록이 없으면 ②로 넘어가지 **않는다**. 로그에는 이전 시도의 오래된 블록이 남아 있을 수 있기 때문이다 (AS-IS 1·4). 0바이트 보고서도 "존재함"으로 본다.<br>run_dir는 DB의 Job 행에서만 얻는다. 사용자 입력으로 경로를 받지 않는다 | [코드] 보고서는 덮어쓰고 로그는 이어씀. [합의] 임의 경로 입력 금지 |
| **FR-4** | 원인 블록은 두 부분으로 이루어진다.<br>① 헤더: 줄 맨 앞에서 시작하는 `[ERROR] Resource bundle validation failed:` 줄. 시각 접두어가 붙은 줄은 헤더가 아니다<br>② 원인 줄: 헤더 바로 뒤에 이어지는 `  - `(공백 2칸, 하이픈, 공백)로 시작하는 줄들<br>그런 줄이 처음 끊기는 곳에서 블록이 끝나며, 한 줄이 원인 하나다. 로그에서 어느 구간을 볼지는 FR-16을 따른다 | [코드] [main.sh:2176-2178](../../script/main.sh#L2176-L2178), AS-IS 14 |
| **FR-5** | 원인 문장마다 §7.3의 규칙표로 `kind`(원인 종류), `resourceRole`(대상 리소스 역할), `tool`(관련 외부 도구, 해당 시)을 결정한다. 규칙은 **문장 자체의 고정 문구와 label**(문장 안에 들어가는 리소스 이름표, 예: `target_bed`)로만 판단한다 | [합의] LLM 추측 금지 |
| **FR-6** | 어떤 규칙에도 맞지 않는 문장은 `kind: "unknown"`, `resourceRole: "unknown"`, `tool: null`, `ruleId: null`로 목록에 **보존**한다. 버리거나 가장 비슷한 종류로 바꾸지 않는다. 원문 문장은 내부 분석 결과에 그대로 남는다. 외부로 내보내는 `evidenceText`는 NFR-2의 공개 조건을 따른다 (조건을 못 넘으면 `null`이어도 원인 항목 자체는 남음) | [합의]. v4: 사용자 정책 P4 |
| **FR-7** | 각 원인에는 분류 결과와 별도로 원문 근거 `evidenceText`를 넣는다. 내보내기 전에 정보 보호 규칙(NFR-2)을 적용한다. NFR-2의 **공개 조건**을 넘지 못한 문장은 `evidenceText: null`로 내보내고 `withheldTextCount`에 센다. 분류 필드(`kind`, `resourceRole`, `tool`, `ruleId`)는 미리 정한 어휘이므로 이 경우에도 유지한다 | [합의] 노출 금지. [코드] 기존 `Redactor.text()` ([privacy.py:140-152](../../backend/app/services/agent/privacy.py#L140-L152)). v4: 정책 P3·P4 |
| **FR-8** | 상태(`state`)는 아래 여섯 가지 중 정확히 하나다. 판정 순서도 아래 순서다.<br>① `not_applicable`: FR-2 조건<br>② `source_unavailable`: 보고서와 로그가 모두 존재하지 않음<br>③ `source_unreadable`: 존재하는 출처를 하나도 끝까지 읽지 못함 (열기 또는 읽는 도중 OS 오류. 일부만 읽은 내용은 쓰지 않음)<br>④ `segment_unresolved`: 출처를 읽었으나, 원인 블록이 현재 실행의 기록인지 확정할 수 없음 (FR-16, NFR-6)<br>⑤ `no_error_block`: 해석 구간을 확정했으나 그 안에 원인 블록이 없거나, 헤더 뒤 원인 줄이 0개<br>⑥ `parsed`: 해석 구간에서 원인 줄을 1개 이상 읽음 (모두 `unknown`이어도 `parsed`)<br>**원인 목록 `causes`는 ⑥일 때만 비어 있지 않다.** ①–⑤에서는 항상 빈 목록이다. 크기 제한으로 기록이 잘렸는지는 상태와 별개로 `truncated`로 표시한다 (NFR-6). 읽기 실패(③)와 잘림은 서로 다른 것이다 | [합의] 실제 근거 없는 원인 생성 금지, 로그 없음·손상 구분, Q4 |
| **FR-9** | `no_error_block`일 때(예: Python 예외로 traceback, 즉 오류 발생 지점까지의 호출 기록만 남은 경우) **원인을 만들지 않는다.** 대신 해석 구간의 끝부분을 **참고 로그** `unparsedExcerpt`로 제공할 수 있다.<br>- 참고 로그는 `causes`와 다른 필드이며 분류하지 않는다.<br>- NFR-2 정보 보호와 NFR-10 문자 처리를 거친다. NFR-2 공개 조건을 넘지 못하면 `null`로 두고 `withheldTextCount`에 센다 (v4).<br>- 최대 1000자이며, 넘으면 잘린 표시를 붙인다.<br>- `no_error_block`이 아닌 상태에서는 항상 `null`이다. 특히 `segment_unresolved`에서는 과거 실행의 기록일 수 있으므로 제공하지 않는다 | [코드] heredoc이 비정상 종료해도 rc ≠ 0이면 FAIL로 기록됨 ([main.sh:2195-2197](../../script/main.sh#L2195-L2197)). [합의] Q7 |
| **FR-10** | 같은 step의 다른 check 결과(특히 `required_tools`의 status와 detail)를 원인 목록과 **같은 응답 안에서** 함께 볼 수 있어야 한다. 이 기능은 **원인 사이의 원인·결과 관계를 판정하지 않으며**, 그런 의미의 필드(예: `derivedFrom`, `rootCause`, `relatedCheck`)를 만들지 않는다. 그 판단은 후속 Agent의 책임이다 | [코드] `required_tools` detail에 빠진 도구 이름이 있음 (b94559). [합의] Q3 |
| **FR-11** | **Agent 소비자:** 결과는 Agent 근거 `StepEvidence`에 새 필드로 추가된다. Agent는 추가 tool 호출 없이 `get_step_detail("00_input_validation")` 한 번으로 받는다. 문자열은 해당 Job의 `Redactor`(샘플 식별자 literal 포함)를 거친다. 다른 step의 `StepEvidence`에서는 이 필드가 `null`이다 | [코드] 기존 Agent 경로 ([step_evidence.py](../../backend/app/services/agent/step_evidence.py)). [합의] Q1 |
| **FR-12** | **공개 API 소비자:** `StepDetailResponse`의 **최상위에 선택적 새 필드**(기본값 `null`)로 노출한다. `CheckResult`와 `validation`에는 넣지 않는다. `CheckResult`는 다른 두 응답에서도 공유되므로, 넣으면 영향 범위가 이 기능 밖으로 넓어진다 (AS-IS 10). 다른 step의 응답에서는 `null`이다. 문자열은 Agent와 같은 정보 보호 규칙(경로·해시값·데이터 파일명·샘플 식별자 제거)을 거친다 (NFR-2). 기존 응답의 다른 필드는 바꾸지 않는다 | [합의] Q1·Q8. [코드] `CheckResult` 공유 구조 |
| **FR-13** | 원본 기록(보고서, 로그, step JSON)은 읽기만 한다. 해석 결과를 디스크에 저장하지 않는다 | [합의] 원본 변경 금지 |
| **FR-14** | 기존 Run(이 기능 이전에 만들어진 Run)에도 같은 규칙으로 동작한다. 실패 기록 아카이브 형식(보고서 없이 로그만 있음)에서도 동작한다 | [합의] |
| **FR-15** | **공통 해석 기능:** 분류 규칙과 상태 판정은 Backend 안의 한 곳에만 둔다. 두 소비자는 그 결과를 받아 투영만 한다. 같은 Run이면 두 소비자의 `state`, 원인 개수와 순서, `kind`·`resourceRole`·`tool`·`ruleId`, `truncated`가 같아야 한다. 정보 보호 규칙도 같으므로(NFR-2) `evidenceText`와 `unparsedExcerpt`도 같아야 한다. 즉 새 필드의 값 전체가 두 소비자에서 같다 | [합의] Q1·Q8 |
| **FR-16** | **로그의 해석 구간:** 출처가 로그일 때는 **마지막 `START 00_input_validation` 줄**(00 단계의 마지막 실행 시작 기록)부터 읽은 내용의 끝까지만 해석한다. 그 앞의 원인 블록은 과거 실행의 기록으로 보고 쓰지 않는다.<br>다음 경우에는 구간을 확정할 수 없으므로 `segment_unresolved`를 반환한다. 이때 과거 오류를 현재 원인으로 확정하지 않는다.<br>ⓐ 읽은 내용에 `START 00_input_validation` 줄이 없음 (시작 기록 누락, 또는 크기 제한으로 시작 기록이 잘림)<br>ⓑ 해석 구간 안에 원인 블록이 2개 이상 (한 번의 실행에서는 생기지 않는 형식)<br>보고서는 실행마다 덮어쓰므로(AS-IS 1) 시작 기록 규칙(ⓐ)을 적용하지 않는다. 다만 보고서에 헤더가 2개 이상이면 ⓑ와 같은 이유로 `segment_unresolved`다 (v4 명확화: `PYBUNDLE`은 한 번만 출력하므로 정상적으로는 생기지 않음). 서로 다른 실행의 블록을 합치지 않는다 | [합의] Q4. [코드] AS-IS 4·5·14 |

---

## 5. 비기능 요구사항 (NFR)

| ID | 요구사항 | 근거 |
|---|---|---|
| **NFR-1 결정성** | 같은 입력 파일에는 항상 같은 출력. 시각·환경·LLM에 의존하지 않음 | [합의] |
| **NFR-2 개인정보·보안** | 새 필드의 모든 문자열(`evidenceText`, `unparsedExcerpt`)은 **Agent와 공개 API 모두 같은 규칙**으로 가린다.<br>- 가릴 것: 절대·상대 경로, 데이터 파일명, 64자리 hex 해시값, 샘플 식별자(Job 행 `sample_id` 등 기존 Agent 경로와 같은 literal 목록), 인증정보<br>- 규칙은 기존 Job별 `Redactor`를 재사용함<br>- 해석 기능은 원문을 서버 로그나 오류 응답에 쓰지 않음<br>- 공개 API의 **기존** 필드(`InputSummary.sample`, `logTail` 등)는 이번 범위에서 바꾸지 않음. 새 필드는 `logTail`처럼 경로를 노출하는 선례를 따르지 않음<br>**공개 조건 (v4, fail-closed: 안전이 확인되지 않으면 내보내지 않음):** 문자열 치환이 모든 식별정보를 지운다고 가정하지 않는다. 원문 문자열(`evidenceText`, `unparsedExcerpt`)은 다음을 **모두** 만족할 때만 내보낸다.<br>ⓐ Job 행에 샘플 식별자(`sample_id`)가 있어 literal로 가릴 수 있음. 없는 Job(오래된 행)은 원문 문자열을 내보내지 않음<br>ⓑ 가린 뒤 남은 문자열에 경로 흔적(역슬래시, `/`로 시작하는 경로, 두 개 이상의 `/` 구분), 32자 이상 hex, 알려진 식별자 literal이 남아 있지 않음<br>조건을 못 넘은 문자열은 `null`로 두고 개수를 `withheldTextCount`로 알림. 미리 정한 어휘인 분류 필드와 `state`·`source`·`truncated`는 조건과 무관하게 유지함 (진단에 필요한 정보를 무조건 지우지 않음)<br>이 조건은 **알려진 위험**(경로, 파일명, 해시, Job 식별자, 샘플 식별자)만 막는다. 원문에 섞인 그 밖의 자유 텍스트(예: 사용자 파일의 contig 이름)가 식별정보가 아니라는 것까지 증명하지는 않는다 (§10.3 U5) | [합의] Q8. v4: 사용자 정책 P1–P6. [코드] [privacy.py](../../backend/app/services/agent/privacy.py), AS-IS 8 |
| **NFR-3 경로 안전** | 읽는 파일은 FR-3의 두 고정 상대경로뿐. 원인 문장 안의 경로나 파일 이름을 따라가 다른 파일을 열지 않음. 원인 문장 속 경로·파일 이름을 `resourceRole` 판정에 쓰지 않음 (Q2) | [합의] |
| **NFR-4 하위 호환** | 기존 응답 필드의 이름·타입·의미를 바꾸지 않음. 새 필드는 선택적(없거나 `null`이어도 됨). 새 필드가 없는 응답도, 있는 응답도 frontend 스키마 파싱을 통과 | [코드] AS-IS 11. [합의] |
| **NFR-5 견고성** | 파일 없음, 0바이트, 깨진 바이트, 잘린 마지막 줄, 상한 초과 크기에서 예외를 밖으로 내보내지 않음. 결과는 FR-8 상태 중 하나로 반환하고, 기존 step 응답은 계속 200.<br>문자 해독은 UTF-8이며 해독할 수 없는 바이트는 대체 문자로 바꿔 계속 읽음 (기존 `read_log_tail`과 같은 방식). 따라서 **깨진 바이트만으로는 `source_unreadable`이 되지 않는다.** `source_unreadable`은 OS 오류(권한, 디렉터리임 등)에만 해당함.<br>잘린 마지막 줄도 `  - `로 시작하면 원인 줄로 읽음 | [합의] 로그 없음·손상 포함. [코드] AS-IS 8 |
| **NFR-6 크기 제한** | 초기 정책 값이다. 테스트와 운영 측정으로 재검토한다.<br>- **읽기:** 출처 파일마다 최대 256 KiB(262,144 바이트)를 읽는다. 파일이 더 크면 **끝에서부터** 256 KiB만 읽는다. 첫 줄은 중간에서 잘렸을 수 있으므로 버린다. 파일 전체를 메모리에 올리지 않는다<br>- **원인 개수:** 최대 50개. 초과분은 버린다<br>- **문자열:** `evidenceText`와 `unparsedExcerpt`는 각각 최대 1000자. 넘으면 잘린 표시를 붙인다 (기존 `MAX_TEXT` 동작)<br>**`truncated`의 의미:** `true`는 "크기 제한 때문에 원인 목록이 완전하지 않을 수 있음"이다. 다음 경우에 `true`다.<br>ⓐ 원인이 50개를 넘어 버림<br>ⓑ 읽기 제한으로 파일 앞부분을 버렸고, 해석에 필요한 시작점이 읽은 범위 안에 없음. 시작점은 로그는 `START 00_input_validation` 줄, 보고서는 헤더 줄이다. 이 경우 상태는 `segment_unresolved`다<br>시작점이 읽은 범위 안에 있으면, 앞부분을 버렸어도 해석 구간은 온전하므로 `false`다. 개별 문자열의 1000자 잘림은 목록의 완전성과 관계없으므로 `truncated`에 반영하지 않는다.<br>`truncated: true`인 목록을 **완전한 원인 목록으로 취급하지 않는다.** 소비자는 "이 원인이 없다"는 결론의 근거로 쓰지 않는다 | [합의] Q5. [코드] AS-IS 8: 기존 로그 읽기에 바이트 상한 없음 |
| **NFR-7 비용** | 해석은 FR-1 조건일 때만 수행. 3초 polling 경로(`GET /api/jobs/{id}`)에는 추가하지 않음. step 상세는 실행 중일 때만 polling되는데(AS-IS 12), FR-1 조건은 끝난 step에만 성립하므로 polling 중에는 파일을 읽지 않음 | [코드] [steps.py](../../backend/app/api/steps.py), [queries.ts](../../front/src/features/run-detail/queries.ts#L80-L94) |
| **NFR-8 확장성** | 규칙표는 코드 한 곳에 데이터로 모음. 향후 방법 B(파이프라인이 구조화된 파일을 직접 기록)가 생기면 출처 우선순위 맨 앞에 추가할 수 있게 출처 읽기와 분류를 분리 | [합의] B 확장 가능성 유지 |
| **NFR-9 일관성** | 규칙표는 `PYBUNDLE`의 실제 문장과 일치해야 함. main.sh 문구가 바뀌면 테스트가 실패해야 함 | [제안] 원본 heredoc 추출 테스트 (§11) |
| **NFR-10 신뢰할 수 없는 문자열** | 원인 문장에는 사용자가 올린 파일 내용(BED contig 이름 등)이 섞일 수 있음 (AS-IS 6). `evidenceText`와 `unparsedExcerpt`는 **데이터로만** 취급함. 출력 전에 제어 문자(줄바꿈 제외 불가시 문자, 터미널 색상 코드 등)를 제거하고 길이를 제한함. Agent에 넘길 때는 기존 근거 문자열과 같은 방식(지시가 아닌 근거 데이터)으로 다룸 | [코드] [main.sh:2065](../../script/main.sh#L2065). [제안] 제거 대상 문자 범위 |

---

## 6. 시나리오

| # | 상황 | 입력 | 기대 결과 |
|---|---|---|---|
| S1 정상 (원인 2개) | `3a22c5` | 로그에 BED 누락 2줄 | `parsed`, 원인 2개: (`resource_missing_or_empty`, `target_bed`), (`resource_missing_or_empty`, `coverage_bed`) |
| S2 정상 (복합) | `b94559` | BED 누락 2줄 + `bcftools unavailable` 2줄. `required_tools` FAIL | `parsed`, 원인 4개. 그중 2개는 `vcf_tool_unavailable`, `tool: "bcftools"`, `resourceRole: "unknown"`(Q2). 같은 응답의 checks에 `required_tools` FAIL과 detail이 함께 있음. 관계 필드 없음 (FR-10) |
| S3 통과 | `68aa20` 00 단계 | `resource_bundle` PASS | `not_applicable`, 원인 0개, 파일 읽지 않음 |
| S4 알 수 없는 문장 | 합성: `  - something new happened` | 규칙 불일치 | `parsed`, 원인 1개 `unknown`, evidenceText에 원문(정보 보호 후) |
| S5 섞임 | 합성: 알려진 1줄 + 모르는 1줄 | — | 순서 유지, `[알려진 kind, unknown]` |
| S6 보고서 없음 | 보고서 없음, 로그에 블록 있음 | — | `parsed`, `source: "pipeline_log"`. 아카이브 4건은 보고서 파일을 담지 않아 이 형식이다. 실제 서버에서 보고서가 없는 경우가 얼마나 흔한지는 확인되지 않음 |
| S7 둘 다 없음 | 보고서·로그 모두 없음 | — | `source_unavailable`, 원인 0개. **"원인 없음"으로 표시하지 않음** |
| S8 블록 없음 | 보고서에 traceback만 있음 | — | `no_error_block`, **원인 0개**. `unparsedExcerpt`에 traceback 끝부분(정보 보호 후, 1000자 이내)이 있을 수 있음 |
| S9 헤더만 있음 | 헤더 뒤 원인 줄 0개 | — | `no_error_block`, 원인 0개 |
| S10 보고서에 블록 없음 + 로그에 옛 블록 | 보고서 traceback, 로그에 이전 시도 블록 | — | `no_error_block`, `source: "report"`. 로그로 넘어가지 않음 (FR-3) |
| S11 보고서 읽기 OS 오류 | 보고서가 디렉터리이거나 권한 없음, 로그에 블록 | — | 로그로 넘어감. `parsed`, `source: "pipeline_log"` |
| S12 둘 다 읽기 OS 오류 | — | — | `source_unreadable`, 원인 0개 |
| S13 깨진 바이트 | 원인 줄에 UTF-8이 아닌 바이트 | — | `parsed`. 해당 문자는 대체 문자. 예외 없음 |
| S14 재실행 로그 | 보고서 없음. 로그에 `START 00` 2회, 각 구간에 블록 1개 (CLI 재실행) | — | `parsed`. **마지막 `START 00` 뒤의 블록만** 사용. 앞 블록의 원인은 결과에 없음 |
| S15 다른 step | `03_alignment` 조회 | — | 공개 API·Agent 모두 새 필드 `null` |
| S16 공개 API 정보 보호 | S1·S2 입력을 공개 API로 조회 | — | `evidenceText`에 경로·해시값·샘플 식별자 0회. 새 필드 값 전체가 Agent 결과와 같음 (FR-15) |
| S17 재실행 후 마지막 구간에 블록 없음 | 보고서 없음. 로그에 `START 00` 2회, 앞 구간에만 블록, 뒤 구간은 traceback | — | `no_error_block`, 원인 0개. 앞 구간의 블록을 쓰지 않음. 참고 로그는 뒤 구간에서만 |
| S18 시작 기록 없음 | 보고서 없음. 256 KiB 이하 로그에 블록은 있으나 `START 00` 줄 없음 | — | `segment_unresolved`, 원인 0개, `truncated: false`, 참고 로그 `null` |
| S19 큰 로그, 시작 기록이 잘림 | 보고서 없음. 256 KiB를 넘는 로그에서 `START 00`이 끝 256 KiB 밖에 있음 | — | `segment_unresolved`, 원인 0개, `truncated: true` |
| S20 큰 로그, 시작 기록이 범위 안 | 256 KiB를 넘는 로그에서 `START 00`과 블록이 끝 256 KiB 안에 있음 | — | `parsed`, `truncated: false`. 읽은 바이트는 256 KiB 이하 |
| S21 원인 50개 초과 | 합성: 원인 줄 60개 | — | `parsed`, 원인 50개(앞에서부터, 순서 유지), `truncated: true` |
| S22 긴 원인 문장 | 합성: 3000자 원인 줄 | — | `evidenceText` 1000자 + 잘린 표시. `truncated`는 이 이유만으로는 `false` |
| S23 읽는 도중 OS 오류 | 보고서·로그 모두 읽는 도중 오류 | — | `source_unreadable`. 일부 읽은 내용으로 원인을 만들지 않음 |

---

## 7. 데이터 계약 초안 [제안]

### 7.1 출력 (Agent 근거와 공개 API 공통 형태)

```jsonc
"resourceBundleDiagnosis": {    // 00 이외 step에서는 null
  "state": "parsed",            // not_applicable | source_unavailable | source_unreadable
                                // | segment_unresolved | no_error_block | parsed
  "source": "report",           // report | pipeline_log | null (읽은 출처가 없을 때)
  "causes": [                   // state가 parsed일 때만 비어 있지 않음
    {
      "kind": "resource_missing_or_empty",   // §7.3. 모르면 "unknown"
      "resourceRole": "target_bed",          // §7.3. 확인 불가면 "unknown"
      "tool": null,                          // "bcftools" | "tabix" | null
      "evidenceText": "target_bed missing or empty: <path>",  // 정보 보호 후 원문. 공개 조건 미달이면 null
      "ruleId": "R-MISSING"                  // 일치한 규칙. unknown이면 null
    }
  ],
  "unparsedExcerpt": null,      // 참고 로그. no_error_block일 때만 값이 있을 수 있음. 원인 아님
  "withheldTextCount": 0,       // NFR-2 공개 조건 때문에 null로 내보낸 원문 문자열 수 (v4)
  "truncated": false            // true면 원인 목록이 완전하지 않을 수 있음 (NFR-6)
}
```

- 분류 결과(`kind`, `resourceRole`, `tool`, `ruleId`)와 원문 근거(`evidenceText`)를 **별도 필드로** 둔다.
- 필드 이름은 기존 camelCase 규칙을 따른다 [코드: `StepDetailResponse`].
- `unknown` 원인의 개수는 `causes`에서 셀 수 있으므로 별도 필드를 두지 않는다.
- 이 필드는 **기록된 시점**의 원인이다. 현재 서버 상태를 뜻하지 않는다 (R5).

### 7.2 입력

- Job 행에서 얻는 `run_dir`, planned steps, run_mode, `sample_id`(정보 보호용).
- step id (기존 검증 `STEP_ID_RE`와 planned 목록 통과 후).
- 정보 보호 규칙: 두 소비자 모두 Job `Redactor` (NFR-2).
- 사용자가 경로나 파일 이름을 지정할 수 없다.

### 7.3 규칙표 초안 — 원인 문장 template 출처는 모두 [코드] `PYBUNDLE`

일치 방식(문장 시작 부분 비교, 정규식 등)은 구현 단계에서 정한다. 요구사항은 FR-5다. 고정 문구와 label만으로 판단한다.

| ruleId | 문장 형태 (main.sh) | kind | resourceRole 결정 | tool |
|---|---|---|---|---|
| R-NOTSET | `{label} is not set in the resource bundle` | `resource_not_declared` | label에서 | — |
| R-MISSING | `{label} missing or empty: …` | `resource_missing_or_empty` | label에서 | — |
| R-BWA-INCOMPLETE | `BWA index at '…' is incomplete` | `bwa_index_incomplete` | `bwa_index` | — |
| R-BWA-NONE | `BWA index not found:` | `bwa_index_not_found` | `bwa_index` | — |
| R-FAI-DICT | `reference .fai and .dict disagree` | `reference_index_mismatch` | `reference_fasta` | — |
| R-STYLE | `contig_style='…' declares …` / `… is not a recognised …` | `contig_style_mismatch` / `contig_style_unrecognised` | `reference_fasta` | — |
| R-SHA | `{label} SHA-256 mismatch:` | `checksum_mismatch` | label에서 (`target BED`, `coverage BED`) | — |
| R-BED-CONTENT | `{label} line N: …`, `{label} contains no usable intervals` | `bed_content_invalid` | label에서 | — |
| R-VCF-INDEX | `{label} index missing (.tbi or .csi):` | `vcf_index_missing` | label에서 | — |
| R-VCF-HEADER | `cannot parse VCF header:` | `vcf_header_unparseable` | `unknown` (label 없음) | `bcftools` |
| R-VCF-TOOL-B | `bcftools unavailable for …` | `vcf_tool_unavailable` | `unknown` (label 없음. Q2) | `bcftools` |
| R-VCF-TOOL-T | `tabix unavailable for …` | `vcf_tool_unavailable` | `unknown` (Q2) | `tabix` |
| R-TABIX-LIST | `cannot read tabix contig list:` | `vcf_contig_list_unreadable` | `unknown` | `tabix` |
| R-VCF-LEN | `{label} declares contig lengths that differ` | `vcf_contig_length_mismatch` | label에서 | — |
| R-VCF-ABSENT | `{label} contigs absent from the reference:` | `vcf_contigs_absent` | label에서 | — |
| R-KS-EMPTY | `known_sites is empty;` | `known_sites_empty` | `known_sites` | — |
| (없음) | `str(exc)` 등 그 밖의 문장 | `unknown` | `unknown` | — |

label → `resourceRole` 대응 [코드: `need()`, `check_bed()`, `check_vcf_resource()`의 label 인자]:

| label | resourceRole |
|---|---|
| `reference_fasta` | `reference_fasta` |
| `reference FASTA index (.fai)` | `reference_fai` |
| `reference sequence dictionary (.dict)` | `reference_dict` |
| `target_bed`, `target BED` | `target_bed` |
| `coverage_bed`, `coverage BED` | `coverage_bed` |
| `known_sites entry` | `known_sites` |
| `dbsnp_vcf` | `dbsnp_vcf` |

규칙과 일치했지만 label이 위 표에 없으면 `kind`는 규칙대로 두고 `resourceRole`만 `unknown`으로 한다.

> **Q2 결정 반영 [합의]:** `bcftools unavailable for {vcf}`에는 label이 없다 [코드]. 문장 속 파일 경로·이름으로 known_sites인지 dbSNP인지 추측하지 않는다. run config의 경로 목록과 비교하는 방식도 쓰지 않는다. 대상은 `unknown`이다.

---

## 8. 요구사항별 완료 조건

| ID | 검증 가능한 완료 조건 |
|---|---|
| FR-1·2 | 68aa20·d87484 원본 00 step 문서로 `not_applicable`, 원인 0개. 해석 대상이 아닐 때 두 출처 파일 모두 열지 않음 (테스트에서 파일 접근이 없음을 확인) |
| FR-3 | (보고서 있음, 로그 있음) → `report`. (없음, 있음) → `pipeline_log`. (OS 오류, 있음) → `pipeline_log`. (있음·블록 없음, 로그에 블록) → `report`, `no_error_block`. 두 출처 외의 경로는 열지 않음 |
| FR-4·5 | 3a22c5 로그 블록으로 원인 2개, `kind`·`resourceRole`이 S1과 일치 |
| FR-5·10 | b94559로 원인 4개, 그중 `tool: "bcftools"`·`resourceRole: "unknown"` 2개. 같은 응답의 checks에 `required_tools` FAIL과 detail 포함. 출력에 관계 필드가 없음 |
| FR-6 | 규칙에 없는 문장이 `unknown`으로 남고, 입력 원인 줄 수 = 출력 원인 수이며 순서가 같음 (상한 미만일 때) |
| FR-7·NFR-2 | 4건 원본과 합성 입력 모두에서 두 소비자의 새 필드 문자열에 `/`·`\` 경로, 64자리 hex, Job `sample_id`(예: `DEMO_WES`)가 0회 등장. 공개 API의 기존 필드 값은 이전과 같음 |
| FR-8 | S3·S7·S8·S9·S12·S18·S23 각각이 정해진 `state`를 반환. `parsed`가 아닌 모든 경우 `causes == []` |
| FR-9 | S8에서 `causes == []`, `unparsedExcerpt`는 정보 보호 후 1000자 이내. `no_error_block`이 아닌 모든 상태(특히 S18·S19)에서 `unparsedExcerpt == null` |
| FR-11 | `get_step_detail("00_input_validation")` 결과에 새 필드가 있고, 기존 필드 값은 이전과 같음. 다른 step은 `null` |
| FR-12·NFR-4 | 기존 `test_step_detail.py`가 수정 없이 통과. 새 필드는 최상위에만 있고 `CheckResult` 모양은 그대로. 새 필드가 있는 응답·없는 응답 모두 frontend 스키마 파싱 통과 |
| FR-13 | 실행 전후 원본 파일의 hash가 같음 |
| FR-14 | 아카이브 형식(보고서 없이 로그만)에서 S1·S2·S3 조건을 만족 |
| FR-15 | 같은 입력에서 두 소비자의 새 필드 값 전체가 같음 |
| FR-16 | S14: 마지막 구간의 원인만 나옴. S17: 앞 구간 블록을 쓰지 않고 `no_error_block`. S18·S19: `segment_unresolved`. 구간 안 블록 2개: `segment_unresolved`. 어떤 경우에도 서로 다른 구간의 원인이 합쳐지지 않음 |
| NFR-1 | 같은 입력을 두 번 해석한 결과가 바이트 단위로 같음 |
| NFR-5 | 0바이트, 깨진 바이트, 잘린 마지막 줄 입력에서 예외 없음, 정해진 상태 반환, step 응답 200 |
| NFR-6 | S19–S22: 파일마다 읽은 바이트 수 ≤ 262,144. 원인 ≤ 50개. 문자열 ≤ 1000자 + 잘린 표시. `truncated` 값이 각 시나리오 기대와 같음. 예외 없음 |
| NFR-9 | 원본 `PYBUNDLE`을 추출해 실행한 출력이 규칙표로 기대한 kind로 분류됨. 규칙과 문장이 어긋나면 테스트 실패 |
| NFR-10 | 제어 문자·색상 코드를 넣은 합성 원인 줄에서 출력에 그 문자가 없음. 길이 상한을 지킴 |

---

## 9. 변경하면 안 되는 기존 동작 [합의] [코드]

- main.sh의 검사 로직, 종료 코드, `resource_bundle` failure code와 message. **이번 범위에서 main.sh는 수정하지 않는다.**
- step 상태 판정 (`step_reader._state_of`, `run_status_reader`).
- `StepDetailResponse`, `StepEvidence`, `CheckResult`의 기존 필드 이름·타입·의미.
- privacy 투영 규칙: 기존 필드의 redaction, metric allowlist.
- Agent 단계 조회 예산(`DEFAULT_MAX_DISTINCT_STEPS = 2`)과 MCP tool 이름.
- `GET /api/jobs/{id}` polling 응답 (`logTail` 포함, 이번 범위에서 바꾸지 않음).
- `wes_failures.json`의 `closedSet: false` 정책. 등록되지 않은 code도 원문을 그대로 보여 줌.
- 원본 Run 파일 (읽기 전용).

---

## 10. 결정 사항, 미해결 질문, 기술적 위험

### 10.1 Clarify 단계에서 결정된 사항 [합의]

| # | 결정 | 반영 위치 |
|---|---|---|
| Q1 | Backend 안에 공통 해석 기능을 하나 둔다. 공개 API와 Agent가 각자의 정보 보호 정책으로 투영해 쓴다. 공개 API 필드 위치는 코드 구조를 보고 `StepDetailResponse` 최상위의 선택적 필드로 정했다 (`CheckResult` 공유 때문) | §3, FR-11·12·15, NFR-2 |
| Q2 | 대상 파일을 확정할 근거가 없으면 파일 이름이나 종류를 추측하지 않고 `unknown`으로 둔다 | FR-5, NFR-3, §7.3 |
| Q3 | 이 기능은 개별 오류의 추출·분류까지만 한다. 원인·결과 관계는 후속 Agent의 책임이다 | FR-10 |
| Q6 | 실제 로그를 테스트에 쓸 수 있으나, 서버 경로·샘플 정보·식별정보를 지운 최소 fixture만 허용한다. 이번 단계에서는 fixture 파일을 만들지 않는다 | §11 |
| A | FR-8·9 충돌 해소: `no_error_block`에서 가상의 `unknown` 원인을 만들지 않는다. 원인은 `parsed`일 때만 존재한다 | FR-8·9 |
| Q4 | 로그는 마지막 실행 시작 지점(마지막 `START 00_input_validation` 줄) 이후의 오류 기록만 쓴다. 구간을 구별할 수 없으면 과거 오류를 현재 원인으로 확정하지 않는다 (`segment_unresolved`) | FR-8·16, S14·S17–S19 |
| Q5 | 초기 정책: 읽기 256 KiB(끝에서부터), 원인 최대 50개, 근거 문자열 최대 1000자. 잘린 목록은 완전한 목록으로 취급하지 않는다. 값은 테스트와 운영 측정으로 재검토한다 | NFR-6, S19–S22 |
| Q7 | 오류 문장을 찾지 못하면 제한된 참고 로그를 줄 수 있다. 참고 로그는 원인 목록과 구분하고, 정보 보호와 크기 제한을 적용한다 | FR-9 |
| Q8 | 새 오류 정보는 공개 API와 Agent 모두 샘플 식별자와 서버 경로를 가린다. 기존 API의 다른 필드는 바꾸지 않는다 | FR-12, NFR-2 |
| P1–P6 (v4) | 구현 단계 사용자 정책:<br>(P1) 정보 보호 때문에 진단 정보를 무조건 지우지 않는다<br>(P2) 샘플 ID와 기존 보호 대상(경로·파일명·해시)을 모두 보호한다<br>(P3) 사전 허용된 진단 정보(종류·도구·role)는 유지한다<br>(P4) `sample_id`가 없거나 안전하게 제거할 수 없으면 원문 공개를 제한하되 구조화된 원인은 남긴다<br>(P5) 새로 발견한 노출 위험은 미해결 상태로 공개하지 않는다<br>(P6) 확장 비식별화는 후속으로 기록한다. ADR-001 §6 Q-A는 P4로 해소 | FR-6·7·9, NFR-2 공개 조건, §7.1 `withheldTextCount` |

### 10.2 이전 미결정 항목의 검토 기록 (결정 근거로 보존)

아래 표는 결정 전에 비교한 근거와 선택지다. 위 10.1의 결정이 우선한다.

| # | 질문 | 확인된 근거 | 선택지 | 추천 |
|---|---|---|---|---|
| **Q4** | 로그에 원인 블록이 여러 개일 때 어느 것을 쓸까 (FR-16) | [코드] 로그는 이어쓰기, 보고서는 덮어쓰기 (AS-IS 1·4). [코드] 웹 제출은 매번 새 run_id라 웹 경로에서는 블록이 여러 개 생기지 않음 (AS-IS 5). [기록] 아카이브 4건과 로컬 성공 Run 1건 모두 로그 블록 0–1개, `START 00_input_validation` 1회. **블록이 여러 개인 실제 기록은 없음** | a) 파일 전체에서 마지막 블록<br>b) 마지막 `START 00_input_validation` 줄 이후 구간 안의 블록만. 그 구간에 없으면 `no_error_block`<br>c) 블록이 2개 이상이면 해석하지 않고 별도 상태(예: `ambiguous`)로 반환 | **b**. a는 마지막 시도가 traceback으로 끝났을 때 이전 시도의 블록을 현재 원인처럼 보여 줄 위험이 있다. 이는 FR-3에서 피하려던 문제다. 다만 실제 사례가 없어 근거가 코드 분석뿐이므로 사용자가 결정 |
| **Q5** | 읽는 크기·개수·길이 상한 (NFR-6) | [코드] 기존 `read_log_tail()`은 파일 전체를 읽고 줄 수만 자름. 바이트 상한 없음 (AS-IS 8). [코드] `Redactor`의 문자열 상한 `MAX_TEXT = 1000`. [기록] 로그 크기: 실패 Run 2.8–5.0 KB, 성공한 full Run 6.8 KB(110줄). 가장 긴 줄 414자(b94559 bcftools 줄). [코드] BED 오류는 BED마다 첫 오류 1건에서 멈춤 ([main.sh:2030-2072](../../script/main.sh#L2030-L2072)). 그래서 원인 수는 리소스 수에 비례함. [미확인] 보고서 파일의 실제 크기 (로컬·아카이브에 없음), 운영 서버의 오래된 Run 로그 최대 크기 | 읽는 방식:<br>a) 파일 끝에서 최대 N 바이트만 읽음 (파일 위치를 끝 쪽으로 옮긴 뒤 읽는 방식. 첫 줄은 잘렸을 수 있어 버림). 00 실패 시 파이프라인이 거기서 멈추므로 블록은 로그 끝 근처에 있음 (3a22c5: 29줄 중 20–22행)<br>b) 앞에서 최대 N 바이트 (재실행 시 옛 시도를 읽게 되어 Q4와 충돌)<br>c) 크기 확인 후 상한 초과면 읽지 않고 `truncated: true` + `no_error_block`<br>값 후보 (근거: 실측의 수십 배 여유): 읽기 64–256 KiB, 원인 최대 50개, `evidenceText`는 `MAX_TEXT` 재사용, 발췌는 1000자 이내 | 방식 **a**. 값은 실제 운영 로그 최대 크기를 확인한 뒤 확정 권장 |
| **Q7** | `no_error_block`일 때 `unparsedExcerpt`(원인이 아닌 참고 발췌)를 제공할까 | [코드] traceback은 heredoc 비정상 종료 때 생길 수 있음. [기록] 실제 traceback 사례 없음 | a) 제공 (정보 보호·길이 상한 적용)<br>b) 제공하지 않음 (상태만) | **a**. Agent가 "기록은 있으나 분류 불가"를 사용자에게 설명할 근거가 된다. 원인 목록과 분리되어 있어 가상 원인 문제는 없다 |
| **Q8** | 공개 API의 `evidenceText`에서 샘플 식별자 literal까지 지울까 | [코드] 공개 API는 이미 `InputSummary.sample`로 샘플 이름을 응답함 ([schemas.py:189-199](../../backend/app/schemas.py#L189-L199)) | a) Agent와 같은 `Redactor` (literal 포함)<br>b) 형태 규칙만 (경로·해시값·파일명) | **a**. 한 가지 정보 보호 규칙만 유지하면 테스트와 설명이 단순해진다 |

### 10.3 남은 미해결 문제 (명세 확정을 막지는 않음)

| # | 문제 | 처리 |
|---|---|---|
| U1 | Q4의 "실행 시작 지점"을 **00 단계 시작 기록**(`START 00_input_validation`)으로 해석했다. 실행 전체의 시작 기록(파이프라인 머리말)이 아니다. 이유: step 문서와 보고서는 00 단계를 마지막으로 실행한 시도가 쓴 것이므로, 같은 시도의 구간을 고르려면 00 단계 시작이 맞다. 예를 들어 마지막 실행이 00 단계 전에 멈추면, 실행 머리말 기준으로는 현재 step 문서와 맞는 블록을 잃는다 | 사용자 확인 필요. 다르게 의도했다면 FR-16만 바꾸면 됨 |
| U2 | 256 KiB·50개·1000자는 실측(로그 2.8–6.8 KB, 최장 줄 414자) 대비 여유 있게 잡은 초기값이다. 운영 서버의 오래된 Run 로그 최대 크기와 보고서 실제 크기는 측정하지 않았다 | 운영 측정 후 재검토 (Q5 합의) |
| U3 | NFR-10에서 제거할 제어 문자 범위는 [제안]이다 | 구현 전 ADR에서 확정 |
| U5 (v4) | NFR-2 공개 조건은 알려진 식별자와 경로·해시 형태만 확인한다. 원문 속 자유 텍스트(contig 이름, 예외 메시지 등)에 다른 식별정보가 섞일 가능성까지 증명하지 않는다. Agent 경로는 이 문자열을 외부 AI 모델로 보낸다 | 후속 비식별화 개선 과제 (P6). 위험으로 유지 |
| U4 | 실제 기록에는 블록이 여러 개인 로그, traceback만 남은 보고서, 256 KiB를 넘는 로그가 없다. 이 경우들은 합성 입력으로만 검증된다 | T-07·T-14·T-16을 합성 입력으로 작성 |

### 10.4 기술적 위험

| # | 위험 | 완화 |
|---|---|---|
| R1 | main.sh 문구가 바뀌면 규칙이 조용히 `unknown`으로 떨어짐 | NFR-9 heredoc 계약 테스트 |
| R2 | `Redactor`의 경로 패턴이 원인 문장 속 특이한 경로(따옴표, 공백 포함)를 놓칠 수 있음 | 출력 전체에 경로 검사 테스트 (T-08) |
| R3 | 아카이브 4건에는 보고서 파일이 없음. 보고서 형식은 코드로만 확인됨 | heredoc 실행 결과로 보고서 형식 테스트 (T-09) |
| R4 | `unknown` 비율이 높으면 Agent 진단 가치가 떨어짐 | `causes`에서 unknown 개수를 셀 수 있음. 평가에서 측정 |
| R5 | 해석은 "기록된 시점"의 원인이다. 현재 서버 상태(이미 고쳐졌는지)와 혼동할 수 있음 | §7.1에 명시. 현재 상태 점검은 별도 기능 |
| R6 | 사용자 파일 내용이 원인 문장에 섞여 Agent 입력에 들어감 | NFR-10 |

---

## 11. 요구사항 → 테스트 추적표 초안 [제안]

테스트는 **아직 작성하지 않았다.** 아래는 TDD(Test-Driven Development, 실패하는 테스트를 먼저 쓰고 그 테스트를 통과하도록 구현하는 방식)로 옮길 목록이다.

fixture(테스트 입력으로 쓰는 고정 데이터) 정책 [합의 Q6]: 실제 로그에서 서버 경로·샘플 정보·식별정보를 지운 **최소 발췌**만 허용한다. 이번 단계에서는 만들지 않는다. 아카이브 파일 자체는 저장소에 넣지 않는다.

| 테스트 ID | 대상 요구사항 | 방식 | 재사용할 기존 자산 |
|---|---|---|---|
| T-01 3a22c5 로그 블록 | FR-4·5·14 | 정보를 지운 최소 발췌 | — |
| T-02 b94559 복합 | FR-5·10·14 | 최소 발췌 + step 문서. 관계 필드 없음 확인 | `conftest.py` run builder |
| T-03 68aa20·d87484 통과 | FR-1·2 | step 문서만, 파일 접근 감시 | `test_step_detail.py` 패턴 |
| T-04 unknown 보존 | FR-6 | 합성 | — |
| T-05 섞인 순서 | FR-6 | 합성 | — |
| T-06 출처 선택 | FR-3 | 보고서 (있음/없음/OS 오류/블록 없음) × 로그 (있음/없음) 조합 | — |
| T-07 상태값 | FR-8·9, NFR-5 | S7·S8·S9·S12·S13·S23, 0바이트, 잘린 줄, 참고 로그 `null` 조건 | — |
| T-08 정보 보호 | FR-7·9·12, NFR-2 | 두 소비자의 `evidenceText`·`unparsedExcerpt`에서 경로·hex·sample_id 검사. 공개 API 기존 필드 불변 확인 | `privacy.Redactor`, 기존 privacy 검사 방식 |
| T-09 heredoc 계약 | NFR-9 | 원본 `PYBUNDLE`을 추출해 BED 없음, sha 불일치, PATH에 bcftools 없음(PATH를 빈 디렉터리로 고정해 환경 의존 제거)으로 실행 → 분류 확인 | `test_reference_bundle_validation.py`의 추출 fixture |
| T-10 공개 API 하위 호환 | FR-12, NFR-4 | 기존 테스트 무수정 통과, 새 필드는 최상위·다른 step `null` | `test_step_detail.py`, `test_results_precheck.py` |
| T-11 Agent 근거 | FR-11 | `read_step_evidence` 결과에 새 필드, 기존 필드 동일, 다른 step `null` | `test_agent_step_tool.py` |
| T-12 원본 불변 | FR-13 | 실행 전후 hash 비교 | `real_runs.capture_manifest` 방식 |
| T-13 결정성 | NFR-1 | 두 번 실행 비교 | — |
| T-14 상한 | NFR-6 | S19–S22 합성 입력. 읽은 바이트 수·원인 수·문자열 길이·`truncated` 확인 | — |
| T-15 소비자 일관성 | FR-15 | 같은 입력을 두 소비자로 투영해 새 필드 값 전체 비교 | — |
| T-16 해석 구간 | FR-16 | S14·S17·S18, 구간 안 블록 2개 합성 입력. 구간끼리 합쳐지지 않음 확인 | — |
| T-17 신뢰할 수 없는 문자열 | NFR-10 | 제어 문자·색상 코드·긴 contig 이름이 든 합성 줄 | — |
| T-18 polling 비용 | NFR-7 | 실행 중 step 조회 시 두 출처 파일을 열지 않음 | `test_step_detail.py` 패턴 |

역방향 확인: FR-1–16, NFR-1·2·4·5·6·7·9·10은 위 표에 대응 테스트가 있다. NFR-3은 T-06(두 출처 외 경로 미접근)과 T-02(`resourceRole: unknown`)로 확인한다. NFR-8(확장성)은 자동 테스트 대상이 아니며 ADR 검토로 확인한다.

---

## 12. 구현 테스트 추적 (v4, 2026-11-13)

§11의 계획을 실제 테스트로 옮긴 결과다. 파일:
- `backend/app/tests/test_resource_bundle_causes.py` (C): 67개
- `backend/app/tests/test_resource_bundle_diagnosis.py` (D): 21개

로컬 Windows에서 모두 통과했다. 실행 기록은 [ADR-001 §10](../adr/ADR-001-resource-cause-boundary.md).

표기: [실제] 아카이브 원본 / [heredoc] main.sh 원본 실행 / [합성] 테스트용 입력

| 요구사항 | 테스트 (파일: 함수) | 근거 |
|---|---|---|
| FR-1·2 | C `test_not_failed_is_not_applicable_and_reads_nothing`(4종), `test_other_steps_have_no_analysis_and_read_nothing`, `test_real_68aa20_passed_is_not_applicable_without_reading` | 합성, 실제 |
| FR-3 | C `test_report_wins_over_log`, `test_report_without_block_does_not_fall_back_to_the_log`, `test_empty_report_counts_as_present`, `test_unreadable_report_falls_back_to_the_log` | 합성 |
| FR-4 | C `test_header_without_items_is_no_error_block`, `test_timestamped_error_line_is_not_the_header`, `test_cut_last_line_still_counts` | 합성 |
| FR-5·§7.3 | C `test_rule_table`(26종), `test_heredoc_*`(4개) | 합성, heredoc |
| FR-6 | C `test_unclassified_sentence_is_unknown`, `test_known_and_unknown_keep_their_order`, `test_raw_text_is_kept_internally_verbatim` | 합성 |
| FR-7·NFR-2 | D `test_structured_fields_are_kept_and_text_is_redacted`, `test_unknown_sample_withholds_every_raw_string_but_keeps_the_causes`, `test_residual_path_shape_is_withheld_even_with_a_sample`, `test_api_old_job_without_sample_id_withholds_text`, `test_real_runs_through_api_and_agent` | 합성, 실제 |
| FR-8 | C `test_both_missing_is_source_unavailable`, `test_both_unreadable_is_source_unreadable`, `test_os_error_while_reading_is_unreadable_not_partial`, `test_no_start_marker_is_unresolved` 외 | 합성 |
| FR-9 | C `test_report_without_block_does_not_fall_back_to_the_log`, D `test_excerpt_is_redacted_or_withheld` | 합성 |
| FR-10 | D `test_api_returns_the_diagnosis_for_a_failed_bundle` (required_tools FAIL 동시 확인, 관계 필드 없음), C `test_real_b94559_four_causes` | 합성, 실제 |
| FR-11 | D `test_agent_gets_exactly_what_the_api_returns`, `test_agent_null_for_other_steps`. 기존 `test_agent_step_tool.py` 고정 필드 테스트 갱신 | 합성 |
| FR-12·NFR-4 | D `test_api_keeps_every_existing_field_unchanged`, `test_api_null_for_other_steps`. 기존 `test_step_detail.py` 무수정 통과 | 합성 |
| FR-13 | C `test_sources_are_not_modified`, `test_real_sources_are_not_modified` | 합성, 실제 |
| FR-14 | C `test_real_3a22c5_two_bed_causes`, `test_real_b94559_four_causes` | 실제 |
| FR-15 | D `test_agent_gets_exactly_what_the_api_returns`, `test_agent_parity_also_holds_without_a_sample`, `test_real_runs_through_api_and_agent` | 합성, 실제 |
| FR-16 | C `test_only_the_last_attempt_counts`, `test_old_block_is_not_reused_when_the_last_attempt_has_none`, `test_no_start_marker_is_unresolved`, `test_two_blocks_in_one_segment_is_unresolved`, `test_two_blocks_in_one_report_is_unresolved` | 합성 |
| NFR-1 | C `test_same_input_same_output` | 합성 |
| NFR-2 (서버 로그) | C `test_raw_sentences_never_reach_the_server_log` | 합성 |
| NFR-3 | C 출처 테스트 전체(두 경로 외 읽기 없음은 `reads` 감시로 확인), `test_beds_plus_bcftools_is_four_causes_with_unknown_role` | 합성 |
| NFR-5 | C `test_undecodable_bytes_are_replaced_not_fatal`, `test_cut_last_line_still_counts`, `test_empty_report_counts_as_present` | 합성 |
| NFR-6 | C `test_large_log_with_start_outside_the_window_is_unresolved_and_truncated`, `test_large_log_with_segment_inside_the_window_is_complete`(읽은 바이트 ≤ 262,144), `test_large_report_without_header_in_window_is_unresolved`, `test_more_than_fifty_causes_is_truncated`, D `test_long_text_is_capped_at_1000_characters` | 합성 |
| NFR-7 | D `test_api_running_step_reads_no_source` | 합성 |
| NFR-9 | C `test_heredoc_output_has_no_unclassified_sentence` 외 heredoc 3개 | heredoc |
| NFR-10 | D `test_control_characters_and_escapes_are_removed` | 합성 |
| ADR E1·E2 | D `test_step_reader_output_carries_no_analysis`, `test_internal_value_is_not_a_response_model` | 합성 |
| ADR K4 | D `test_redactor_for_row_matches_the_agent_scope` + 기존 Agent 정보 보호 테스트 무수정 통과 | 합성 |

자동 테스트로 확인하지 않은 것:
- NFR-4의 frontend 파싱. 코드만 확인했다.
- NFR-8 확장성. ADR 검토로 확인한다.
- U5 미지의 식별정보.

## 부록 A. 이번 명세에서 하지 않는 것

- 복구 작업 실행 (`restore_capture_bed` 등)
- 현재 서버 리소스 상태 점검 (별도 읽기 도구 후보)
- 원인 사이의 관계(근본 원인·파생 증상) 판정
- 기존 `logTail`의 경로 노출 개선 (별도 과제)
- main.sh 수정 (방법 B)
- ADR(Architecture Decision Record, 설계 결정을 이유와 함께 남기는 기록) 확정
- 화면(UI) 표시
- fixture 파일 작성

## 부록 B. 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-11-12 | 초안 작성 (Specify 단계). 구현·테스트 없음 |
| 2026-11-13 | 구현 단계 정책 반영 (v4):<br>- 사용자 정책 P1–P6: §10.1<br>- NFR-2에 공개 조건(fail-closed) 추가. FR-6·7·9에 원문 비공개 시 `null` 처리 추가<br>- §7.1에 `withheldTextCount` 추가<br>- FR-16에 보고서 헤더 2개 이상 명확화. U5 추가<br>- §12 구현 테스트 추적 추가<br>- 기존 합의 항목은 삭제·약화하지 않음 |
| 2026-11-12 | 최종 결정 반영 (v3):<br>- Q4: FR-16 해석 구간 확정, 상태 `segment_unresolved` 추가<br>- Q5: NFR-6 값과 `truncated` 의미 확정<br>- Q7: FR-9 참고 로그 확정<br>- Q8: FR-12·NFR-2 두 소비자 동일 규칙<br>- AS-IS 14(로그 줄 형식) 추가, FR-4 헤더 조건 명확화<br>- 시나리오 S14 수정, S17–S23 추가. 10.3 남은 미해결 문제 정리. 추적표 T-07·08·14·16 갱신 |
| 2026-11-12 | Clarify 반영 (v2):<br>- Q1·Q2·Q3·Q6 결정 반영. FR-8·9 충돌 해소 (`no_error_block`에서 원인 생성 금지)<br>- FR-3 출처 전환 조건 명확화. FR-15(공통 해석 기능)·FR-16(블록 선택) 추가<br>- NFR-2 소비자별 정보 보호, NFR-5 해독 규칙, NFR-10(신뢰할 수 없는 문자열) 추가<br>- S2 역할 표기 모순 수정, 시나리오 S9–S16 추가. Q4·Q5·Q7·Q8 미결정으로 정리<br>- 추적표 T-15–T-18 추가 |
