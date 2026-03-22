# ABOUTME: Chat API routes for natural language data requests.
# ABOUTME: Manages multi-turn conversation sessions and job confirmation.

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from tablebuilder.service.routes_api import get_current_user

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    message: str
    session_id: str | None = None


class ChatConfirm(BaseModel):
    session_id: str


@router.post("/chat")
async def chat(
    body: ChatMessage, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    resolver = request.app.state.chat_resolver

    if body.session_id:
        session = db.get_chat_session(body.session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Chat session not found")
        history = json.loads(session["messages_json"])
        session_id = session["id"]
    else:
        session_id = db.create_chat_session(
            user_id=user["id"], messages_json="[]"
        )
        history = []

    # Build cart context for Claude
    proposals = db.get_proposals(session_id)
    cart_context = ""
    if proposals:
        lines = []
        for p in proposals:
            status = "CHECKED" if p["status"] == "checked" else "unchecked"
            lines.append(f"- [{status}] {p['dataset']}: rows={p.get('rows', [])}")
        cart_context = "\n".join(lines)

    # Log user message event
    db.add_session_event(session_id, "user_message", body.message)

    result = resolver.resolve(
        body.message,
        conversation_history=history,
        session_id=session_id,
        db=db,
        cart_context=cart_context,
    )

    # Persist any proposals from display payloads
    for payload in result.get("display_payloads", []):
        if payload["type"] == "proposal":
            db.add_proposal(session_id, payload["data"])
            db.add_session_event(
                session_id, "proposal_created",
                f"Proposed: {payload['data']['dataset']}",
                metadata_json=json.dumps(payload["data"]),
            )

    # Log assistant response
    db.add_session_event(session_id, "assistant_message", result.get("text", ""))

    # Persist conversation history (full Anthropic message format)
    db.update_chat_session(session_id, json.dumps(result.get("messages", [])))

    return {
        "session_id": session_id,
        "response": {
            "text": result.get("text", ""),
            "display_payloads": result.get("display_payloads", []),
        },
    }


@router.post("/chat/confirm")
async def confirm_chat(
    body: ChatConfirm, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    session = db.get_chat_session(body.session_id)
    if session is None or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Chat session not found")

    proposals = db.get_proposals(body.session_id)
    checked = [p for p in proposals if p.get("status") == "checked"]
    if not checked:
        raise HTTPException(status_code=400, detail="No checked proposals to confirm")

    jobs = []
    for proposal in checked:
        request_json = json.dumps({
            "dataset": proposal["dataset"],
            "rows": proposal.get("rows", []),
            "cols": proposal.get("cols", []),
            "wafers": proposal.get("wafers", []),
        })
        job_id = db.create_job(user_id=user["id"], request_json=request_json)
        db.update_proposal_status(body.session_id, proposal["id"], "confirmed")
        proposal["job_id"] = job_id
        jobs.append({"job_id": job_id, "dataset": proposal["dataset"]})

    db.add_session_event(
        body.session_id, "jobs_queued",
        f"Queued {len(jobs)} job(s)",
        metadata_json=json.dumps(jobs),
    )

    return {
        "session_id": body.session_id,
        "jobs": jobs,
        "status": "queued",
    }
