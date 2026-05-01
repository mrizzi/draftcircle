import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ai_orchestrator import AIOrchestrator
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
def mock_client():
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


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
