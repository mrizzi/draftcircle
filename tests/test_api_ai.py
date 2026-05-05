import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.conftest import parse_create_session_response
from tests.test_ai_orchestrator import mock_agent_messages


@pytest.fixture()
def app_with_ai(populated_data_repo):
    return create_app(data_repo_path=str(populated_data_repo))


@pytest.fixture()
def client_ai(app_with_ai):
    return TestClient(app_with_ai)


class TestSessionCreationWithAI:
    def test_generates_drafts_on_creation(self, client_ai):
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
        assert resp.status_code == 201
        session = parse_create_session_response(resp)
        session_id = session["id"]

        section_resp = client_ai.get(f"/api/sessions/{session_id}/sections/overview")
        assert section_resp.json()["content"] == "AI-generated overview."

    def test_streams_progress_during_draft_generation(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    ("write_section_draft", {"section_id": "overview", "content": "O"}),
                    ("write_section_draft", {"section_id": "details", "content": "D"}),
                ],
                session_id="s1",
            )
            resp = client_ai.post(
                "/api/sessions",
                json={
                    "template": "test-template",
                    "coordinator": "alice",
                    "participants": [],
                    "seed_text": "Seed.",
                },
            )
        assert resp.status_code == 201
        assert "application/x-ndjson" in resp.headers["content-type"]

        lines = [
            json.loads(line) for line in resp.text.strip().split("\n") if line.strip()
        ]
        progress_msgs = [msg for msg in lines if msg["type"] == "progress"]
        done_msgs = [msg for msg in lines if msg["type"] == "done"]

        assert len(progress_msgs) >= 1
        assert any("Generating drafts" in m["message"] for m in progress_msgs)
        assert any("overview" in m["message"] for m in progress_msgs)
        assert len(done_msgs) == 1
        assert "id" in done_msgs[0]["session"]

    def test_no_streaming_without_seed(self, client_ai):
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
        assert "id" in resp.json()

    def test_works_without_seed(self, client_ai):
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
        mock_query.assert_not_called()


class TestCommentWithAI:
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
        return parse_create_session_response(resp)["id"]

    def test_comment_triggers_proposal(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = [
                mock_agent_messages(
                    tool_calls=[
                        (
                            "write_section_draft",
                            {
                                "section_id": "overview",
                                "content": "AI-generated overview.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {
                                "section_id": "details",
                                "content": "AI-generated details.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {"section_id": "notes", "content": "AI-generated notes."},
                        ),
                    ],
                    session_id="s1",
                ),
                mock_agent_messages(
                    tool_calls=[
                        (
                            "propose_revision",
                            {
                                "revised_text": "Revised overview with more detail.",
                                "summary": "Added detail per comment",
                            },
                        ),
                    ],
                    session_id="s2",
                ),
            ]

            session_id = self._create_session_with_drafts(
                client_ai,
                mock_query,
                participants=[
                    {
                        "user_id": "alice",
                        "assigned_sections": ["overview"],
                        "role": "pm",
                    }
                ],
            )

            comment_resp = client_ai.post(
                f"/api/sessions/{session_id}/comments",
                json={
                    "section_id": "overview",
                    "author": "alice",
                    "text": "Add more detail please",
                },
            )
        assert comment_resp.status_code == 201

        proposals_resp = client_ai.get(
            f"/api/sessions/{session_id}/sections/overview/proposals"
        )
        proposals = proposals_resp.json()
        assert len(proposals) == 1
        assert proposals[0]["summary"] == "Added detail per comment"

    def test_comment_triggers_reply(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = [
                mock_agent_messages(
                    tool_calls=[
                        (
                            "write_section_draft",
                            {
                                "section_id": "overview",
                                "content": "AI-generated overview.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {
                                "section_id": "details",
                                "content": "AI-generated details.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {"section_id": "notes", "content": "AI-generated notes."},
                        ),
                    ],
                    session_id="s1",
                ),
                mock_agent_messages(
                    tool_calls=[
                        (
                            "post_reply",
                            {"text": "That's already covered in the requirements."},
                        )
                    ],
                    session_id="s2",
                ),
            ]

            session_id = self._create_session_with_drafts(client_ai, mock_query)

            client_ai.post(
                f"/api/sessions/{session_id}/comments",
                json={
                    "section_id": "overview",
                    "author": "alice",
                    "text": "Is this covered?",
                },
            )

        comments_resp = client_ai.get(
            f"/api/sessions/{session_id}/sections/overview/comments"
        )
        comments = comments_resp.json()
        assert len(comments) == 2
        assert comments[1]["author"] == "ai"
        assert "already covered" in comments[1]["text"]


class TestAIGracefulDegradation:
    def test_session_created_despite_ai_failure(self, client_ai):
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
        session = parse_create_session_response(resp)
        session_id = session["id"]
        section_resp = client_ai.get(f"/api/sessions/{session_id}/sections/overview")
        assert section_resp.json()["content"] == ""

    def test_comment_persisted_despite_ai_failure(self, client_ai):
        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.side_effect = [
                mock_agent_messages(
                    tool_calls=[
                        (
                            "write_section_draft",
                            {
                                "section_id": "overview",
                                "content": "AI-generated overview.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {
                                "section_id": "details",
                                "content": "AI-generated details.",
                            },
                        ),
                        (
                            "write_section_draft",
                            {"section_id": "notes", "content": "AI-generated notes."},
                        ),
                    ],
                    session_id="s1",
                ),
                RuntimeError("API down"),
            ]

            resp = client_ai.post(
                "/api/sessions",
                json={
                    "template": "test-template",
                    "coordinator": "alice",
                    "participants": [],
                    "seed_text": "Feature X.",
                },
            )
            session_id = parse_create_session_response(resp)["id"]

            resp = client_ai.post(
                f"/api/sessions/{session_id}/comments",
                json={
                    "section_id": "overview",
                    "author": "alice",
                    "text": "Please fix this",
                },
            )
        assert resp.status_code == 201
        comments = client_ai.get(
            f"/api/sessions/{session_id}/sections/overview/comments"
        ).json()
        assert len(comments) == 1
        assert comments[0]["author"] == "alice"
