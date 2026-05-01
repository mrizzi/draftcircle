import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ai_orchestrator import (
    AIOrchestrator,
    DraftResult,
    ProposalResult,
    ReplyResult,
)
from backend.git_store import GitStore


def make_tool_use_block(name: str, input_data: dict, tool_id: str = "tool_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_data
    return block


def make_text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def make_response(*content_blocks, stop_reason="end_turn"):
    response = MagicMock()
    response.content = list(content_blocks)
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


@pytest.fixture()
def git(data_repo):
    store = GitStore(data_repo)
    store.commit("init", {"sessions/test-session/session.json": "{}"})
    return store


@pytest.fixture()
def orchestrator(git, mock_client):
    return AIOrchestrator(client=mock_client, git=git)


class TestConversationPersistence:
    @pytest.mark.asyncio
    async def test_saves_conversation_after_interaction(self, orchestrator, git):
        orchestrator._client.messages.create.return_value = make_response(
            make_text_block("Hello"),
            stop_reason="end_turn",
        )
        await orchestrator._send_message(
            session_id="test-session",
            system="You are a helper.",
            user_content="Hi there",
        )
        history_content = git.read_file("sessions/test-session/ai_history.json")
        assert history_content is not None
        history = json.loads(history_content)
        assert len(history["messages"]) == 2
        assert history["messages"][0]["role"] == "user"
        assert history["messages"][1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_loads_existing_conversation(self, orchestrator, git):
        existing = {
            "system": "You are a helper.",
            "messages": [
                {"role": "user", "content": "First message"},
                {"role": "assistant", "content": "First reply"},
            ],
        }
        git.commit(
            "save history",
            {"sessions/test-session/ai_history.json": json.dumps(existing)},
        )
        orchestrator._client.messages.create.return_value = make_response(
            make_text_block("Second reply"),
        )
        await orchestrator._send_message(
            session_id="test-session",
            system="You are a helper.",
            user_content="Second message",
        )
        call_args = orchestrator._client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 4
        assert messages[0]["content"] == "First message"
        assert messages[2]["content"] == "Second message"


class TestGenerateDrafts:
    @pytest.mark.asyncio
    async def test_generates_draft_for_each_section(self, orchestrator):
        from backend.models import Template
        from tests.conftest import SAMPLE_TEMPLATE

        template = Template.model_validate(SAMPLE_TEMPLATE)
        orchestrator._client.messages.create.return_value = make_response(
            make_tool_use_block(
                "write_section_draft",
                {"section_id": "overview", "content": "# Overview\n\nDraft content."},
                tool_id="tool_1",
            ),
            make_tool_use_block(
                "write_section_draft",
                {"section_id": "details", "content": "# Details\n\nMore content."},
                tool_id="tool_2",
            ),
            make_tool_use_block(
                "write_section_draft",
                {"section_id": "notes", "content": "# Notes\n\nSome notes."},
                tool_id="tool_3",
            ),
            stop_reason="tool_use",
        )
        drafts = await orchestrator.generate_drafts(
            session_id="test-session",
            template=template,
            seed_content="Feature X enables users to do Y.",
        )
        assert len(drafts) == 3
        assert drafts[0].section_id == "overview"
        assert "Draft content" in drafts[0].content

    @pytest.mark.asyncio
    async def test_sends_seed_and_template_context(self, orchestrator):
        from backend.models import Template
        from tests.conftest import SAMPLE_TEMPLATE

        template = Template.model_validate(SAMPLE_TEMPLATE)
        orchestrator._client.messages.create.return_value = make_response(
            make_tool_use_block(
                "write_section_draft",
                {"section_id": "overview", "content": "draft"},
                tool_id="tool_1",
            ),
            stop_reason="tool_use",
        )
        await orchestrator.generate_drafts(
            session_id="test-session",
            template=template,
            seed_content="Seed material here",
        )
        call_args = orchestrator._client.messages.create.call_args
        user_messages = [
            m
            for m in call_args.kwargs["messages"]
            if m["role"] == "user" and isinstance(m["content"], str)
        ]
        assert "Seed material here" in user_messages[-1]["content"]
        assert template.ai_context in call_args.kwargs["system"]


class TestProcessComment:
    @pytest.mark.asyncio
    async def test_returns_proposal_when_revision_needed(self, orchestrator):
        orchestrator._client.messages.create.return_value = make_response(
            make_tool_use_block(
                "propose_revision",
                {
                    "revised_text": "Updated draft with rate limiting.",
                    "summary": "Added rate limiting per Alice's comment",
                },
            ),
            stop_reason="tool_use",
        )
        result = await orchestrator.process_comment(
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
    async def test_returns_reply_when_no_revision_needed(self, orchestrator):
        orchestrator._client.messages.create.return_value = make_response(
            make_tool_use_block(
                "post_reply",
                {
                    "text": "Good question — rate limiting is already covered in section 5."
                },
            ),
            stop_reason="tool_use",
        )
        result = await orchestrator.process_comment(
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
    async def test_includes_comment_thread_in_prompt(self, orchestrator):
        orchestrator._client.messages.create.return_value = make_response(
            make_tool_use_block("post_reply", {"text": "reply"}),
            stop_reason="tool_use",
        )
        thread = [
            {"author": "alice", "text": "First comment"},
            {"author": "bob", "text": "I agree"},
        ]
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
        call_args = orchestrator._client.messages.create.call_args
        user_messages = [
            m
            for m in call_args.kwargs["messages"]
            if m["role"] == "user" and isinstance(m["content"], str)
        ]
        user_msg = user_messages[-1]["content"]
        assert "First comment" in user_msg
        assert "New comment" in user_msg

    @pytest.mark.asyncio
    async def test_uses_section_lock(self, orchestrator):
        call_order = []

        async def slow_create(**kwargs):
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("end")
            return make_response(
                make_tool_use_block("post_reply", {"text": "reply"}),
                stop_reason="tool_use",
            )

        orchestrator._client.messages.create = AsyncMock(side_effect=slow_create)

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

    @pytest.mark.asyncio
    async def test_fallback_reply_when_no_tool_used(self, orchestrator):
        orchestrator._client.messages.create.return_value = make_response(
            make_text_block("I'm not sure what to do here."),
            stop_reason="end_turn",
        )
        result = await orchestrator.process_comment(
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


class TestGenerateDraftsEdgeCases:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_tool_used(self, orchestrator):
        from backend.models import Template
        from tests.conftest import SAMPLE_TEMPLATE

        template = Template.model_validate(SAMPLE_TEMPLATE)
        orchestrator._client.messages.create.return_value = make_response(
            make_text_block("I can't generate drafts right now."),
            stop_reason="end_turn",
        )
        drafts = await orchestrator.generate_drafts(
            session_id="test-session",
            template=template,
            seed_content="Seed material",
        )
        assert drafts == []


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
