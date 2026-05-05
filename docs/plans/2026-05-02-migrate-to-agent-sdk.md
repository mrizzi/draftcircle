# Migrate AI Orchestrator to Claude Agent SDK — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw Anthropic Client SDK (`anthropic.AsyncAnthropic`) with the Claude Agent SDK (`claude-agent-sdk`) for AI orchestration, gaining built-in session persistence and spec compliance.

**Architecture:** The AI orchestrator currently makes direct `client.messages.create()` calls with a hand-rolled tool loop and manual JSON history saved to git. The Agent SDK provides `query()` with `resume=session_id` for session persistence, and `@tool`/`create_sdk_mcp_server` for custom tools — all documented at https://code.claude.com/docs/en/agent-sdk/overview. The `Session.agent_session_id` field already exists in the model. Vertex AI is handled by the Agent SDK via `CLAUDE_CODE_USE_VERTEX=1` env var (https://code.claude.com/docs/en/agent-sdk/overview#set-your-api-key).

**Tech Stack:** `claude-agent-sdk` (Python), FastAPI, existing `backend/models.py` and `backend/session_manager.py`

**Spec reference:** Section 4.1 "Context Persistence via Claude Agent SDK" in `docs/specs/2026-04-30-collaborative-document-authoring-design.md`

---

### Task 1: Update dependencies

**Files:**
- Modify: `pyproject.toml:9-16`

- [ ] **Step 1: Add claude-agent-sdk, remove anthropic**

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pygit2>=1.17",
    "pydantic>=2.11",
    "claude-agent-sdk>=0.1.70",
    "httpx>=0.28",
]
```

Note: `anthropic` is a transitive dependency of `claude-agent-sdk` so it will still be installed, but the app should not import it directly.

- [ ] **Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: installs `claude-agent-sdk` and its dependencies

- [ ] **Step 3: Verify import works**

Run: `python3 -c "from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: replace anthropic with claude-agent-sdk"
```

---

### Task 2: Rewrite ai_orchestrator.py with Agent SDK

This is the core rewrite. The new orchestrator uses `query()` with custom MCP tools instead of `client.messages.create()` with JSON tool schemas.

**Files:**
- Rewrite: `backend/ai_orchestrator.py`
- Test: `tests/test_ai_orchestrator.py`

**Key design decisions (all backed by Agent SDK docs):**
- Custom tools via `@tool` decorator + `create_sdk_mcp_server` (https://code.claude.com/docs/en/agent-sdk/custom-tools)
- Session persistence via `resume=session_id` (https://code.claude.com/docs/en/agent-sdk/sessions#resume-by-id)
- No built-in tools (`tools=[]`) — only our custom MCP tools
- `max_turns=1` — the AI should respond in a single turn

- [ ] **Step 1: Write failing test for generate_drafts**

```python
# tests/test_ai_orchestrator.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ai_orchestrator import AIOrchestrator, DraftResult, ProposalResult, ReplyResult


class TestGenerateDrafts:
    @pytest.mark.asyncio
    async def test_generates_drafts_from_query_result(self):
        from backend.models import Template
        from tests.conftest import SAMPLE_TEMPLATE

        template = Template.model_validate(SAMPLE_TEMPLATE)
        orchestrator = AIOrchestrator()

        draft_texts = {
            "overview": "# Overview\n\nDraft content.",
            "details": "# Details\n\nMore content.",
            "notes": "# Notes\n\nSome notes.",
        }

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    ("write_section_draft", {"section_id": sid, "content": text})
                    for sid, text in draft_texts.items()
                ],
                session_id="agent-session-123",
            )

            drafts, session_id = await orchestrator.generate_drafts(
                session_id=None,
                template=template,
                seed_content="Feature X enables users to do Y.",
            )

        assert len(drafts) == 3
        assert drafts[0].section_id == "overview"
        assert "Draft content" in drafts[0].content
        assert session_id == "agent-session-123"
```

Note: `mock_agent_messages` is a test helper we'll define — see step 2.

- [ ] **Step 2: Write test helper for mocking Agent SDK messages**

Add to the top of the test file:

```python
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock, TextBlock


def mock_agent_messages(tool_calls=None, text=None, session_id="test-session"):
    """Return an async iterator that mimics query() output."""
    messages = []
    if tool_calls:
        content = []
        for name, input_data in tool_calls:
            content.append(ToolUseBlock(id=f"tool_{name}", name=f"mcp__draftcircle__{name}", type="tool_use", input=input_data))
        messages.append(AssistantMessage(type="assistant", content=content, message=MagicMock(content=content)))
    if text:
        content = [TextBlock(type="text", text=text)]
        messages.append(AssistantMessage(type="assistant", content=content, message=MagicMock(content=content)))
    messages.append(ResultMessage(
        type="result",
        subtype="success",
        result=text or "",
        session_id=session_id,
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_output_tokens=50,
        num_turns=1,
    ))

    async def async_iter():
        for m in messages:
            yield m

    return async_iter()
```

Note: The exact fields on `AssistantMessage`, `ResultMessage`, `ToolUseBlock`, and `TextBlock` must match the SDK's actual types. Before writing the implementation, verify these by running:
```bash
python3 -c "from claude_agent_sdk import AssistantMessage, ResultMessage; help(ResultMessage)" 2>&1 | head -30
```
Adjust the mock helper to match the actual SDK types.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ai_orchestrator.py::TestGenerateDrafts::test_generates_drafts_from_query_result -v`
Expected: FAIL — `AIOrchestrator()` no longer accepts the same constructor

- [ ] **Step 4: Write the new ai_orchestrator.py**

```python
# backend/ai_orchestrator.py
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    query,
    tool,
    create_sdk_mcp_server,
)

from backend.models import Template


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


# --- Custom MCP Tools ---

@tool(
    "write_section_draft",
    "Write the initial draft for a document section",
    {
        "type": "object",
        "properties": {
            "section_id": {"type": "string", "description": "The section identifier"},
            "content": {"type": "string", "description": "The markdown content for this section"},
        },
        "required": ["section_id", "content"],
    },
)
async def write_section_draft_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Draft written for {args['section_id']}"}]}


@tool(
    "propose_revision",
    "Propose a revision to the current section draft based on the comment",
    {
        "type": "object",
        "properties": {
            "revised_text": {"type": "string", "description": "The complete revised section draft"},
            "summary": {"type": "string", "description": "Brief explanation of what changed and why"},
        },
        "required": ["revised_text", "summary"],
    },
)
async def propose_revision_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Revision proposed: {args['summary']}"}]}


@tool(
    "post_reply",
    "Reply to the comment without changing the draft",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The reply text"},
        },
        "required": ["text"],
    },
)
async def post_reply_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": args["text"]}]}


DRAFT_SERVER = create_sdk_mcp_server(
    name="draftcircle",
    version="1.0.0",
    tools=[write_section_draft_tool, propose_revision_tool, post_reply_tool],
)


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
        """Run a query via the Agent SDK. Returns (content_blocks, session_id)."""
        opts = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=self._model,
            max_turns=1,
            tools=[],
            mcp_servers={"draftcircle": DRAFT_SERVER},
            allowed_tools=allowed_tools or ["mcp__draftcircle__*"],
        )
        if agent_session_id:
            opts.resume = agent_session_id

        content_blocks = []
        session_id = None

        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    content_blocks.append(block)
            if isinstance(message, ResultMessage):
                session_id = message.session_id

        return content_blocks, session_id

    async def generate_drafts(
        self, session_id: str | None, template: Template, seed_content: str
    ) -> tuple[list[DraftResult], str | None]:
        section_descriptions = []
        for i, section in enumerate(template.sections, start=1):
            section_descriptions.append(
                f"{i}. **{section.title}** (id: {section.id}) — {section.guidance}"
            )
        sections_text = "\n".join(section_descriptions)

        prompt = (
            f"Here is the seed material for this document:\n\n"
            f"{seed_content}\n\n"
            f"Generate initial drafts for each of the following sections. "
            f"Call the write_section_draft tool once for each section.\n\n"
            f"{sections_text}"
        )

        content_blocks, new_session_id = await self._run_query(
            prompt=prompt,
            system_prompt=template.ai_context,
            agent_session_id=session_id,
            allowed_tools=["mcp__draftcircle__write_section_draft"],
        )

        drafts = []
        for block in content_blocks:
            if hasattr(block, "name") and "write_section_draft" in block.name:
                drafts.append(
                    DraftResult(
                        section_id=block.input["section_id"],
                        content=block.input["content"],
                    )
                )
        return drafts, new_session_id

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
    ) -> tuple[ProposalResult | ReplyResult, str | None]:
        lock_key = f"{section_id}"
        async with self._section_locks[lock_key]:
            thread_text = ""
            if comment_thread:
                lines = [f"- **{c['author']}**: {c['text']}" for c in comment_thread]
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

            content_blocks, new_session_id = await self._run_query(
                prompt=prompt,
                system_prompt=system_prompt,
                agent_session_id=session_id,
                allowed_tools=[
                    "mcp__draftcircle__propose_revision",
                    "mcp__draftcircle__post_reply",
                ],
            )

            for block in content_blocks:
                if not hasattr(block, "name"):
                    continue
                if "propose_revision" in block.name:
                    return (
                        ProposalResult(
                            revised_text=block.input["revised_text"],
                            summary=block.input["summary"],
                        ),
                        new_session_id,
                    )
                if "post_reply" in block.name:
                    return ReplyResult(text=block.input["text"]), new_session_id

            return ReplyResult(text="I've noted your comment."), new_session_id
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ai_orchestrator.py -v`
Expected: Tests pass (after adjusting mock helper to match actual SDK types)

- [ ] **Step 6: Write remaining orchestrator tests**

Add tests for:
- `test_returns_proposal_when_revision_needed` — mock `query()` returning a `propose_revision` tool call
- `test_returns_reply_when_no_revision_needed` — mock `query()` returning a `post_reply` tool call
- `test_fallback_reply_when_no_tool_used` — mock `query()` returning only text
- `test_captures_session_id` — verify `session_id` is extracted from `ResultMessage`
- `test_passes_resume_session_id` — verify `resume` is set on `ClaudeAgentOptions` when `agent_session_id` is provided
- `test_uses_section_lock` — same concurrent test as before
- `test_dataclass_validation` — same `DraftResult`, `ProposalResult`, `ReplyResult` validation

Each test should mock `backend.ai_orchestrator.query` and verify the correct behavior.

- [ ] **Step 7: Run all orchestrator tests**

Run: `pytest tests/test_ai_orchestrator.py -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add backend/ai_orchestrator.py tests/test_ai_orchestrator.py
git commit -m "feat: rewrite AI orchestrator to use Claude Agent SDK"
```

---

### Task 3: Update main.py to use new orchestrator

The orchestrator no longer needs a client passed to it. The `create_app` function must store/retrieve `agent_session_id` from sessions.

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_api_ai.py`

- [ ] **Step 1: Update create_app — remove anthropic client init, simplify AI setup**

Replace lines 60-75 in `main.py` (the entire `ai = None` / `anthropic` block) with:

```python
    ai = None
    try:
        from backend.ai_orchestrator import AIOrchestrator

        ai = AIOrchestrator()
    except Exception:
        logger.warning("AI unavailable: Agent SDK init failed", exc_info=True)
```

Remove the `anthropic_client` parameter from `create_app()` — it's no longer needed.

Update the function signature:
```python
def create_app(data_repo_path: str | None = None) -> FastAPI:
```

Remove the import of `AIOrchestrator` from the top of the file (it's now imported inside `create_app`).

- [ ] **Step 2: Update create_session endpoint to store agent_session_id**

In the `create_session` endpoint, after AI generates drafts, store the returned `agent_session_id`:

```python
        if req.seed_text and ai:
            template = templates.get_template(req.template)
            try:
                drafts, agent_session_id = await ai.generate_drafts(
                    session_id=session.agent_session_id,
                    template=template,
                    seed_content=req.seed_text,
                )
                draft_files = {}
                for draft in drafts:
                    meta = session.section_meta.get(draft.section_id)
                    if meta:
                        section_path = (
                            f"sessions/{session.id}/sections/{meta.filename}.md"
                        )
                        draft_files[section_path] = draft.content
                if draft_files:
                    git.commit(
                        f"draft: AI generated drafts for {session.id}",
                        draft_files,
                    )
                if agent_session_id:
                    sessions.set_agent_session_id(session.id, agent_session_id)
            except Exception:
                logger.warning(
                    "AI draft generation failed for %s", session.id, exc_info=True
                )
```

- [ ] **Step 3: Update add_comment endpoint to pass/store agent_session_id**

In the comment handler, pass `session.agent_session_id` and store the returned session ID:

```python
                result, agent_session_id = await ai.process_comment(
                    session_id=session.agent_session_id,
                    section_id=req.section_id,
                    ...
                )

                if agent_session_id and agent_session_id != session.agent_session_id:
                    sessions.set_agent_session_id(session_id, agent_session_id)
```

- [ ] **Step 4: Add set_agent_session_id to SessionManager**

In `backend/session_manager.py`, add:

```python
    def set_agent_session_id(self, session_id: str, agent_session_id: str) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")
        session.agent_session_id = agent_session_id
        session_path = f"sessions/{session_id}/session.json"
        self._git.commit(
            f"session: store agent session ID for {session_id}",
            {session_path: session.model_dump_json(indent=2)},
        )
```

- [ ] **Step 5: Update test fixtures — remove mock_client**

In `tests/conftest.py`, remove the `mock_client` fixture. It is no longer needed since the orchestrator doesn't take a client.

In `tests/test_api_ai.py`, update `app_with_ai` fixture — remove `anthropic_client` parameter:

```python
@pytest.fixture()
def app_with_ai(populated_data_repo):
    return create_app(data_repo_path=populated_data_repo)
```

- [ ] **Step 6: Update API AI tests to mock query()**

Tests in `test_api_ai.py` currently mock `mock_client.messages.create`. They need to mock `backend.ai_orchestrator.query` instead.

The mock should return an async iterator of Agent SDK messages (using the `mock_agent_messages` helper from Task 2).

Example for `test_generates_drafts_on_creation`:

```python
class TestSessionCreationWithAI:
    def test_generates_drafts_on_creation(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    ("write_section_draft", {"section_id": "overview", "content": "AI-generated overview."}),
                    ("write_section_draft", {"section_id": "details", "content": "AI-generated details."}),
                    ("write_section_draft", {"section_id": "notes", "content": "AI-generated notes."}),
                ],
                session_id="agent-123",
            )
            resp = client_ai.post(
                "/api/sessions",
                json={
                    "template": "test-template",
                    "coordinator": "alice",
                    "participants": [],
                    "seed_text": "Feature X allows users to do Y.",
                },
            )
        assert resp.status_code == 201
        session_id = resp.json()["id"]
        section_resp = client_ai.get(f"/api/sessions/{session_id}/sections/overview")
        assert section_resp.json()["content"] == "AI-generated overview."
```

Repeat for all tests in `TestCommentWithAI` and `TestAIGracefulDegradation`, adapting each mock to use `mock_agent_messages`.

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -v`
Expected: All 179+ tests pass

- [ ] **Step 8: Commit**

```bash
git add backend/main.py backend/session_manager.py tests/conftest.py tests/test_api_ai.py
git commit -m "feat: integrate Agent SDK session persistence into API layer"
```

---

### Task 4: Update documentation and cleanup

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md tech stack table**

Change the AI integration row from:

```
| AI integration | Claude Agent SDK (session persistence) |
```

Verify it already says this. If the table still says `anthropic` anywhere, update it.

- [ ] **Step 2: Update CLAUDE.md install command**

The install command should no longer reference `anthropic`:

```bash
pip install fastapi uvicorn pygit2 claude-agent-sdk
```

- [ ] **Step 3: Update README.md environment variables section**

Add note about Vertex AI:

```markdown
export ANTHROPIC_API_KEY=sk-...        # optional — or use Vertex AI:
# export CLAUDE_CODE_USE_VERTEX=1
# export CLOUD_ML_REGION=us-east5
# export ANTHROPIC_VERTEX_PROJECT_ID=your-project
```

- [ ] **Step 4: Remove dead code**

Remove any remaining `import anthropic` lines. Remove the old `ai_history.json` references if any exist in test files or conftest.

- [ ] **Step 5: Run full validation**

Run: `pytest tests/ -v && python3 -m ruff check . && python3 -m ruff format --check .`
Expected: All tests pass, no lint errors, no format issues

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update for Claude Agent SDK migration"
```

---

### Task 5: Integration test — end-to-end with live Agent SDK

This task is manual verification, not automated tests.

- [ ] **Step 1: Start the server**

```bash
export DRAFTCIRCLE_DATA_REPO=/path/to/data-repo
export CLAUDE_CODE_USE_VERTEX=1  # or ANTHROPIC_API_KEY
uvicorn backend.main:create_app --factory --reload --port 8000
```

- [ ] **Step 2: Create a session with seed text**

Open http://localhost:8000, create a session with the Jira Feature template and seed text. Verify AI drafts are generated.

- [ ] **Step 3: Post a comment**

Comment on a section. Verify the AI responds with either a proposal or a reply.

- [ ] **Step 4: Verify session persistence**

Restart the server (`Ctrl+C`, then start again). Open the same session and post another comment. The AI should have context from the previous interaction (seed material, prior comments) without re-sending them.

- [ ] **Step 5: Check agent_session_id in session.json**

```bash
cat <data-repo>/sessions/<session-id>/session.json | python3 -m json.tool | grep agent_session_id
```

Expected: a non-null session ID string
