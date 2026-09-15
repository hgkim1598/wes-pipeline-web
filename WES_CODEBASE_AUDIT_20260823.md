# WES Codebase Audit - 2026-08-23

Audit Scope: This document is a static repository/code audit. Runtime evidence
such as server startup, API health checks, `main.sh` execution success, and real
pipeline behavior should be verified from separate execution or operations logs.

## 1. Executive Summary

현재 프로젝트는 "브라우저에서 FASTQ R1/R2를 업로드하고, Backend가 `main.sh`를 실행해 WES pipeline을 돌리고, 진행 상태와 Backend-level 결과 API를 제공하는" 수준까지 구현되어 있다.
핵심 실행 경로는 `SubmitPage -> upload API -> POST /api/jobs -> SQLite job row -> single Worker -> PipelineExecutor -> script/main.sh`로 실제 코드가 연결되어 있다.
Backend는 job status, step detail, results summary, artifacts listing/download API를 갖추고 있고, `main.sh`가 쓰는 `status/`, `metrics/`, `artifacts/`, `logs/` 파일을 읽는다.
Pipeline core 단계는 `00_input_validation`부터 `06_variant_calling`, `99_finalization`까지 구현되어 있고 optional 단계로 `08_filtering`, `10_annotation`, `11_intervar`가 존재한다.
현재 웹 제출로는 filtering/annotation이 활성화되지 않으며, InterVar만 server capability와 `run_acmg`에 따라 조건부 활성화된다.
Frontend는 submit/upload/job polling/cancel/timeline/log viewer까지 연결되어 있지만, 결과 화면은 placeholder이며 Backend results/artifacts/step detail API를 아직 사용하지 않는다.
가장 큰 gap은 "분석은 돌릴 수 있지만, 사용자가 결과를 웹에서 제대로 볼 수 있는 부분은 아직 부족하다"는 점이다.
정적 코드 감사 기준으로 명백한 P0 blocker는 발견되지 않았다. 단, 이번 감사에서는 실제 build/test/pipeline/server 실행을 수행하지 않았으므로 runtime P0 부재까지 검증한 것은 아니다.
P1은 ResultsPage 연결, artifact/download UI, unsupported option 표시, Step Detail UI 연결이다.
이번 감사는 읽기 중심이며 test/build/pipeline/server 실행은 하지 않았다.

## 2. Current Architecture

```text
User
  -> front/src/pages/SubmitPage.tsx
  -> front/src/features/upload/useChunkedUpload.ts
  -> POST/GET/PUT/POST /api/uploads
  -> POST /api/jobs
  -> backend/app/api/jobs.py:create_job
  -> backend/app/services/config_builder.py
  -> backend/app/db.py SQLite jobs/uploads
  -> backend/app/services/worker.py single background queue
  -> backend/app/services/pipeline_executor.py
  -> script/main.sh --config <run_config.json>
  -> runs/<run_id>/
       status/run_status.json
       status/steps/<step>.json
       metrics/<step>.json
       artifacts/<step>.json
       logs/stage_status.tsv
       logs/pipeline.log
       core_summary.json
  -> backend readers
       run_status_reader.py
       step_reader.py
       result_reader.py
       artifact_reader.py
  -> GET /api/jobs/{id}
     GET /api/jobs/{id}/steps/{step_id}
     GET /api/jobs/{id}/results
     GET /api/jobs/{id}/artifacts
     GET /api/jobs/{id}/artifacts/{file_id}/download
  -> Frontend JobPage / currently-placeholder ResultsPage
```

Core architecture is intentionally small: React, FastAPI, SQLite, one worker thread, one Bash pipeline. This scale is appropriate for the current educational WES prototype.

## 3. Repository Map

| Path | Role | Current state |
|---|---|---|
| `front/` | React/Vite UI | Submit, upload, job polling, cancel connected. Results placeholder. |
| `backend/` | FastAPI API server | Upload/job/results/artifact/step APIs implemented. |
| `script/main.sh` | Actual WES orchestrator | Core WES, optional filtering/annotation/intervar, status/metrics/artifacts writers. |
| `config/capture_kits.grch38.json` | Capture kit registry | Backend validates kit id and confirmed status. |
| `docs/` | Pipeline/resource docs | Useful, but some docs are broader than what Front currently exposes. |
| `runs/`, `uploads/` | Runtime data roots | Runtime state, not source of code truth. |
| `backend/app/tests/` | Backend tests | Covers jobs, results, artifacts, step detail, InterVar capability, stage status. Not executed in this audit. |

Current git baseline at audit start:

```text
branch: khg
modified: front/README.md
untracked: backend/README.md, script/README.md, wes-results-api-patch.tar.gz, wes-web_c0a94a5.tar.gz
```

## 4. Frontend Audit

### Pages and flow

| Page | File | Current role | Status |
|---|---|---|---|
| Home | `front/src/pages/HomePage.tsx` | Entry page, start navigation | Connected |
| Submit | `front/src/pages/SubmitPage.tsx` | Profile selection, FASTQ upload, options, POST job | Connected |
| Job | `front/src/pages/JobPage.tsx` | Poll job, show progress, timeline, log, cancel, result button | Connected |
| Results | `front/src/pages/ResultsPage.tsx` | Tab shell based on profile result view metadata | Mock / Placeholder |

Routes are defined in `front/src/app/router.tsx:7-11`.

### Frontend API calls

| Caller | Method | Endpoint | Request/response expectation | Backend match |
|---|---:|---|---|---|
| `useChunkedUpload.ts:76` | POST | `/api/uploads` | `{filename,size,sampleId,slotId}` -> `{uploadId,chunkSize}` | Yes, `uploads.py:75-110` |
| `useChunkedUpload.ts:94` | GET | `/api/uploads/{id}` | `{receivedChunks}` | Yes, `uploads.py:115-123` |
| `useChunkedUpload.ts:118` | PUT | `/api/uploads/{id}/{index}` | raw chunk -> 204 | Yes, `uploads.py:127-156` |
| `useChunkedUpload.ts:155` | POST | `/api/uploads/{id}/complete` | `{path}` token | Yes, `uploads.py:159-220` |
| `SubmitPage.tsx:73-76` | POST | `/api/jobs` | `{profileId,captureKitId,options,samples}` -> `{jobId}` | Yes, `jobs.py:46-156` |
| `useJobStream.ts:101` | GET | `/api/jobs/{id}/stream` | SSE first | Backend intentionally 404, fallback works |
| `useJobStream.ts:80` | GET | `/api/jobs/{id}` | job state | Yes, `jobs.py:180-237` |
| `useJobStream.ts:160` | POST | `/api/jobs/{id}/cancel` | 204 | Yes, `jobs.py:240-255` |
| ResultsPage | none currently | `/api/jobs/{id}/results` | not called | Backend exists, Front not connected |
| ResultsPage | none currently | `/api/jobs/{id}/artifacts` | not called | Backend exists, Front not connected |
| StepTimeline | none currently | `/api/jobs/{id}/steps/{step}` | not called | Backend exists, Front not connected |

### Mock state

MSW is opt-in through `VITE_USE_MOCK=true` in `front/src/main.tsx:18-20`. Vite proxies `/api` to FastAPI at `front/vite.config.ts:12-19`.

Mock handlers exist for profiles, uploads, jobs, job status and cancel in `front/src/mocks/handlers.ts:56-100`. Mock does not cover step detail, results, artifacts, or download. Mock job response also lacks several real fields such as `profileId`, `logTail`, `runMode`, `pipelineStatus`, `currentStep`, `unsupportedOptions`.

### What the user can currently see

| User-visible item | Current Front display |
|---|---|
| upload progress | Yes |
| job status | Yes |
| progress percentage | Yes |
| step timeline | Yes |
| step warning/failure messages from `/jobs` | Yes |
| log tail | UI exists, but polling mode text says detailed log is not shown; Backend does return `logTail` |
| output files | No UI |
| QC/coverage result | No real UI |
| alignment metrics | Only if exposed as step messages; no step detail UI |
| variant result | No real UI |
| annotation/ACMG result | No real UI |
| downloads | No UI |

## 5. Backend Audit

### Endpoint table

| Method | Path | Role | Request | Response | Internal functions/files |
|---|---|---|---|---|---|
| GET | `/api/health` | Health | none | basic config/status | `main.py:62` |
| POST | `/api/uploads` | Start chunk upload | `UploadInitRequest` | `UploadInitResponse` | `uploads.py:create_upload` |
| GET | `/api/uploads/{upload_id}` | Resume info | path id | `UploadStatusResponse` | `uploads.py:upload_status` |
| PUT | `/api/uploads/{upload_id}/{chunk_index}` | Store chunk | octet stream | 204 | `uploads.py:put_chunk` |
| POST | `/api/uploads/{upload_id}/complete` | Assemble upload | path id | `UploadCompleteResponse(path=upload_id)` | `uploads.py:complete_upload` |
| POST | `/api/jobs` | Create queued pipeline job | `CreateJobRequest` | `CreateJobResponse(jobId)` | `jobs.py:create_job`, `config_builder.py` |
| GET | `/api/jobs/{job_id}` | Polled job state | path id | `JobStateResponse` | `jobs.py:get_job`, `run_status_reader.py` |
| POST | `/api/jobs/{job_id}/cancel` | Cancel queued/running job | path id | 204 | `jobs.py:cancel_job`, `pipeline_executor.py:terminate` |
| GET | `/api/jobs/{job_id}/stream` | SSE placeholder | path id | 404 | intentional fallback, `jobs.py:job_stream` |
| GET | `/api/jobs/{job_id}/steps/{step_id}` | One step detail | path ids | `StepDetailResponse` | `steps.py`, `step_reader.py` |
| GET | `/api/jobs/{job_id}/results` | Precheck/full result summary | path id | `JobResultsResponse` or 409 | `results.py`, `result_reader.py` |
| GET | `/api/jobs/{job_id}/artifacts` | Artifact list | path id | `ArtifactListResponse` | `results.py`, `artifact_reader.py` |
| GET | `/api/jobs/{job_id}/artifacts/{file_id}/download` | Download one safe registered file | path ids | file response | `results.py`, `artifact_reader.py` |

### Job lifecycle

Backend orchestration states are in `backend/app/services/worker.py:27-31`:

```text
QUEUED -> RUNNING -> DONE
QUEUED/RUNNING -> CANCELLED/CANCELLING
launch/pre-run failure -> EXEC_FAILED
```

Pipeline states are adapted separately in `backend/app/services/run_status_reader.py:40-50`:

```text
running, completed, completed_with_warnings, failed, cancelled,
resume_refused, stopped_at_requested_step, check_only
```

This separation is correct: SQLite is orchestration metadata, while run progress is read from `main.sh` JSON.

### Worker and subprocess

`worker.py` has a single in-process queue and daemon thread (`worker.py:21-23`, `worker.py:162-168`). `PipelineExecutor` builds an argv list, never `shell=True`, redirects stdout/stderr to `executor.log`, and on POSIX uses `start_new_session=True` for process-group cancellation (`pipeline_executor.py:41-93`). Non-zero exit is not automatically an executor failure if `status/run_status.json` exists (`worker.py:87-100`).

### WES_RUN_MODE

`WES_RUN_MODE` allows `check_only` and `full`, default `check_only` (`config.py:60-89`). In `check_only`, Backend planned steps are only `["00_input_validation"]` (`config_builder.py:150-158`), matching `main.sh` behavior (`main.sh:5160-5180` region). In `full`, Backend plans core steps, conditional InterVar, and finalization.

### Config

Important env names used by Backend:

```text
WES_BASH
WES_RUN_MODE
WES_RUNS_ROOT
WES_UPLOAD_ROOT
WES_ASSEMBLY
WES_CONTIG_STYLE
WES_BUNDLE_ID
WES_REFERENCE_FASTA
WES_DBSNP_VCF
WES_KNOWN_SITES
WES_INTERVAR_DIR
WES_INTERVAR_BUILD
WES_INTERVAR_HUMANDB
WES_THREADS
WES_JAVA_MEM_GB
```

`.env` is loaded from `backend/.env` (`config.py:21-43`). InterVar is fail-closed: none means no capability, all three means enabled capability, partial means startup `ConfigError` (`config.py:125-163`).

## 6. Pipeline Audit

Actual step metadata is defined in `script/main.sh:140-180`. Step dispatch is in `script/main.sh:4935-4950`. Step plan is built in `script/main.sh:4615-4622`.

| Order | Step | Tool/operation | Input | Output | Success/failure basis | Backend detects? | User value |
|---:|---|---|---|---|---|---|---|
| 0 | `00_input_validation` | samplesheet/resource/tool validation | run_config, samplesheet, FASTQ, reference, capture kit | `manifest.tsv`, `normalized_manifest.json`, metrics/artifacts | step checks/failures | Yes: job, step detail, results precheck | Confirms input/resource readiness |
| 1 | `01_raw_qc` | FastQC, optional MultiQC | FASTQ lanes | FastQC HTML/ZIP, MultiQC | step checks/warnings | Yes via artifacts/step detail | Raw read QC |
| 2 | `02_preprocessing` | trimming mode, currently config says `trim_mode: skip` | FASTQ | preprocessing decision, possibly trimmed reads | step status | Yes | Documents preprocessing decision |
| 3 | `03_alignment` | BWA-MEM, samtools | FASTQ/reference | sample BAM/BAI, flagstat/stats, `alignment_output.json` | BAM validation and metrics | Yes, `mapped_pct` via step detail | Alignment quality |
| 4 | `04_processing` | MarkDuplicates, BQSR, validation | sample BAM, known-sites | analysis-ready BAM/BAI, metrics | BAM validation | Yes | Final BAM for calling |
| 5 | `05_coverage_qc` | mosdepth | analysis-ready BAM, coverage BED | `coverage_metrics.json`, regions/thresholds/low coverage BED | warnings for low coverage, failure for missing required files | Yes, results coverage + artifacts | Coverage summary |
| 6 | `06_variant_calling` | GATK HaplotypeCaller / GenotypeGVCFs style flow | analysis-ready BAM, reference | gVCF, raw VCF, stats, `variant_calling_output.json` | VCF validation | Yes, results variantCalling + artifacts | Raw variants |
| optional | `08_filtering` | bcftools filtering | raw VCF | filtered VCF | optional failure does not fail core | Backend can read if enabled | Filtered variants |
| optional | `10_annotation` | normalization, ClinVar if configured, TSV | raw VCF | normalized/ClinVar VCF, variant TSV | optional failure does not fail core | Backend can read if enabled | Annotated variant table |
| optional | `11_intervar` | InterVar | raw VCF + intervar config | InterVar result/summary | optional failure does not fail core | Backend can read if enabled | ACMG classification |
| final | `99_finalization` | summary/provenance/methods | previous outputs | `core_summary.json`, `artifact_manifest.json`, `final_validation.tsv`, `methods.md` | final validation | Yes | Run summary and downloads |

Every step uses `start_step()` and `finish_step()`. `finish_step()` writes `status/steps/<step>.json`, `metrics/<step>.json`, and `artifacts/<step>.json` atomically via `.part` + `os.replace` (`main.sh:700-833`). `write_run_status()` also uses `.part` + `os.replace` (`main.sh:867-916`). `stage_status.tsv` format is `timestamp<TAB>step<TAB>status<TAB>exit_code` (`main.sh:541-545`).

## 7. End-to-End Trace

1. User selects a profile and drops FASTQ files.
   - Files: `SubmitPage.tsx`, `UploadZone.tsx`, `pairDetection.ts`.
   - Data: local `File`, sample id, slots `r1/r2`.

2. Frontend uploads chunks.
   - API: `/api/uploads`, `/api/uploads/{id}`, `/api/uploads/{id}/{index}`, `/api/uploads/{id}/complete`.
   - Backend returns opaque upload token as `path`, not a filesystem path (`uploads.py:8-13`, `uploads.py:218-220`).

3. Frontend creates job.
   - `SubmitPage.tsx:73-76` posts `profileId`, `captureKitId`, `options`, `samples`.
   - Backend validates one sample, R1/R2, assembly, capture kit, upload tokens (`jobs.py:48-100`).

4. Backend writes pipeline inputs.
   - `config_builder.write_samplesheet()` writes one-sample one-lane CSV (`config_builder.py:177-190`).
   - `config_builder.build_run_config()` writes server-owned resource paths and optional flags (`config_builder.py:193-255`).

5. Backend stores job and queues worker.
   - SQLite schema in `db.py:28-63`.
   - `jobs.py:132-155` inserts job, then `worker.submit(run_id)`.

6. Worker launches pipeline.
   - `worker.py:48-112` launches and waits.
   - `pipeline_executor.py:41-93` executes `bash script/main.sh --config ...`.

7. Pipeline writes machine documents.
   - `status/run_status.json`, `status/steps/*.json`, `metrics/*.json`, `artifacts/*.json`, `logs/*`, `core_summary.json`.

8. Backend reads progress/results.
   - `/jobs/{id}` uses `run_status_reader.py`.
   - `/steps/{step}` uses `step_reader.py`.
   - `/results` uses `result_reader.py`.
   - `/artifacts` and download use `artifact_reader.py`.

9. Frontend displays progress.
   - `JobPage.tsx` shows progress, timeline, log viewer, cancel, results button.
   - Results button navigates to `/results/{jobId}` without `profileId`; ResultsPage therefore usually shows the missing-profile placeholder.

## 8. Pipeline Result Exposure Matrix

| Pipeline result | File | Backend recognizes | API provides | Front displays | Current state |
|---|---|---:|---:|---:|---|
| run status | `status/run_status.json` | Yes | Yes, `/jobs` | Yes | Connected |
| step status | `status/steps/<step>.json` | Yes | Yes, `/jobs`, `/steps` | Partly: `/jobs` only | Partly connected |
| running elapsed | `logs/stage_status.tsv` | Yes | Yes, `/jobs`, `/steps` | Yes in timeline if rendered | Connected |
| log tail | `logs/pipeline.log` | Yes | Yes, `/jobs` | UI exists | Partly connected |
| step metrics | `metrics/<step>.json` | Yes | Yes, `/steps` | No | Implemented but not connected |
| step artifacts | `artifacts/<step>.json` | Yes | Yes, `/steps`, `/artifacts` | No | Implemented but not connected |
| precheck result | `00_input_validation` step + metrics | Yes | Yes, `/results` | No | Implemented but not connected |
| coverage summary | `05_coverage_qc/coverage_metrics.json` | Yes | Yes, `/results.coverage` | No | Implemented but not connected |
| variant calling summary | `06_variant_calling/variant_calling_output.json` | Yes | Yes, `/results.variantCalling` | No | Implemented but not connected |
| raw VCF/gVCF download | artifact records | Yes | Yes, artifact download | No | Implemented but not connected |
| filtering result | optional artifacts | Yes if step enabled | Yes if produced | No | CLI/script capable, web disabled |
| annotation result | optional artifacts | Yes if step enabled | Yes if produced | No | CLI/script capable, web disabled |
| InterVar result | optional artifacts | Yes if capability enabled and produced | Yes if produced | No | Conditional backend support, no UI |
| final summary | `core_summary.json` | Yes | Yes, `/results` | No | Implemented but not connected |
| methods/provenance | final artifacts | Yes | Yes, `/artifacts` | No | Implemented but not connected |

## 9. Progress Tracking Feasibility

Current progress is `completed planned steps / planned steps`, not CPU or byte-level progress (`run_status_reader.py:17-18`, `run_status_reader.py:238-239`). This is simple and correct for the current UI.

| Step | Start detection | Finish detection | Failure detection | Related files/logs | Backend difficulty |
|---|---|---|---|---|---|
| `00_input_validation` | `current_step` + `stage_status.tsv` | `status/steps/00_input_validation.json` | failures in same doc | validation report, metrics | Easy |
| `01_raw_qc` | same | step doc | step failures/warnings | FastQC artifacts | Easy |
| `02_preprocessing` | same | step doc | step failures/warnings | decision JSON | Easy |
| `03_alignment` | same | step doc | step failures/warnings | BAM, flagstat, metrics `mapped_pct` | Easy |
| `04_processing` | same | step doc | step failures/warnings | analysis-ready BAM, markdup metrics | Easy |
| `05_coverage_qc` | same | step doc | step failures/warnings | `coverage_metrics.json` | Easy |
| `06_variant_calling` | same | step doc | step failures/warnings | `variant_calling_output.json` | Easy |
| `08_filtering` | only if planned | step doc | optional failure recorded | filtered VCF | Easy if enabled |
| `10_annotation` | only if planned | step doc | optional failure recorded | normalized/ClinVar/TSV | Easy if enabled |
| `11_intervar` | only if planned | step doc | optional failure recorded | InterVar summary/table | Easy if enabled |
| `99_finalization` | same | step doc + `core_summary.json` | finalization failures | summary/provenance/methods | Easy |

The key missing work is Frontend usage of `/steps/{step_id}` for detailed metrics/artifacts, not Backend feasibility.

## 10. Gaps and Mismatches

### Gap 1: ResultsPage is not connected to Backend results

Problem: Backend provides `GET /api/jobs/{id}/results`, but ResultsPage does not call it. It renders placeholder tabs only.

Evidence:

```text
backend/app/api/results.py:82
front/src/pages/ResultsPage.tsx:47-50
front/src/features/results/registry.tsx:4-11
```

Impact: The pipeline can produce results, and Backend can serve them, but the user cannot inspect them in the web UI.

Suggested direction: ResultsPage should fetch `/api/jobs/{jobId}` for `profileId`, then fetch `/api/jobs/{jobId}/results` and render summary cards.

### Gap 2: Result view endpoint mismatch in comments

Problem: Front placeholder text refers to `GET /api/jobs/{jobId}/results/{v.id}`, but Backend implements one summary endpoint `/api/jobs/{job_id}/results`.

Evidence:

```text
front/src/pages/ResultsPage.tsx:50
backend/app/api/results.py:82
```

Impact: Future implementation may target the wrong endpoint if the comment is followed literally.

Suggested direction: Use existing summary endpoint first; add per-view endpoint only if later needed.

### Gap 3: JobPage does not pass profileId to ResultsPage

Problem: Backend returns `profileId`, but JobPage navigates to `/results/{jobId}` without state. ResultsPage reads only router state.

Evidence:

```text
backend/app/api/jobs.py:226
front/src/pages/JobPage.tsx:82
front/src/pages/ResultsPage.tsx:9-14
```

Impact: Clicking "result" normally shows the missing-profile placeholder.

Suggested direction: ResultsPage should load job state by `jobId`; router state should be optional cache only.

### Gap 4: Unsupported options are not shown to users

Problem: Backend records unsupported options and returns `unsupportedOptions`; Front does not display them.

Evidence:

```text
backend/app/services/config_builder.py:55-63
backend/app/api/jobs.py:101-108
backend/app/schemas.py:96
front/src/features/job/useJobStream.ts:38-55
```

Impact: Users may think `variant_caller`, `min_depth`, `min_gq`, etc. changed analysis when they did not.

Suggested direction: Show an "ignored options" warning on JobPage and/or SubmitPage after job creation.

### Gap 5: Filtering and annotation exist in script but are disabled by web config

Problem: `main.sh` can run `08_filtering` and `10_annotation`, but Backend-generated `run_config.optional_steps.filtering/annotation` is always false.

Evidence:

```text
script/main.sh:4615-4619
backend/app/services/config_builder.py:237-240
```

Impact: Code exists, but current web full run cannot include those steps.

Suggested direction: Treat as "implemented but not connected", not as broken pipeline.

### Gap 6: Backend step detail and artifacts are not used by Front

Problem: `/steps`, `/artifacts`, `/download` exist but no Front call exists.

Evidence:

```text
backend/app/api/steps.py:46
backend/app/api/results.py:127
backend/app/api/results.py:155
front/src search: no fetch for /steps or /artifacts
```

Impact: Valuable metrics/downloads are invisible in the UI.

Suggested direction: Add step drawer/panel and downloads section before adding new analysis features.

### Gap 7: Mock differs from real Backend shape

Problem: Mock `/api/jobs/:id` returns only `jobId,status,progress,steps`; real Backend also returns `profileId`, `logTail`, `runMode`, `pipelineStatus`, `currentStep`, `unsupportedOptions`, timestamps, error.

Evidence:

```text
front/src/mocks/handlers.ts:90-94
backend/app/schemas.py:79-96
```

Impact: Frontend can pass in mock mode while missing fields used in real integration.

Suggested direction: Update mock after real result UI is connected.

## 11. Priority

### P0 - must fix first

None found.

Reason: In this static review, the inspected code paths show a coherent submit -> backend -> worker -> main.sh contract, and did not identify an obvious P0 blocker that would block commit/deploy on code structure alone. This is not a claim that runtime startup, security behavior, or real pipeline execution have been dynamically verified.

### P1 - high impact for demonstration

1. ResultsPage not connected to `/api/jobs/{id}/results`.
2. Artifact list/download UI missing.
3. Step Detail API missing from Front timeline interaction.
4. Unsupported options not shown to the user.
5. ResultsPage `profileId` acquisition broken on direct navigation/result click.

### P2 - later improvements

1. Enable filtering/annotation through web options after defining UI contract.
2. Replace placeholder/mismatched result-view endpoint comments.
3. Improve mock response fidelity.
4. Optimize `pipeline.log` tail from full-file read to seek-tail if large WES logs become a problem.
5. Add SSE only after polling UX is complete.

## 12. Recommended Next 5 Tasks

### 1. Connect ResultsPage to real results API

Task: Fetch `/api/jobs/{jobId}` and `/api/jobs/{jobId}/results`, then render summary/precheck/full result states.
Why needed now: Backend already exposes result data, but users cannot see it.
Related files: `front/src/pages/ResultsPage.tsx`, `backend/app/api/results.py`, `backend/app/schemas.py`.
Done when: ResultsPage shows precheck/full summary, coverage summary when present, and 409 "not ready" as a waiting state.
Expected user change: After a run, users see actual summary instead of placeholder.
Preceding work: Decide minimal result cards and loading/error state.

### 2. Add artifact/download panel

Task: Fetch `/api/jobs/{jobId}/artifacts` and expose download links for downloadable artifacts.
Why needed now: The pipeline's concrete outputs are already registered and safely downloadable.
Related files: `front/src/pages/ResultsPage.tsx`, `backend/app/api/results.py`, `backend/app/services/artifact_reader.py`.
Done when: Users can download raw VCF, gVCF, coverage metrics, methods/provenance when available.
Expected user change: Users can retrieve real files without browsing the server filesystem.
Preceding work: Design a simple table grouped by step/kind.

### 3. Add Step Detail UI from the timeline

Task: Clicking a step calls `/api/jobs/{jobId}/steps/{stepId}` and opens status/metrics/artifacts/warnings/failures.
Why needed now: This is the best way to expose `mapped_pct`, coverage metrics, failures and step artifacts while a run is still in progress.
Related files: `front/src/features/job/StepTimeline.tsx`, `front/src/pages/JobPage.tsx`, `backend/app/api/steps.py`.
Done when: Running/completed/failed steps show detail without waiting for final results.
Expected user change: Users understand where a run is stuck and what each step produced.
Preceding work: Define compact step detail component.

### 4. Display unsupported options

Task: Include `unsupportedOptions` in Front job state type and render a warning.
Why needed now: Current UI shows options that Backend intentionally ignores.
Related files: `front/src/features/job/useJobStream.ts`, `front/src/pages/JobPage.tsx`, `backend/app/services/config_builder.py`.
Done when: Jobs clearly show option keys that are actually returned in `unsupportedOptions`. `run_acmg` should be shown only when the Backend reports it as unsupported for that job, because it is a conditional option controlled by InterVar server capability.
Expected user change: Users stop assuming unimplemented options affected analysis.
Preceding work: Add type fields matching `JobStateResponse`.

### 5. Clarify web-supported option set

Task: Disable or label options not passed to `main.sh`; keep `capture_kit_id`, `assembly`, and conditional `run_acmg` as supported.
Why needed now: Prevents misleading scientific/clinical interpretation.
Related files: `front/src/features/analysis-profile/registry.ts`, `backend/app/services/config_builder.py`.
Done when: Every visible option is either applied or explicitly marked "not yet connected".
Expected user change: Submit screen matches real analysis behavior.
Preceding work: Product decision on whether to hide or annotate unsupported fields.

## 13. What NOT to Build Yet

Do not introduce Celery, Kafka, event bus, CQRS, a repository framework, or microservices. The current single-worker model intentionally limits this Backend process to one pipeline execution at a time, which is sufficient for the current prototype.

Do not build a broad clinical-grade interpretation UI before raw result exposure works. First show run summary, coverage, variants, artifacts, and step diagnostics.

Do not add multi-sample cohort/joint calling before the current one-sample run is fully visible end-to-end.

Do not build SSE before polling-based result/step/artifact screens are complete. The current 404 fallback is deliberate and stable.

Do not enable filtering/annotation from the web until the user-facing option names and actual `main.sh` config fields are defined together.

## 14. Beginner-Friendly Explanation

### 지금 이 WES 웹 프로젝트에서 사용자가 파일을 올린 뒤 내부에서 무엇이 일어나는가?

사용자가 브라우저에서 FASTQ R1/R2 파일을 올리면, Frontend는 파일을 작은 chunk로 나눠 Backend에 업로드한다. Backend는 업로드된 파일을 서버 내부 token으로 관리하고, 브라우저에는 실제 서버 경로를 알려주지 않는다.

사용자가 분석 시작을 누르면 Frontend는 `profileId`, `captureKitId`, 분석 option, sample의 R1/R2 token을 `/api/jobs`로 보낸다. Backend는 한 sample인지, R1/R2가 모두 있는지, capture kit이 등록되고 confirmed 상태인지, assembly가 서버 reference와 맞는지 확인한다.

그 다음 Backend는 `samplesheet.csv`와 `run_config.json`을 만들고 SQLite에 job row를 저장한다. 이 시점에서 HTTP 요청은 끝나고, 실제 WES 실행은 background worker가 맡는다.

Worker는 `bash script/main.sh --config ...`를 실행한다. `main.sh`는 입력 검증, QC, 전처리, 정렬, BAM 처리, coverage QC, variant calling, finalization 순서로 진행한다. 각 단계가 끝날 때마다 상태 JSON, metric JSON, artifact JSON을 쓴다.

JobPage는 3초마다 `/api/jobs/{id}`를 polling해서 지금 어떤 단계인지, 몇 퍼센트인지, 어떤 warning/failure message가 있는지 보여준다. 여기까지는 연결되어 있다.

하지만 결과 화면은 아직 완전히 연결되지 않았다. Backend는 `/api/jobs/{id}/results`와 `/api/jobs/{id}/artifacts`를 제공하지만, Frontend ResultsPage는 아직 그 API를 호출하지 않고 placeholder만 보여준다. 그래서 현재 프로젝트의 다음 핵심 작업은 "pipeline을 더 많이 만드는 것"보다 "이미 만들어진 결과를 웹에서 보이게 연결하는 것"이다.
