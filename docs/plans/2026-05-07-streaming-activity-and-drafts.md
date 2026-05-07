# Streaming AI Activity & Progressive Draft Delivery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream AI reasoning to a collapsible frontend panel during comment processing, and deliver drafts progressively via background task + WebSocket during session creation.

**Architecture:** Convert `process_comment` and `generate_drafts` to async generators that yield streaming events. The `add_comment` endpoint consumes the generator inline, broadcasting `ai_activity` events via WebSocket. Session creation returns immediately; a background `asyncio.create_task` generates drafts and broadcasts `section_drafted` events. Frontend gets a collapsible log panel and `DRAFTING` badge.

**Tech Stack:** Python async generators, Claude Agent SDK `StreamEvent`, FastAPI WebSocket, vanilla JS DOM manipulation.

**Spec:** `docs/specs/2026-05-07-streaming-activity-and-drafts-design.md`

---

### Task 1: Add DRAFTING status and SessionManager methods

**Files:**
- Modify: `backend/models.py:14-18` (SectionStatus enum)
- Modify: `backend/session_manager.py` (add two public methods)
- Modify: `tests/test_session_manager.py` (add tests for new methods)

- [ ] **Step 1: Add DRAFTING to SectionStatus enum**

In `backend/models.py`, add `DRAFTING` before `DRAFT`:

```python
class SectionStatus(str, Enum):
    DRAFTING = "drafting"
    DRAFT = "draft"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    SKIPPED = "skipped"
```

- [ ] **Step 2: Write failing tests for SessionManager methods**

Add to `tests/test_session_manager.py`:

```python
class TestSectionStatusTransitions:
    def test_begin_drafting_sets_all_to_drafting(self, sessions, sample_session):
        sessions.begin_drafting(sample_session.id)
        session = sessions.get_session(sample_session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFTING

    def test_recover_drafting_resets_to_draft(self, sessions, sample_session):
        sessions.begin_drafting(sample_session.id)
        # Simulate one section completing
        sessions.set_section_status(
            sample_session.id, "overview", SectionStatus.DRAFT
        )
        sessions.recover_drafting(sample_session.id)
        session = sessions.get_session(sample_session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFT

    def test_recover_drafting_noop_when_no_drafting(self, sessions, sample_session):
        sessions.recover_drafting(sample_session.id)
        session = sessions.get_session(sample_session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFT

    def test_set_section_status(self, sessions, sample_session):
        sessions.set_section_status(
            sample_session.id, "overview", SectionStatus.IN_REVIEW
        )
        session = sessions.get_session(sample_session.id)
        assert session.section_meta["overview"].status == SectionStatus.IN_REVIEW

    def test_set_section_status_unknown_section(self, sessions, sample_session):
        with pytest.raises(ValueError, match="not found"):
            sessions.set_section_status(
                sample_session.id, "nonexistent", SectionStatus.DRAFT
            )
```

This requires the `sessions` and `sample_session` fixtures. Check existing test_session_manager.py for how they're set up — use the same pattern. Import `SectionStatus` from `backend.models`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_session_manager.py::TestSectionStatusTransitions -v`
Expected: FAIL — `begin_drafting`, `recover_drafting`, `set_section_status` don't exist yet.

- [ ] **Step 4: Implement the three SessionManager methods**

Add to `backend/session_manager.py` at the end of the class:

```python
def set_section_status(
    self, session_id: str, section_id: str, status: SectionStatus
) -> None:
    session = self._require_session(session_id)
    if section_id not in session.section_meta:
        raise ValueError(f"Section '{section_id}' not found")
    session.section_meta[section_id].status = status
    self._save_session(
        session, f"status: {section_id} → {status.value}"
    )

def begin_drafting(self, session_id: str) -> None:
    session = self._require_session(session_id)
    for meta in session.section_meta.values():
        meta.status = SectionStatus.DRAFTING
    self._save_session(
        session, f"draft: begin AI drafts for {session_id}"
    )

def recover_drafting(self, session_id: str) -> None:
    session = self._require_session(session_id)
    changed = False
    for meta in session.section_meta.values():
        if meta.status == SectionStatus.DRAFTING:
            meta.status = SectionStatus.DRAFT
            changed = True
    if changed:
        self._save_session(
            session,
            f"draft: recover stuck sections for {session_id}",
        )
```

Add `SectionStatus` to the imports from `backend.models` if not already present (it's already imported on line 8).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_session_manager.py::TestSectionStatusTransitions -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: All tests pass. The new DRAFTING enum value doesn't break anything because existing code never checks for it.

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/session_manager.py tests/test_session_manager.py
git commit -m "feat: add DRAFTING section status and SessionManager transition methods"
```

---

### Task 2: Test mock infrastructure for StreamEvent

**Files:**
- Modify: `tests/test_ai_orchestrator.py:1-63` (imports + mock_agent_messages)

- [ ] **Step 1: Add StreamEvent import and update mock_agent_messages**

In `tests/test_ai_orchestrator.py`, add `StreamEvent` to the `claude_agent_sdk` import:

```python
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKError,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
)
```

Replace the `mock_agent_messages` function with this version that supports streaming:

```python
def mock_agent_messages(
    tool_calls=None, text=None, session_id="test-session", stream_text=None
):
    """Create an async generator mimicking query() output.

    Args:
        stream_text: List of text chunks to yield as StreamEvent text deltas.
    """
    messages = []
    if stream_text:
        for chunk in stream_text:
            messages.append(
                StreamEvent(
                    uuid="evt-1",
                    session_id=session_id,
                    event={
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": chunk},
                    },
                )
            )
    if tool_calls:
        content = []
        for name, input_data in tool_calls:
            content.append(
                ToolUseBlock(
                    id=f"tool_{name}",
                    name=f"mcp__draftcircle__{name}",
                    input=input_data,
                )
            )
        messages.append(AssistantMessage(content=content, model="claude-sonnet-4-6"))
    if text:
        content = [TextBlock(text=text)]
        messages.append(AssistantMessage(content=content, model="claude-sonnet-4-6"))
    messages.append(
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id=session_id,
            result=text or "",
        )
    )

    async def _iter():
        for m in messages:
            yield m

    return _iter()
```

- [ ] **Step 2: Add collect_events helper**

Add this helper function after `mock_agent_messages` (tests will need it to consume async generators):

```python
async def collect_events(gen):
    """Consume an async generator and return all yielded events as a list."""
    events = []
    async for event in gen:
        events.append(event)
    return events
```

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `pytest tests/test_ai_orchestrator.py -v`
Expected: All existing tests pass (mock_agent_messages signature is backward-compatible — `stream_text` defaults to `None`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_ai_orchestrator.py
git commit -m "test: add StreamEvent mock support and collect_events helper"
```

---

### Task 3: Convert orchestrator to async generators

**Files:**
- Modify: `backend/ai_orchestrator.py` (replace `_collect_messages`+`_run_query` with `_stream_query`+`_run_query_streaming`; convert `process_comment` and `generate_drafts` to generators)

- [ ] **Step 1: Add StreamEvent import**

In `backend/ai_orchestrator.py`, add `StreamEvent` to the SDK import:

```python
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
```

- [ ] **Step 2: Replace _collect_messages and _run_query**

Remove the `_collect_messages` static method (lines 133-145) and `_run_query` method (lines 147-191). Replace with:

```python
async def _stream_query(self, prompt: str, opts: ClaudeAgentOptions):
    content_blocks: list = []
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
            content_blocks.extend(message.content)
        elif isinstance(message, ResultMessage):
            session_id = message.session_id
    yield ("result", (content_blocks, session_id))

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
```

- [ ] **Step 3: Convert generate_drafts to async generator**

Replace the current `generate_drafts` method (lines 193-234) with:

```python
async def generate_drafts(
    self,
    draftcircle_session_id: str,
    agent_session_id: str | None,
    template: Template,
    seed_content: str,
):
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

    content_blocks = None
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
        elif event_type == "result":
            content_blocks, result_session_id = data

    for block in content_blocks or []:
        if isinstance(block, ToolUseBlock) and block.name.endswith(
            "write_section_draft"
        ):
            yield {
                "type": "section_drafted",
                "section_id": block.input["section_id"],
                "content": block.input["content"],
            }

    yield {"type": "drafts_complete", "session_id": result_session_id}
```

- [ ] **Step 4: Convert process_comment to async generator**

Replace the current `process_comment` method (lines 236-295) with:

```python
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
):
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

        content_blocks = None
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
            elif event_type == "result":
                content_blocks, result_session_id = data

        result = ReplyResult(text="I've noted your comment.")
        for block in content_blocks or []:
            if not isinstance(block, ToolUseBlock):
                continue
            if block.name.endswith("propose_revision"):
                result = ProposalResult(
                    revised_text=block.input["revised_text"],
                    summary=block.input["summary"],
                )
                break
            if block.name.endswith("post_reply"):
                result = ReplyResult(text=block.input["text"])
                break

        result_type = (
            "proposal" if isinstance(result, ProposalResult) else "reply"
        )
        yield {
            "type": "ai_complete",
            "section_id": section_id,
            "result_type": result_type,
            "result": result,
            "session_id": result_session_id,
        }
```

- [ ] **Step 5: Verify the file is syntactically valid**

Run: `python3 -c "import backend.ai_orchestrator"`
Expected: No import errors.

- [ ] **Step 6: Commit**

```bash
git add backend/ai_orchestrator.py
git commit -m "feat: convert orchestrator to async generators with StreamEvent filtering"
```

---

### Task 4: Update all orchestrator tests for generator pattern

**Files:**
- Modify: `tests/test_ai_orchestrator.py` (update all existing tests + add streaming-specific tests)

- [ ] **Step 1: Update TestGenerateDrafts to consume generator**

Replace the entire `TestGenerateDrafts` class with:

```python
class TestGenerateDrafts:
    @pytest.mark.asyncio
    async def test_generates_drafts(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {
                            "section_id": "overview",
                            "content": "# Overview\n\nDraft content.",
                        },
                    ),
                    (
                        "write_section_draft",
                        {
                            "section_id": "details",
                            "content": "# Details\n\nMore content.",
                        },
                    ),
                    (
                        "write_section_draft",
                        {"section_id": "notes", "content": "# Notes\n\nSome notes."},
                    ),
                ],
                session_id="sess-123",
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Feature X enables users to do Y.",
                )
            )

        drafted = [e for e in events if e["type"] == "section_drafted"]
        assert len(drafted) == 3
        assert drafted[0]["section_id"] == "overview"
        assert "Draft content" in drafted[0]["content"]
        assert drafted[1]["section_id"] == "details"
        assert drafted[2]["section_id"] == "notes"

    @pytest.mark.asyncio
    async def test_yields_drafts_complete_with_session_id(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
                session_id="sess-456",
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )

        complete = next(e for e in events if e["type"] == "drafts_complete")
        assert complete["session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_sends_seed_and_template_context(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )
            await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed material here",
                )
            )

            call_args = mock_query.call_args
            prompt = call_args.kwargs["prompt"]
            opts = call_args.kwargs["options"]

            assert "Seed material here" in prompt
            assert "overview" in prompt.lower()
            assert opts.system_prompt == template.ai_context

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tools(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                text="I can't generate drafts right now.",
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed material",
                )
            )

        drafted = [e for e in events if e["type"] == "section_drafted"]
        assert drafted == []
        complete = next(e for e in events if e["type"] == "drafts_complete")
        assert complete is not None

    @pytest.mark.asyncio
    async def test_yields_activity_events_with_stream_text(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
                stream_text=["Analyzing ", "the seed ", "material..."],
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )

        activity = [e for e in events if e["type"] == "ai_activity"]
        assert len(activity) == 3
        assert activity[0]["text"] == "Analyzing "
        assert activity[0]["section_id"] is None
```

- [ ] **Step 2: Update TestProcessComment to consume generator**

Replace the entire `TestProcessComment` class with:

```python
class TestProcessComment:
    @pytest.mark.asyncio
    async def test_returns_proposal(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "propose_revision",
                        {
                            "revised_text": "Updated draft with rate limiting.",
                            "summary": "Added rate limiting per Alice's comment",
                        },
                    ),
                ],
            )
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="nfrs",
                    section_title="Non-Functional Requirements",
                    section_guidance="Architecture characteristics and NFRs",
                    current_draft="Initial NFR draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="We need rate limiting.",
                )
            )

        complete = next(e for e in events if e["type"] == "ai_complete")
        assert complete["result_type"] == "proposal"
        assert isinstance(complete["result"], ProposalResult)
        assert "rate limiting" in complete["result"].revised_text

    @pytest.mark.asyncio
    async def test_returns_reply(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "post_reply",
                        {
                            "text": "Good question -- rate limiting is already covered in section 5."
                        },
                    ),
                ],
            )
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="nfrs",
                    section_title="NFRs",
                    section_guidance="NFR guidance",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="bob",
                    new_comment_text="Is rate limiting covered?",
                )
            )

        complete = next(e for e in events if e["type"] == "ai_complete")
        assert complete["result_type"] == "reply"
        assert isinstance(complete["result"], ReplyResult)
        assert "rate limiting" in complete["result"].text

    @pytest.mark.asyncio
    async def test_includes_thread_in_prompt(self, orchestrator):
        thread = [
            {"author": "alice", "text": "First comment"},
            {"author": "bob", "text": "I agree"},
        ]

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "reply"})],
            )
            await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="Write an overview",
                    current_draft="Draft.",
                    comment_thread=thread,
                    new_comment_author="alice",
                    new_comment_text="New comment",
                )
            )

            call_args = mock_query.call_args
            prompt = call_args.kwargs["prompt"]
            assert "First comment" in prompt
            assert "New comment" in prompt

    @pytest.mark.asyncio
    async def test_fallback_reply_no_tool(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                text="I'm not sure what to do here.",
            )
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="Write an overview",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="Please revise",
                )
            )

        complete = next(e for e in events if e["type"] == "ai_complete")
        assert isinstance(complete["result"], ReplyResult)
        assert complete["result"].text == "I've noted your comment."

    @pytest.mark.asyncio
    async def test_returns_session_id(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
                session_id="sess-789",
            )
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="Write an overview",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="Comment",
                )
            )

        complete = next(e for e in events if e["type"] == "ai_complete")
        assert complete["session_id"] == "sess-789"

    @pytest.mark.asyncio
    async def test_passes_resume_id(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
            )
            await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="Write an overview",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="Comment",
                    agent_session_id="existing-session-42",
                )
            )

            call_args = mock_query.call_args
            opts = call_args.kwargs["options"]
            assert opts.resume == "existing-session-42"

    @pytest.mark.asyncio
    async def test_section_lock(self, orchestrator):
        call_order = []

        def slow_query(**kwargs):
            async def _gen():
                call_order.append("start")
                await asyncio.sleep(0.05)
                call_order.append("end")
                content = [
                    ToolUseBlock(
                        id="tool_post_reply",
                        name="mcp__draftcircle__post_reply",
                        input={"text": "reply"},
                    )
                ]
                yield AssistantMessage(content=content, model="claude-sonnet-4-6")
                yield ResultMessage(
                    subtype="success",
                    duration_ms=100,
                    duration_api_ms=80,
                    is_error=False,
                    num_turns=1,
                    session_id="test-session",
                    result="",
                )

            return _gen()

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = slow_query
            await asyncio.gather(
                collect_events(
                    orchestrator.process_comment(
                        "test-session", "overview", "Overview", "g",
                        "Draft.", [], "alice", "comment 1",
                    )
                ),
                collect_events(
                    orchestrator.process_comment(
                        "test-session", "overview", "Overview", "g",
                        "Draft.", [], "bob", "comment 2",
                    )
                ),
            )

        assert call_order == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_yields_activity_events(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
                stream_text=["Let me ", "think about ", "this..."],
            )
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="Write an overview",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="Comment",
                )
            )

        activity = [e for e in events if e["type"] == "ai_activity"]
        assert len(activity) == 3
        assert activity[0]["text"] == "Let me "
        assert activity[0]["section_id"] == "overview"

    @pytest.mark.asyncio
    async def test_filters_tool_input_events(self, orchestrator):
        tool_input_event = StreamEvent(
            uuid="evt-tool",
            session_id="test-session",
            event={
                "type": "content_block_delta",
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"secret": "data"}',
                },
            },
        )
        tool_start_event = StreamEvent(
            uuid="evt-start",
            session_id="test-session",
            event={
                "type": "content_block_start",
                "content_block": {"type": "tool_use"},
            },
        )
        text_event = StreamEvent(
            uuid="evt-text",
            session_id="test-session",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "visible"},
            },
        )

        async def custom_query(**kwargs):
            yield text_event
            yield tool_input_event
            yield tool_start_event
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="t1",
                        name="mcp__draftcircle__post_reply",
                        input={"text": "reply"},
                    )
                ],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="test-session",
                result="",
            )

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = custom_query()
            events = await collect_events(
                orchestrator.process_comment(
                    session_id="test-session",
                    section_id="overview",
                    section_title="Overview",
                    section_guidance="g",
                    current_draft="Draft.",
                    comment_thread=[],
                    new_comment_author="alice",
                    new_comment_text="Comment",
                )
            )

        activity = [e for e in events if e["type"] == "ai_activity"]
        assert len(activity) == 1
        assert activity[0]["text"] == "visible"
```

- [ ] **Step 3: Update TestSessionStoreIntegration to consume generator**

Replace the entire `TestSessionStoreIntegration` class with:

```python
class TestSessionStoreIntegration:
    @pytest.mark.asyncio
    async def test_run_query_sets_session_store_and_partial_messages(
        self, orchestrator, data_repo
    ):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
                session_id="sess-001",
            )
            await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )
            opts = mock_query.call_args.kwargs["options"]
            assert opts.session_store is not None
            assert opts.env.get("CLAUDE_CONFIG_DIR") is not None
            assert opts.include_partial_messages is True

    @pytest.mark.asyncio
    async def test_run_query_sets_resume(self, orchestrator, data_repo):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )
            await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id="existing-session-42",
                    template=template,
                    seed_content="Seed.",
                )
            )
            opts = mock_query.call_args.kwargs["options"]
            assert opts.resume == "existing-session-42"

    @pytest.mark.asyncio
    async def test_flush_called_on_success(self, orchestrator, data_repo):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with (
            patch("backend.ai_orchestrator.query") as mock_query,
            patch("backend.git_session_store.GitSessionStore.flush") as mock_flush,
        ):
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )
            await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )
            mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_session_retries_without_resume(
        self, orchestrator, data_repo
    ):
        template = Template.model_validate(SAMPLE_TEMPLATE)
        call_count = 0

        def query_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClaudeSDKError(
                    "No conversation found with session ID: old-session"
                )
            return mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
                session_id="new-session",
            )

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = query_side_effect
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id="old-session",
                    template=template,
                    seed_content="Seed.",
                )
            )

        complete = next(e for e in events if e["type"] == "drafts_complete")
        assert complete["session_id"] == "new-session"
        drafted = [e for e in events if e["type"] == "section_drafted"]
        assert len(drafted) == 1
        assert mock_query.call_count == 2
        retry_opts = mock_query.call_args_list[1].kwargs["options"]
        assert retry_opts.resume is None
        assert retry_opts.session_store is not None

    @pytest.mark.asyncio
    async def test_non_session_sdk_error_propagates(self, orchestrator, data_repo):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = ClaudeSDKError("rate limit exceeded")
            with pytest.raises(ClaudeSDKError, match="rate limit exceeded"):
                await collect_events(
                    orchestrator.generate_drafts(
                        draftcircle_session_id="test-session",
                        agent_session_id="some-session",
                        template=template,
                        seed_content="Seed.",
                    )
                )
        assert mock_query.call_count == 1

    @pytest.mark.asyncio
    async def test_flush_called_on_error(self, orchestrator, data_repo):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with (
            patch("backend.ai_orchestrator.query") as mock_query,
            patch("backend.git_session_store.GitSessionStore.flush") as mock_flush,
        ):
            mock_query.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError):
                await collect_events(
                    orchestrator.generate_drafts(
                        draftcircle_session_id="test-session",
                        agent_session_id=None,
                        template=template,
                        seed_content="Seed.",
                    )
                )
            mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_store_persists_across_stale_retry(
        self, orchestrator, data_repo
    ):
        template = Template.model_validate(SAMPLE_TEMPLATE)
        call_count = 0

        def query_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClaudeSDKError(
                    "No conversation found with session ID: stale"
                )
            return mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = query_side_effect
            await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id="stale",
                    template=template,
                    seed_content="Seed.",
                )
            )
            first_opts = mock_query.call_args_list[0].kwargs["options"]
            retry_opts = mock_query.call_args_list[1].kwargs["options"]
            assert type(first_opts.session_store) is type(retry_opts.session_store)
```

- [ ] **Step 4: Run all orchestrator tests**

Run: `pytest tests/test_ai_orchestrator.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ai_orchestrator.py
git commit -m "test: update orchestrator tests for async generator pattern"
```

---

### Task 5: Simplify conftest and update API tests for JSON response

**Files:**
- Modify: `tests/conftest.py:69-79` (simplify `parse_create_session_response`)
- Modify: `tests/test_api_ai.py` (update session creation tests)

- [ ] **Step 1: Simplify parse_create_session_response**

In `tests/conftest.py`, replace the `parse_create_session_response` function (lines 69-79) with:

```python
def parse_create_session_response(resp):
    return resp.json()
```

Keep the `json` import in conftest.py — the `populated_data_repo` fixture uses `json.dumps`.

- [ ] **Step 2: Update TestSessionCreationWithAI**

In `tests/test_api_ai.py`, replace the `TestSessionCreationWithAI` class with:

```python
class TestSessionCreationWithAI:
    def test_returns_json_immediately_with_seed(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "AI overview."},
                    ),
                    (
                        "write_section_draft",
                        {"section_id": "details", "content": "AI details."},
                    ),
                    (
                        "write_section_draft",
                        {"section_id": "notes", "content": "AI notes."},
                    ),
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
        assert "application/json" in resp.headers["content-type"]
        session = resp.json()
        assert "id" in session

    def test_no_ai_without_seed(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            resp = client_ai.post(
                "/api/sessions",
                json={
                    "template": "test-template",
                    "coordinator": "alice",
                    "participants": [],
                },
            )
        assert resp.status_code == 201
        assert "application/json" in resp.headers["content-type"]
        mock_query.assert_not_called()

    def test_drafts_generated_in_background(self, client_ai):
        import time

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "AI-generated overview."},
                    ),
                    (
                        "write_section_draft",
                        {"section_id": "details", "content": "AI-generated details."},
                    ),
                    (
                        "write_section_draft",
                        {"section_id": "notes", "content": "AI-generated notes."},
                    ),
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
            session_id = resp.json()["id"]
            time.sleep(0.2)

        section_resp = client_ai.get(
            f"/api/sessions/{session_id}/sections/overview"
        )
        assert section_resp.json()["content"] == "AI-generated overview."
```

Note: The `time.sleep(0.2)` gives the background task time to complete on the event loop. If this is flaky, increase to 0.5s.

- [ ] **Step 3: Update TestCommentWithAI._create_session_with_drafts**

The helper creates a session with `seed_text`, which now triggers a background task. Add a `time.sleep(0.2)` to let the background task complete before returning, and update to use `resp.json()` instead of `parse_create_session_response`:

```python
def _create_session_with_drafts(self, client_ai, mock_query, participants=None):
    if participants is None:
        participants = []
    resp = client_ai.post(
        "/api/sessions",
        json={
            "template": "test-template",
            "coordinator": "alice",
            "participants": participants,
            "seed_text": "Feature X.",
        },
    )
    import time
    time.sleep(0.2)
    return resp.json()["id"]
```

- [ ] **Step 4: Update TestAIGracefulDegradation**

Replace `test_session_created_despite_ai_failure`:

```python
def test_session_created_despite_ai_failure(self, client_ai):
    import time

    with patch("backend.ai_orchestrator.query") as mock_query:
        mock_query.side_effect = RuntimeError("API timeout")
        resp = client_ai.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [],
                "seed_text": "Feature X.",
            },
        )
    assert resp.status_code == 201
    session = resp.json()
    session_id = session["id"]
    time.sleep(0.2)

    section_resp = client_ai.get(f"/api/sessions/{session_id}/sections/overview")
    assert section_resp.json()["content"] == ""

    session_resp = client_ai.get(f"/api/sessions/{session_id}")
    session_data = session_resp.json()
    for meta in session_data["section_meta"].values():
        assert meta["status"] == "draft"
```

- [ ] **Step 5: Run API AI tests (they will fail until main.py is updated)**

Run: `pytest tests/test_api_ai.py -v`
Expected: Tests fail because `main.py` still uses NDJSON streaming. This is expected — we update main.py in the next tasks.

- [ ] **Step 6: Commit the test updates**

```bash
git add tests/conftest.py tests/test_api_ai.py
git commit -m "test: update API tests for JSON response and background drafts"
```

---

### Task 6: Update add_comment endpoint for streaming

**Files:**
- Modify: `backend/main.py:241-334` (add_comment endpoint)

- [ ] **Step 1: Replace the AI processing block in add_comment**

In `backend/main.py`, replace lines 263-333 (the `if ai and req.author != "ai":` block) with:

```python
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
                    git.read_file(
                        f"sessions/{session_id}/sections/{meta.filename}.md"
                    )
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
                    section_guidance=(
                        section_def.guidance if section_def else ""
                    ),
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
                            sessions.set_agent_session_id(
                                session_id, agent_session_id
                            )

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
                                    "proposal": proposal.model_dump(
                                        mode="json"
                                    ),
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
```

- [ ] **Step 2: Run the comment-related API tests**

Run: `pytest tests/test_api_ai.py::TestCommentWithAI -v`
Expected: Pass. The comment tests still work because `process_comment` is now a generator consumed inline — the end result (proposals/replies created) is the same.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: stream AI activity events during comment processing"
```

---

### Task 7: Update create_session endpoint with background task

**Files:**
- Modify: `backend/main.py:131-205` (create_session endpoint)

- [ ] **Step 1: Replace create_session endpoint**

In `backend/main.py`, replace the entire `create_session` function (the `@app.post("/api/sessions")` handler, lines 131-205) with:

```python
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
                            meta = session.section_meta.get(
                                event["section_id"]
                            )
                            if meta:
                                section_path = (
                                    f"sessions/{session.id}/sections/"
                                    f"{meta.filename}.md"
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
                                        "type": "section_drafted",
                                        "section_id": event["section_id"],
                                        "status": "draft",
                                    },
                                )
                        elif event["type"] == "drafts_complete":
                            agent_session_id = event.get("session_id")

                    if agent_session_id:
                        sessions.set_agent_session_id(
                            session.id, agent_session_id
                        )
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

            asyncio.create_task(draft_in_background())

        result = sessions.get_session(session.id)
        return JSONResponse(result.model_dump(mode="json"), status_code=201)
```

- [ ] **Step 2: Add missing imports to main.py**

Add `asyncio` to imports at the top of `backend/main.py`:

```python
import asyncio
```

Add `SectionStatus` to the models import:

```python
from backend.models import ParticipantInput, SectionStatus, SessionStatus, User
```

Remove `StreamingResponse` from the starlette import (line 11) since it's no longer used:

```python
from starlette.responses import JSONResponse, Response
```

- [ ] **Step 3: Run all API AI tests**

Run: `pytest tests/test_api_ai.py -v`
Expected: All tests pass.

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: replace NDJSON streaming with background task and WebSocket broadcasts"
```

---

### Task 8: Frontend HTML and CSS

**Files:**
- Modify: `frontend/index.html:62-93` (workspace view)
- Modify: `frontend/style.css` (add log panel styles + DRAFTING badge)

- [ ] **Step 1: Add activity log panel HTML**

In `frontend/index.html`, add the log panel inside `#view-workspace`, after the `#review-area` div (after line 92, before the closing `</div>` of `#view-workspace`):

```html
      <div id="ai-log-panel" class="ai-log-collapsed">
        <div id="ai-log-toggle" class="ai-log-toggle">
          <span>AI Activity</span>
          <span id="ai-log-dot" class="ai-log-dot" style="display:none"></span>
        </div>
        <div id="ai-log-body" class="ai-log-body">
          <div id="ai-log-entries"></div>
        </div>
      </div>
```

- [ ] **Step 2: Add CSS for DRAFTING badge**

In `frontend/style.css`, add after the `.badge-skipped` rule (after line 171):

```css
.badge-drafting { background: #f59e0b; color: white; animation: pulse-badge 1.5s ease-in-out infinite; }
@keyframes pulse-badge { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
```

- [ ] **Step 3: Add CSS for activity log panel**

In `frontend/style.css`, add at the end of the file:

```css
#ai-log-panel {
  position: fixed; bottom: 0; left: 220px; right: 0;
  background: var(--surface); border-top: 1px solid var(--border);
  z-index: 50; transition: max-height 0.2s ease;
}
.ai-log-collapsed #ai-log-body { display: none; }
.ai-log-toggle {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 1rem; cursor: pointer; font-size: 0.8rem;
  font-weight: 600; color: var(--text-secondary);
  user-select: none; border-bottom: 1px solid var(--border);
}
.ai-log-toggle:hover { color: var(--text); }
.ai-log-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--primary); animation: pulse-dot 1s ease-in-out infinite;
}
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.ai-log-body { max-height: 200px; overflow-y: auto; padding: 0.5rem 1rem; }
#ai-log-entries { display: flex; flex-direction: column; gap: 0.15rem; }
.ai-log-entry { font-size: 0.8rem; font-family: "SF Mono", "Fira Code", monospace; color: var(--text-secondary); line-height: 1.4; }
.ai-log-entry.error { color: #dc2626; }
.ai-log-entry.complete { color: var(--success); font-weight: 500; }
```

- [ ] **Step 4: Verify HTML is valid**

Open `frontend/index.html` in a browser or check structure manually — the new `#ai-log-panel` div should be the last child of `#view-workspace`.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/style.css
git commit -m "feat: add activity log panel HTML/CSS and DRAFTING badge styles"
```

---

### Task 9: Frontend JavaScript

**Files:**
- Modify: `frontend/app.js` (add log panel state + rendering, update WebSocket handlers, remove NDJSON reader)

- [ ] **Step 1: Add AI log state variables**

In `frontend/app.js`, add to the `state` object (after line 39, before the closing `}`):

```javascript
  aiLogOpen: false,
  aiLogHasNew: false,
  aiLogAutoOpened: false,
```

- [ ] **Step 2: Add log panel rendering functions**

Add after the `formatTime` function (after line 72):

```javascript
function appendAiLog(text, className) {
  const entries = document.getElementById('ai-log-entries');
  if (!entries) return;

  const entry = document.createElement('div');
  entry.className = 'ai-log-entry' + (className ? ' ' + className : '');
  entry.textContent = text;
  entries.appendChild(entry);

  const body = document.getElementById('ai-log-body');
  if (body) {
    const isScrolledToBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    if (isScrolledToBottom) body.scrollTop = body.scrollHeight;
  }
}

function showAiLogPanel() {
  const panel = document.getElementById('ai-log-panel');
  if (!panel) return;
  panel.style.display = '';
}

function toggleAiLog() {
  const panel = document.getElementById('ai-log-panel');
  if (!panel) return;
  state.aiLogOpen = !state.aiLogOpen;
  panel.classList.toggle('ai-log-collapsed', !state.aiLogOpen);
  if (state.aiLogOpen) {
    state.aiLogHasNew = false;
    document.getElementById('ai-log-dot').style.display = 'none';
  }
}

function clearAiLog() {
  const entries = document.getElementById('ai-log-entries');
  if (entries) entries.textContent = '';
  state.aiLogAutoOpened = false;
  state.aiLogHasNew = false;
  state.aiLogOpen = false;
  const panel = document.getElementById('ai-log-panel');
  if (panel) {
    panel.classList.add('ai-log-collapsed');
    panel.style.display = 'none';
  }
  const dot = document.getElementById('ai-log-dot');
  if (dot) dot.style.display = 'none';
}
```

- [ ] **Step 3: Add log toggle event listener in init()**

In the `init()` function, add after the existing event listeners (around line 1216):

```javascript
  document.getElementById('ai-log-toggle').addEventListener('click', toggleAiLog);
```

- [ ] **Step 4: Clear log on session switch**

In the `openSession` function, add `clearAiLog();` after line 392 (after `state.activeSection = null;`):

```javascript
  clearAiLog();
```

- [ ] **Step 5: Update handleWsMessage for new event types**

In `frontend/app.js`, replace the `handleWsMessage` function with:

```javascript
async function handleWsMessage(msg) {
  const sid = state.currentSession ? state.currentSession.id : null;
  if (!sid) return;

  const sectionId = msg.section_id;

  if (msg.type === 'ai_activity') {
    showAiLogPanel();
    if (!state.aiLogAutoOpened) {
      state.aiLogAutoOpened = true;
      state.aiLogOpen = true;
      document.getElementById('ai-log-panel').classList.remove('ai-log-collapsed');
    }
    if (!state.aiLogOpen) {
      state.aiLogHasNew = true;
      document.getElementById('ai-log-dot').style.display = '';
    }
    appendAiLog(msg.text, msg.error ? 'error' : '');
  } else if (msg.type === 'ai_complete') {
    appendAiLog('AI processing complete.', 'complete');
  } else if (msg.type === 'drafts_started') {
    showAiLogPanel();
    appendAiLog('Generating drafts...', '');
    state.currentSession = await apiFetch(sessionPath(sid));
    renderSidebar();
  } else if (msg.type === 'section_drafted' && sectionId) {
    appendAiLog('Drafted: ' + sectionId, '');
    state.currentSession = await apiFetch(sessionPath(sid));
    state.sectionContent[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId);
    renderSidebar();
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'drafts_complete') {
    appendAiLog('All drafts complete.', 'complete');
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'drafts_failed') {
    appendAiLog(msg.message || 'Draft generation failed.', 'error');
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'comment_added' && sectionId) {
    state.sectionComments[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/comments');
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'proposal_created' && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    if (state.activeSection === sectionId) renderReviewArea();
    renderSidebar();
  } else if ((msg.type === 'proposal_accepted' || msg.type === 'proposal_rejected') && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    state.sectionContent[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId);
    if (state.activeSection === sectionId) renderReviewArea();
    renderSidebar();
  } else if (msg.type === 'section_approved' || msg.type === 'section_reopened' || msg.type === 'section_skipped') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'session_published') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'section_assigned') {
    state.currentSession = await apiFetch(sessionPath(sid));
    renderSidebar();
  }
}
```

- [ ] **Step 6: Remove NDJSON reader from handleCreateSession**

In `frontend/app.js`, replace `handleCreateSession` (lines 238-333) with:

```javascript
async function handleCreateSession(e) {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = '';
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  submitBtn.appendChild(spinner);
  submitBtn.appendChild(document.createTextNode('Creating…'));

  const slug = document.getElementById('template-select').value;
  const seedText = document.getElementById('seed-text').value.trim();

  const template = state.templates.find(t => (t.slug || t.name) === slug);
  const coordinatorId = document.getElementById('coordinator-select').value;

  const assignments = {};
  document.querySelectorAll('.section-owner-select').forEach(sel => {
    const sectionId = sel.dataset.sectionId;
    let userId = sel.value;
    if (!userId) {
      const sectionDef = template && template.sections.find(s => s.id === sectionId);
      if (sectionDef && sectionDef.priority === 'required') {
        userId = coordinatorId;
      }
    }
    if (userId) {
      if (!assignments[userId]) assignments[userId] = [];
      assignments[userId].push(sectionId);
    }
  });

  const participants = Object.entries(assignments).map(([userId, sections]) => {
    const user = state.users.find(u => u.id === userId);
    const role = (user && user.default_roles && user.default_roles[0]) || 'participant';
    return { user_id: userId, assigned_sections: sections, role };
  });

  try {
    const session = await apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        template: slug,
        coordinator: coordinatorId,
        participants: participants,
        seed_text: seedText || undefined,
      }),
    });

    if (session) {
      showInviteLinks(session);
      window.history.pushState({}, '', '/session/' + session.id);
      await openSession(session.id);
    }
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Create Session';
  }
}
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/app.js
git commit -m "feat: add AI activity log panel and WebSocket handlers, remove NDJSON reader"
```

---

### Final Verification

After all tasks are complete:

- [ ] **Run the full test suite**

```bash
pytest tests/ -v
```

- [ ] **Run linting**

```bash
ruff check .
ruff format --check .
```

- [ ] **Manual smoke test** (if dev server is available)

```bash
DRAFTCIRCLE_DATA_REPO=/path/to/data-repo uvicorn backend.main:create_app --factory --reload --port 8000
```

1. Create a session with seed text — verify it returns immediately and the log panel shows draft progress.
2. Post a comment — verify AI activity streams to the log panel, then proposal/reply appears.
3. Verify DRAFTING badges pulse while drafts are generating.
4. Verify the log panel auto-opens on first AI activity, then respects toggle.
