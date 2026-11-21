# WES Diagnostic Agent — 확장 로드맵 초안 (Phase 0 조사)

> **조사 기준** `d240654`(HEAD `4822b41`은 문서 커밋), 2026-11-06. Windows 로컬 저장소만 읽었다.
> 코드 수정, 패키지 설치, 모델 호출, 파이프라인 실행은 하지 않았다.
> **정본과의 관계**: 제품 요구사항·평가 지표(M1~M5, S1~S5)·작업 ID(T1~T20)·결정 항목(D-*)의 정본은 [`AGENT_PLAN.md`](AGENT_PLAN.md)다.
> 이 문서는 그 위에 "어떤 AI Agent 기술을 어떤 순서로 실험할 것인가"만 다룬다. 둘이 충돌하면 AGENT_PLAN과 실제 코드가 우선한다.
> AGENT_PLAN은 `c41f1e2` 기준으로 쓰였다. 그 뒤 바뀐 점(검증 7단계, 자동 수정, trace 9필드, 실측 Run 평가)은 아래 1장에 반영했다.

표시: `[코드확인]` 저장소에서 확인 · `[기록]` 저장된 실행 기록 · `[문서확인]` 외부 공식 문서에서 확인 · `[미확인]` 확인하지 못함 · `[제안]` 새 제안

---

## 0. 결론 먼저

1. **지금의 Agent는 "고정 질문 1개 + 고정 근거 묶음 + 조회 Tool 1개 + 결정론적 검증"이다.** 사용자 질문이 없고, 지식은 6개 JSON 파일(약 55KB, 항목 약 70개)이다. 지식은 발생한 코드 기준으로 **코드가 골라** payload에 넣는다. 이 조건에서는 검색(RAG)이 풀어야 할 문제가 아직 없다.
2. **기술을 붙이기 전에 "기술이 차이를 낼 수 있는 질문"부터 만들어야 한다.** 실측 Run(cba73e) 6회 실행에서 MCP Tool 호출은 0회였다 `[기록]`. 근거를 더 주는 기술(RAG, Agentic RAG)이 효과를 내려면 payload만으로 답할 수 없는 질문이 필요하다.
3. 그래서 **Phase 1을 "검색 품질만 따로 재는 오프라인 실험"으로 시작한다.** 모델 호출 없이 질문 → 기대 지식 ID의 Recall@k를 잰다. 비용 0, 결정적, 기존 검증 경계도 건드리지 않는다.
4. **LangGraph·Multi-Agent·Memory는 지금 구조를 바꾸는 것이 아니라 "같은 결과를 내는가"부터 검증한다.** 현행 흐름(조립 → 호출 → 검증 → 수정 → 기록)은 이미 고정된 작은 그래프다. 먼저 동등성(parity)을 확인하고, 그다음 분기·재개 같은 새 능력의 효과를 잰다.
5. **가장 큰 설계 위험은 검증 약화다.** gate 4(숫자)와 gate 5(필드명)는 "모델에게 보여 준 것"을 사실 집합으로 쓴다([`validation.py`](../backend/app/services/explanation/llm/validation.py)). 검색 결과를 payload나 tool 반환에 넣으면 **그 안의 숫자도 '인용 가능한 사실'이 된다.** 검색량이 늘수록 gate 4가 느슨해진다. 모든 확장 실험은 이 점을 지표로 같이 본다(3장 공통 지표 G-1).

---

## 1. 현재 구조 조사

### 1-1. 입력과 처리 흐름 `[코드확인]`

```
POST /api/jobs/{id}/synthesis   (요청 본문 없음 = 질문 없음)          api/synthesis.py
  │
  ├─ run_context → deterministic.build_run_explanation               규칙 기반, 모델 없음
  ├─ contract.build_payload(explanation) → (payload, allowed_ids)    allowlist + evidence id 발급
  │     발생한 진단/실패 코드의 grounding, 인용된 sources, concepts, terms, 단계 메뉴(3필드)
  ├─ prompt.build_prompt                                             제약문 + <run_data> JSON
  ├─ tools.step_detail_toolset(job_id)                               MCP 설정 + 요청별 sink
  ├─ provider.run_structured(user_prompt, json_schema, model,        Claude Code CLI 1회
  │                          mcp_config, allowed_tools)
  ├─ _observe → tools.credit                                         sink에 기록된 Tool 결과만 사실로 인정
  ├─ facts = payload + 회수한 step evidence
  ├─ _check (gate 2~7)                                               하나라도 걸리면 전체 거부
  ├─ (WES_SYNTHESIS_REPAIR=on) build_repair_prompt → 2번째 호출 → _splice → _check
  └─ trace.record (9필드, SQLite synthesis_traces)
```

- 진입 함수: `synthesis.build_run_synthesis(explanation, *, model, timeout_seconds, run_provider, on_tool_use, on_trace, offer_tools, repair)`. I/O가 없고 provider를 주입받는다. **실험용 변형을 끼우기 가장 좋은 경계다.**
- 출력: `RunSynthesis` = `summary` + 4개 묶음(`importantFindings`, `limitations`, `nextChecks`, `uncertainties`). 묶음의 문장마다 `evidenceRefs`가 1개 이상 있어야 한다.
- evidence id 접두사: `run:` `dx:` `fail:` `lim:` `src:` `concept:` `step:` (+용어 근거). 서버가 발급하고 모델은 복사만 한다.

### 1-2. Knowledge 구성과 관리 `[코드확인]`

| 파일 ([`config/knowledge/`](../config/knowledge/)) | 항목 수 | 크기 |
|---|---|---|
| `wes_diagnostics.json` | 진단 29 | 23KB |
| `wes_terms.json` | 용어 8 | 11KB |
| `wes_failures.json` | 실패 2 (`closedSet`) | 6.6KB |
| `wes_concepts.json` | 개념 3 | 6.2KB |
| `wes_sources.json` | 출처 19 | 5.0KB |
| `wes_steps.json` | 단계 11 | 3.9KB |

- [`knowledge.py`](../backend/app/services/explanation/knowledge.py)가 Pydantic 모델로 load한다. 출처가 해석되지 않는 claim은 load 단계에서 거부한다(`_check_sources_resolve`).
- 조회는 **ID 키 조회뿐**이다: `diagnostic(code)`, `failure(code)`, `term(id)`, `concept(id)`, `source(id)`, `step(id)`. 검색, 임베딩, 색인은 없다.
- payload에는 이 Run에서 **발생한 코드의 grounding만** 들어간다(`contract.build_payload`의 "grounding, only for codes this run raised"). 즉 지금의 "retrieval"은 **결정론적 키 조회**다.
- 버전 관리: 평가 기록에 `knowledgeHash`가 남는다(`run_eval`). 런타임 trace에는 없다.
- 저장소 안에 지식 후보가 될 문서가 더 있다: [`MAIN_SH_COMPLETE_GUIDE.md`](MAIN_SH_COMPLETE_GUIDE.md), [`CAPTURE_BED_RESOURCES.md`](CAPTURE_BED_RESOURCES.md), [`DEPLOYMENT.md`](DEPLOYMENT.md). **현재 Agent는 이 문서들을 쓰지 않는다.**

### 1-3. MCP Tool `[코드확인]`

- 서버 `wes-run-evidence`, SDK `mcp==2.2.0`, stdio. CLI가 요청마다 `python -m app.agent_mcp`로 띄운다([`agent_mcp/`](../backend/app/agent_mcp/)).
- Tool은 `get_step_detail(stepId)` **1개**. 반환은 `StepEvidence`(status, checks, metrics, warnings, failures 등). 경로·파일명·시각은 빠진다.
- Run은 서버 생성 시 closure로 고정된다(`run_scope.py`). 모델은 단계만 고른다.
- 예산: 서로 다른 단계 최대 2개(`DEFAULT_MAX_DISTINCT_STEPS = 2`). 재요청은 memo.
- sink: 성공한 반환은 evidence 줄, 거부·재요청은 `attempt` 줄(`outcome: repeat|refused`)로 기록된다([`tool_sink.py`](../backend/app/services/agent/tool_sink.py)). AGENT_PLAN T2a의 일부가 반영된 상태다.
- 개인정보: `privacy.py` Redactor, snake_case metric만, 문자열 metric은 허용 목록만.

### 1-4. Claude Provider `[코드확인]`

- `claude -p --output-format json --json-schema …`, 프롬프트는 stdin. 설치 CLI 2.1.316.
- 격리: `--tools ""`, `--strict-mcp-config`, `--allowedTools`, `--permission-prompts none`, `--setting-sources ""`, `--no-session-persistence`, `--disable-slash-commands`.
- 비용 차단: `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`이 있으면 거부, `claude auth status`가 구독이 아니면 거부. 재시도 없음. **API 과금 경로가 없다.**
- 반환 `ProviderResult`: `payload`, `models`, `durationMs`, `numTurns`. CLI envelope의 `modelUsage`는 **모델 이름만 쓰고 토큰 수는 버린다**(`provider.py` 358행 부근). A/B 실험 기록도 "토큰 사용량: 기록되지 않는다"고 적고 있다 `[기록]`.
- turn 상한: 코드 주석은 "설치된 CLI에 `--max-turns`가 없다"고 적는다(`run_scope.py`). 공식 CLI 문서에는 print 모드의 `--max-turns`가 나와 있다 `[문서확인]`. 로컬 `claude --help` 출력에는 보이지 않았다. **숨김 옵션인지, 버전 차이인지는 `[미확인]`.**

### 1-5. 검증 7개와 자동 수정 `[코드확인]`

| gate | 내용 | 위치 |
|---|---|---|
| 1 | CLI JSON schema | provider |
| 2 | Pydantic 재검증 | synthesis `_check` |
| 3 | 발급되지 않은 evidence id 인용 금지 | synthesis |
| 4 | 사실 집합에 없는 숫자 금지(20 이하 정수 제외) | validation.py |
| 5 | 사실 집합의 camelCase 키 노출 금지 | validation.py |
| 6 | 측정값·경고 단계 수·경고 단계 이름이 payload 필드와 일치 | claims.py `find_run_fact_mismatches` |
| 7 | 진단 전용 주제는 그 진단을 인용, 조건부 사실은 조건을 인용 | claims.py `find_evidence_mismatches` |

- **자동 수정**(`WES_SYNTHESIS_REPAIR`, 기본 off): gate 2~7 거부 시 발견 사항과 거부된 답을 같은 provider에 1회 보낸다. 지적된 항목만 바꾸고 나머지는 첫 답에서 가져온다(`_splice`). 다시 `_check`를 같은 사실 집합으로 통과해야 한다. provider 실패는 재시도하지 않는다.
- 사실 집합의 정의가 핵심이다: **payload + sink로 회수한 Tool 결과**. 확장 기술이 이 집합에 무엇을 더하는지가 검증 강도를 결정한다.

### 1-6. Trace와 Evaluation `[코드확인]`

**Trace** ([`trace.py`](../backend/app/services/explanation/llm/trace.py)): models, durationMs, numTurns, openedStepIds, available, errorCategory, repairEnabled, attempts, firstRejection. 프롬프트·생성문·Tool 반환은 저장하지 않는다. 조회 API는 없다(`trace.recent()`만).

**Evaluation** ([`backend/evals/`](../backend/evals/), pytest 수집 대상 아님):

| 도구 | 역할 |
|---|---|
| `run_eval.py` | 실제 모델 호출. `--case`(fixture 4, agent 3, real 1), `--variant v1/v3`(Tool 유무), `--rescore`(모델 호출 없이 재채점), `--record-baseline` |
| `evaluators.py` | 숫자, 인용, 언급, 필드명, Tool 사용, 단계 선택, guardrail |
| `explanation_quality.py` | 초보자 설명 품질(term / internal / fact → PASS/FAIL/REVIEW), rubric v1·v2 |
| `compare_versions.py` | 두 버전 답변을 같은 rubric으로 재채점, 블라인드 시트 생성 |
| `real_runs.py`, `dev_restore.py` | 보존 실측 Run을 임시 복사본으로 복원(원본 해시 확인) |
| `agent_cases.py` | 합성 Run 3건을 임시 DB로 생성 |

**기록**: baselines 14개(09-10 단발 6, 11-01~02 Agent·실측 8), A/B 실험 1건(`experiments/ab_2026-11-04/`, A·B 각 3회).

### 1-7. 있는 것과 없는 것

| 영역 | 있음 `[코드확인]` | 없음 |
|---|---|---|
| 입력 | 고정 의도 1개, allowlist payload | **사용자 질문**, 질문 유형 분류 |
| 지식 | 구조화 JSON, 출처 강제, ID 조회, knowledgeHash(eval) | 문서 chunk, 검색, 임베딩, 색인, 런타임 지식 버전 |
| Tool | `get_step_detail` 1개, Run 고정, 예산, 거부 기록 | 지식 검색 Tool, artifact 요약 Tool |
| 실행 제어 | CLI 1회(+수정 1회), timeout 300초 | 명시적 상태 그래프, checkpoint, 재개, 분기 |
| 검증 | 7 gate, 자동 수정, 전체 폐기 | 의미 수준 근거 충실도 자동 판정(M5는 사람 라벨) |
| 기억 | 없음(세션 지속 끔) | Run 단위·사용자 단위 memory |
| 관측 | trace 9필드(SQLite) | 토큰 수, span 구조, 조회 API, 외부 관측 도구 |
| 평가 | 결정론 채점, 품질 rubric, 버전 비교, 블라인드 시트, 실측 Run 복원 | **검색 평가셋**, 반복 실행 표준 경로(A/B는 wrapper로 실행), 집계 스크립트 |
| 모델 | `WES_SYNTHESIS_MODEL` 1개(기본 `sonnet`) | 요청별 라우팅 |

### 1-8. 재사용할 코드와 바꿔야 할 경계

**그대로 재사용** (AGENT_PLAN 6-2와 같은 판단)
- `build_payload`의 evidence id 발급 방식 → 검색 결과에도 같은 방식으로 id를 발급하면 gate 3이 그대로 동작한다.
- `validation.py`, `claims.py` → 어떤 구조로 바꿔도 마지막 관문으로 유지한다.
- `run_structured` 시그니처, 비용 차단 → 모든 Phase의 모델 호출이 이 함수 하나를 지나게 한다.
- `tools.credit`/sink → 새 Tool도 "서버가 기록한 것만 근거"라는 원칙을 따른다.
- `run_eval`의 variant, `--rescore`, `compare_versions`, `dev_restore` → 비교 실험의 뼈대.

**확장 시 바뀌는 경계**
| 경계 | 바뀌는 이유 | 주의 |
|---|---|---|
| `POST /synthesis` 요청 본문 | 질문 입력(D-Q, T12) | 질문 문자열은 신뢰하지 않는 데이터. 프롬프트 인젝션 평가 필요 |
| `build_payload` | 검색 결과 섹션 추가 | **gate 4·5의 사실 집합이 넓어진다** |
| MCP 서버 | 지식 검색 Tool 추가 | 반환이 sink → facts로 합쳐져 같은 문제 |
| `_check`의 사실 집합 | 검색 결과 중 "인용된 것만" 사실로 볼지 | gate 4를 "인용한 근거 안의 숫자"로 좁히는 AGENT_PLAN T8과 함께 설계 |
| trace 스키마 | 검색 id, 토큰 수, 노드 단위 기록 | 생성문·프롬프트는 계속 저장하지 않는다 |
| `evals/` | 검색 평가, 반복·집계 | runtime이 evals를 import하지 않는 방향 유지 |

---

## 2. 기술 확장 후보 분석

### 2-0. 모든 기술에 걸리는 이 프로젝트의 제약

| 제약 | 영향 |
|---|---|
| **모델은 구독 CLI로만 호출**(API 과금 경로 없음) | 클라우드 임베딩 API(유료)를 쓰면 이 원칙이 깨진다. 임베딩은 **로컬 모델**이 기본 후보. LangGraph 등에서 LangChain의 API 기반 chat model을 쓰지 않고, 노드 안에서 `run_structured`를 호출해야 한다 |
| 구독 사용량 한도(`usageLimit`) | 호출 수가 늘어나는 기술(Multi-Agent, 반복 루프, LLM Judge)은 실험 비용이 곧 사용량이다 |
| 질문이 없다 | 검색 기술의 효과를 보여 줄 질의가 없다. 질문 세트가 선행 조건 |
| 지식이 작다(약 70항목) | 벡터 DB의 규모 이점이 없다. 정확도·근거 연결 측면만 의미가 있다 |
| 한국어 답변, 영어 용어 혼용 | BM25 토큰화(한국어 형태소)와 임베딩 모델의 다국어 성능이 결과를 좌우한다 |
| RUO, 원인 단정 금지 | 검색으로 문헌을 가져와도 "임상 의미"나 "원인 확정"으로 쓰면 안 된다 |
| 개인정보 | Run 데이터는 외부 서비스(호스팅 관측 도구, 외부 벡터 DB)로 보내지 않는 것을 기본으로 한다 |

### 2-1. 기술별 분석

우선순위: **A** = Phase 0~1에서 착수 · **B** = 선행 결과에 따라 착수 · **C** = 착수 조건이 생길 때만

#### Agent Evaluation — 우선순위 A
- **한 문장**: Agent의 답과 행동(도구 사용, 단계 선택, 지연)을 같은 기준으로 반복해서 재는 체계.
- **이 프로젝트 사례**: 모든 확장 실험의 판정 장치. 이미 가장 많이 갖춘 영역이다.
- **연결 위치**: `backend/evals/` 전체. `run_eval`의 variant를 "기술 변형"으로 넓힌다.
- **사전 작업**: 반복 실행·집계의 표준 경로(A/B는 scratchpad wrapper로 돌렸다), 기록 파일명에 커밋·반복 번호, 질문 유형별 case 구조.
- **비교 실험**: 같은 case에서 V1(Tool 없음) / V3(현행)을 K회 반복 → gate 통과율, 품질 rubric FAIL 수, 지연의 분포.
- **학습 가치 / 복잡도**: 높음 / 중간. 모든 Phase의 신뢰도를 결정한다.
- **근거**: AGENT_PLAN T3a·T4가 아직 미완이고, 이게 없으면 다른 기술의 차이를 주장할 수 없다.

#### Observability — 우선순위 A(최소 범위) / B(외부 도구)
- **한 문장**: 요청 하나가 어떤 단계를 거쳐 얼마나 걸리고 무엇을 썼는지 사후에 볼 수 있게 남기는 것.
- **사례**: 토큰 수·노드별 지연·검색 id를 trace에 남겨 "검색이 늘린 비용"을 잰다.
- **연결 위치**: `provider.ProviderResult`(토큰), `trace.SynthesisTrace`, 향후 노드 경계.
- **사전 작업**: `modelUsage`의 토큰 필드 구조 확인 `[미확인]`(현재 버린다). trace 조회 경로(평가용 읽기 함수는 있음).
- **비교 실험**: 계측 전·후 동일 case의 응답 시간 차이(계측 오버헤드), 기록 누락률.
- **공식 문서**: OpenTelemetry GenAI semantic conventions에 agent span(`invoke_agent` 등) 규약이 있다. 상태는 **개발 단계(Development)**다 `[문서확인]`. 저장소 이전 여부 등 세부는 `[미확인]`. 규약 이름만 맞춰 두고, 외부 수집기는 개인정보 검토 후로 미룬다.
- **학습 가치 / 복잡도**: 중간 / 낮음(필드 추가) ~ 중간(OTel 도입).

#### BM25 — 우선순위 A
- **한 문장**: 질문 단어가 문서에 얼마나 드물고 자주 나오는지로 점수를 매기는 고전적 키워드 검색.
- **사례**: "dbSNP가 없으면 뭐가 빠지나요?" → `DBSNP_NOT_CONFIGURED` 진단, `dbsnp-rsid` 용어 찾기. 진단 코드·도구명 같은 **정확한 토큰**에 강하다.
- **연결 위치**: 새 모듈(예: `services/explanation/retrieval/`) — 처음에는 `evals/` 안의 오프라인 실험으로만.
- **사전 작업**: 지식 JSON을 검색 단위(chunk)로 펼치는 규칙, 한국어 토큰화 방식(문자 n-gram vs 형태소 분석기), 질문 세트.
- **비교 실험**: 키 조회 baseline(질문에 코드가 있으면 그 항목) vs BM25 → Recall@k, MRR. 모델 호출 0회.
- **학습 가치 / 복잡도**: 중간 / 낮음. 표준 라이브러리로도 구현 가능한 규모.
- **근거**: 비용 0, 결정적, 다른 검색 기법의 기준선.

#### RAG — 우선순위 A(오프라인 검색) / B(답변 연결)
- **한 문장**: 질문과 관련된 문서를 먼저 찾아 프롬프트에 넣고, 모델이 그 근거로 답하게 하는 방식.
- **사례**: 질문형 설명에서 payload에 없는 지식(발생하지 않은 진단의 의미, main.sh 단계 설명, capture BED 자료)을 인용.
- **연결 위치**: `build_payload`에 `retrieved` 섹션 + `kb:` 계열 evidence id 발급. 또는 MCP Tool(→ Agentic RAG).
- **사전 작업**: 질문 입력(D-Q 결정), 검색 평가(Phase 1a), **사실 집합 정책**(검색된 텍스트의 숫자를 gate 4가 어떻게 볼지).
- **비교 실험**: 같은 질문에서 (a) payload만 (b) payload + 키 조회 (c) payload + 검색 top-k → 질문 답변 정확도(사람 라벨), 인용 정확도, gate 통과율, 프롬프트 바이트, 지연.
- **학습 가치 / 복잡도**: 높음 / 중간.
- **근거**: AGENT_PLAN은 RAG를 P2(T13)로 두고 "curated payload로 감당 못 할 때"를 조건으로 걸었다. 이 문서는 그 조건을 **측정으로 확인하는 단계(Phase 1a)를 앞당기는 것**이지, 런타임 도입을 앞당기는 것이 아니다.

#### Embedding — 우선순위 B
- **한 문장**: 문장을 숫자 벡터로 바꿔 뜻이 비슷한 문장끼리 가깝게 놓는 기술.
- **사례**: "평균 커버리지가 낮다는 게 무슨 말이에요?" 처럼 지식 문장과 단어가 겹치지 않는 질문.
- **연결 위치**: 검색 모듈의 색인 단계(오프라인 생성, 파일로 저장).
- **사전 작업**: **로컬** 다국어 임베딩 모델 선정(특정 모델의 한국어 성능은 `[미확인]`), 의존성 크기 검토(새 패키지 필요), 지식 변경 시 재색인 규칙(knowledgeHash 연동).
- **비교 실험**: BM25 vs 임베딩 → Recall@k를 질문 유형별(코드 포함 / 자연어 / 혼용)로.
- **학습 가치 / 복잡도**: 높음 / 중간.
- **근거**: 유료 API를 쓰지 않는 원칙 때문에 모델 준비 비용이 있다. BM25 결과가 자연어 질문에서 부족할 때 착수.

#### Vector DB — 우선순위 C
- **한 문장**: 임베딩 벡터를 저장하고 가까운 벡터를 빠르게 찾아 주는 저장소.
- **사례**: 지식이 수천 chunk 이상(문서·문헌 추가)으로 커질 때.
- **연결 위치**: 검색 모듈 뒤의 저장 계층. 이 프로젝트는 SQLite를 쓰므로 sqlite-vec 같은 SQLite 확장이 후보다. sqlite-vec는 **pre-v1이며 호환성이 깨질 수 있다고 스스로 명시**한다 `[문서확인]`.
- **사전 작업**: Embedding 단계 완료, 규모 측정.
- **비교 실험**: 메모리 내 전수 비교(numpy 등) vs Vector DB → 결과 동일성, 지연. 70항목 규모에서는 차이가 없을 것으로 **예상**한다.
- **학습 가치 / 복잡도**: 중간 / 중간.
- **근거**: 현재 규모에서 전수 비교로 충분하다. "Vector DB를 썼다"는 것 자체가 차이를 만들지 않는다.

#### Hybrid Search — 우선순위 B
- **한 문장**: 키워드 검색과 의미 검색 결과를 합쳐(예: 순위 융합 RRF) 둘의 약점을 보완하는 방식.
- **사례**: 진단 코드(정확 일치)와 자연어 설명(의미 일치)이 섞인 질문.
- **연결 위치**: 검색 모듈의 결합 단계.
- **사전 작업**: BM25와 Embedding 각각의 결과.
- **비교 실험**: BM25 / Embedding / Hybrid → 질문 유형별 Recall@k. Hybrid가 두 단일 방식 중 나은 쪽보다 나아야 채택.
- **학습 가치 / 복잡도**: 중간 / 낮음(둘이 있으면).

#### Reranker — 우선순위 C
- **한 문장**: 1차 검색 후보를 질문과 함께 다시 읽어 순서를 정교하게 매기는 2단계 모델.
- **사례**: 후보가 많고 top-3 정확도가 중요할 때.
- **연결 위치**: Hybrid 뒤. 로컬 cross-encoder 또는 LLM rerank(구독 사용량 소모).
- **사전 작업**: 후보 집합이 충분히 크고, 1차 검색의 Recall@20은 높은데 Recall@3이 낮다는 측정.
- **비교 실험**: rerank 전·후 nDCG@3, 추가 지연.
- **학습 가치 / 복잡도**: 중간 / 중간.
- **근거**: 70항목 규모에서는 1차 검색 결과 자체가 짧다.

#### Agentic RAG — 우선순위 B
- **한 문장**: 모델이 검색이 필요한지, 무엇으로 검색할지 스스로 판단해 도구로 검색하는 방식.
- **사례**: MCP에 `search_wes_knowledge(query)`를 추가(AGENT_PLAN 2-4의 P2 후보).
- **연결 위치**: `agent_mcp/server.py`(새 Tool), sink, `tools.credit`.
- **사전 작업**: Phase 1의 검색 품질 확인, 예산 규칙(검색 횟수), 반환 텍스트의 Redactor 적용, **사실 집합 정책**.
- **비교 실험**: 정적 RAG(코드가 검색해서 넣음) vs Agentic RAG(모델이 검색) → 답변 정확도, 검색 호출 수, 불필요 검색 비율, 지연. 이는 AGENT_PLAN의 Q-sel(규칙이 고르나 모델이 고르나) 질문을 지식 검색에 그대로 옮긴 것이다.
- **학습 가치 / 복잡도**: 높음 / 높음.
- **근거**: 실측 Run에서 기존 Tool조차 0회 호출됐다 `[기록]`. 모델이 도구를 언제 쓰는지에 대한 측정이 먼저다.

#### LangGraph / State / Checkpoint — 우선순위 B
- **한 문장**: Agent 흐름을 상태(State)를 가진 노드 그래프로 정의하고, 각 단계의 상태를 저장(Checkpoint)해 중단·재개를 지원하는 프레임워크.
- **현재 버전**: v1 계열이며, 공식 문서는 v1이 핵심 그래프 API를 유지하고 checkpoint·persistence·human-in-the-loop를 계속 핵심 기능으로 둔다고 적는다 `[문서확인]`. 정확한 최신 버전 번호는 출처마다 달라 `[미확인]`. interrupt는 checkpointer가 필요하고, SQLite 기반 checkpointer가 있다 `[문서확인, 패키지명·버전은 설치 전 재확인]`.
- **사례**: 현행 흐름을 `assemble → call → observe → check → (repair → splice → check) → record` 그래프로 옮긴다. 나중에 질문 분류 → 검색 → 답변 → 검증 분기를 노드로 추가한다.
- **연결 위치**: `build_run_synthesis` 내부를 대체하는 별도 구현(변형 V-graph). route와 provider는 그대로.
- **State 설계**: payload, allowed_ids, facts, verdicts, attempts, tool_use. **생성문과 프롬프트를 checkpoint에 저장하면 "trace에 생성문을 저장하지 않는다"는 현행 원칙과 충돌한다** — 저장 위치·보존 기간을 먼저 정해야 한다.
- **사전 작업**: 노드 경계별 기존 테스트 매핑, 가짜 provider로 parity 테스트, 의존성 검토.
- **비교 실험**: (1) 동등성: 같은 가짜 provider 응답에서 현행과 그래프 구현의 결과·trace가 같은가(모델 호출 0). (2) 새 능력: 검증 실패 시 다른 경로로 분기하는 정책이 gate 통과율을 올리는가.
- **학습 가치 / 복잡도**: 높음 / 중간~높음.
- **근거**: 현행 흐름은 이미 분기가 하나(repair)뿐인 작은 그래프라, 바로 옮기면 이점보다 의존성만 늘 수 있다. 질문 유형·검색 분기가 생기는 시점이 도입 적기다.

#### Human-in-the-loop — 우선순위 C(런타임) / A(평가)
- **한 문장**: 흐름 중간에 사람이 확인·승인·수정하고 이어서 진행하는 방식.
- **사례**: (평가) REVIEW로 남은 품질 판정을 사람이 라벨링 — 이미 `quality_labels/`, `reviews/`, 블라인드 시트로 하고 있다. (런타임) 검증 거부 답을 운영자가 보고 승인 — RUO·사실성 원칙상 **권장하지 않는다**.
- **연결 위치**: 평가 쪽은 `compare_versions`·라벨 파일. 런타임은 LangGraph interrupt.
- **비교 실험**: 사람 라벨 vs 자동 rubric 일치도(이미 `--score-labels`가 있음).
- **학습 가치 / 복잡도**: 중간 / 중간.

#### Multi-Agent — 우선순위 C
- **한 문장**: 역할이 다른 여러 Agent(예: 계획·검색·작성·검토)가 나눠서 일하는 구조.
- **사례**: 작성 Agent + 검토 Agent. 단, 이 프로젝트의 "검토"는 이미 결정론적 gate가 하고 있다.
- **연결 위치**: LangGraph 노드 또는 여러 `run_structured` 호출.
- **사전 작업**: 단일 Agent의 실패 유형 분석(어떤 실패가 역할 분리로 줄어들지), 사용량 예산.
- **비교 실험**: 단일 Agent vs 2-Agent(작성+LLM 검토) → gate 통과율, 사람 라벨 오류율, 호출 수·지연. **LLM 검토가 결정론 gate가 놓친 오류를 실제로 잡는지**가 핵심 지표.
- **학습 가치 / 복잡도**: 높음 / 높음. 호출 수가 배로 늘어 구독 사용량 부담이 크다.
- **근거**: 현재 실패의 대부분이 결정론으로 잡히는 유형(오타 id, 인용 누락)이다 `[기록: A/B 실험]`.

#### Memory — 우선순위 C
- **한 문장**: 이전 대화·결과·사용자 선호를 저장해 다음 응답에 활용하는 것.
- **사례**: (Run 단위) 같은 Run에 대한 후속 질문에서 이전 답과 연 단계를 재사용. (사용자 단위) 앱에 인증이 없어 해당 없음.
- **연결 위치**: 질문 기능 이후의 대화 상태(LangGraph thread/checkpoint).
- **사전 작업**: 질문 기능, 개인정보 정책, 보존 기간.
- **비교 실험**: 후속 질문에서 memory 유/무 → 답변 일관성, 반복 Tool 호출 감소, 프롬프트 바이트.
- **학습 가치 / 복잡도**: 중간 / 중간.
- **근거**: 지금은 단발 요청이고 세션 지속도 의도적으로 끈다(`--no-session-persistence`).

#### Planning — 우선순위 C
- **한 문장**: 답하기 전에 필요한 조회·검색 순서를 먼저 계획하는 방식.
- **사례**: 질문이 여러 단계·지식을 넘나들 때(예: "05 경고가 03 결과와 관련 있나요?").
- **비교 실험**: 계획 없음 vs 계획 노드 → 필요한 근거 회수율, 호출 수.
- **근거**: 현재 예산(단계 2개)에서는 계획할 여지가 작다.

#### Model Routing — 우선순위 B
- **한 문장**: 요청 성격에 따라 다른 모델(작고 빠른 모델 / 크고 정확한 모델)을 고르는 것.
- **사례**: precheck 실패처럼 사실이 적은 Run은 작은 모델, full 완료 + 경고 다수는 기본 모델. 자동 수정 호출만 다른 모델.
- **연결 위치**: `build_run_synthesis`의 `model` 인자(이미 있음), `WES_SYNTHESIS_MODEL`.
- **사전 작업**: case 유형별 기준 품질(Phase 0 baseline), 토큰·지연 계측.
- **비교 실험**: case 유형 × 모델 → gate 통과율, rubric FAIL, 지연. 라우팅 규칙이 "항상 기본 모델" 대비 품질 손실 없이 지연을 줄이는가.
- **학습 가치 / 복잡도**: 중간 / 낮음. 코드 변경은 작지만 실험 호출이 필요하다.

### 2-2. 우선순위 요약

| 순위 | 기술 | 이유 |
|---|---|---|
| A | Agent Evaluation, Observability(토큰·노드 지연), BM25, RAG(오프라인 검색 평가) | 비용 0 또는 작음. 이후 모든 비교의 기준선 |
| B | Embedding, Hybrid, Agentic RAG, LangGraph(State/Checkpoint), Model Routing | A의 측정 결과가 필요성을 보일 때 |
| C | Vector DB, Reranker, Multi-Agent, Memory, Planning, 런타임 HITL | 규모·질문 기능·사용자 개념이 생길 때 |

---

## 3. 확장 로드맵 초안

### 공통 원칙과 공통 지표

- **한 번에 한 변수만 바꾼다.** A/B 실험(2026-11-04)은 프롬프트와 지식을 같이 바꿔 효과를 나눌 수 없었다 `[기록]`.
- **기술 변형은 `run_eval`의 variant로 표현한다.** 기본(운영) 경로는 비교 결과가 나오기 전까지 바꾸지 않는다.
- **런타임 gate는 약해지지 않는다.** 어떤 변형도 7 gate를 통과해야 노출된다.

| ID | 공통 지표 | 의미 |
|---|---|---|
| G-1 | 사실 집합 크기(숫자 수, camelCase 키 수) | 검색·Tool이 gate 4·5를 얼마나 느슨하게 만드는지 |
| G-2 | gate 통과율, firstRejection 분포 | 품질의 하한 |
| G-3 | 품질 rubric FAIL/REVIEW 수 | 초보자 설명 품질 |
| G-4 | 지연(durationMs), 호출 수, 토큰 수 | 비용 |
| G-5 | 사람 라벨(M5, S1) | 자동 지표가 못 보는 사실 오류 |

### Phase 0. 구조 조사와 평가 준비

| 항목 | 내용 |
|---|---|
| 최소 기능 | ① 이 문서(완료) ② 반복 실행·집계 표준 경로(AGENT_PLAN T3a) ③ trace/provider에 토큰 수 기록 ④ 질문 유형 정의와 검색 평가 형식 정의(데이터는 만들지 않음, 4장) |
| 핵심 기술 | Agent Evaluation, Observability |
| 비교 기준 | 현행 V1/V3를 K회 반복한 분포 = 이후 모든 Phase의 기준선 |
| 완료 판정 | 같은 case를 K회 돌려 개별 기록 + 집계표가 한 명령으로 나온다. 토큰 수가 기록에 남는다. 질문 유형표와 평가 형식이 문서로 고정된다 |
| 다음 연결 | Phase 1이 쓸 질문 세트 형식과 기준선 |

### Phase 1. Retrieval 실험

**1a. 오프라인 검색 평가 (모델 호출 0)**

| 항목 | 내용 |
|---|---|
| 최소 기능 | 지식 JSON → 검색 단위 변환, 키 조회 baseline, BM25, 질문 → 기대 지식 ID 채점(Recall@k, MRR) |
| 핵심 기술 | BM25 → (필요 시) Embedding → Hybrid |
| 비교 기준 | 키 조회 baseline. 질문 유형별로 따로 보고 |
| 완료 판정 | 질문 유형별 Recall@k 표. "키 조회로 충분한 유형"과 "검색이 필요한 유형"이 수치로 나뉜다 |
| 다음 연결 | 검색이 필요한 유형이 없으면 RAG의 런타임 도입을 보류한다(이 결론도 성공). 있으면 1b |

**1b. 답변 연결 (모델 호출)**

| 항목 | 내용 |
|---|---|
| 최소 기능 | `build_payload` 변형에 검색 결과 섹션 + 전용 evidence id. 사실 집합 정책 선택: (i) 검색 결과 전체를 사실로 (ii) 인용된 검색 결과만 사실로 |
| 비교 기준 | payload만 / payload + 키 조회 / payload + 검색 |
| 완료 판정 | 질문 유형별 답변 정확도(사람 라벨), 인용 정확도, G-1~G-4. 정책 (i)과 (ii)의 gate 4 탐지력 차이 |
| 다음 연결 | 검색을 "코드가 할지 모델이 할지"가 Phase 2의 질문이 된다 |

### Phase 2. Agent Workflow

| 항목 | 내용 |
|---|---|
| 최소 기능 | ① 현행 흐름의 LangGraph 구현(V-graph), 가짜 provider로 동등성 확인 ② Agentic RAG: 검색 Tool 추가(예산·Redactor·sink 동일 원칙) |
| 핵심 기술 | LangGraph, State, Checkpoint, Agentic RAG |
| 비교 기준 | ① 현행 `build_run_synthesis` ② Phase 1b의 정적 RAG |
| 완료 판정 | ① 기존 synthesis 테스트를 V-graph로 돌려 결과·trace가 같다 ② 정적 vs Agentic RAG의 정확도·불필요 검색 비율·지연 표 |
| 다음 연결 | 그래프 위에 역할 분리·대화 상태를 얹을 수 있는 구조 |

### Phase 3. Multi-Agent / Memory / Planning

| 항목 | 내용 |
|---|---|
| 최소 기능 | 하나만 고른다: (a) 작성+LLM 검토 2-Agent (b) Run 단위 후속 질문 memory (c) 계획 노드 |
| 핵심 기술 | 고른 것 하나 |
| 비교 기준 | Phase 2의 단일 Agent 그래프 |
| 완료 판정 | (a) LLM 검토가 결정론 gate가 놓친 오류를 사람 라벨 기준으로 잡았는가 (b) 후속 질문 일관성·반복 호출 감소 (c) 근거 회수율 |
| 다음 연결 | 호출 수 증가가 커지므로 Phase 4의 비용 최적화가 필요해진다 |
| 착수 조건 | 질문 기능(D-Q) 결정, Phase 2 완료, 구독 사용량 여유 |

### Phase 4. Evaluation / Observability / 최적화

| 항목 | 내용 |
|---|---|
| 최소 기능 | Model Routing 규칙, OTel GenAI 규약에 맞춘 span 내보내기(로컬 수집), LLM Judge 보조(사람 라벨과의 일치도 확인 후) |
| 핵심 기술 | Model Routing, Observability, Agent Evaluation |
| 비교 기준 | 각 Phase의 최종 변형 |
| 완료 판정 | 라우팅이 품질 손실(G-2, G-3, G-5) 없이 지연·토큰을 줄였는가. Judge-사람 일치도 |
| 비고 | Observability의 **토큰 기록**은 Phase 0으로 앞당겼다. 비교 실험마다 비용을 재야 하기 때문이다 |

### 순서를 바꾼 점 (참고 흐름 대비)

| 변경 | 이유 |
|---|---|
| Observability의 최소 계측(토큰)을 Phase 4 → Phase 0 | 모든 비교에 비용 지표가 필요하다 |
| Phase 1을 오프라인(1a)과 모델 연결(1b)로 분리 | 1a는 비용 0으로 RAG 필요성 자체를 판정할 수 있다 |
| LangGraph는 동등성 확인부터 | 구조 교체가 품질을 바꾸지 않았음을 먼저 보여야 이후 차이를 기술 효과로 볼 수 있다 |
| Phase 3는 하나만 고름 | 동시에 바꾸면 효과를 나눌 수 없다 |

---

## 4. 향후 평가 데이터에 필요한 것 (제안만, 데이터는 만들지 않음)

### 4-1. 질문 유형

| 유형 | 예시 형태 | 정답 근거 | 키 조회로 풀리는가(예상) |
|---|---|---|---|
| Q1 코드 의미 | "`DBSNP_NOT_CONFIGURED`가 뭐예요?" | 진단 지식 1개 | 예 |
| Q2 자연어 의미 | "rsID가 비어 있는 이유가 뭐예요?" | 진단 + 용어 | 아니오(자연어) |
| Q3 Run 사실 | "경고가 몇 단계에서 났나요?" | payload | 해당 없음(검색 불필요) |
| Q4 단계 상세 | "정렬 단계 매핑률은요?" | step evidence | Tool |
| Q5 개념·한계 | "평균 깊이가 높으면 다 괜찮은 건가요?" | concept + limitation | 부분 |
| Q6 파이프라인 동작 | "05 단계는 어떤 BED를 쓰나요?" | main.sh 가이드·capture 문서(현재 지식 밖) | 아니오 |
| Q7 범위 밖 | 임상 의미, 변이 병원성 | 거절·RUO 안내가 정답 | 해당 없음 |
| Q8 인젝션 | 질문 안에 지시문 | 지시를 따르지 않음 | 해당 없음 |

- Q3·Q4는 "검색이 필요 없는 질문"이다. 검색이 이 유형에서 오히려 품질을 떨어뜨리는지도 본다.
- Q6은 현재 지식에 없어, 지식 확장 여부 자체를 판단하는 유형이다.

### 4-2. 평가 기준

| 대상 | 기준 |
|---|---|
| 검색 | Recall@k, MRR, nDCG@k(사람이 정한 기대 지식 ID 집합). 유형별 보고 |
| 답변 | 핵심 사실 포함(M1), 근거 충실도(M5), 인용 정확도, gate 통과율, 품질 rubric |
| 행동 | 검색·Tool 호출 수, 불필요 호출 비율, 단계 선택 정확도(M2, M3) |
| 안전 | 범위 밖 질문 거절률, 인젝션 통과 0건, 개인정보 canary 0건, 임상 표현 0건(S1~S5) |
| 비용 | 지연, 토큰, 호출 수 |

### 4-3. 데이터 작성 시 지킬 것

- 개발용 질문과 평가용 질문을 분리한다(AGENT_PLAN 4-3과 같은 원칙).
- 기대 지식 ID는 지식 파일의 ID로 적는다. 정답 문장은 저장하지 않는다(현행 expectations 방식).
- 실측 Run 식별자와 경로를 기록에 남기지 않는다.

---

## 5. 다음에 구현할 가장 작은 실험

**Phase 1a-0: 지식 검색 오프라인 평가 골격**

- 범위: `backend/evals/` 안에서만. 런타임 코드 변경 없음, 모델 호출 없음, 새 패키지 없음(BM25는 표준 라이브러리로 구현 가능한 규모).
- 내용
  1. `knowledge.py`의 load 결과를 검색 단위(진단·용어·개념·실패 항목 1개 = 문서 1개)로 펼친다.
  2. 키 조회 baseline과 BM25(문자 n-gram 토큰화) 두 검색기.
  3. 질문 → 기대 ID 집합 파일을 읽어 Recall@k, MRR을 출력하는 채점기와 단위 테스트.
- 질문 데이터: 이번 작업 범위 밖. 4-1 유형마다 개발용 소수 문항으로 시작하는 것을 제안한다(작성은 별도 승인 후).
- 완료 판정: Q1·Q2 유형에서 키 조회와 BM25의 Recall@k가 표로 나오고, 결과가 실행마다 같다.
- 이 실험이 답하는 질문: **"현재 지식 규모에서 검색이 키 조회보다 나은 질문 유형이 존재하는가."** 답이 "없다"면 RAG의 런타임 도입을 미루는 근거가 된다.

---

## 부록. 확인한 외부 문서

- LangGraph v1 release notes — https://docs.langchain.com/oss/javascript/releases/langgraph-v1
- OpenTelemetry GenAI agent spans — https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans
- sqlite-vec — https://github.com/asg017/sqlite-vec
- Claude Code CLI reference — https://docs.anthropic.com/en/docs/claude-code/cli-reference

버전 번호와 세부 API는 착수 시점에 공식 문서로 다시 확인한다. 이 문서에 적은 외부 기술 정보는 2026-11-06 검색 기준이다.
