import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass

from backend.git_store import GitStore

DRAFT_TOOL = {
    "name": "write_section_draft",
    "description": "Write the initial draft for a document section",
    "input_schema": {
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
}

REVISION_TOOL = {
    "name": "propose_revision",
    "description": "Propose a revision to the current section draft based on the comment",
    "input_schema": {
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
}

REPLY_TOOL = {
    "name": "post_reply",
    "description": "Reply to the comment without changing the draft",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The reply text",
            },
        },
        "required": ["text"],
    },
}


@dataclass
class DraftResult:
    section_id: str
    content: str


@dataclass
class ProposalResult:
    revised_text: str
    summary: str


@dataclass
class ReplyResult:
    text: str


class AIOrchestrator:
    def __init__(self, client, git: GitStore, model: str = "claude-sonnet-4-6"):
        self._client = client
        self._git = git
        self._model = model
        self._section_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _history_path(self, session_id: str) -> str:
        return f"sessions/{session_id}/ai_history.json"

    def _load_history(self, session_id: str) -> dict:
        content = self._git.read_file(self._history_path(session_id))
        if content is None:
            return {"system": "", "messages": []}
        return json.loads(content)

    def _save_history(self, session_id: str, history: dict) -> None:
        self._git.commit(
            f"ai: update conversation history for {session_id}",
            {self._history_path(session_id): json.dumps(history, indent=2)},
        )

    async def _send_message(
        self,
        session_id: str,
        system: str,
        user_content: str,
        tools: list[dict] | None = None,
    ) -> list:
        history = self._load_history(session_id)
        history["system"] = system
        history["messages"].append({"role": "user", "content": user_content})

        kwargs = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": history["messages"],
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        history["messages"].append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Acknowledged.",
                        }
                    )
            history["messages"].append({"role": "user", "content": tool_results})

        self._save_history(session_id, history)
        return response.content
