import asyncio
from unittest.mock import patch

import pytest

from backend.ai_orchestrator import (
    AIOrchestrator,
    DraftResult,
    ProposalResult,
    ReplyResult,
)
from backend.models import Template
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from tests.conftest import SAMPLE_TEMPLATE


def mock_agent_messages(tool_calls=None, text=None, session_id="test-session"):
    """Create an async generator mimicking query() output."""
    messages = []
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


class TestGenerateDrafts:
    @pytest.mark.asyncio
    async def test_generates_drafts(self):
        orchestrator = AIOrchestrator()
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
            drafts, sid = await orchestrator.generate_drafts(
                session_id=None,
                template=template,
                seed_content="Feature X enables users to do Y.",
            )

        assert len(drafts) == 3
        assert drafts[0].section_id == "overview"
        assert "Draft content" in drafts[0].content
        assert drafts[1].section_id == "details"
        assert drafts[2].section_id == "notes"

    @pytest.mark.asyncio
    async def test_returns_session_id(self):
        orchestrator = AIOrchestrator()
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
            _, sid = await orchestrator.generate_drafts(
                session_id=None, template=template, seed_content="Seed."
            )

        assert sid == "sess-456"

    @pytest.mark.asyncio
    async def test_sends_seed_and_template_context(self):
        orchestrator = AIOrchestrator()
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
            await orchestrator.generate_drafts(
                session_id=None,
                template=template,
                seed_content="Seed material here",
            )

            call_args = mock_query.call_args
            prompt = call_args[0][0]
            opts = call_args[0][1]

            assert "Seed material here" in prompt
            assert "overview" in prompt.lower()
            assert opts.system_prompt == template.ai_context

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tools(self):
        orchestrator = AIOrchestrator()
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                text="I can't generate drafts right now.",
            )
            drafts, sid = await orchestrator.generate_drafts(
                session_id=None,
                template=template,
                seed_content="Seed material",
            )

        assert drafts == []


class TestProcessComment:
    @pytest.mark.asyncio
    async def test_returns_proposal(self):
        orchestrator = AIOrchestrator()

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
            result, _ = await orchestrator.process_comment(
                session_id="test-session",
                section_id="nfrs",
                section_title="Non-Functional Requirements",
                section_guidance="Architecture characteristics and NFRs",
                current_draft="Initial NFR draft.",
                comment_thread=[],
                new_comment_author="alice",
                new_comment_text="We need rate limiting.",
            )

        assert isinstance(result, ProposalResult)
        assert "rate limiting" in result.revised_text

    @pytest.mark.asyncio
    async def test_returns_reply(self):
        orchestrator = AIOrchestrator()

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
            result, _ = await orchestrator.process_comment(
                session_id="test-session",
                section_id="nfrs",
                section_title="NFRs",
                section_guidance="NFR guidance",
                current_draft="Draft.",
                comment_thread=[],
                new_comment_author="bob",
                new_comment_text="Is rate limiting covered?",
            )

        assert isinstance(result, ReplyResult)
        assert "rate limiting" in result.text

    @pytest.mark.asyncio
    async def test_includes_thread_in_prompt(self):
        orchestrator = AIOrchestrator()
        thread = [
            {"author": "alice", "text": "First comment"},
            {"author": "bob", "text": "I agree"},
        ]

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "reply"})],
            )
            await orchestrator.process_comment(
                session_id="test-session",
                section_id="overview",
                section_title="Overview",
                section_guidance="Write an overview",
                current_draft="Draft.",
                comment_thread=thread,
                new_comment_author="alice",
                new_comment_text="New comment",
            )

            call_args = mock_query.call_args
            prompt = call_args[0][0]
            assert "First comment" in prompt
            assert "New comment" in prompt

    @pytest.mark.asyncio
    async def test_fallback_reply_no_tool(self):
        orchestrator = AIOrchestrator()

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                text="I'm not sure what to do here.",
            )
            result, _ = await orchestrator.process_comment(
                session_id="test-session",
                section_id="overview",
                section_title="Overview",
                section_guidance="Write an overview",
                current_draft="Draft.",
                comment_thread=[],
                new_comment_author="alice",
                new_comment_text="Please revise",
            )

        assert isinstance(result, ReplyResult)
        assert result.text == "I've noted your comment."

    @pytest.mark.asyncio
    async def test_returns_session_id(self):
        orchestrator = AIOrchestrator()

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
                session_id="sess-789",
            )
            _, sid = await orchestrator.process_comment(
                session_id="test-session",
                section_id="overview",
                section_title="Overview",
                section_guidance="Write an overview",
                current_draft="Draft.",
                comment_thread=[],
                new_comment_author="alice",
                new_comment_text="Comment",
            )

        assert sid == "sess-789"

    @pytest.mark.asyncio
    async def test_passes_resume_id(self):
        orchestrator = AIOrchestrator()

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[("post_reply", {"text": "noted"})],
            )
            await orchestrator.process_comment(
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

            call_args = mock_query.call_args
            opts = call_args[0][1]
            assert opts.resume == "existing-session-42"

    @pytest.mark.asyncio
    async def test_section_lock(self):
        orchestrator = AIOrchestrator()
        call_order = []

        def slow_query(prompt, opts):
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
                orchestrator.process_comment(
                    "test-session",
                    "overview",
                    "Overview",
                    "g",
                    "Draft.",
                    [],
                    "alice",
                    "comment 1",
                ),
                orchestrator.process_comment(
                    "test-session",
                    "overview",
                    "Overview",
                    "g",
                    "Draft.",
                    [],
                    "bob",
                    "comment 2",
                ),
            )

        assert call_order == ["start", "end", "start", "end"]


class TestResultDataclasses:
    def test_draft_result_rejects_empty_section_id(self):
        with pytest.raises(ValueError, match="section_id"):
            DraftResult(section_id="", content="some content")

    def test_draft_result_rejects_empty_content(self):
        with pytest.raises(ValueError, match="content"):
            DraftResult(section_id="overview", content="")

    def test_proposal_result_rejects_empty_revised_text(self):
        with pytest.raises(ValueError, match="revised_text"):
            ProposalResult(revised_text="", summary="changed something")

    def test_reply_result_rejects_empty_text(self):
        with pytest.raises(ValueError, match="text"):
            ReplyResult(text="")
