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
from .api import explanations, jobs, results, steps, synthesis, uploads
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
# And again for the deterministic explanation. It is the only endpoint that
# answers for a run /results cannot describe -- one that failed before
# finalization -- so it is not folded into results.py.
app.include_router(explanations.router)
# Model-backed synthesis. Separate from explanations.py because it is the one
# route that consumes the operator's Claude subscription usage: it is POST-only
# and is never reached by the three-second polling that Run Detail runs.
app.include_router(synthesis.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Liveness plus the facts that most often explain a failed run.

    `pipelineScript` and `referenceConfigured` are here so a misconfigured
    server is obvious before anyone uploads 12 GB of FASTQ.

    `pipelineScript` is relative to the repository root. The absolute path
    named the server's directory layout (a deploy root, a user's home) to
    anyone who can reach this unauthenticated route.

    What the operator did read from that path is which release is serving
    (docs/DEPLOYMENT.md: `releases/<date>_<seq>_<commit>`). `release` keeps
    exactly that: the name of the checkout directory, which `ROOT` resolves
    through the `current` symlink. On a development checkout it is simply the
    repository folder's name.
    """
    return {
        "status": "ok",
        "runMode": config.RUN_MODE,
        "release": config.ROOT.name,
        "pipelineScript": config.PIPELINE_SH.relative_to(config.ROOT).as_posix(),
        "pipelineScriptPresent": config.PIPELINE_SH.is_file(),
        "captureKitRegistryPresent": config.CAPTURE_KIT_REGISTRY.is_file(),
        "referenceConfigured": bool(config.REFERENCE_FASTA and config.CONTIG_STYLE),
    }
