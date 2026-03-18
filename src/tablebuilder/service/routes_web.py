# ABOUTME: Web UI routes serving HTML pages for chat and job management.
# ABOUTME: Uses Jinja2 templates with HTMX for dynamic updates.

import json
from pathlib import Path

from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from tablebuilder.service.auth import (
    encrypt_credentials,
    generate_api_key,
    hash_api_key,
)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_api_key_from_cookie(request: Request) -> str | None:
    return request.cookies.get("tb_api_key")


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    api_key = _get_api_key_from_cookie(request)
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "api_key": api_key,
    })


@router.post("/web/register", response_class=HTMLResponse)
async def web_register(
    request: Request,
    abs_user_id: str = Form(...),
    abs_password: str = Form(...),
):
    db = request.app.state.db
    encryption_key = request.app.state.encryption_key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    encrypted = encrypt_credentials(encryption_key, abs_user_id, abs_password)
    db.create_user(api_key_hash=key_hash, abs_credentials_encrypted=encrypted)

    response = HTMLResponse(
        '<p>Registered! Ask me for ABS data. For example: '
        '"population by remoteness area from the 2021 census"</p>'
    )
    response.set_cookie("tb_api_key", api_key, httponly=True, max_age=86400 * 365)
    return response


@router.post("/web/chat", response_class=HTMLResponse)
async def web_chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(""),
):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    resolver = request.app.state.chat_resolver
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired. Please register again.</p>", status_code=401)

    history = []
    if session_id:
        session = db.get_chat_session(session_id)
        if session and session["user_id"] == user["id"]:
            history = json.loads(session["messages_json"])
    else:
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")

    result = resolver.resolve(message, conversation_history=history)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": json.dumps(result)})

    resolved_json = None
    if "dataset" in result and "rows" in result:
        resolved_json = json.dumps({
            "dataset": result["dataset"],
            "rows": result["rows"],
            "cols": result.get("cols", []),
            "wafers": result.get("wafers", []),
        })

    db.update_chat_session(session_id, json.dumps(history), resolved_json)

    html = f'<div class="chat-message user"><div class="chat-bubble">{message}</div></div>'

    if "confirmation" in result:
        html += f"""<div class="chat-message assistant"><div class="chat-bubble">
            {result['confirmation']}
            <form hx-post="/web/confirm" hx-target="#chat-messages" hx-swap="beforeend">
                <input type="hidden" name="session_id" value="{session_id}">
                <button type="submit">Fetch this data</button>
            </form>
        </div></div>"""
    elif "clarification" in result:
        html += f'<div class="chat-message assistant"><div class="chat-bubble">{result["clarification"]}</div></div>'

    html += f'<script>document.getElementById("session_id").value = "{session_id}";</script>'
    return HTMLResponse(html)


@router.post("/web/confirm", response_class=HTMLResponse)
async def web_confirm(request: Request, session_id: str = Form(...)):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired.</p>", status_code=401)

    session = db.get_chat_session(session_id)
    if not session or not session["resolved_request_json"]:
        return HTMLResponse("<p>No request to confirm.</p>", status_code=400)

    job_id = db.create_job(
        user_id=user["id"],
        request_json=session["resolved_request_json"],
    )
    db.link_chat_to_job(session_id, job_id)

    return HTMLResponse(f"""<div class="chat-message assistant"><div class="chat-bubble">
        Job submitted! <a href="/jobs/{job_id}">Track progress</a>
        <div hx-get="/web/job-status/{job_id}" hx-trigger="every 10s" hx-swap="innerHTML">
            Status: queued
        </div>
    </div></div>""")


@router.get("/web/job-status/{job_id}", response_class=HTMLResponse)
async def web_job_status(job_id: str, request: Request):
    db = request.app.state.db
    job = db.get_job(job_id)
    if not job:
        return HTMLResponse("Job not found")

    status = job["status"]
    progress = job["progress"] or status
    if status == "completed":
        return HTMLResponse(
            f'<span class="status-completed">Completed!</span> '
            f'<a href="/api/jobs/{job_id}/download">Download CSV</a>'
        )
    elif status == "failed":
        return HTMLResponse(
            f'<span class="status-failed">Failed: {job["error_message"]}</span> '
            f'<a href="/jobs/{job_id}">View details</a>'
        )
    return HTMLResponse(f'<span class="status-{status}">{progress}</span>')


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    api_key = _get_api_key_from_cookie(request)
    jobs = []
    if api_key:
        db = request.app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        if user:
            raw_jobs = db.list_user_jobs(user["id"])
            for j in raw_jobs:
                req = json.loads(j.get("request_json", "{}"))
                j["dataset_name"] = req.get("dataset", "Unknown")
                j["duration"] = ""
                if j.get("started_at") and j.get("completed_at"):
                    j["duration"] = "completed"
                jobs = raw_jobs

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "api_key": api_key,
        "jobs": jobs,
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(job_id: str, request: Request):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return templates.TemplateResponse("jobs.html", {
            "request": request, "api_key": None, "jobs": [],
        })

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    job = db.get_job(job_id)
    if not job or job["user_id"] != user["id"]:
        return HTMLResponse("Job not found", status_code=404)

    req = json.loads(job.get("request_json", "{}"))
    job["dataset_name"] = req.get("dataset", "Unknown")

    events = db.get_events(job_id)
    screenshots = [
        e["screenshot_path"].split("/")[-1]
        for e in events
        if e.get("screenshot_path")
    ]

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "events": events,
        "screenshots": screenshots,
    })


@router.get("/web/screenshot/{job_id}/{filename}")
async def serve_screenshot(job_id: str, filename: str, request: Request):
    results_dir = request.app.state.results_dir
    path = results_dir / job_id / "screenshots" / filename
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path, media_type="image/png")
