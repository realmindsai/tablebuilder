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
    else:
        session_id = db.create_chat_session(
            user_id=user["id"], messages_json="[]"
        )
        session = db.get_chat_session(session_id)
        history = []

    result = resolver.resolve(body.message, conversation_history=history)

    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": json.dumps(result)})

    resolved_json = None
    if "dataset" in result and "rows" in result:
        resolved_json = json.dumps({
            "dataset": result["dataset"],
            "rows": result["rows"],
            "cols": result.get("cols", []),
            "wafers": result.get("wafers", []),
        })

    db.update_chat_session(
        session["id"],
        messages_json=json.dumps(history),
        resolved_request_json=resolved_json,
    )

    return {
        "session_id": session["id"],
        "response": result,
    }


@router.post("/chat/confirm")
async def confirm_chat(
    body: ChatConfirm, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    session = db.get_chat_session(body.session_id)
    if session is None or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if not session["resolved_request_json"]:
        raise HTTPException(
            status_code=400, detail="No resolved request to confirm"
        )

    request_data = json.loads(session["resolved_request_json"])
    request_json = json.dumps(request_data)

    job_id = db.create_job(user_id=user["id"], request_json=request_json)
    db.link_chat_to_job(session["id"], job_id)

    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/jobs/{job_id}",
    }
