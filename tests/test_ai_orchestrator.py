import asyncio
from unittest.mock import patch

import pytest

from backend.ai_orchestrator import (
    AIOrchestrator,
    ProposalResult,
    ReplyResult,
)
from backend.git_store import GitStore
from backend.models import Template
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKError,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
)
from tests.conftest import SAMPLE_TEMPLATE


@pytest.fixture()
def orchestrator(data_repo):
    git = GitStore(data_repo)
    return AIOrchestrator(git=git)


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


async def collect_events(gen):
    """Consume an async generator and return all yielded events as a list."""
    events = []
    async for event in gen:
        events.append(event)
    return events


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

    @pytest.mark.asyncio
    async def test_event_ordering(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "d"},
                    ),
                ],
                stream_text=["thinking..."],
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )

        types = [e["type"] for e in events]
        assert types.index("ai_activity") < types.index("section_drafted")
        assert types.index("section_drafted") < types.index("drafts_complete")
        assert types[-1] == "drafts_complete"

    @pytest.mark.asyncio
    async def test_yields_unknown_section_id(self, orchestrator):
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "bogus", "content": "x"},
                    ),
                ],
            )
            events = await collect_events(
                orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            )

        drafted = [e for e in events if e["type"] == "section_drafted"]
        assert len(drafted) == 1
        assert drafted[0]["section_id"] == "bogus"


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
                        "test-session",
                        "overview",
                        "Overview",
                        "g",
                        "Draft.",
                        [],
                        "alice",
                        "comment 1",
                    )
                ),
                collect_events(
                    orchestrator.process_comment(
                        "test-session",
                        "overview",
                        "Overview",
                        "g",
                        "Draft.",
                        [],
                        "bob",
                        "comment 2",
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

    @pytest.mark.asyncio
    async def test_event_ordering(self, orchestrator):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
                stream_text=["thinking..."],
            )
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

        types = [e["type"] for e in events]
        assert all(
            i < types.index("ai_complete")
            for i, t in enumerate(types)
            if t == "ai_activity"
        )
        assert types[-1] == "ai_complete"


class TestResultDataclasses:
    def test_proposal_result_rejects_empty_revised_text(self):
        with pytest.raises(ValueError, match="revised_text"):
            ProposalResult(revised_text="", summary="changed something")

    def test_reply_result_rejects_empty_text(self):
        with pytest.raises(ValueError, match="text"):
            ReplyResult(text="")


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
    async def test_stale_session_retries_without_resume(self, orchestrator, data_repo):
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
                raise ClaudeSDKError("No conversation found with session ID: stale")
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
