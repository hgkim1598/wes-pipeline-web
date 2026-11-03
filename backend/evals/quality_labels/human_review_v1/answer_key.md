# 설명 품질 검사기 — 대조 자료 v1 (검사기 판정과 근거)

`review_sheet.md`를 판정한 **뒤에** 여세요.

- 검사기: `evals/explanation_quality.py` + `evals/rubric/explanation_checks_v1.json` (이 자료를 만들 때 수정하지 않음).
- 'AI 임시 정답'은 Claude가 만든 `ai_provisional` 정답입니다. **사람 정답이 아니며** 비교 기준으로 쓰지 않습니다.
  사람 판정과 검사기 판정을 비교하는 것이 이 검토의 목적입니다.
- '선정 이유'는 사례를 고를 때 Claude가 추정한 분류입니다. 정답이 아닙니다.
- '검사기가 본 부분'의 □는 검사기가 단계 이름(wes_steps.json label)을 가린 자리입니다.

## 검사기 판정과 사람 질문의 대응

| 검사기 판정(규칙) | 뜻 | 사람 판정이 이렇다면 검사기와 일치 |
|---|---|---|
| PASS explained / conveyed_plain | 이 항목에서 설명됨, 또는 쉬운 말로 전달 | Q1 정상 |
| FAIL never_explained | 답변 어디에서도 설명 없음 | Q1 오류 + Q2 오류 |
| FAIL inaccurate_gloss | 괄호 설명이 틀림 | Q1 오류(뜻이 틀림) |
| REVIEW explained_elsewhere | 이 항목엔 없고 다른 항목에서 설명 | Q1 오류 + Q2 정상 (검사기는 사람에게 넘김) |
| REVIEW gloss_unverified / possible_definition | 설명이 있으나 맞는지 문자열로 확인 못 함 | 사람 판정이 곧 정답. 검사기는 판단을 미룸 |
| REVIEW review_substitute | 용어 대신 쓴 말이 뜻을 전하는지 모름 | 사람 판정이 곧 정답 |
| 내부 표현 FAIL | 설명 없는 내부 표현 있음 | Q 오류 |
| 내부 표현 REVIEW | 있으나 필요성·위치를 사람이 봐야 함 | 사람 판정이 곧 정답 |
| 내부 표현 판정 없음 | 검사기가 아무것도 찾지 못함 | Q 정상. 사람이 오류면 검사기가 놓친 것 |
| 사실 PASS / REVIEW | 문구를 찾음 / 찾지 못함 | PASS ↔ 정상, REVIEW는 사람 판정이 정답 |

Precision·Recall·F1은 사람이 `responses.json`을 채운 뒤에만 계산합니다. 이 자료를 만들 때는 계산하지 않았습니다.
REVIEW는 검사기가 판단을 미룬 것이라 '맞음/틀림'에 넣지 않고 따로 셉니다(`explanation_quality.score_labels`와 같은 방식).

## HR01

- 선정 이유: 용어 설명 누락(read)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **FAIL** (`never_explained`) — read: 답변 어디에서도 설명하지 않음
- 검사기가 본 부분: “…905%인 3,387,168개가 read에 한 번도 덮이지 않았습니다.”
- AI 임시 정답(사람 정답 아님): FAIL — read 설명 없음
- 같은 답변 전체에서 이 용어(검사기): FAIL `never_explained`, 설명된 항목 0/4

## HR02

- 선정 이유: 용어 설명이 올바르게 제공된 경우
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **PASS** (`explained`) — dbSNP 설명 있음
- 검사기가 본 부분: “dbSNP(이미 알려진 변이를 모아 둔 공개 데이터베이스)가 설정되…”
- AI 임시 정답(사람 정답 아님): PASS — dbSNP·rsID 모두 괄호 설명
- 같은 답변 전체에서 이 용어(검사기): REVIEW `explained_elsewhere`, 설명된 항목 1/3

## HR03 [synthetic]

- 선정 이유: 설명이 있지만 의미가 잘못된 경우(합성)
- 검사기 판정: **FAIL** (`inaccurate_gloss`) — 깊이 설명이 부정확: 깊이는 겹쳐 덮인 횟수(배)이지 비율이 아니다(wes_terms definition)
- 검사기가 본 부분: “target 염기 중 read에 덮인 비율”
- AI 임시 정답(사람 정답 아님): FAIL — 깊이를 비율로 설명 -- 부정확

## HR04

- 선정 이유: 다른 항목에서만 설명한 경우(read는 summary에서만 설명)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **REVIEW** (`explained_elsewhere`) — read: 이 항목에서는 설명 없음, 다른 항목에서 설명함
- 검사기가 본 부분: “목표 영역에서 read가 한 번도 덮지 않은(0×) 염…”
- AI 임시 정답(사람 정답 아님): REVIEW — 설명 없음, summary에서만 설명
- 같은 답변 전체에서 이 용어(검사기): REVIEW `explained_elsewhere`, 설명된 항목 1/3

## HR05

- 선정 이유: 검사기가 잘못 판단했을 가능성(바꿔 쓴 단계 이름의 BAM)
- 필수 용어 출처(검사기): payload terms (usedWhen)
- 검사기 판정: **FAIL** (`never_explained`) — BAM: 답변 어디에서도 설명하지 않음
- 검사기가 본 부분: “…검 중 8개는 통과, 3개 단계(BAM 처리, 커버리지 점검, □□□□…”
- 같은 답변 전체에서 이 용어(검사기): FAIL `never_explained`, 설명된 항목 0/1

## HR06

- 선정 이유: 올바른 설명(앞쪽 설명). 검사기 규칙을 1차 수정에서 넓힌 부분
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **PASS** (`explained`) — NM/MD 설명 있음
- 검사기가 본 부분: “read와 참조 서열의 차이 개수를 적는 보조 태그(NM·M…”
- 같은 답변 전체에서 이 용어(검사기): REVIEW `explained_elsewhere`, 설명된 항목 1/2

## HR07

- 선정 이유: 쉬운 한국어 대체인지 애매한 경우(목표 영역) -- 검사기 REVIEW
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **REVIEW** (`review_substitute`) — 용어 대신 쓴 말이 초보자에게 뜻을 전하는지 확인 필요
- 검사기가 본 부분: “…습니다. 가장 눈여겨볼 경고는, 목표 영역 안에 read(시퀀싱으로 읽은 …”
- AI 임시 정답(사람 정답 아님): REVIEW — "목표 영역"으로만 바꿔 씀. 뜻이 전달되는지 사람 판단
- 같은 답변 전체에서 이 용어(검사기): REVIEW `review_substitute`, 설명된 항목 0/3

## HR08

- 선정 이유: 용어 설명 누락이지만 오해 방지 문장은 있음 -- 경계 사례
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **FAIL** (`never_explained`) — 깊이: 답변 어디에서도 설명하지 않음
- 검사기가 본 부분: “target 전체의 평균 깊이는 11.0116배로 기록되었습니…”
- AI 임시 정답(사람 정답 아님): FAIL — "평균 깊이" -- 깊이 자체를 정의하지 않음(오해 방지 문장만 있음)
- 같은 답변 전체에서 이 용어(검사기): FAIL `never_explained`, 설명된 항목 0/4

## HR09

- 선정 이유: 검사기가 REVIEW로 넘긴 경우(문장 안 정의)
- 필수 용어 출처(검사기): payload terms (usedWhen)
- 검사기 판정: **REVIEW** (`possible_definition`) — 깊이를 문장 안에서 정의하는 것으로 보이나 확인 필요
- 검사기가 본 부분: “목표 구간 전체의 평균 깊이는 85.2배로 기록되었습니다. …”
- 같은 답변 전체에서 이 용어(검사기): REVIEW `possible_definition`, 설명된 항목 0/4

## HR10

- 선정 이유: 쉬운 한국어로 대체한 경우(0×)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **PASS** (`conveyed_plain`) — 용어 없이 쉬운 말로 전달
- 검사기가 본 부분: “…arget 구간 안에 read가 한 번도 덮지 않은 염기가 있다는 것이고, 변이 …”
- AI 임시 정답(사람 정답 아님): PASS — "read가 한 번도 덮지 않은 염기" -- 쉬운 말
- 같은 답변 전체에서 이 용어(검사기): REVIEW `explained_elsewhere`, 설명된 항목 3/7

## HR11

- 선정 이유: 용어 설명 누락(dbSNP)과 올바른 설명(rsID)이 한 문장에
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **FAIL** (`never_explained`) — dbSNP: 답변 어디에서도 설명하지 않음
- 검사기가 본 부분: “…. 이 서버의 참조 자료 묶음에 dbSNP 파일이 선언되어 있지 않기 때문…”
- AI 임시 정답(사람 정답 아님): FAIL — rsID는 "공개 식별자"로 설명, dbSNP는 답변 어디에서도 설명 없음
- 같은 답변 전체에서 이 용어(검사기): FAIL `never_explained`, 설명된 항목 0/3

## HR12 [synthetic]

- 선정 이유: 설명이 있지만 의미가 잘못된 경우(합성)
- 검사기 판정: **FAIL** (`inaccurate_gloss`) — rsID 설명이 부정확: rsID 유무는 검출 여부도 의학적 의미도 아니다(wes_terms misreadings)
- 검사기가 본 부분: “변이가 검출되었는지 표시하는 값”
- AI 임시 정답(사람 정답 아님): FAIL — rsID를 검출 여부로 설명 -- 부정확

## HR13

- 선정 이유: 검사기가 REVIEW로 넘긴 경우(알려진 표현과 다른 괄호 설명)
- 필수 용어 출처(검사기): payload terms (usedWhen)
- 검사기 판정: **REVIEW** (`gloss_unverified`) — dbSNP에 괄호 설명이 있으나 알려진 표현과 맞지 않아 정확성 확인 필요
- 검사기가 본 부분: “공개 변이 식별자 데이터베이스”
- 같은 답변 전체에서 이 용어(검사기): REVIEW `gloss_unverified`, 설명된 항목 0/3

## HR14

- 선정 이유: 다른 항목에서만 설명한 경우(rsID)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **REVIEW** (`explained_elsewhere`) — rsID: 이 항목에서는 설명 없음, 다른 항목에서 설명함
- 검사기가 본 부분: “rsID를 채우고 싶다면 서버 관리자가 …”
- AI 임시 정답(사람 정답 아님): REVIEW — "rsID" 설명 없음, importantFindings[6]에서 설명
- 같은 답변 전체에서 이 용어(검사기): REVIEW `explained_elsewhere`, 설명된 항목 1/3

## HR15

- 선정 이유: 내부 기술 표현 노출(설정 이름·영어 원문)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정:
  - **FAIL** `config-key:dbsnp_vcf` — snake_case 설정 키·내부 값이다. 한국어 설명 없이 쓰면 초보자가 읽을 수 없다
  - **FAIL** `internal-config:resource bundle` — 서버 설정의 내부 이름이다. Day 2 답변은 같은 내용을 '참조 자료 묶음'으로 썼다 (쉬운 말: 참조 자료 묶음)
  - **FAIL** `internal-config:ID column` — 영어 원문 표기다. Day 2 답변은 같은 내용을 'ID 열'로 썼다 (쉬운 말: ID 열)
- AI 임시 정답(사람 정답 아님): `internal-config:resource bundle` → FAIL — 설명 없는 서버 설정 이름
- AI 임시 정답(사람 정답 아님): `config-key:dbsnp_vcf` → FAIL — 설정 키
- AI 임시 정답(사람 정답 아님): `internal-config:ID column` → FAIL — 영어 원문 표기("ID 열")

## HR16

- 선정 이유: 검사기가 놓쳤을 가능성(데이터 필드 이름을 옮긴 표현)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **판정 없음** (내부 표현을 찾지 못함)
- AI 임시 정답(사람 정답 아님): `field-translation:겹치지 않는 염기` → REVIEW — 필드 이름 번역. 미탐 예상

## HR17

- 선정 이유: 검사기가 REVIEW로 넘긴 경우(한국어 설명 뒤 파일 이름, 보고서 표시)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정:
  - **REVIEW** `file-name:resource_validation.txt` — 파일 이름이다. 웹 화면에서 찾을 수 있는 이름인지는 사람이 확인한다
  - **REVIEW** `log-marker:[NOTE]` — 보고서 원문의 표시다. 사용자가 그 보고서를 볼 수 있는지는 사람이 확인한다
- AI 임시 정답(사람 정답 아님): `file-name:resource_validation.txt` → REVIEW — "참조 자료 검증 보고서(resource_validation.txt)" -- 한국어 설명 뒤 파일 이름
- AI 임시 정답(사람 정답 아님): `log-marker:[NOTE]` → REVIEW — 보고서 원문 표시

## HR18

- 선정 이유: 내부 기술 표현 노출(단계 ID)
- 필수 용어 출처(검사기): payload terms (usedWhen)
- 검사기 판정:
  - **FAIL** `step-id:step_04_processing` — 내부 단계 ID다. 화면은 단계 이름으로 보여 준다
  - **FAIL** `step-id:step_05_coverage_qc` — 내부 단계 ID다. 화면은 단계 이름으로 보여 준다
  - **FAIL** `step-id:step_06_variant_calling` — 내부 단계 ID다. 화면은 단계 이름으로 보여 준다

## HR19

- 선정 이유: 중요한 Run 정보가 누락된 경우 -- 검사기 REVIEW
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **REVIEW** (`not_found`) — 경고가 3건이라는 것이나 경고 단계 이름을 찾지 못함. 각 경고의 인용 여부는 mustCite가 보며, 경고 단계를 구분했는지는 사람 검토(step-scope)가 본다
- AI 임시 정답(사람 정답 아님): REVIEW — 경고 수·경고 단계 이름 없음. 각 경고는 인용함 -- 사람 검토 step-scope와 같은 문제

## HR20

- 선정 이유: 같은 사실을 전한 경우(비교용)
- 필수 용어 출처(검사기): case spec beginnerRubricV2.requiredTerms (proposed_pending_approval)
- 검사기 판정: **PASS** (`count_stated`) — 경고 3건(또는 경고 단계 수)을 씀
- 검사기가 본 부분: “경고로 기록된 세 단계의 세부 내용은 열어 보지 않았기…”
- AI 임시 정답(사람 정답 아님): PASS — uncertainties[3] "경고로 기록된 세 단계"

---

## 이 자료를 만들 때 지킨 것

- 검사기 코드·규칙, 원본 답변, 기존 정답 파일은 수정하지 않았다.
- 사례 문장은 baseline에서 프로그램으로 그대로 옮겼다. 합성 사례는 기존 라벨 파일의 synthetic 문장만 썼다.
- 사례는 검사기 판정이 다양하게 나오도록 골랐다. 그래서 이 20개의 일치율은 전체 답변에서의 일치율을 대표하지 않는다
  (무작위 표본이 아님).
- 실제 답변 6개는 모두 규칙 작성·수정에 쓰인 개발 데이터다.

