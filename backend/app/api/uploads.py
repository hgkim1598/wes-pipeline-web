"""Chunked upload endpoints.

The contract is fixed by front/src/features/upload/useChunkedUpload.ts:

  POST /api/uploads                 {filename,size,sampleId,slotId} -> {uploadId, chunkSize}
  GET  /api/uploads/{id}            -> {receivedChunks: number[]}
  PUT  /api/uploads/{id}/{index}    raw octet-stream body -> 2xx (204 here)
  POST /api/uploads/{id}/complete   -> {path}

`path` is named that way because the hook reads `path`, but the value returned is
an opaque token (upl_...). The browser never learns a server filesystem path, and
the token it hands back to POST /api/jobs is resolved through the database — a
client-supplied string is never treated as a path.
"""

from __future__ import annotations

import math
import re
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from .. import config, db
from ..schemas import (
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadStatusResponse,
)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD_ID_RE = re.compile(r"^upl_[0-9a-f]{24}$")
# Deliberately narrow: everything else in the name is replaced.
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")
MAX_CHUNKS = 100_000  # 100k * 8MiB = 800GiB, far beyond any real FASTQ


def sanitize_filename(raw: str) -> str:
    """Reduce a client-supplied name to a bare, safe basename.

    Path separators are stripped before anything else, so neither "../" nor
    "C:\\windows\\..." can survive. The result is only ever used as a leaf name
    inside a server-generated directory.
    """
    name = raw.replace("\\", "/").split("/")[-1].strip()
    name = SAFE_NAME_RE.sub("_", name)
    name = name.lstrip(".") or "upload"
    return name[:200]


def _accepted_extension(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in config.ALLOWED_FASTQ_SUFFIXES)


def _upload_dir(upload_id: str) -> Path:
    if not UPLOAD_ID_RE.fullmatch(upload_id):
        raise HTTPException(status_code=400, detail="malformed upload id")
    return config.UPLOAD_ROOT / upload_id


def _load(upload_id: str):
    if not UPLOAD_ID_RE.fullmatch(upload_id):
        raise HTTPException(status_code=400, detail="malformed upload id")
    row = db.query_one("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="unknown upload id")
    return row


@router.post("", response_model=UploadInitResponse)
@router.post("/", response_model=UploadInitResponse, include_in_schema=False)
def create_upload(payload: UploadInitRequest) -> UploadInitResponse:
    filename = sanitize_filename(payload.filename)
    if not _accepted_extension(filename):
        raise HTTPException(
            status_code=400,
            detail=(
                "only gzip-compressed FASTQ is accepted "
                f"({', '.join(config.ALLOWED_FASTQ_SUFFIXES)}). "
                "main.sh rejects uncompressed FASTQ in validate_samplesheet."
            ),
        )
    if payload.size is not None and payload.size <= 0:
        raise HTTPException(status_code=400, detail="file size must be greater than zero")

    upload_id = "upl_" + secrets.token_hex(12)
    chunk_dir = config.UPLOAD_ROOT / upload_id / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    db.execute(
        """INSERT INTO uploads
           (upload_id, original_filename, stored_filename, sample_id, slot_id,
            expected_size, chunk_dir, final_path, completed, created_at)
           VALUES (?,?,?,?,?,?,?,?,0,?)""",
        (
            upload_id,
            payload.filename,
            filename,
            payload.sampleId,
            payload.slotId,
            payload.size,
            str(chunk_dir),
            None,
            db.now_iso(),
        ),
    )
    return UploadInitResponse(uploadId=upload_id, chunkSize=config.CHUNK_SIZE)


@router.get("/{upload_id}", response_model=UploadStatusResponse)
def upload_status(upload_id: str) -> UploadStatusResponse:
    row = _load(upload_id)
    chunk_dir = Path(row["chunk_dir"])
    received: list[int] = []
    if chunk_dir.is_dir():
        for entry in chunk_dir.iterdir():
            if entry.is_file() and entry.name.isdigit():
                received.append(int(entry.name))
    return UploadStatusResponse(receivedChunks=sorted(received))


@router.put("/{upload_id}/{chunk_index}", status_code=204)
async def put_chunk(upload_id: str, chunk_index: int, request: Request) -> Response:
    row = _load(upload_id)
    if row["completed"]:
        raise HTTPException(status_code=409, detail="upload is already finalised")
    if chunk_index < 0 or chunk_index > MAX_CHUNKS:
        raise HTTPException(status_code=400, detail="chunk index out of range")

    chunk_dir = Path(row["chunk_dir"])
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Write to a temporary name first so an interrupted PUT never looks like a
    # received chunk to the resume path (GET /api/uploads/{id}).
    target = chunk_dir / str(chunk_index)
    staging = chunk_dir / f".{chunk_index}.part"
    written = 0
    try:
        with staging.open("wb") as fh:
            async for block in request.stream():
                if block:
                    fh.write(block)
                    written += len(block)
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    if written == 0:
        staging.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="empty chunk")
    staging.replace(target)
    return Response(status_code=204)


@router.post("/{upload_id}/complete", response_model=UploadCompleteResponse)
def complete_upload(upload_id: str) -> UploadCompleteResponse:
    row = _load(upload_id)
    upload_root = config.UPLOAD_ROOT / upload_id
    final_path = upload_root / row["stored_filename"]

    if row["completed"] and final_path.is_file():
        return UploadCompleteResponse(path=upload_id)

    chunk_dir = Path(row["chunk_dir"])
    indices = sorted(
        int(p.name) for p in chunk_dir.iterdir() if p.is_file() and p.name.isdigit()
    ) if chunk_dir.is_dir() else []
    if not indices:
        raise HTTPException(status_code=400, detail="no chunks were received")
    if indices != list(range(len(indices))):
        missing = sorted(set(range(indices[-1] + 1)) - set(indices))
        raise HTTPException(status_code=400, detail=f"missing chunks: {missing[:20]}")

    expected_size = row["expected_size"]
    if expected_size:
        expected_chunks = math.ceil(expected_size / config.CHUNK_SIZE)
        if len(indices) != expected_chunks:
            raise HTTPException(
                status_code=400,
                detail=f"expected {expected_chunks} chunks, received {len(indices)}",
            )

    staging = upload_root / ".assembling"
    with staging.open("wb") as out:
        for index in indices:
            with (chunk_dir / str(index)).open("rb") as part:
                shutil.copyfileobj(part, out, length=1024 * 1024)

    assembled = staging.stat().st_size
    if expected_size and assembled != expected_size:
        staging.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"assembled size {assembled} does not match declared size {expected_size}",
        )

    # main.sh checks the gzip magic itself in validate_samplesheet; catching it
    # here means the user finds out at upload time instead of at run time.
    with staging.open("rb") as fh:
        if fh.read(2) != b"\x1f\x8b":
            staging.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="assembled file is not gzip-compressed",
            )

    staging.replace(final_path)
    shutil.rmtree(chunk_dir, ignore_errors=True)

    db.execute(
        "UPDATE uploads SET final_path = ?, completed = 1 WHERE upload_id = ?",
        (str(final_path), upload_id),
    )
    # Opaque handle, not a path.
    return UploadCompleteResponse(path=upload_id)


def resolve_token(token: str) -> Path:
    """Map an upload token back to the real file. Raises HTTPException on abuse."""
    row = _load(token)
    if not row["completed"] or not row["final_path"]:
        raise HTTPException(status_code=400, detail=f"upload {token} was never completed")
    path = Path(row["final_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail=f"uploaded file for {token} is gone")
    return path
