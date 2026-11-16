# Git 공개 준비 기록 — 2026-11-16

이 문서는 후속 조치와 검증 결과다. 기존 개발판단·기술조사 문서 세 개는 수정하지 않았다.
Git staging, commit, push, amend, rebase, reset을 실행하지 않았다.
현재 HEAD는 `d732bbf`이며, 아래 변경을 커밋해도 이전 이력의 공개 위험은 남는다.

## 적용한 경계

- 실제 Run 등록값은 `config/local/wes_eval_runs.json`에 원래 값 그대로 보존했다. 이 파일은 공유 ignore 대상이다.
- `backend/evals/local_data.py`가 로컬 등록값과 경로를 읽는다. 설정이 없으면 실제 Run 통합은 사용할 수 없으며, 합성 Run으로 실제 측정을 대신하지 않는다. 명시한 설정 파일이 없거나 잘못되면 값·경로를 노출하지 않는 오류로 중단한다.
- 기존 case alias는 baseline·정답 연결을 유지하기 위해 보존했다. alias를 보존한 사실이 익명성이나 공개 권리의 증명은 아니다.
- 실제 샘플은 복사된 원본 metrics에서 읽는다. 원본 Run ID나 샘플을 치환하여 측정 의미를 바꾸지 않았다.
- 실제 baseline과 실제 정답 원본은 삭제·수정하지 않았다. 신규 파일의 Git 유입을 차단했다. 이미 추적된 과거 자료에는 ignore만으로 보호가 적용되지 않는다.
- `config/knowledge/wes_doc_passages.json`의 21개 원문은 그대로 로컬 보존했다. 새 공개 corpus `wes_doc_passages.public.json`은 비어 있다.
- backend는 기존 로컬 corpus가 있으면 계속 읽고, 없으면 공개 빈 corpus를 읽는다. `WES_DOC_PASSAGES_FILE`로 명시적으로 선택할 수도 있다. 선택 경로는 MCP 자식 환경에도 전달된다.
- frontend 개발 서버는 같은 로컬 corpus를 선택할 수 있다. release build는 항상 공개 corpus를 사용한다. 로컬 원문이 빌드에 조용히 포함되지 않는다.
- 공개 테스트의 문장은 직접 작성한 합성 문장이다. 실제 공식 매뉴얼이라고 제시하지 않으며 제품 데이터로 사용하지 않는다.
- 고정 검색 실험 질의 원본은 변경하지 않고 로컬 보존했다. 질의가 없는 환경에서는 해당 실험 검증을 명시적으로 skip한다. BM25 구현 자체는 별도의 합성 테스트로 검증한다.

## 평가 정책

공개 회귀 테스트와 비공개 성능 평가를 구분한다.

합성 resource 사례 3개의 정답은 공개 회귀 테스트로 포함할 수 있다. 코드 변경 이후 같은 개발자가 작성·사용한 사례이므로 독립적인 일반화 성능의 근거로 삼지 않는다.
검색 질의의 heldout 표시는 임계값 조정에 사용하지 않았다는 구분이며, 외부 독립 평가라는 뜻이 아니다.
정답 공개만으로 평가가 자동 무효가 되는 것은 아니다. 공개 회귀 테스트의 재현성과 비공개 성능 평가의 독립성은 목적이 다르다.
실제 실패 Run에서 파생된 정답과 baseline은 별도의 공개 근거 확인이 필요하므로 이번 후보에 포함하지 않는다.

## 발췌 21개 확인 방법

2026-11-16 공식 페이지·공식 소스·명세 PDF와 대조했다. 인용문 원문은 이 보고서에 복제하지 않는다.
아래 길이는 로컬 원본 quote의 공백 기준 단어 수 / 문자 수다.
“일치”는 해당 부분 문자열이 확인됐다는 뜻이며 재배포 승인이나 immutable 버전 고정을 뜻하지 않는다.
master·웹페이지 주소는 변할 수 있다. 향후 배포하려면 실제 commit/tag 또는 문서 버전과 당시 라이선스를 고정해야 한다.

- HTSlib 웹사이트의 [이용 조건](https://www.htslib.org/terms/)은 일반 온라인 콘텐츠에 CC BY-NC-ND 4.0을 명시한다. 배포 패키지 MIT 표기를 웹페이지 발췌에 그대로 적용할 수 없다. 출처·저작자·라이선스 링크 및 비영리·변경 금지 조건의 적용 범위를 검토해야 한다.
- [Picard 해당 소스](https://raw.githubusercontent.com/broadinstitute/picard/master/src/main/java/picard/sam/CreateSequenceDictionary.java)는 MIT 고지를 포함한다. 재배포 시 적용되는 저작권·허가·면책 고지 보존이 필요하다.
- [GATK 라이선스](https://raw.githubusercontent.com/broadinstitute/gatk/master/LICENSE.TXT)는 예외 없는 파일에 Apache 2.0을 적용한다. 라이선스 사본과 적용되는 저작권·NOTICE·변경 고지를 확인해야 한다.
- [CWL v1.2](https://www.commonwl.org/v1.2/CommandLineTool.html)는 문서에 Apache 2.0을 명시한다.
- [BWA 매뉴얼](https://bio-bwa.sourceforge.net/bwa.shtml)의 GPLv3 설명은 전체 패키지에 관한 것이다. 발췌의 배포 조건과 원문 해당 파일을 별도로 확인해야 한다.
- bcftools 웹 매뉴얼, VCF/BED 명세, UCSC FAQ는 이번에 확인한 해당 자료만으로 발췌의 재배포 조건을 확정하지 않았다.
- 현재 공개 corpus가 비어 있으므로 위 발췌를 위한 제3자 고지를 코드 배포에 넣어 권리 검토를 대신하지 않는다. 21개 모두 로컬로 유지한다.

| ID | 실제 출처 | 길이(단어/문자) | 원문 대조 | 버전 | 권리·고지 |
|---|---|---|---|---|---|
| `tabix-input-sorted-bgzip` | [tabix-manual](https://www.htslib.org/doc/tabix.html) | 18/103 | 부분 문자열 일치 | htslib 1.25 manual page (released 27 October 2026) | 웹 일반 조건 CC BY-NC-ND 4.0; 별도 배포 검토 |
| `tabix-csi-option` | [tabix-manual](https://www.htslib.org/doc/tabix.html) | 12/73 | 부분 문자열 일치 | htslib 1.25 manual page (released 27 October 2026) | 웹 일반 조건 CC BY-NC-ND 4.0; 별도 배포 검토 |
| `tabix-force-overwrite` | [tabix-manual](https://www.htslib.org/doc/tabix.html) | 10/51 | 부분 문자열 일치 | htslib 1.25 manual page (released 27 October 2026) | 웹 일반 조건 CC BY-NC-ND 4.0; 별도 배포 검토 |
| `bcftools-index-default-csi` | [bcftools-manual](https://samtools.github.io/bcftools/bcftools.html) | 7/52 | 부분 문자열 일치 | bcftools git version 1.22-8 manual page (last updated 2025-06-17) | 해당 매뉴얼의 배포 조건 미확정 |
| `bcftools-index-tbi` | [bcftools-manual](https://samtools.github.io/bcftools/bcftools.html) | 8/49 | 옵션명·설명 행 연결 | bcftools git version 1.22-8 manual page (last updated 2025-06-17) | 해당 매뉴얼의 배포 조건 미확정 |
| `bcftools-rename-chrs` | [bcftools-manual](https://samtools.github.io/bcftools/bcftools.html) | 8/47 | 부분 문자열 일치 | bcftools git version 1.22-8 manual page (last updated 2025-06-17) | 해당 매뉴얼의 배포 조건 미확정 |
| `faidx-creates-fai` | [samtools-faidx](https://www.htslib.org/doc/samtools-faidx.html) | 10/52 | 부분 문자열 일치 | samtools 1.25 manual page (released 27 October 2026) | 웹 일반 조건 CC BY-NC-ND 4.0; 별도 배포 검토 |
| `picard-dict-from-fasta` | [picard-create-dict](https://github.com/broadinstitute/picard/blob/master/src/main/java/picard/sam/CreateSequenceDictionary.java) | 18/120 | Java 문자열 결합·escape 해석 후 일치 | Picard master branch source (no release shown) | 해당 소스 MIT; 저작권·허가·면책 고지 |
| `picard-dict-no-overwrite` | [picard-create-dict](https://github.com/broadinstitute/picard/blob/master/src/main/java/picard/sam/CreateSequenceDictionary.java) | 14/83 | 이중 공백을 단일 공백으로 정규화 | Picard master branch source (no release shown) | 해당 소스 MIT; 저작권·허가·면책 고지 |
| `vcf-contig-length-md5` | [vcf-spec](https://samtools.github.io/hts-specs/VCFv4.3.pdf) | 18/102 | 별도 bullet 연결·세미콜론·아포스트로피 변경; 엄밀한 verbatim 아님 | VCFv4.3 specification, hts-specs version c101c79 (5 Nov 2025) | 명세 발췌 권리 미확정 |
| `gatk-same-name-different-length` | [gatk-dict-utils](https://github.com/broadinstitute/gatk/blob/master/src/main/java/org/broadinstitute/hellbender/utils/SequenceDictionaryUtils.java) | 9/54 | 부분 문자열 일치 | GATK master branch source (no release shown) | 프로젝트 Apache 2.0; 라이선스·관련 NOTICE 확인 |
| `gatk-no-overlapping-contigs` | [gatk-dict-utils](https://github.com/broadinstitute/gatk/blob/master/src/main/java/org/broadinstitute/hellbender/utils/SequenceDictionaryUtils.java) | 4/28 | 부분 문자열 일치 | GATK master branch source (no release shown) | 프로젝트 Apache 2.0; 라이선스·관련 NOTICE 확인 |
| `gatk-disable-validation-risk` | [gatk-dict-validation](https://github.com/broadinstitute/gatk/blob/master/src/main/java/org/broadinstitute/hellbender/cmdline/argumentcollections/SequenceDictionaryValidationArgumentCollection.java) | 18/109 | 공식 소스 주소 조회 실패; 이번 대조 미확인 | GATK master branch source (no release shown) | 프로젝트 Apache 2.0; 본문 재확인 미완료 |
| `bwa-index-bwtsw` | [bwa-manual](https://bio-bwa.sourceforge.net/bwa.shtml) | 12/79 | 부분 문자열 일치 | bwa manual page (bwa-0.7.1, 8 March 2013) | 페이지는 패키지 GPLv3 설명; 발췌 적용 범위 미확정 |
| `bwa-index-default-is-limit` | [bwa-manual](https://bio-bwa.sourceforge.net/bwa.shtml) | 8/43 | 부분 문자열 일치 | bwa manual page (bwa-0.7.1, 8 March 2013) | 페이지는 패키지 GPLv3 설명; 발췌 적용 범위 미확정 |
| `bwa-index-resources` | [bwa-manual](https://bio-bwa.sourceforge.net/bwa.shtml) | 14/94 | 부분 문자열 일치 | bwa manual page (bwa-0.7.1, 8 March 2013) | 페이지는 패키지 GPLv3 설명; 발췌 적용 범위 미확정 |
| `cwl-file-checksum` | [cwl-v12-commandlinetool](https://www.commonwl.org/v1.2/CommandLineTool.html) | 17/104 | code 서식 제거 후 일치 | CWL v1.2 (v1.2.1 has no behaviour changes) | 문서 Apache 2.0; 라이선스·관련 고지 확인 |
| `htslib-provides-tabix` | [htslib-install](https://www.htslib.org/download/) | 23/133 | 부분 문자열 일치 | htslib.org download page (samtools, bcftools, htslib 1.25) | 웹 일반 조건 CC BY-NC-ND 4.0; 별도 배포 검토 |
| `bed-three-mandatory-fields` | [ga4gh-bed-spec](https://github.com/samtools/hts-specs/blob/master/BEDv1.tex) | 7/37 | PDF 줄바꿈 정규화 후 일치 | GA4GH BED v1, hts-specs version 9ddbc52 (5 Jan 2022) | 명세 발췌 권리 미확정 |
| `bed-zero-based-half-open` | [ga4gh-bed-spec](https://github.com/samtools/hts-specs/blob/master/BEDv1.tex) | 14/90 | PDF 줄바꿈 정규화 후 일치 | GA4GH BED v1, hts-specs version 9ddbc52 (5 Jan 2022) | 명세 발췌 권리 미확정 |
| `ucsc-bed-first-base-zero` | [ucsc-bed-format](https://genome.ucsc.edu/FAQ/FAQformat.html#format1) | 9/45 | 부분 문자열 일치 | UCSC Genome Browser FAQ (no version shown) | FAQ 발췌 권리 미확정 |

## 이력 선택지

| 선택지 | 결과 |
|---|---|
| 현재 이력 유지 | 로컬 커밋은 가능하지만 Push하면 기존 미푸시 커밋의 식별정보도 함께 공개될 수 있다. 후속 삭제 커밋으로 과거 내용이 사라지지 않는다. |
| 미푸시 커밋 수정 | 공개하지 않을 실제 식별정보를 최초 포함 커밋에서 제거할 수 있다. 사용자 승인 후에만 진행한다. |
| 안전한 새 커밋으로 재구성 | 별도 브랜치/기준점에서 안전한 내용만 재구성할 수 있다. 이전 커밋을 조상으로 남기면 같은 문제가 남으므로 정확한 기준점과 포함 범위 승인이 필요하다. |

`d732bbf`의 두 resource_bundle 테스트에는 실제 Run 식별자와 샘플 연결이 포함돼 있다.
새 ADR·명세에는 실제 사례의 부분 식별자와 샘플 표기가 있다.
이번 작업은 작업 트리만 수정했고 해당 커밋은 그대로 보존했다.
이전 감사에서 로컬 `origin/main`의 19개 파일에서도 실제 Run 연결 정보를 확인했다. 이 범위의 정리와 원격 공개 상태 확인은 별도 작업이다.
작성자 이메일 등 Git 메타데이터의 공개 여부도 별도 판단한다.

## 검증 결과

- 로컬 전체 backend: **1,403 passed / 33 skipped**, 모델 호출 없음.
- 후보 파일만 HEAD 위에 복사하고 새 로컬 설정·원문 corpus·비공개 신규 정답·질의·baseline을 빼서 검사: **1,291 passed / 136 skipped**.
  기존 HEAD가 이미 추적하던 자료는 이력 변경 없이 그대로 상속했다. 이 검사는 저장소 전체가 비식별화됐다는 보증이 아니다.
  실제 데이터가 없는 검사는 명시적으로 skip하며, 공개 fixture·코드 검증은 실행한다. 데이터에 따른 parametrization 수가 달라 총 수가 다르다.
- P1의 3개 파일만 HEAD에 적용한 독립 조합: **125 passed / 3 skipped**.
- 실제 capture 1건·실패 archive 2건을 수정 전 모듈과 수정 후 모듈로 각각 사전 검증: 모든 사전 검증 필드와 payload hash 동일, 개인정보 검사 pass.
- frontend TypeScript 검사와 release build 통과. 생성 JS에서 기존 21개 quote 원문 검출 **0건**.
- frontend lint 통과.
- 비공개 corpus가 없는 후보 환경에서 RAG를 켜고 서비스 시작·health 요청 통과. frontend 개발 alias는 로컬, build alias는 공개 corpus임을 확인했다.
- 공유 ignore 경계 검증 통과. 새 규칙과 일치하지만 이미 추적 중인 파일 17개는 그대로 추적된다. 추적 해제와 이력 정리는 실행하지 않았다.
- 보호 문서·Git index·아카이브·원본 capture·실행 데이터·기존 정답·baseline은 시작 시 해시와 대조한다.
- 기존 dependency deprecation 및 bundle 크기 경고는 기능 실패로 취급하지 않았으며 관련 없는 수정은 하지 않았다.

## 이번에 수정한 파일별 동작

| 경로 | 수정 이유 | 수정 전후 동작 | 검증·기존 평가 영향 |
|---|---|---|---|
| `backend/app/tests/test_doc_retrieval.py` | 외부 문장 없는 공개 테스트 | 원문 corpus 의존 → 합성 corpus | 원인별 검색·인용·스위치 검사 유지 |
| `backend/evals/archive_runs.py` | 실제 식별자·아카이브 위치 분리 | 하드코딩 → 로컬 등록값 | 실제 실패 2건 preflight 완전 동일 |
| `backend/evals/test_archive_runs.py` | 비공개 정답 없는 checkout 지원 | 정답 부재 시 해당 검사만 skip | 정답이 있으면 기존 모든 검증 유지 |
| `backend/evals/test_dev_restore_failed.py` | 공개 테스트의 corpus 경계 | 원문 corpus 의존 → 합성 corpus | 실제 source 복사·원본 검증은 유지 |
| `backend/evals/test_doc_rag_variant.py` | 외부 문장 없는 공개 테스트 | 원문 corpus 의존 → 합성 corpus | v3/v3rag 입력 동등성 검사 유지 |
| `backend/evals/test_doc_retrieval_compare.py` | 원문 corpus·질의 경계 | 합성 corpus 사용, 비공개 질의 부재 명시 skip | 기존 질의 원본은 변경하지 않음 |
| `backend/evals/test_retrieval_compare.py` | 고정 연구 질의 보존 | 질의 부재 시 명시 skip, 토큰화 테스트 유지 | 기존 파일 해시·실험 의미 유지 |
| `.gitignore` | 개인 자료 유입 차단 | 로컬 제외에 의존 → 공유 규칙으로 보호, example은 유지 | ignore 경계 검사; 원본 파일은 보존 |
| `backend/app/agent_mcp/launch.py` | 부모/자식 corpus 일치 | 스위치만 전달 → 선택한 파일 경로도 전달 | MCP·variant 테스트 |
| `backend/app/config.py` | corpus 선택 분리 | 필수 로컬 원문 → 로컬 호환 + 빈 공개 fallback | 전체·후보 테스트; 로컬 payload 동일 |
| `backend/app/tests/test_resource_bundle_causes.py` | 실제 Run ID 제거 | 문자열 하드코딩 → 로컬 등록값 | 기존 실제 source 검사와 합성 테스트 유지 |
| `backend/app/tests/test_resource_bundle_diagnosis.py` | 실제 Run/샘플 매핑 제거 | 하드코딩 → 로컬 Run + 원본 metrics의 sample | 실제 API/Agent 투영 검증 유지 |
| `backend/evals/real_runs.py` | 실제 capture 식별자 분리 | 하드코딩 → 로컬 등록값 | 실제 capture preflight 완전 동일 |
| `backend/evals/run_eval.py` | 출처 필드 예외 검사 강화 | 필드명으로 제외 → 등록값과 일치할 때만 제외 | 오염된 출처 필드 회귀 테스트; 정상 기록 의미 유지 |
| `backend/evals/test_real_runs.py` | 무관한 실제 식별자 제거 | 미등록 실제 ID → 명백한 합성 미등록 ID | 도구의 다른 Run 거부 의미 동일 |
| `front/src/registries/knowledge.ts` | 공개 import 완결성 | 로컬 원문 직접 import → 공개 corpus import | TypeScript·release build·lint |
| `front/vite.config.ts` | 원문의 release 혼입 방지 | 개발 alias는 로컬 호환, build는 공개 corpus | release JS 원문 검출 0건 |
| `backend/app/tests/doc_corpus_fixture.py` | 테스트 격리 | 합성 corpus 선택·cache 정리 | 전체·공개 후보 테스트 |
| `backend/app/tests/fixtures/doc_passages.synthetic.json` | 직접 작성한 테스트 문장 | 제품용 지식과 분리된 합성 corpus | 검색·MCP·인용 테스트 |
| `backend/evals/local_data.py` | 로컬 데이터 경계 추가 | 원본 등록값 읽기, 부재/오류 fail closed | 합성 단위검사·실제 preflight |
| `backend/evals/test_publication_boundaries.py` | 공개 경계 회귀 검증 | 빈 corpus·비공개 설정 부재·정상 등록값·오염 필드 | 공개 환경에서도 실행 |
| `config/knowledge/wes_doc_passages.public.json` | 원문 없는 배포 기본값 | 빈 corpus; 원본은 로컬 유지 | 서비스 import·빈 corpus·release build |
| `config/local.example/wes_eval_runs.json` | 공개 설정 형식 | 실제 값 없는 합성 예시 | 실제 기본값으로 자동 사용하지 않음 |
| `docs/GIT_PUBLICATION_PREPARATION.md` | 결정과 검증 근거 | 새 후속 조치 기록; 기존 보호 문서 불변 | 본문·목록·파일 해시 검토 |

## 전체 파일 분류와 커밋 후보

“지금 커밋 가능”은 이번 변경 내용과 의존성이 검증됐다는 뜻이다. 기존 이력의 공개 승인이나 저장소 전체 라이선스를 보증하지 않는다.
이전 B 코드·테스트는 로컬 설정/원본 metadata 경계로 수정했다. C의 합성 정답은 공개 회귀 테스트로 분류하고, 원문 corpus·고정 질의는 로컬로 유지한다.

| 경로 | 최종 분류 | 근거 |
|---|---|---|
| `.gitignore` | 지금 커밋 가능 | 개인 자료 유입 차단 |
| `backend/app/agent_mcp/launch.py` | 지금 커밋 가능 | 부모/자식 corpus 일치 |
| `backend/app/config.py` | 지금 커밋 가능 | corpus 선택 분리 |
| `backend/app/services/agent/doc_retrieval.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/agent/privacy.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/agent/step_evidence.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/explanation/knowledge.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/explanation/llm/claims.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/explanation/llm/prompt.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/explanation/llm/synthesis.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/explanation/llm/tools.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/services/resource_bundle_diagnosis.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/doc_corpus_fixture.py` | 지금 커밋 가능 | 테스트 격리 |
| `backend/app/tests/fixtures/doc_passages.synthetic.json` | 지금 커밋 가능 | 직접 작성한 테스트 문장 |
| `backend/app/tests/test_agent_step_tool.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_beginner_terms.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_cause_kind_knowledge.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_doc_retrieval.py` | 지금 커밋 가능 | 외부 문장 없는 공개 테스트 |
| `backend/app/tests/test_knowledge_enrichment.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_model_input_release.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_privacy_redactor_punctuation.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_rejection_observer.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_resource_bundle_causes.py` | 지금 커밋 가능 | 실제 Run ID 제거 |
| `backend/app/tests/test_resource_bundle_diagnosis.py` | 지금 커밋 가능 | 기존 B 수정 완료: 실제 값은 로컬/원본 경계로 분리 |
| `backend/app/tests/test_run_fact_gates.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/app/tests/test_tool_toggle.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/agent_cases.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/archive_runs.py` | 지금 커밋 가능 | 기존 B 수정 완료: 실제 값은 로컬/원본 경계로 분리 |
| `backend/evals/dev_restore.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/evaluators.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/expectations/agent_resource_heldout.json` | 지금 커밋 가능 | 합성 공개 회귀 테스트; 독립 성능 평가와 구분 |
| `backend/evals/expectations/agent_resource_index_pair.json` | 지금 커밋 가능 | 합성 공개 회귀 테스트; 독립 성능 평가와 구분 |
| `backend/evals/expectations/agent_resource_unclassified.json` | 지금 커밋 가능 | 합성 공개 회귀 테스트; 독립 성능 평가와 구분 |
| `backend/evals/experiments/__init__.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/experiments/doc_retrieval_compare.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/experiments/retrieval_compare.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/explanation_quality.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/local_data.py` | 지금 커밋 가능 | 로컬 데이터 경계 추가 |
| `backend/evals/real_runs.py` | 지금 커밋 가능 | 기존 B 수정 완료: 실제 값은 로컬/원본 경계로 분리 |
| `backend/evals/rubric/explanation_checks_v2.json` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/run_eval.py` | 지금 커밋 가능 | 출처 필드 예외 검사 강화 |
| `backend/evals/test_archive_runs.py` | 지금 커밋 가능 | 비공개 정답 없는 checkout 지원 |
| `backend/evals/test_dev_restore_failed.py` | 지금 커밋 가능 | 공개 테스트의 corpus 경계 |
| `backend/evals/test_doc_rag_variant.py` | 지금 커밋 가능 | 외부 문장 없는 공개 테스트 |
| `backend/evals/test_doc_retrieval_compare.py` | 지금 커밋 가능 | 원문 corpus·질의 경계 |
| `backend/evals/test_evaluators.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/test_publication_boundaries.py` | 지금 커밋 가능 | 공개 경계 회귀 검증 |
| `backend/evals/test_real_baseline_privacy.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/test_real_runs.py` | 지금 커밋 가능 | 기존 B 수정 완료: 실제 값은 로컬/원본 경계로 분리 |
| `backend/evals/test_recorded_answers_pass_claims.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/test_rejected_output.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `backend/evals/test_retrieval_compare.py` | 지금 커밋 가능 | 고정 연구 질의 보존 |
| `backend/evals/test_synthetic_resource_cases.py` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `config/knowledge/wes_cause_kinds.json` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `config/knowledge/wes_doc_passages.public.json` | 지금 커밋 가능 | 원문 없는 배포 기본값 |
| `config/knowledge/wes_failures.json` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `config/knowledge/wes_sources.json` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `config/knowledge/wes_terms.json` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `config/local.example/wes_eval_runs.json` | 지금 커밋 가능 | 공개 설정 형식 |
| `docs/GIT_PUBLICATION_PREPARATION.md` | 지금 커밋 가능 | 결정과 검증 근거 |
| `front/src/features/run-detail/components/RunSynthesisPanel.tsx` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `front/src/registries/evidence.ts` | 지금 커밋 가능 | 기존 A 근거 유지 + 전체 조합 검증 |
| `front/src/registries/knowledge.ts` | 지금 커밋 가능 | 공개 import 완결성 |
| `front/vite.config.ts` | 지금 커밋 가능 | 원문의 release 혼입 방지 |
| `backend/evals/baselines/2026-11-15_agent_resource_heldout_v3_sonnet_4c7087633f10e05c.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_3a22c5_v1_sonnet_30a9df6c0fe04709.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_3a22c5_v3_sonnet_3e95d20d110eb4c5.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_3a22c5_v3_sonnet_4a4f2d9ddf604ce8.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_3a22c5_v3_sonnet_4c7087633f10e05c.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_b94559_v1_sonnet_30a9df6c0fe04709.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_b94559_v3_sonnet_3e95d20d110eb4c5.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_b94559_v3_sonnet_4a4f2d9ddf604ce8.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/baselines/2026-11-15_real_b94559_v3_sonnet_4c7087633f10e05c.json` | 로컬 전용 | 기존 baseline 원본 보존; Git 유입 차단 |
| `backend/evals/expectations/real_3a22c5.json` | 로컬 전용 | 실제 Run 파생 정답 원본 보존 |
| `backend/evals/expectations/real_b94559.json` | 로컬 전용 | 실제 Run 파생 정답 원본 보존 |
| `backend/evals/experiments/retrieval_queries.json` | 권리·공개 추가 판단 / 로컬 전용 | 동결된 연구 질의 원본 보존; 공개 범위 미확정 |
| `config/knowledge/wes_doc_passages.json` | 권리·공개 추가 판단 / 로컬 전용 | 21개 원문 그대로 보존; 공개 corpus와 분리 |
| `docs/AGENT_PLAN.md` | 사용자 승인 전 제외 | 보호 문서; 이번 작업에서 변경하지 않음 |
| `docs/AGENT_EXPANSION_ROADMAP.md` | 사용자 승인 전 제외 | 보호 문서; 이번 작업에서 변경하지 않음 |
| `docs/HG002_RESOURCE_VERIFICATION.md` | 사용자 승인 전 제외 | 보호 문서; 이번 작업에서 변경하지 않음 |

이번 검토 목록은 80개다: 커밋 후보 64개, 기존 변경 중 로컬 보존 13개, 보호 문서 3개.
별도로 새 로컬 설정, 백업, 해시 기록, 검증용 복사본과 빌드 산출물은 모두 ignore된 local 영역에 보존한다.
이미 추적된 과거 자료의 추적 해제·이력 수정은 이번 분류에서 실행한 것으로 취급하지 않는다.

## 커밋 구성

권장 단일 커밋은 아래 후보 전체다. 공개 corpus, 로컬 설정 loader, synthetic fixture, frontend import가 함께 들어가므로 데이터 파일을 제외해도 의존성이 끊기지 않는다.

메시지: `feat(agent): prepare privacy-safe diagnostics and optional document retrieval`

두 커밋으로 나누려면:
1. P1: `backend/app/services/agent/privacy.py`, `backend/app/services/resource_bundle_diagnosis.py`, `backend/app/tests/test_privacy_redactor_punctuation.py`
   메시지: `fix(privacy): harden path redaction and release checks`
2. P2: 나머지 후보 전체. P1 위에 적용한다.
   메시지: `feat(agent): add optional document retrieval and reproducible evaluation boundaries`

실제 파일 단위로 섞인 Agent·RAG·평가 변경을 더 잘게 나누면 중간 커밋의 import나 데이터 계약이 깨질 수 있어 이번에는 권하지 않는다.
안전한 후보와 제외 목록, 파일 해시는 `local-context/git-safety-20261116/`에 보존한다.
이 위치의 Git 명령 초안은 사용자 실행용이며 자동 실행하지 않았다.

## 남은 결정

- 실제 Run 연결 정보 및 기존 baseline/정답의 공개 근거.
- 미푸시 `d732bbf`를 수정할지, 안전한 기준점에서 재구성할지.
- 이미 추적된 과거 자료와 원격 이력의 별도 정리 범위.
- 공식 발췌를 향후 배포하려면 출처별 권리·고지·버전·인용 정확성 재확인.
- 공개 frontend와 비공개 corpus를 켠 backend를 배포 조합으로 사용하면 private doc ID는 원문 링크로 해석되지 않는다. 로컬 개발 조합은 유지되며, 공개 배포에 문서 근거가 필요하면 권리가 정리된 공유 corpus가 필요하다.
- 이번 로컬 평가·공개 회귀 테스트와 분리된 독립 성능 평가 데이터 설계.

이번에는 위 판단을 대신하여 이력을 수정하거나 실제 원본 데이터를 바꾸지 않았다.
