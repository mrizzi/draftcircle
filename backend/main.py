import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from backend.git_store import GitStore
from backend.models import ParticipantInput, SectionStatus, SessionStatus, User
from backend.plugin_loader import list_plugins, load_plugin, validate_plugin_config
from backend.session_manager import SessionManager
from backend.template_loader import TemplateLoader
from backend.user_registry import UserRegistryManager
from backend.ws_manager import WebSocketManager


class CreateSessionRequest(BaseModel):
    template: str
    coordinator: str
    participants: list[ParticipantInput] = Field(default_factory=list)
    seed: dict[str, Any] | None = None
    seed_text: str | None = None


class AddCommentRequest(BaseModel):
    section_id: str
    author: str = Field(min_length=1)
    text: str = Field(min_length=1)


class UserIdRequest(BaseModel):
    user_id: str


class AssignRequest(BaseModel):
    user_id: str


class PublishRequest(BaseModel):
    plugin: str
    config: dict[str, Any]


logger = logging.getLogger(__name__)


def create_app(data_repo_path: str | None = None) -> FastAPI:
    repo_path = data_repo_path or os.getenv("DRAFTCIRCLE_DATA_REPO")
    if not repo_path:
        raise ValueError(
            "data_repo_path not provided and DRAFTCIRCLE_DATA_REPO env var not set"
        )

    repo_path = Path(repo_path)
    git = GitStore(repo_path)
    templates = TemplateLoader(repo_path)
    users = UserRegistryManager(git)
    sessions = SessionManager(git, templates)
    ws_manager = WebSocketManager()

    gitignore = repo_path / ".gitignore"
    if not gitignore.exists() or ".claude-sdk/" not in gitignore.read_text():
        with open(gitignore, "a") as f:
            f.write("\n.claude-sdk/\n")

    ai = None
    try:
        from backend.ai_orchestrator import AIOrchestrator

        ai = AIOrchestrator(git=git)
    except Exception:
        logger.warning("AI unavailable: Agent SDK init failed", exc_info=True)

    app = FastAPI()
    app.state.sessions = sessions
    app.state.git = git

    @app.get("/api/templates")
    def list_templates():
        return templates.list_templates()

    @app.get("/api/templates/{slug}")
    def get_template(slug: str):
        template = templates.get_template(slug)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return template

    @app.get("/api/plugins")
    def get_plugins():
        custom_dir = repo_path / "plugins"
        names = list_plugins(
            custom_plugins_dir=custom_dir if custom_dir.is_dir() else None
        )
        result = []
        for name in names:
            try:
                plugin = load_plugin(
                    name,
                    custom_plugins_dir=custom_dir if custom_dir.is_dir() else None,
                )
                result.append(
                    {
                        "name": name,
                        "download": plugin.download,
                        "config_schema": plugin.config_schema,
                    }
                )
            except ValueError:
                pass
        return result

    @app.get("/api/users")
    def list_users():
        return users.list_users()

    @app.post("/api/users", status_code=201)
    def add_user(user: User):
        try:
            users.add_user(user)
            return user
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    @app.post("/api/sessions")
    async def create_session(req: CreateSessionRequest):

        try:
            session = sessions.create_session(
                template_slug=req.template,
                coordinator=req.coordinator,
                participants=req.participants,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if req.seed_text and ai:
            template = templates.get_template(req.template)

            async def draft_in_background():
                try:
                    sessions.begin_drafting(session.id)
                    await ws_manager.broadcast(
                        session.id,
                        {"type": "drafts_started", "session_id": session.id},
                    )

                    agent_session_id = None
                    async for event in ai.generate_drafts(
                        draftcircle_session_id=session.id,
                        agent_session_id=session.agent_session_id,
                        template=template,
                        seed_content=req.seed_text,
                    ):
                        if event["type"] == "ai_activity":
                            await ws_manager.broadcast(session.id, event)
                        elif event["type"] == "section_drafted":
                            meta = session.section_meta.get(event["section_id"])
                            if meta:
                                section_path = (
                                    f"sessions/{session.id}/sections/{meta.filename}.md"
                                )
                                git.commit(
                                    f"draft: AI generated "
                                    f"{event['section_id']} for {session.id}",
                                    {section_path: event["content"]},
                                )
                                sessions.set_section_status(
                                    session.id,
                                    event["section_id"],
                                    SectionStatus.DRAFT,
                                )
                                await ws_manager.broadcast(
                                    session.id,
                                    {
                                        "type": "section_draft_ready",
                                        "section_id": event["section_id"],
                                        "status": "draft",
                                    },
                                )
                        elif event["type"] == "drafts_complete":
                            agent_session_id = event.get("session_id")

                    if agent_session_id:
                        sessions.set_agent_session_id(session.id, agent_session_id)
                    await ws_manager.broadcast(
                        session.id,
                        {
                            "type": "drafts_complete",
                            "session_id": session.id,
                        },
                    )
                except Exception:
                    logger.warning(
                        "AI draft generation failed for %s",
                        session.id,
                        exc_info=True,
                    )
                    sessions.recover_drafting(session.id)
                    await ws_manager.broadcast(
                        session.id,
                        {
                            "type": "drafts_failed",
                            "session_id": session.id,
                            "message": "Draft generation encountered an error.",
                        },
                    )

            task = asyncio.create_task(draft_in_background())
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )

        result = sessions.get_session(session.id)
        return JSONResponse(result.model_dump(mode="json"), status_code=201)

    def _strip_tokens(session_data: dict) -> dict:
        for p in session_data.get("participants", []):
            p.pop("token", None)
        return session_data

    @app.get("/api/sessions")
    def list_sessions():
        return [
            _strip_tokens(s.model_dump(mode="json")) for s in sessions.list_sessions()
        ]

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, token: str | None = None):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        result = session.model_dump(mode="json")
        result["progress"] = sessions.get_progress(session_id)
        result["ready_to_publish"] = sessions.is_ready_to_publish(session_id)

        is_coordinator = False
        if token:
            for p in session.participants:
                if p.token == token:
                    result["current_user_id"] = p.user_id
                    if session.coordinator == p.user_id:
                        is_coordinator = True
                    break

        if not is_coordinator:
            _strip_tokens(result)

        return result

    @app.post("/api/sessions/{session_id}/comments", status_code=201)
    async def add_comment(session_id: str, req: AddCommentRequest):
        if req.author.lower() == "ai":
            raise HTTPException(status_code=400, detail="'ai' is a reserved author")
        try:
            comment = sessions.add_comment(
                session_id=session_id,
                section_id=req.section_id,
                author=req.author,
                text=req.text,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {
                "type": "comment_added",
                "comment": comment.model_dump(mode="json"),
                "section_id": req.section_id,
            },
        )

        if ai and req.author != "ai":
            try:
                from backend.ai_orchestrator import ProposalResult, ReplyResult

                session = sessions.get_session(session_id)
                template = templates.get_template(session.template)
                section_def = next(
                    (s for s in template.sections if s.id == req.section_id),
                    None,
                )
                meta = session.section_meta[req.section_id]
                current_draft = (
                    git.read_file(f"sessions/{session_id}/sections/{meta.filename}.md")
                    or ""
                )
                thread = [
                    {"author": c.author, "text": c.text}
                    for c in sessions.get_comments(session_id, req.section_id)
                ]

                async for event in ai.process_comment(
                    session_id=session_id,
                    section_id=req.section_id,
                    section_title=(
                        section_def.title if section_def else req.section_id
                    ),
                    section_guidance=(section_def.guidance if section_def else ""),
                    current_draft=current_draft,
                    comment_thread=thread[:-1],
                    new_comment_author=req.author,
                    new_comment_text=req.text,
                    system_prompt=template.ai_context,
                    agent_session_id=session.agent_session_id,
                ):
                    if event["type"] == "ai_activity":
                        await ws_manager.broadcast(session_id, event)
                    elif event["type"] == "ai_complete":
                        result = event["result"]
                        agent_session_id = event["session_id"]

                        if (
                            agent_session_id
                            and agent_session_id != session.agent_session_id
                        ):
                            sessions.set_agent_session_id(session_id, agent_session_id)

                        if isinstance(result, ProposalResult):
                            proposal = sessions.create_proposal(
                                session_id=session_id,
                                section_id=req.section_id,
                                triggered_by_comment=comment.id,
                                revised_text=result.revised_text,
                                summary=result.summary,
                            )
                            await ws_manager.broadcast(
                                session_id,
                                {
                                    "type": "proposal_created",
                                    "section_id": req.section_id,
                                    "proposal": proposal.model_dump(mode="json"),
                                },
                            )
                        elif isinstance(result, ReplyResult):
                            reply = sessions.add_comment(
                                session_id=session_id,
                                section_id=req.section_id,
                                author="ai",
                                text=result.text,
                            )
                            await ws_manager.broadcast(
                                session_id,
                                {
                                    "type": "comment_added",
                                    "section_id": req.section_id,
                                    "comment": reply.model_dump(mode="json"),
                                },
                            )
            except Exception:
                logger.warning(
                    "AI comment processing failed for %s",
                    session_id,
                    exc_info=True,
                )
                await ws_manager.broadcast(
                    session_id,
                    {
                        "type": "ai_activity",
                        "section_id": req.section_id,
                        "text": "AI processing encountered an error.",
                        "error": True,
                    },
                )
                try:
                    sessions.add_comment(
                        session_id,
                        req.section_id,
                        "ai",
                        "I encountered an error processing this comment. "
                        "Please try again.",
                    )
                except Exception:
                    pass

        return comment

    @app.get("/api/sessions/{session_id}/sections/{section_id}/comments")
    def get_comments(session_id: str, section_id: str):
        return sessions.get_comments(session_id, section_id)

    @app.get("/api/sessions/{session_id}/sections/{section_id}/proposals")
    def get_proposals(session_id: str, section_id: str):
        return sessions.get_proposals(session_id, section_id)

    @app.post("/api/sessions/{session_id}/proposals/{proposal_id}/accept")
    async def accept_proposal(session_id: str, proposal_id: str, req: UserIdRequest):
        try:
            section_id = sessions.accept_proposal(session_id, proposal_id, req.user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {
                "type": "proposal_accepted",
                "proposal_id": proposal_id,
                "section_id": section_id,
            },
        )
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/proposals/{proposal_id}/reject")
    async def reject_proposal(session_id: str, proposal_id: str, req: UserIdRequest):
        try:
            section_id = sessions.reject_proposal(session_id, proposal_id, req.user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {
                "type": "proposal_rejected",
                "proposal_id": proposal_id,
                "section_id": section_id,
            },
        )
        return {"status": "rejected"}

    @app.post("/api/sessions/{session_id}/sections/{section_id}/approve")
    async def approve_section(session_id: str, section_id: str, req: UserIdRequest):
        try:
            sessions.approve_section(session_id, section_id, req.user_id)
            await ws_manager.broadcast(
                session_id,
                {
                    "type": "section_approved",
                    "section_id": section_id,
                    "user_id": req.user_id,
                },
            )
            return {"status": "approved"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sessions/{session_id}/sections/{section_id}/reopen")
    async def reopen_section(session_id: str, section_id: str, req: UserIdRequest):
        try:
            sessions.reopen_section(session_id, section_id, req.user_id)
            await ws_manager.broadcast(
                session_id,
                {
                    "type": "section_reopened",
                    "section_id": section_id,
                    "user_id": req.user_id,
                },
            )
            return {"status": "reopened"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sessions/{session_id}/sections/{section_id}/skip")
    async def skip_section(session_id: str, section_id: str, req: UserIdRequest):
        try:
            sessions.skip_section(session_id, section_id, req.user_id)
            await ws_manager.broadcast(
                session_id,
                {
                    "type": "section_skipped",
                    "section_id": section_id,
                    "user_id": req.user_id,
                },
            )
            return {"status": "skipped"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/sessions/{session_id}/sections/{section_id}/assign")
    async def assign_section(session_id: str, section_id: str, req: AssignRequest):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if users.get_user(req.user_id) is None:
            raise HTTPException(
                status_code=400, detail=f"User '{req.user_id}' not found"
            )
        try:
            sessions.assign_section(session_id, section_id, req.user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {
                "type": "section_assigned",
                "section_id": section_id,
                "user_id": req.user_id,
            },
        )
        return {"status": "assigned"}

    @app.post("/api/sessions/{session_id}/publish")
    async def publish_session(session_id: str, req: PublishRequest):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status == SessionStatus.PUBLISHED:
            raise HTTPException(status_code=400, detail="Session already published")
        if not sessions.is_ready_to_publish(session_id):
            raise HTTPException(status_code=400, detail="Session not ready to publish")

        custom_dir = repo_path / "plugins"
        try:
            plugin = load_plugin(
                req.plugin,
                custom_plugins_dir=custom_dir if custom_dir.is_dir() else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        errors = validate_plugin_config(plugin.config_schema, req.config)
        if errors:
            raise HTTPException(status_code=422, detail=errors)

        approved_sections = sessions.get_approved_sections(session_id)
        assembled = plugin.assemble(approved_sections)
        output_ref = plugin.publish(assembled, req.config)

        if plugin.download:
            filename = req.config.get("filename", f"{session_id}.md")
            sessions.mark_published(session_id, filename)
            await ws_manager.broadcast(
                session_id,
                {"type": "session_published", "output_ref": filename},
            )
            return Response(
                content=output_ref,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

        sessions.mark_published(session_id, output_ref)
        await ws_manager.broadcast(
            session_id,
            {"type": "session_published", "output_ref": output_ref},
        )
        return {"status": "published", "output_ref": output_ref}

    @app.get("/api/sessions/{session_id}/history")
    def get_history(session_id: str):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = f"sessions/{session_id}"
        return git.log(session_dir)

    @app.get("/api/sessions/{session_id}/sections/{section_id}")
    def get_section_content(session_id: str, section_id: str):
        try:
            return sessions.get_section_content(session_id, section_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.websocket("/ws/sessions/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        token = websocket.query_params.get("token")
        session = sessions.get_session(session_id)
        if session is None:
            await websocket.close(code=4004, reason="Session not found")
            return

        user_id = None
        if token:
            for p in session.participants:
                if p.token == token:
                    user_id = p.user_id
                    break

        await websocket.accept()
        ws_manager.connect(session_id, websocket)

        await ws_manager.broadcast(
            session_id,
            {
                "type": "participant_joined",
                "user": {"user_id": user_id},
            },
        )

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(session_id, websocket)
            await ws_manager.broadcast(
                session_id,
                {
                    "type": "participant_left",
                    "user": {"user_id": user_id},
                },
            )

    frontend_dir = Path(__file__).parent.parent / "frontend"

    @app.get("/session/{session_id}")
    async def spa_session_route(session_id: str):
        return FileResponse(str(frontend_dir / "index.html"))

    if frontend_dir.exists():
        app.mount(
            "/", StaticFiles(directory=str(frontend_dir), html=True), name="static"
        )

    return app
