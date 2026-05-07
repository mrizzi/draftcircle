import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from typing import Any, Literal, TypedDict

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    StreamEvent,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from backend.git_session_store import GitSessionStore
from backend.git_store import GitStore
from backend.models import Template

logger = logging.getLogger(__name__)


@tool(
    name="write_section_draft",
    description="Write the initial draft for a document section",
    input_schema={
        "type": "object",
        "properties": {
            "section_id": {
                "type": "string",
                "description": "The section identifier",
            },
            "content": {
                "type": "string",
                "description": "The markdown content for this section",
            },
        },
        "required": ["section_id", "content"],
    },
)
async def write_section_draft(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


@tool(
    name="propose_revision",
    description="Propose a revision to the current section draft based on the comment",
    input_schema={
        "type": "object",
        "properties": {
            "revised_text": {
                "type": "string",
                "description": "The complete revised section draft",
            },
            "summary": {
                "type": "string",
                "description": "Brief explanation of what changed and why",
            },
        },
        "required": ["revised_text", "summary"],
    },
)
async def propose_revision(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


@tool(
    name="post_reply",
    description="Reply to the comment without changing the draft",
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The reply text",
            },
        },
        "required": ["text"],
    },
)
async def post_reply(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


DRAFT_SERVER = create_sdk_mcp_server(
    name="draftcircle",
    tools=[write_section_draft, propose_revision, post_reply],
)


@dataclass(frozen=True)
class ProposalResult:
    revised_text: str
    summary: str

    def __post_init__(self):
        if not self.revised_text:
            raise ValueError("revised_text must be non-empty")
        if not self.summary:
            raise ValueError("summary must be non-empty")


@dataclass(frozen=True)
class ReplyResult:
    text: str

    def __post_init__(self):
        if not self.text:
            raise ValueError("text must be non-empty")


class AiActivityEvent(TypedDict):
    type: Literal["ai_activity"]
    section_id: str | None
    text: str


class SectionDraftedEvent(TypedDict):
    type: Literal["section_drafted"]
    section_id: str
    content: str


class DraftsCompleteEvent(TypedDict):
    type: Literal["drafts_complete"]
    session_id: str | None


class AiCompleteEvent(TypedDict):
    type: Literal["ai_complete"]
    section_id: str
    result_type: Literal["proposal", "reply"]
    result: ProposalResult | ReplyResult
    session_id: str | None


DraftEvent = AiActivityEvent | SectionDraftedEvent | DraftsCompleteEvent
CommentEvent = AiActivityEvent | AiCompleteEvent


class AIOrchestrator:
    def __init__(self, git: GitStore, model: str = "claude-sonnet-4-6"):
        self._model = model
        self._git = git
        self._config_dir = str(git.repo_path / ".claude-sdk")
        self._section_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _stream_query(self, prompt: str, opts: ClaudeAgentOptions):
        session_id: str | None = None
        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, StreamEvent):
                event = message.event
                if (
                    event.get("type") == "content_block_delta"
                    and event.get("delta", {}).get("type") == "text_delta"
                ):
                    yield ("text_delta", event["delta"]["text"])
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        yield ("tool_use", block)
            elif isinstance(message, ResultMessage):
                session_id = message.session_id
        yield ("done", session_id)

    async def _run_query_streaming(
        self,
        prompt: str,
        system_prompt: str,
        draftcircle_session_id: str,
        agent_session_id: str | None = None,
        allowed_tools: list[str] | None = None,
    ):
        store = GitSessionStore(self._git, draftcircle_session_id)

        opts_kwargs: dict = {
            "system_prompt": system_prompt,
            "model": self._model,
            "max_turns": 3,
            "permission_mode": "bypassPermissions",
            "tools": [],
            "mcp_servers": {"draftcircle": DRAFT_SERVER},
            "session_store": store,
            "env": {"CLAUDE_CONFIG_DIR": self._config_dir},
            "include_partial_messages": True,
        }
        if allowed_tools is not None:
            opts_kwargs["allowed_tools"] = allowed_tools
        if agent_session_id is not None:
            opts_kwargs["resume"] = agent_session_id

        opts = ClaudeAgentOptions(**opts_kwargs)

        try:
            try:
                async for event in self._stream_query(prompt, opts):
                    yield event
            except ClaudeSDKError as exc:
                if agent_session_id is not None and "session" in str(exc).lower():
                    logger.warning(
                        "Stale agent session %s, starting fresh: %s",
                        agent_session_id,
                        exc,
                    )
                    opts_kwargs.pop("resume", None)
                    opts = ClaudeAgentOptions(**opts_kwargs)
                    async for event in self._stream_query(prompt, opts):
                        yield event
                else:
                    raise
        finally:
            store.flush()

    async def generate_drafts(
        self,
        draftcircle_session_id: str,
        agent_session_id: str | None,
        template: Template,
        seed_content: str,
    ) -> AsyncGenerator[DraftEvent]:
        section_descriptions = []
        for i, section in enumerate(template.sections, start=1):
            section_descriptions.append(
                f"{i}. **{section.title}** (id: {section.id}) -- {section.guidance}"
            )
        sections_text = "\n".join(section_descriptions)

        prompt = (
            f"Here is the seed material for this document:\n\n"
            f"{seed_content}\n\n"
            f"Generate initial drafts for each of the following sections. "
            f"Call the write_section_draft tool once for each section.\n\n"
            f"{sections_text}"
        )

        result_session_id = None

        async for event_type, data in self._run_query_streaming(
            prompt=prompt,
            system_prompt=template.ai_context,
            draftcircle_session_id=draftcircle_session_id,
            agent_session_id=agent_session_id,
            allowed_tools=["mcp__draftcircle__write_section_draft"],
        ):
            if event_type == "text_delta":
                yield {"type": "ai_activity", "section_id": None, "text": data}
            elif event_type == "tool_use" and data.name.endswith(
                "write_section_draft"
            ):
                yield {
                    "type": "section_drafted",
                    "section_id": data.input["section_id"],
                    "content": data.input["content"],
                }
            elif event_type == "done":
                result_session_id = data

        yield {"type": "drafts_complete", "session_id": result_session_id}

    async def process_comment(
        self,
        session_id: str | None,
        section_id: str,
        section_title: str,
        section_guidance: str,
        current_draft: str,
        comment_thread: list[dict],
        new_comment_author: str,
        new_comment_text: str,
        system_prompt: str = "",
        agent_session_id: str | None = None,
    ) -> AsyncGenerator[CommentEvent]:
        lock_key = f"{session_id}:{section_id}"
        async with self._section_locks[lock_key]:
            thread_text = ""
            if comment_thread:
                lines = []
                for c in comment_thread:
                    lines.append(f"- **{c['author']}**: {c['text']}")
                thread_text = "Previous comments:\n" + "\n".join(lines) + "\n\n"

            prompt = (
                f'A comment has been posted on section "{section_title}".\n\n'
                f"Section guidance: {section_guidance}\n\n"
                f"Current draft:\n{current_draft}\n\n"
                f"{thread_text}"
                f"New comment by **{new_comment_author}**: {new_comment_text}\n\n"
                f"If this comment warrants a revision to the draft, use the "
                f"propose_revision tool with the complete revised draft. "
                f"If this is a question or discussion point that doesn't require "
                f"a draft change, use the post_reply tool."
            )

            result = ReplyResult(text="I've noted your comment.")
            result_session_id = None

            async for event_type, data in self._run_query_streaming(
                prompt=prompt,
                system_prompt=system_prompt,
                draftcircle_session_id=session_id or "unknown",
                agent_session_id=agent_session_id,
                allowed_tools=[
                    "mcp__draftcircle__propose_revision",
                    "mcp__draftcircle__post_reply",
                ],
            ):
                if event_type == "text_delta":
                    yield {
                        "type": "ai_activity",
                        "section_id": section_id,
                        "text": data,
                    }
                elif event_type == "tool_use":
                    if data.name.endswith("propose_revision"):
                        result = ProposalResult(
                            revised_text=data.input["revised_text"],
                            summary=data.input["summary"],
                        )
                    elif data.name.endswith("post_reply"):
                        result = ReplyResult(text=data.input["text"])
                elif event_type == "done":
                    result_session_id = data

            result_type = "proposal" if isinstance(result, ProposalResult) else "reply"
            yield {
                "type": "ai_complete",
                "section_id": section_id,
                "result_type": result_type,
                "result": result,
                "session_id": result_session_id,
            }
