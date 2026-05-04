import json

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.conftest import SAMPLE_TEMPLATE, SAMPLE_USERS


@pytest.fixture()
def app(populated_data_repo):
    from backend.git_store import GitStore

    git = GitStore(populated_data_repo)
    git.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE),
            "users.json": json.dumps(SAMPLE_USERS),
        },
    )
    return create_app(data_repo_path=populated_data_repo)


@pytest.fixture()
def client(app):
    return TestClient(app)


class TestTemplateEndpoints:
    def test_list_templates(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Test Template"

    def test_get_template(self, client):
        resp = client.get("/api/templates/test-template")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Template"

    def test_get_template_not_found(self, client):
        resp = client.get("/api/templates/nonexistent")
        assert resp.status_code == 404


class TestUserEndpoints:
    def test_list_users(self, client):
        resp = client.get("/api/users")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_add_user(self, client):
        resp = client.post(
            "/api/users",
            json={
                "id": "carol",
                "name": "Carol Davis",
                "email": "carol@example.com",
                "default_roles": ["tech-writer"],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == "carol"
        resp = client.get("/api/users")
        assert len(resp.json()) == 3

    def test_add_duplicate_user(self, client):
        resp = client.post(
            "/api/users", json={"id": "alice", "name": "Dup", "email": "d@e.com"}
        )
        assert resp.status_code == 409


class TestSessionEndpoints:
    def test_create_session(self, client):
        resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {
                        "user_id": "alice",
                        "assigned_sections": ["overview"],
                        "role": "pm",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["template"] == "test-template"
        assert len(resp.json()["participants"]) == 1

    def test_create_session_bad_template(self, client):
        resp = client.post(
            "/api/sessions", json={"template": "nope", "coordinator": "alice"}
        )
        assert resp.status_code == 400

    def test_list_sessions(self, client):
        client.post(
            "/api/sessions", json={"template": "test-template", "coordinator": "alice"}
        )
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_session(self, client):
        create_resp = client.post(
            "/api/sessions", json={"template": "test-template", "coordinator": "alice"}
        )
        session_id = create_resp.json()["id"]
        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        assert "progress" in resp.json()
        assert "ready_to_publish" in resp.json()

    def test_get_session_not_found(self, client):
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404


@pytest.fixture()
def session_with_participant(client):
    resp = client.post(
        "/api/sessions",
        json={
            "template": "test-template",
            "coordinator": "alice",
            "participants": [
                {
                    "user_id": "alice",
                    "assigned_sections": ["overview", "details", "notes"],
                    "role": "pm",
                }
            ],
        },
    )
    return resp.json()


class TestCommentEndpoints:
    def test_add_comment(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "alice", "text": "Needs work"},
        )
        assert resp.status_code == 201
        assert resp.json()["author"] == "alice"

    def test_rejects_ai_author(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "ai", "text": "Fake AI"},
        )
        assert resp.status_code == 400
        assert "reserved" in resp.json()["detail"]

    @pytest.mark.parametrize("author", ["AI", "Ai", "aI"])
    def test_rejects_ai_author_case_insensitive(
        self, client, session_with_participant, author
    ):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": author, "text": "Fake"},
        )
        assert resp.status_code == 400
        assert "reserved" in resp.json()["detail"]

    def test_get_comments(self, client, session_with_participant):
        sid = session_with_participant["id"]
        client.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "alice", "text": "Hi"},
        )
        resp = client.get(f"/api/sessions/{sid}/sections/overview/comments")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestProposalEndpoints:
    def test_accept_proposal_updates_content(self, client, session_with_participant):
        sid = session_with_participant["id"]
        sm = client.app.state.sessions
        sm.add_comment(sid, "overview", "alice", "Fix it")
        proposal = sm.create_proposal(
            sid, "overview", "comment-001", "Better text", "improved"
        )
        resp = client.post(
            f"/api/sessions/{sid}/proposals/{proposal.id}/accept",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        section = client.get(f"/api/sessions/{sid}/sections/overview").json()
        assert section["content"] == "Better text"

    def test_reject_proposal_keeps_content(self, client, session_with_participant):
        sid = session_with_participant["id"]
        sm = client.app.state.sessions
        sm.add_comment(sid, "overview", "alice", "Fix it")
        proposal = sm.create_proposal(
            sid, "overview", "comment-001", "New text", "change"
        )
        resp = client.post(
            f"/api/sessions/{sid}/proposals/{proposal.id}/reject",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200
        section = client.get(f"/api/sessions/{sid}/sections/overview").json()
        assert section["content"] == ""

    def test_accept_unauthorized_fails(self, client, session_with_participant):
        sid = session_with_participant["id"]
        sm = client.app.state.sessions
        sm.add_comment(sid, "overview", "alice", "Fix it")
        proposal = sm.create_proposal(sid, "overview", "comment-001", "text", "change")
        resp = client.post(
            f"/api/sessions/{sid}/proposals/{proposal.id}/accept",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 400

    def test_reject_unauthorized_fails(self, client, session_with_participant):
        sid = session_with_participant["id"]
        sm = client.app.state.sessions
        sm.add_comment(sid, "overview", "alice", "Fix it")
        proposal = sm.create_proposal(sid, "overview", "comment-001", "text", "change")
        resp = client.post(
            f"/api/sessions/{sid}/proposals/{proposal.id}/reject",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 400


class TestTokenStripping:
    def test_get_session_strips_tokens(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.get(f"/api/sessions/{sid}")
        for p in resp.json()["participants"]:
            assert "token" not in p

    def test_list_sessions_strips_tokens(self, client, session_with_participant):
        resp = client.get("/api/sessions")
        for session in resp.json():
            for p in session["participants"]:
                assert "token" not in p

    def test_create_session_returns_tokens(self, client):
        resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {
                        "user_id": "alice",
                        "assigned_sections": ["overview"],
                        "role": "pm",
                    }
                ],
            },
        )
        assert "token" in resp.json()["participants"][0]


class TestSectionActionEndpoints:
    def test_approve_section(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"}
        )
        assert resp.status_code == 200
        session = client.get(f"/api/sessions/{sid}").json()
        assert session["section_meta"]["overview"]["status"] == "approved"

    def test_reopen_section(self, client, session_with_participant):
        sid = session_with_participant["id"]
        client.post(
            f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"}
        )
        resp = client.post(
            f"/api/sessions/{sid}/sections/overview/reopen", json={"user_id": "alice"}
        )
        assert resp.status_code == 200

    def test_skip_optional_section(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/notes/skip", json={"user_id": "alice"}
        )
        assert resp.status_code == 200

    def test_skip_required_section_fails(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/overview/skip", json={"user_id": "alice"}
        )
        assert resp.status_code == 400

    def test_get_section_content(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.get(f"/api/sessions/{sid}/sections/overview")
        assert resp.status_code == 200
        assert resp.json()["section_id"] == "overview"
        assert resp.json()["status"] == "draft"


class TestPublishEndpoint:
    def test_publish_when_ready(self, client, session_with_participant, tmp_path):
        sid = session_with_participant["id"]
        client.post(
            f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"}
        )
        resp = client.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(tmp_path / "output.md"),
                    "allowed_dir": str(tmp_path),
                }
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"
        assert (tmp_path / "output.md").exists()

    def test_publish_when_not_ready(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(f"/api/sessions/{sid}/publish", json={"config": {}})
        assert resp.status_code == 400

    def test_publish_twice_fails(self, client, session_with_participant, tmp_path):
        sid = session_with_participant["id"]
        client.post(
            f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"}
        )
        client.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(tmp_path / "out1.md"),
                    "allowed_dir": str(tmp_path),
                }
            },
        )
        resp = client.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(tmp_path / "out2.md"),
                    "allowed_dir": str(tmp_path),
                }
            },
        )
        assert resp.status_code == 400


class TestHistoryEndpoint:
    def test_returns_commit_log(self, client, session_with_participant):
        sid = session_with_participant["id"]
        client.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "alice", "text": "Hi"},
        )
        resp = client.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        assert len(resp.json()) > 0


class TestTokenResolution:
    def test_valid_token_returns_current_user_id(
        self, client, session_with_participant
    ):
        sid = session_with_participant["id"]
        token = session_with_participant["participants"][0]["token"]
        resp = client.get(f"/api/sessions/{sid}?token={token}")
        assert resp.status_code == 200
        assert resp.json()["current_user_id"] == "alice"

    def test_invalid_token_omits_current_user_id(
        self, client, session_with_participant
    ):
        sid = session_with_participant["id"]
        resp = client.get(f"/api/sessions/{sid}?token=bogus-token")
        assert resp.status_code == 200
        assert "current_user_id" not in resp.json()

    def test_no_token_omits_current_user_id(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        assert "current_user_id" not in resp.json()

    def test_coordinator_token_preserves_tokens(self, client, session_with_participant):
        sid = session_with_participant["id"]
        token = session_with_participant["participants"][0]["token"]
        resp = client.get(f"/api/sessions/{sid}?token={token}")
        for p in resp.json()["participants"]:
            assert "token" in p


class TestSpaRoute:
    def test_session_route_returns_html(self, client):
        resp = client.get("/session/any-session-id")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "DraftCircle" in resp.text


class TestSectionAssignment:
    def test_assign_section_to_user(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/overview/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "assigned"

        session_resp = client.get(f"/api/sessions/{sid}")
        session = session_resp.json()
        bob_p = next(
            (p for p in session["participants"] if p["user_id"] == "bob"), None
        )
        assert bob_p is not None
        assert "overview" in bob_p["assigned_sections"]

    def test_assign_section_nonexistent_section(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/nonexistent/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 400

    def test_assign_section_nonexistent_session(self, client):
        resp = client.post(
            "/api/sessions/fake-session/sections/overview/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 404


class TestWebSocket:
    def test_connect_and_receive_join(self, client, session_with_participant):
        sid = session_with_participant["id"]
        token = session_with_participant["participants"][0]["token"]
        with client.websocket_connect(f"/ws/sessions/{sid}?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "participant_joined"
            assert data["user"]["user_id"] == "alice"


class TestCoordinatorTokenAccess:
    def test_coordinator_sees_participant_tokens(self, client, populated_data_repo):
        create_resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {
                        "user_id": "bob",
                        "assigned_sections": ["overview"],
                        "role": "participant",
                    },
                ],
            },
        )
        session = create_resp.json()
        sid = session["id"]
        coordinator_token = next(
            p["token"] for p in session["participants"] if p["user_id"] == "alice"
        )

        resp = client.get(f"/api/sessions/{sid}?token={coordinator_token}")
        data = resp.json()
        for p in data["participants"]:
            assert "token" in p

    def test_non_coordinator_tokens_stripped(self, client, populated_data_repo):
        create_resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {
                        "user_id": "bob",
                        "assigned_sections": ["overview"],
                        "role": "participant",
                    },
                ],
            },
        )
        session = create_resp.json()
        sid = session["id"]
        bob_token = next(
            p["token"] for p in session["participants"] if p["user_id"] == "bob"
        )

        resp = client.get(f"/api/sessions/{sid}?token={bob_token}")
        data = resp.json()
        for p in data["participants"]:
            assert "token" not in p
