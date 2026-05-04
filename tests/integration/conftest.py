# tests/integration/conftest.py
import json
from unittest.mock import AsyncMock, MagicMock

import pygit2
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.conftest import SAMPLE_TEMPLATE
from tests.test_ai_orchestrator import make_response, make_tool_use_block

INTEGRATION_USERS = {
    "users": [
        {
            "id": "alice",
            "name": "Alice Chen",
            "email": "alice@example.com",
            "default_roles": ["product-manager"],
        },
        {
            "id": "bob",
            "name": "Bob Kumar",
            "email": "bob@example.com",
            "default_roles": ["architect"],
        },
        {
            "id": "carol",
            "name": "Carol Reyes",
            "email": "carol@example.com",
            "default_roles": ["engineer"],
        },
    ]
}

DRAFT_CONTENT = {
    "overview": "# Overview\n\nInitial draft for the overview section.",
    "details": "# Details\n\nInitial draft for the details section.",
    "notes": "# Notes\n\nInitial draft for the notes section.",
}

REVISED_TEXT = "# Overview\n\nRevised draft with improvements based on feedback."
PROPOSAL_SUMMARY = "Expanded overview with more detail per reviewer feedback."


def _mock_draft_response():
    return make_response(
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "overview", "content": DRAFT_CONTENT["overview"]},
            "t1",
        ),
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "details", "content": DRAFT_CONTENT["details"]},
            "t2",
        ),
        make_tool_use_block(
            "write_section_draft",
            {"section_id": "notes", "content": DRAFT_CONTENT["notes"]},
            "t3",
        ),
        stop_reason="end_turn",
    )


def _mock_proposal_response():
    return make_response(
        make_tool_use_block(
            "propose_revision",
            {"revised_text": REVISED_TEXT, "summary": PROPOSAL_SUMMARY},
            "t1",
        ),
        stop_reason="end_turn",
    )


def _ai_side_effect(*args, **kwargs):
    tools = kwargs.get("tools") or []
    tool_names = {t["name"] for t in tools}
    if "write_section_draft" in tool_names:
        return _mock_draft_response()
    return _mock_proposal_response()


@pytest.fixture()
def integration_app(tmp_path):
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    pygit2.init_repository(str(data_repo))

    git_store = __import__("backend.git_store", fromlist=["GitStore"]).GitStore(
        data_repo
    )
    templates_dir = data_repo / "templates"
    templates_dir.mkdir()
    git_store.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE, indent=2),
            "users.json": json.dumps(INTEGRATION_USERS, indent=2),
        },
    )

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=_ai_side_effect)

    app = create_app(data_repo_path=str(data_repo), anthropic_client=mock_client)
    app.state.mock_client = mock_client
    app.state.data_repo_path = data_repo
    return app


@pytest.fixture()
def api(integration_app):
    return TestClient(integration_app, raise_server_exceptions=False)


@pytest.fixture()
def session_with_drafts(api):
    resp = api.post(
        "/api/sessions",
        json={
            "template": "test-template",
            "coordinator": "alice",
            "participants": [
                {
                    "user_id": "alice",
                    "assigned_sections": ["overview", "details", "notes"],
                    "role": "coordinator",
                },
                {
                    "user_id": "bob",
                    "assigned_sections": ["overview"],
                    "role": "participant",
                },
                {
                    "user_id": "carol",
                    "assigned_sections": ["details"],
                    "role": "participant",
                },
            ],
            "seed_text": "This is seed content for integration testing.",
        },
    )
    assert resp.status_code == 201
    session = resp.json()
    tokens = {p["user_id"]: p["token"] for p in session["participants"]}
    return {"id": session["id"], "tokens": tokens, "session": session}


def drain_join_messages(*websockets):
    """Read and discard participant_joined messages from WebSocket connections.

    Call after all clients have connected. Each ws receives one
    participant_joined message for every client that connected
    (including itself), broadcast at connect time. With 3 clients
    connecting in order (ws_a, ws_b, ws_c):
      ws_a receives 3 (own + 2 subsequent joins)
      ws_b receives 2 (own + 1 subsequent join)
      ws_c receives 1 (own)
    """
    count = len(websockets)
    for i, ws in enumerate(websockets):
        for _ in range(count - i):
            msg = ws.receive_json()
            assert msg["type"] == "participant_joined"
