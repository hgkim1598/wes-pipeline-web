"""FastAPI application.

Run it from the repository root:

    backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8000
    (Linux: backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000)

The dev frontend reaches it through the Vite /api proxy, so no CORS is needed
for the normal path; the permissive localhost origins below only exist so the
built bundle can be served from somewhere else during debugging.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .api import jobs, results, steps, uploads
from .services import worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    db.connect()
    # Re-attach or close out anything a previous process left mid-flight before
    # the worker starts consuming new work.
    worker.recover_orphans()
    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="variant-pipeline-lab backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads.router)
app.include_router(jobs.router)
# Separate router, same /api/jobs prefix: the result endpoints are additive and
# jobs.py is left exactly as it was.
app.include_router(results.router)
# Same again for the per-step detail view; see api/steps.py for why it is not
# folded into the polled job endpoint.
app.include_router(steps.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Liveness plus the facts that most often explain a failed run.

    `pipelineScript` and `referenceConfigured` are here so a misconfigured
    server is obvious before anyone uploads 12 GB of FASTQ.
    """
    return {
        "status": "ok",
        "runMode": config.RUN_MODE,
        "pipelineScript": str(config.PIPELINE_SH),
        "pipelineScriptPresent": config.PIPELINE_SH.is_file(),
        "captureKitRegistryPresent": config.CAPTURE_KIT_REGISTRY.is_file(),
        "referenceConfigured": bool(config.REFERENCE_FASTA and config.CONTIG_STYLE),
    }
