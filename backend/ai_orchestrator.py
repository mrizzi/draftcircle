import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from backend.models import Template


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
class DraftResult:
    section_id: str
    content: str

    def __post_init__(self):
        if not self.section_id:
            raise ValueError("section_id must be non-empty")
        if not self.content:
            raise ValueError("content must be non-empty")


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


class AIOrchestrator:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self._model = model
        self._section_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _run_query(
        self,
        prompt: str,
        system_prompt: str,
        agent_session_id: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> tuple[list, str | None]:
        opts_kwargs: dict = {
            "system_prompt": system_prompt,
            "model": self._model,
            "max_turns": 3,
            "permission_mode": "bypassPermissions",
            "tools": [],
            "mcp_servers": {"draftcircle": DRAFT_SERVER},
        }
        if allowed_tools is not None:
            opts_kwargs["allowed_tools"] = allowed_tools
        if agent_session_id is not None:
            opts_kwargs["resume"] = agent_session_id

        opts = ClaudeAgentOptions(**opts_kwargs)

        content_blocks: list = []
        session_id: str | None = None

        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    content_blocks.append(block)
            elif isinstance(message, ResultMessage):
                session_id = message.session_id

        return content_blocks, session_id

    async def generate_drafts(
        self,
        session_id: str | None,
        template: Template,
        seed_content: str,
    ) -> tuple[list[DraftResult], str | None]:
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

        content_blocks, agent_session_id = await self._run_query(
            prompt=prompt,
            system_prompt=template.ai_context,
            agent_session_id=session_id,
            allowed_tools=["mcp__draftcircle__write_section_draft"],
        )

        drafts = []
        for block in content_blocks:
            if isinstance(block, ToolUseBlock) and "write_section_draft" in block.name:
                drafts.append(
                    DraftResult(
                        section_id=block.input["section_id"],
                        content=block.input["content"],
                    )
                )
        return drafts, agent_session_id

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
    ) -> tuple[ProposalResult | ReplyResult, str | None]:
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

            content_blocks, result_session_id = await self._run_query(
                prompt=prompt,
                system_prompt=system_prompt,
                agent_session_id=agent_session_id,
                allowed_tools=[
                    "mcp__draftcircle__propose_revision",
                    "mcp__draftcircle__post_reply",
                ],
            )

            for block in content_blocks:
                if not isinstance(block, ToolUseBlock):
                    continue
                if "propose_revision" in block.name:
                    return (
                        ProposalResult(
                            revised_text=block.input["revised_text"],
                            summary=block.input["summary"],
                        ),
                        result_session_id,
                    )
                if "post_reply" in block.name:
                    return ReplyResult(text=block.input["text"]), result_session_id

            return ReplyResult(text="I've noted your comment."), result_session_id
