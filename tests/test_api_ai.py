import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.conftest import SAMPLE_TEMPLATE, SAMPLE_USERS
from tests.test_ai_orchestrator import make_response, make_tool_use_block


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture()
def app_with_ai(populated_data_repo, mock_client):
    from backend.git_store import GitStore

    git = GitStore(populated_data_repo)
    git.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE),
            "users.json": json.dumps(SAMPLE_USERS),
        },
    )
    return create_app(
        data_repo_path=populated_data_repo,
        anthropic_client=mock_client,
    )


@pytest.fixture()
def client_ai(app_with_ai):
    return TestClient(app_with_ai)


@pytest.fixture()
def mock_draft_response():
    return make_response(
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "overview", "content": "AI-generated overview."},
            tool_id="t1",
        ),
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "details", "content": "AI-generated details."},
            tool_id="t2",
        ),
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "notes", "content": "AI-generated notes."},
            tool_id="t3",
        ),
        stop_reason="tool_use",
    )


class TestSessionCreationWithAI:
    def test_generates_drafts_on_creation(
        self, client_ai, mock_client, mock_draft_response
    ):
        mock_client.messages.create.return_value = mock_draft_response
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

    def test_works_without_seed(self, client_ai, mock_client):
        resp = client_ai.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [],
            },
        )
        assert resp.status_code == 201
        mock_client.messages.create.assert_not_called()
