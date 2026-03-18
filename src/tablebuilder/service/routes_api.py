# ABOUTME: REST API routes for auth, jobs, dictionary search, and datasets.
# ABOUTME: Handles job submission (202 Accepted), polling, and result download.

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from tablebuilder.browser import LoginError, TableBuilderSession
from tablebuilder.config import Config
from tablebuilder.service.auth import (
    decrypt_credentials,
    encrypt_credentials,
    generate_api_key,
    hash_api_key,
)
from tablebuilder.service.db import ServiceDB

router = APIRouter(prefix="/api")


class RegisterRequest(BaseModel):
    abs_user_id: str
    abs_password: str


class JobRequest(BaseModel):
    dataset: str
    rows: list[str]
    cols: list[str] = []
    wafers: list[str] = []
    timeout_seconds: int = 600

    @field_validator("rows")
    @classmethod
    def rows_not_empty(cls, v):
        if not v:
            raise ValueError("rows must contain at least one variable")
        return v


async def get_current_user(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    api_key = authorization.removeprefix("Bearer ")
    key_hash = hash_api_key(api_key)
    db: ServiceDB = request.app.state.db
    user = db.get_user_by_api_key_hash(key_hash)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    db.touch_user(user["id"])
    return user


@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    db: ServiceDB = request.app.state.db
    encryption_key: str = request.app.state.encryption_key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    encrypted_creds = encrypt_credentials(
        encryption_key, body.abs_user_id, body.abs_password
    )
    db.create_user(api_key_hash=key_hash, abs_credentials_encrypted=encrypted_creds)
    return {"api_key": api_key}


@router.post("/auth/verify")
async def verify_credentials(
    request: Request, user: dict = Depends(get_current_user)
):
    """Test stored credentials by attempting an ABS login."""
    db: ServiceDB = request.app.state.db
    encryption_key: str = request.app.state.encryption_key
    abs_user, abs_pass = decrypt_credentials(
        encryption_key, user["abs_credentials_encrypted"]
    )
    config = Config(user_id=abs_user, password=abs_pass)
    try:
        with TableBuilderSession(config, headless=True) as page:
            pass
        return {"status": "valid", "message": "Credentials verified successfully"}
    except LoginError as e:
        raise HTTPException(status_code=401, detail=f"Credential verification failed: {e}")


@router.delete("/auth/credentials")
async def delete_credentials(
    request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    db.delete_user(user["id"])
    return {"status": "deleted"}


@router.post("/jobs", status_code=202)
async def submit_job(
    body: JobRequest, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    request_json = json.dumps({
        "dataset": body.dataset,
        "rows": body.rows,
        "cols": body.cols,
        "wafers": body.wafers,
    })
    job_id = db.create_job(
        user_id=user["id"],
        request_json=request_json,
        timeout_seconds=body.timeout_seconds,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/jobs/{job_id}",
    }


@router.get("/jobs")
async def list_jobs(request: Request, user: dict = Depends(get_current_user)):
    db: ServiceDB = request.app.state.db
    return db.list_user_jobs(user["id"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user: dict = Depends(get_current_user)):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    result = {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
    }
    if job["status"] == "completed":
        result["result_url"] = f"/api/jobs/{job_id}/download"
    if job["status"] == "failed":
        result["error_message"] = job["error_message"]
    return result


@router.get("/jobs/{job_id}/download")
async def download_job(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail={"error": "Job not yet completed", "status": job["status"]},
        )
    result_path = Path(job["result_path"])
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(result_path, media_type="text/csv", filename="tablebuilder_result.csv")


@router.get("/jobs/{job_id}/events")
async def get_job_events(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return db.get_events(job_id)


@router.get("/jobs/{job_id}/debug")
async def get_job_debug(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "error_message": job["error_message"],
        "error_detail": job["error_detail"],
        "page_url": job["page_url"],
        "page_html_path": job["page_html_path"],
        "screenshot_path": job["screenshot_path"],
        "events": db.get_events(job_id),
    }


@router.get("/search")
async def search_dictionary(q: str, limit: int = 20):
    from tablebuilder.dictionary_db import search, DEFAULT_DB_PATH
    if not DEFAULT_DB_PATH.exists():
        return []
    return search(DEFAULT_DB_PATH, q, limit=limit)


@router.get("/datasets")
async def list_datasets():
    from tablebuilder.dictionary_db import DEFAULT_DB_PATH
    import sqlite3
    if not DEFAULT_DB_PATH.exists():
        return []
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name, summary FROM datasets ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/datasets/{name}/variables")
async def get_dataset_variables(name: str):
    from tablebuilder.dictionary_db import get_dataset, DEFAULT_DB_PATH
    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Dictionary database not found")
    result = get_dataset(DEFAULT_DB_PATH, name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
    return result
