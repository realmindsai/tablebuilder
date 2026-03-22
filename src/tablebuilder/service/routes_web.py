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


def _get_valid_api_key(request: Request) -> str | None:
    """Get API key from cookie, but only if the user still exists in the DB."""
    api_key = request.cookies.get("tb_api_key")
    if not api_key:
        return None
    key_hash = hash_api_key(api_key)
    db = request.app.state.db
    user = db.get_user_by_api_key_hash(key_hash)
    if user is None:
        return None
    return api_key


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    api_key = _get_valid_api_key(request)
    response = templates.TemplateResponse("chat.html", {
        "request": request,
        "api_key": api_key,
    })
    # Clear stale cookie if user no longer exists
    if request.cookies.get("tb_api_key") and not api_key:
        response.delete_cookie("tb_api_key")
    return response


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

    from fastapi.responses import RedirectResponse
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("tb_api_key", api_key, httponly=True, max_age=86400 * 365)
    return response


@router.post("/web/chat", response_class=HTMLResponse)
async def web_chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(""),
):
    api_key = _get_valid_api_key(request)
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

    # Build cart context
    proposals = db.get_proposals(session_id)
    cart_context = ""
    if proposals:
        lines = []
        for p in proposals:
            status = "CHECKED" if p["status"] == "checked" else "unchecked"
            lines.append(f"- [{status}] {p['dataset']}: rows={p.get('rows', [])}")
        cart_context = "\n".join(lines)

    db.add_session_event(session_id, "user_message", message)

    result = resolver.resolve(
        message,
        conversation_history=history,
        session_id=session_id,
        db=db,
        cart_context=cart_context,
    )

    # Persist proposals
    for payload in result.get("display_payloads", []):
        if payload["type"] == "proposal":
            db.add_proposal(session_id, payload["data"])
            db.add_session_event(
                session_id, "proposal_created",
                f"Proposed: {payload['data']['dataset']}",
                metadata_json=json.dumps(payload["data"]),
            )

    text = result.get("text", "")
    db.add_session_event(session_id, "assistant_message", text)
    db.update_chat_session(session_id, json.dumps(result.get("messages", [])))

    # Build response HTML
    html = f'<div class="chat-message user"><div class="chat-bubble">{message}</div></div>'

    # Render choice buttons inline if present
    for payload in result.get("display_payloads", []):
        if payload["type"] == "choices":
            choices_html = _render_choices(payload["data"], session_id)
            text += choices_html

    html += f'<div class="chat-message assistant"><div class="chat-bubble">{text}</div></div>'

    # Set session_id for subsequent messages
    html += f'<script>document.getElementById("session_id").value = "{session_id}";</script>'

    # OOB swap for cart if proposals changed
    all_proposals = db.get_proposals(session_id)
    if all_proposals:
        cart_inner = _render_cart_contents(all_proposals, session_id)
        html += f'<div id="cart-items" hx-swap-oob="innerHTML:#cart-items">{cart_inner}</div>'

    # Ensure HTMX processes OOB-swapped cart content
    html += '<script>setTimeout(function(){htmx.process(document.getElementById("cart-items"))},100);</script>'

    return HTMLResponse(html)


@router.post("/web/confirm", response_class=HTMLResponse)
async def web_confirm(request: Request, session_id: str = Form(...)):
    api_key = _get_valid_api_key(request)
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


@router.post("/web/cart/toggle/{proposal_id}", response_class=HTMLResponse)
async def web_cart_toggle(
    proposal_id: str,
    request: Request,
    session_id: str = Form(...),
):
    api_key = _get_valid_api_key(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired.</p>", status_code=401)

    session = db.get_chat_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return HTMLResponse("<p>Session not found.</p>", status_code=404)

    proposals = db.get_proposals(session_id)
    target = None
    for p in proposals:
        if p["id"] == proposal_id:
            target = p
            break

    if target is None:
        return HTMLResponse("<p>Proposal not found.</p>", status_code=404)

    new_status = "unchecked" if target["status"] == "checked" else "checked"
    db.update_proposal_status(session_id, proposal_id, new_status)
    db.add_session_event(
        session_id, "proposal_toggled",
        f"{proposal_id} -> {new_status}",
    )

    target["status"] = new_status
    return HTMLResponse(_render_cart_card(target, session_id))


@router.post("/web/cart/fetch", response_class=HTMLResponse)
async def web_cart_fetch(
    request: Request,
    session_id: str = Form(...),
):
    api_key = _get_valid_api_key(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired.</p>", status_code=401)

    session = db.get_chat_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return HTMLResponse("<p>Session not found.</p>", status_code=404)

    proposals = db.get_proposals(session_id)
    checked = [p for p in proposals if p.get("status") == "checked"]
    if not checked:
        return HTMLResponse("<p>No proposals selected.</p>", status_code=400)

    job_ids = []
    for proposal in checked:
        request_json = json.dumps({
            "dataset": proposal["dataset"],
            "rows": proposal.get("rows", []),
            "cols": proposal.get("cols", []),
            "wafers": proposal.get("wafers", []),
        })
        job_id = db.create_job(user_id=user["id"], request_json=request_json)
        db.update_proposal_status(session_id, proposal["id"], "confirmed")
        job_ids.append(job_id)

    db.add_session_event(
        session_id, "jobs_queued",
        f"Queued {len(job_ids)} job(s)",
        metadata_json=json.dumps(job_ids),
    )

    proposals = db.get_proposals(session_id)
    cart_html = _render_cart_contents(proposals, session_id)
    return HTMLResponse(cart_html)


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
            f'<a href="/web/download/{job_id}">Download CSV</a>'
        )
    elif status == "failed":
        return HTMLResponse(
            f'<span class="status-failed">Failed: {job["error_message"]}</span> '
            f'<a href="/jobs/{job_id}">View details</a>'
        )
    return HTMLResponse(f'<span class="status-{status}">{progress}</span>')


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    api_key = _get_valid_api_key(request)
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
    api_key = _get_valid_api_key(request)
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


@router.get("/web/download/{job_id}")
async def web_download(job_id: str, request: Request):
    db = request.app.state.db
    job = db.get_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    if job["status"] != "completed" or not job.get("result_path"):
        return HTMLResponse("Job not ready for download", status_code=400)

    result_path = Path(job["result_path"])
    if not result_path.exists():
        return HTMLResponse("Result file not found", status_code=404)

    return FileResponse(
        result_path,
        media_type="text/csv",
        filename=f"tablebuilder_{job_id[:8]}.csv",
    )


@router.get("/web/screenshot/{job_id}/{filename}")
async def serve_screenshot(job_id: str, filename: str, request: Request):
    results_dir = request.app.state.results_dir
    path = results_dir / job_id / "screenshots" / filename
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path, media_type="image/png")


def _render_cart_card(proposal: dict, session_id: str) -> str:
    """Render a single proposal card HTML."""
    p = proposal
    checked = p["status"] == "checked"
    confirmed = p["status"] == "confirmed"
    opacity = "1" if checked or confirmed else "0.5"
    check_mark = "checked" if checked else ""
    disabled = "disabled" if confirmed else ""
    status_label = ""
    if confirmed:
        job_id = p.get("job_id", "")
        status_label = f' <a href="/jobs/{job_id}">Queued</a>'

    rows = ", ".join(p.get("rows", []))
    cols = ", ".join(p.get("cols", []))
    wafers = ", ".join(p.get("wafers", []))
    axes = f"Rows: {rows}" if rows else ""
    if cols:
        axes += f" | Cols: {cols}"
    if wafers:
        axes += f" | Wafers: {wafers}"

    return f"""<div id="cart-card-{p['id']}" style="opacity: {opacity}; padding: 0.5rem; border: 1px solid var(--pico-muted-border-color); border-radius: 0.5rem; margin-bottom: 0.5rem;">
        <label style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
            <input type="checkbox" {check_mark} {disabled}
                hx-post="/web/cart/toggle/{p['id']}"
                hx-target="#cart-card-{p['id']}"
                hx-swap="outerHTML"
                hx-include="[name='session_id']"
                name="session_id" value="{session_id}">
            <strong>{p['dataset']}</strong>{status_label}
        </label>
        <small style="display: block; margin-left: 1.5rem;">{axes}</small>
        <small style="display: block; margin-left: 1.5rem;">Match: {p.get('match_confidence', '?')}% | Clarity: {p.get('clarity_confidence', '?')}%</small>
        <small style="display: block; margin-left: 1.5rem; color: var(--pico-muted-color);">{p.get('rationale', '')}</small>
    </div>"""


def _render_cart_contents(proposals: list[dict], session_id: str) -> str:
    """Render the inner content of the cart (no wrapper div)."""
    if not proposals:
        return '<p style="color: var(--pico-muted-color);">No proposals yet. Start chatting to discover datasets.</p>'

    cards = "".join(_render_cart_card(p, session_id) for p in proposals)
    has_checked = any(p["status"] == "checked" for p in proposals)
    fetch_btn = ""
    if has_checked:
        fetch_btn = f"""<form hx-post="/web/cart/fetch" hx-target="#cart-items" hx-swap="innerHTML">
            <input type="hidden" name="session_id" value="{session_id}">
            <button type="submit" style="width: 100%;">Fetch Selected</button>
        </form>"""

    return f'{cards}{fetch_btn}'


def _render_choices(choices_data: dict, session_id: str) -> str:
    """Render multiple-choice buttons for inline chat display."""
    options = choices_data["options"]
    buttons = ""
    for opt in options:
        label = opt["label"]
        desc = opt.get("description", "")
        title_attr = f' title="{desc}"' if desc else ""
        buttons += f"""<button type="submit" name="message" value="{label}"{title_attr}
            style="margin: 0.25rem;" class="outline">{label}</button>"""

    return f"""<div style="margin-top: 0.5rem;">
        <form hx-post="/web/chat" hx-target="#chat-messages" hx-swap="beforeend">
            <input type="hidden" name="session_id" value="{session_id}">
            {buttons}
        </form>
    </div>"""
