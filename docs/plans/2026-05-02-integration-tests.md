# Integration Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend integration tests and Playwright E2E tests that eliminate manual multi-browser testing of real-time WebSocket communication and session workflows.

**Architecture:** Two test layers — backend integration tests using FastAPI TestClient (HTTP + WebSocket, no server needed) and Playwright E2E tests with an auto-managed uvicorn server in a thread. Both layers mock AI at the orchestrator boundary with deterministic responses. Three participants (alice, bob, carol) in all multi-user scenarios.

**Tech Stack:** pytest, pytest-asyncio, FastAPI TestClient, pytest-playwright, httpx, uvicorn (threaded for E2E)

**Spec:** `docs/specs/2026-05-02-integration-tests-design.md`

---

## File Structure

**Create:**
- `tests/integration/conftest.py` — fixtures: `integration_app`, `api`, `session_with_drafts`, mock AI helpers
- `tests/integration/test_workflow.py` — full lifecycle: users → session → comment → propose → accept → approve → publish → git verification
- `tests/integration/test_multi_client.py` — 3-client WebSocket broadcast for all message types
- `tests/integration/test_authorization.py` — permission enforcement (coordinator vs owner vs outsider)
- `tests/integration/test_concurrency.py` — concurrent proposals, state transitions, race conditions
- `tests/e2e/conftest.py` — threaded uvicorn server, `create_session_via_api` helper
- `tests/e2e/test_realtime_sync.py` — 3 Playwright browser contexts, real-time DOM updates
- `tests/e2e/test_session_workflow.py` — single browser walkthrough of full lifecycle via UI
- `tests/e2e/test_permissions_ui.py` — UI controls visibility based on user role
- `TESTING.md` — contributor guide

**Modify:**
- `pyproject.toml` — add `pytest-playwright` dev dep, pytest markers, asyncio_mode

---

### Task 1: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest-playwright dependency and pytest config**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "pytest-playwright>=0.6",
    "ruff>=0.11",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: backend integration tests (no browser)",
    "e2e: end-to-end browser tests (requires Playwright)",
]
asyncio_mode = "auto"
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -e ".[dev]" && playwright install chromium`
Expected: clean install, chromium browser downloaded

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/ -x -q`
Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pytest-playwright and test markers"
```

---

### Task 2: Create integration test fixtures

**Files:**
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Write integration conftest**

```python
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
```

- [ ] **Step 2: Verify fixture loads**

Run: `python -c "from tests.integration.conftest import drain_join_messages; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/
git commit -m "test: add integration test fixtures with 3 participants and mock AI"
```

---

### Task 3: Write full lifecycle integration tests

**Files:**
- Create: `tests/integration/test_workflow.py`

- [ ] **Step 1: Write test_workflow.py**

```python
# tests/integration/test_workflow.py
import json

import pytest

from tests.integration.conftest import (
    DRAFT_CONTENT,
    INTEGRATION_USERS,
    PROPOSAL_SUMMARY,
    REVISED_TEXT,
)

pytestmark = pytest.mark.integration


class TestUserRegistryIntegration:
    def test_users_available_and_new_user_works(self, api):
        resp = api.get("/api/users")
        assert resp.status_code == 200
        user_ids = {u["id"] for u in resp.json()}
        assert user_ids == {"alice", "bob", "carol"}

        resp = api.post(
            "/api/users",
            json={
                "id": "dave",
                "name": "Dave Park",
                "email": "dave@example.com",
                "default_roles": ["writer"],
            },
        )
        assert resp.status_code == 201

        resp = api.get("/api/users")
        assert {u["id"] for u in resp.json()} == {"alice", "bob", "carol", "dave"}


class TestTemplateIntegration:
    def test_template_loads_correctly(self, api):
        resp = api.get("/api/templates/test-template")
        assert resp.status_code == 200
        tmpl = resp.json()
        assert tmpl["name"] == "Test Template"
        assert len(tmpl["sections"]) == 3
        priorities = {s["id"]: s["priority"] for s in tmpl["sections"]}
        assert priorities == {
            "overview": "required",
            "details": "recommended",
            "notes": "optional",
        }

    def test_session_sections_match_template(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.get(f"/api/sessions/{sid}")
        session = resp.json()
        assert set(session["section_meta"].keys()) == {"overview", "details", "notes"}


class TestFullLifecycle:
    def test_create_comment_accept_approve_publish(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        tokens = session_with_drafts["tokens"]

        # Verify drafts were generated
        resp = api.get(f"/api/sessions/{sid}/sections/overview")
        assert resp.status_code == 200
        assert resp.json()["content"] == DRAFT_CONTENT["overview"]
        assert resp.json()["status"] == "draft"

        # Post comment → triggers AI proposal
        resp = api.post(
            f"/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "bob",
                "text": "Please add more detail to the overview.",
            },
        )
        assert resp.status_code == 201

        # Verify proposal was created
        resp = api.get(f"/api/sessions/{sid}/sections/overview/proposals")
        proposals = resp.json()
        assert len(proposals) == 1
        assert proposals[0]["status"] == "pending"
        assert proposals[0]["revised_text"] == REVISED_TEXT
        assert proposals[0]["summary"] == PROPOSAL_SUMMARY
        proposal_id = proposals[0]["id"]

        # Accept proposal → draft updates
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{proposal_id}/accept",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200

        resp = api.get(f"/api/sessions/{sid}/sections/overview")
        assert resp.json()["content"] == REVISED_TEXT
        assert resp.json()["status"] == "in_review"

        # Approve overview (required) — bob is assigned
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200

        # Approve details (recommended) — carol is assigned
        resp = api.post(
            f"/api/sessions/{sid}/sections/details/approve",
            json={"user_id": "carol"},
        )
        assert resp.status_code == 200

        # Skip notes (optional) — alice is coordinator
        resp = api.post(
            f"/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200

        # Check progress
        resp = api.get(f"/api/sessions/{sid}", params={"token": tokens["alice"]})
        session = resp.json()
        assert session["ready_to_publish"] is True
        assert session["progress"]["approved"] == 2
        assert session["progress"]["skipped"] == 1
        assert session["progress"]["required_remaining"] == 0

        # Publish — markdown plugin writes to file
        output_path = str(
            session_with_drafts["session"]["id"] + "-output.md"
        )
        data_repo = api.app.state.data_repo_path
        resp = api.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(data_repo / output_path),
                    "allowed_dir": str(data_repo),
                }
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

        # Session is now published
        resp = api.get(f"/api/sessions/{sid}")
        assert resp.json()["status"] == "published"

    def test_reject_proposal_preserves_draft(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        original_draft = DRAFT_CONTENT["overview"]

        # Comment triggers proposal
        api.post(
            f"/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "bob",
                "text": "Maybe change this?",
            },
        )
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        proposal_id = proposals[0]["id"]

        # Reject proposal
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{proposal_id}/reject",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200

        # Draft unchanged
        resp = api.get(f"/api/sessions/{sid}/sections/overview")
        assert resp.json()["content"] == original_draft

        # Proposal status is rejected
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        assert proposals[0]["status"] == "rejected"

    def test_skip_optional_counts_toward_progress(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        resp = api.post(
            f"/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200

        resp = api.get(f"/api/sessions/{sid}")
        progress = resp.json()["progress"]
        assert progress["skipped"] == 1
        assert progress["total"] == 3

    def test_cannot_skip_required_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/skip",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()


class TestPostPublishLockdown:
    def _publish_session(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        data_repo = api.app.state.data_repo_path
        api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        api.post(
            f"/api/sessions/{sid}/sections/details/approve",
            json={"user_id": "alice"},
        )
        api.post(
            f"/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )
        resp = api.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(data_repo / "out.md"),
                    "allowed_dir": str(data_repo),
                }
            },
        )
        assert resp.status_code == 200
        return sid

    def test_comment_fails_after_publish(self, api, session_with_drafts):
        sid = self._publish_session(api, session_with_drafts)
        resp = api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Late comment"},
        )
        assert resp.status_code == 400

    def test_double_publish_fails(self, api, session_with_drafts):
        sid = self._publish_session(api, session_with_drafts)
        data_repo = api.app.state.data_repo_path
        resp = api.post(
            f"/api/sessions/{sid}/publish",
            json={
                "config": {
                    "output_path": str(data_repo / "out2.md"),
                    "allowed_dir": str(data_repo),
                }
            },
        )
        assert resp.status_code == 400
        assert "already published" in resp.json()["detail"].lower()


class TestGitPersistence:
    def test_history_tracks_actions(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        # Comment
        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Check this."},
        )

        # Accept proposal
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        api.post(
            f"/api/sessions/{sid}/proposals/{proposals[0]['id']}/accept",
            json={"user_id": "bob"},
        )

        # Approve
        api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "bob"},
        )

        # Check git log
        resp = api.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        messages = [entry["message"] for entry in resp.json()]
        assert any("comment:" in m for m in messages)
        assert any("accept:" in m for m in messages)
        assert any("approve:" in m for m in messages)

    def test_section_content_persisted_to_disk(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        git = api.app.state.git
        meta = api.get(f"/api/sessions/{sid}").json()["section_meta"]
        filename = meta["overview"]["filename"]
        content = git.read_file(f"sessions/{sid}/sections/{filename}.md")
        assert content == DRAFT_CONTENT["overview"]


class TestPluginIntegration:
    def test_custom_plugin_overrides_builtin(self, api, integration_app):
        data_repo = integration_app.state.data_repo_path
        git = integration_app.state.git

        # Write a custom markdown.py plugin that returns a unique ref
        plugins_dir = data_repo / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        (plugins_dir / "markdown.py").write_text(
            'from backend.plugins.base import OutputPlugin\n'
            '\n'
            'class Plugin(OutputPlugin):\n'
            '    def assemble(self, sections):\n'
            '        return "custom-assembled"\n'
            '    def publish(self, output, config):\n'
            '        return "custom-override-ref"\n'
        )

        # Create session and approve all
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
                ],
                "seed_text": "Seed.",
            },
        )
        sid = resp.json()["id"]

        api.post(f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/details/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/notes/skip", json={"user_id": "alice"})

        resp = api.post(
            f"/api/sessions/{sid}/publish",
            json={"config": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["output_ref"] == "custom-override-ref"
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_workflow.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_workflow.py
git commit -m "test: add full lifecycle integration tests"
```

---

### Task 4: Write 3-client WebSocket broadcast tests

**Files:**
- Create: `tests/integration/test_multi_client.py`

- [ ] **Step 1: Write test_multi_client.py**

```python
# tests/integration/test_multi_client.py
import pytest

from tests.integration.conftest import drain_join_messages

pytestmark = pytest.mark.integration


class TestThreeClientBroadcast:
    def test_join_messages_received_by_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            # alice receives her own join
            msg = ws_a.receive_json()
            assert msg["type"] == "participant_joined"
            assert msg["user"]["user_id"] == "alice"

            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                # alice receives bob's join
                msg = ws_a.receive_json()
                assert msg["type"] == "participant_joined"
                assert msg["user"]["user_id"] == "bob"

                # bob receives his own join
                msg = ws_b.receive_json()
                assert msg["type"] == "participant_joined"
                assert msg["user"]["user_id"] == "bob"

    def test_comment_broadcasts_to_all_three(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/comments",
                        json={
                            "section_id": "overview",
                            "author": "bob",
                            "text": "Needs more detail.",
                        },
                    )

                    # All three receive comment_added
                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "comment_added"
                        assert msg["section_id"] == "overview"
                        assert msg["comment"]["author"] == "bob"

    def test_proposal_created_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    # Comment triggers AI proposal
                    api.post(
                        f"/api/sessions/{sid}/comments",
                        json={
                            "section_id": "overview",
                            "author": "bob",
                            "text": "Expand this section.",
                        },
                    )

                    # Drain comment_added from all three
                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "comment_added"

                    # All three receive proposal_created
                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "proposal_created"
                        assert msg["section_id"] == "overview"

    def test_accept_proposal_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        # Create a proposal first (outside WS context for simplicity)
        api.post(
            f"/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "bob",
                "text": "Change needed.",
            },
        )
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        proposal_id = proposals[0]["id"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/proposals/{proposal_id}/accept",
                        json={"user_id": "bob"},
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "proposal_accepted"
                        assert msg["proposal_id"] == proposal_id

    def test_approve_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/sections/overview/approve",
                        json={"user_id": "alice"},
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "section_approved"
                        assert msg["section_id"] == "overview"

    def test_publish_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]
        data_repo = api.app.state.data_repo_path

        # Approve all required, skip optional
        api.post(f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/details/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/notes/skip", json={"user_id": "alice"})

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/publish",
                        json={
                            "config": {
                                "output_path": str(data_repo / "pub.md"),
                                "allowed_dir": str(data_repo),
                            }
                        },
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "session_published"
                        assert "output_ref" in msg

    def test_disconnect_notifies_remaining(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                # Drain join messages
                ws_a.receive_json()  # alice joined
                ws_a.receive_json()  # bob joined
                ws_b.receive_json()  # bob joined

                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    ws_a.receive_json()  # carol joined
                    ws_b.receive_json()  # carol joined
                    ws_c.receive_json()  # carol joined

                # carol disconnected (exited context)
                msg_a = ws_a.receive_json()
                msg_b = ws_b.receive_json()
                assert msg_a["type"] == "participant_left"
                assert msg_a["user"]["user_id"] == "carol"
                assert msg_b["type"] == "participant_left"
                assert msg_b["user"]["user_id"] == "carol"

    def test_broadcast_survives_one_client_disconnect(self, api, session_with_drafts):
        """If one client disconnects, remaining clients still receive broadcasts."""
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                ws_a.receive_json()  # alice joined
                ws_a.receive_json()  # bob joined
                ws_b.receive_json()  # bob joined

                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    ws_a.receive_json()  # carol joined
                    ws_b.receive_json()  # carol joined
                    ws_c.receive_json()  # carol joined

                # carol disconnected — drain participant_left
                ws_a.receive_json()
                ws_b.receive_json()

                # Now comment — should still reach alice and bob
                api.post(
                    f"/api/sessions/{sid}/comments",
                    json={
                        "section_id": "overview",
                        "author": "bob",
                        "text": "After carol left.",
                    },
                )

                for ws in (ws_a, ws_b):
                    msg = ws.receive_json()
                    assert msg["type"] == "comment_added"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_multi_client.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_multi_client.py
git commit -m "test: add 3-client WebSocket broadcast integration tests"
```

---

### Task 5: Write authorization tests

**Files:**
- Create: `tests/integration/test_authorization.py`

- [ ] **Step 1: Write test_authorization.py**

```python
# tests/integration/test_authorization.py
import pytest

pytestmark = pytest.mark.integration


class TestProposalAuthorization:
    def _create_proposal(self, api, sid):
        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Fix this."},
        )
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        return proposals[0]["id"]

    def test_owner_can_accept_own_section_proposal(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        pid = self._create_proposal(api, sid)
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{pid}/accept",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200

    def test_non_owner_cannot_accept_proposal(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        pid = self._create_proposal(api, sid)
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{pid}/accept",
            json={"user_id": "carol"},
        )
        assert resp.status_code == 400
        assert "not authorized" in resp.json()["detail"].lower()

    def test_coordinator_can_accept_any_proposal(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        pid = self._create_proposal(api, sid)
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{pid}/accept",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200

    def test_non_owner_cannot_reject_proposal(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        pid = self._create_proposal(api, sid)
        resp = api.post(
            f"/api/sessions/{sid}/proposals/{pid}/reject",
            json={"user_id": "carol"},
        )
        assert resp.status_code == 400
        assert "not authorized" in resp.json()["detail"].lower()


class TestSectionAuthorization:
    def test_owner_can_approve_own_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200

    def test_non_owner_cannot_approve_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "carol"},
        )
        assert resp.status_code == 400
        assert "not authorized" in resp.json()["detail"].lower()

    def test_coordinator_can_approve_any_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/details/approve",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 200

    def test_non_owner_cannot_skip_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 400

    def test_anyone_can_comment_on_any_section(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        for author in ("alice", "bob", "carol"):
            resp = api.post(
                f"/api/sessions/{sid}/comments",
                json={
                    "section_id": "details",
                    "author": author,
                    "text": f"Comment from {author}",
                },
            )
            assert resp.status_code == 201


class TestTokenResolution:
    def test_valid_token_resolves_user_id(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]
        resp = api.get(f"/api/sessions/{sid}", params={"token": t["bob"]})
        assert resp.json()["current_user_id"] == "bob"

    def test_invalid_token_has_no_user_id(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.get(f"/api/sessions/{sid}", params={"token": "bogus-token"})
        assert "current_user_id" not in resp.json()

    def test_invalid_token_on_websocket_has_null_user(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        with api.websocket_connect(f"/ws/sessions/{sid}?token=bogus") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "participant_joined"
            assert msg["user"]["user_id"] is None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_authorization.py -v`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_authorization.py
git commit -m "test: add authorization integration tests"
```

---

### Task 6: Write concurrency tests

**Files:**
- Create: `tests/integration/test_concurrency.py`

- [ ] **Step 1: Write test_concurrency.py**

```python
# tests/integration/test_concurrency.py
import pytest

pytestmark = pytest.mark.integration


class TestConcurrentProposals:
    def test_two_proposals_can_coexist(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        # Two comments → two proposals
        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "First change."},
        )
        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Second change."},
        )

        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        assert len(proposals) == 2
        assert all(p["status"] == "pending" for p in proposals)

    def test_accept_one_reject_another(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Change A."},
        )
        api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Change B."},
        )

        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        p1_id, p2_id = proposals[0]["id"], proposals[1]["id"]

        api.post(f"/api/sessions/{sid}/proposals/{p1_id}/accept", json={"user_id": "bob"})
        api.post(f"/api/sessions/{sid}/proposals/{p2_id}/reject", json={"user_id": "bob"})

        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        statuses = {p["id"]: p["status"] for p in proposals}
        assert statuses[p1_id] == "accepted"
        assert statuses[p2_id] == "rejected"


class TestSectionStateTransitions:
    def test_approve_then_comment_fails(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        resp = api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "Too late."},
        )
        assert resp.status_code == 400
        assert "approved" in resp.json()["detail"].lower()

    def test_reopen_then_comment_succeeds(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        api.post(
            f"/api/sessions/{sid}/sections/overview/reopen",
            json={"user_id": "alice"},
        )
        resp = api.post(
            f"/api/sessions/{sid}/comments",
            json={"section_id": "overview", "author": "bob", "text": "After reopen."},
        )
        assert resp.status_code == 201

    def test_approve_already_approved_fails(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

        api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 400

    def test_reopen_non_approved_fails(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        resp = api.post(
            f"/api/sessions/{sid}/sections/overview/reopen",
            json={"user_id": "alice"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_concurrency.py -v`
Expected: all tests PASS

- [ ] **Step 3: Run all integration tests together**

Run: `pytest tests/integration/ -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_concurrency.py
git commit -m "test: add concurrency and state transition integration tests"
```

---

### Task 7: Create E2E test fixtures

**Files:**
- Create: `tests/e2e/__init__.py` (empty)
- Create: `tests/e2e/conftest.py`

- [ ] **Step 1: Write E2E conftest**

```python
# tests/e2e/conftest.py
import json
import socket
from threading import Thread
from unittest.mock import AsyncMock, MagicMock

import httpx
import pygit2
import pytest
import uvicorn

from backend.main import create_app
from tests.conftest import SAMPLE_TEMPLATE
from tests.integration.conftest import INTEGRATION_USERS, _ai_side_effect


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url, timeout=10):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/api/templates", timeout=1)
            return
        except httpx.ConnectError:
            time.sleep(0.1)
    raise RuntimeError(f"Server at {url} did not start within {timeout}s")


@pytest.fixture(scope="session")
def e2e_server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("e2e_data")
    pygit2.init_repository(str(data_dir))

    from backend.git_store import GitStore

    git = GitStore(data_dir)
    git.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE, indent=2),
            "users.json": json.dumps(INTEGRATION_USERS, indent=2),
        },
    )

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=_ai_side_effect)

    app = create_app(data_repo_path=str(data_dir), anthropic_client=mock_client)

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    _wait_for_server(base_url)

    yield {"url": base_url, "port": port, "data_dir": data_dir, "server": server}

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def base_url(e2e_server):
    return e2e_server["url"]


@pytest.fixture()
def create_session_via_api(base_url):
    def _create(
        template_slug="test-template",
        coordinator="alice",
        participants=None,
        seed_text="E2E test seed content.",
    ):
        if participants is None:
            participants = [
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
            ]
        resp = httpx.post(
            f"{base_url}/api/sessions",
            json={
                "template": template_slug,
                "coordinator": coordinator,
                "participants": participants,
                "seed_text": seed_text,
            },
        )
        assert resp.status_code == 201
        session = resp.json()
        tokens = {p["user_id"]: p["token"] for p in session["participants"]}
        return {"id": session["id"], "tokens": tokens, "session": session}

    return _create
```

- [ ] **Step 2: Verify the server fixture starts**

Run: `python -c "from tests.e2e.conftest import _find_free_port; print('OK:', _find_free_port())"`
Expected: `OK: <some port number>`

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/
git commit -m "test: add E2E test fixtures with threaded uvicorn server"
```

---

### Task 8: Write multi-browser realtime sync tests

**Files:**
- Create: `tests/e2e/test_realtime_sync.py`

- [ ] **Step 1: Write test_realtime_sync.py**

```python
# tests/e2e/test_realtime_sync.py
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


class TestRealtimeSync:
    def test_comment_appears_in_other_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        # Alice's browser
        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        # Bob's browser
        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        bob_page.wait_for_selector("#section-grid")

        # Carol's browser
        carol_ctx = new_context()
        carol_page = carol_ctx.new_page()
        carol_page.goto(f"{base_url}/session/{sid}?token={tokens['carol']}")
        carol_page.wait_for_selector("#section-grid")

        # Alice opens the overview section
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Bob opens the same section
        bob_page.click('.section-card[data-section="overview"]')
        bob_page.wait_for_selector("#detail-panel.panel-visible")

        # Carol opens the same section
        carol_page.click('.section-card[data-section="overview"]')
        carol_page.wait_for_selector("#detail-panel.panel-visible")

        # Alice posts a comment
        page.fill("#comment-input", "This needs more detail.")
        page.click("#submit-comment-btn")

        # Comment appears in all three browsers
        for p in (page, bob_page, carol_page):
            expect(p.locator("#comments-thread .comment")).to_have_count(
                1, timeout=5000
            )

    def test_section_approval_updates_all_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        bob_page.wait_for_selector("#section-grid")

        # Alice opens overview and approves it
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")
        page.click("#panel-approve-btn")

        # Bob sees the section card updated with approved badge
        expect(
            bob_page.locator('.section-card[data-section="overview"] .badge')
        ).to_have_text("approved", timeout=5000)

    def test_publish_updates_all_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        bob_page.wait_for_selector("#section-grid")

        # Approve all sections via API (coordinator alice)
        import httpx

        httpx.post(
            f"{base_url}/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/sections/details/approve",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )

        # Wait for UI to process section updates
        page.wait_for_timeout(500)

        # Alice publishes
        page.click("#publish-btn")

        # Bob sees published status
        expect(bob_page.locator("#session-info")).to_contain_text(
            "published", timeout=5000
        )
```

- [ ] **Step 2: Run E2E tests**

Run: `pytest tests/e2e/test_realtime_sync.py -v --browser chromium`
Expected: all tests PASS (may take 10-20s due to browser startup)

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_realtime_sync.py
git commit -m "test: add multi-browser real-time sync E2E tests"
```

---

### Task 9: Write single-browser session workflow test

**Files:**
- Create: `tests/e2e/test_session_workflow.py`

- [ ] **Step 1: Write test_session_workflow.py**

```python
# tests/e2e/test_session_workflow.py
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


class TestSessionWorkflow:
    def test_full_lifecycle_through_ui(
        self, page, base_url, create_session_via_api
    ):
        """Walk through the complete session lifecycle in a single browser."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        # Navigate to workspace
        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        # Verify section grid shows all 3 sections
        expect(page.locator(".section-card")).to_have_count(3)

        # Click overview section → detail panel opens
        page.click('.section-card[data-section="overview"]')
        import re

        expect(page.locator("#detail-panel")).to_have_class(re.compile("panel-visible"))

        # Verify draft content is visible
        expect(page.locator("#panel-draft")).to_contain_text("Overview")

        # Post a comment
        page.fill("#comment-input", "Needs more detail here.")
        page.click("#submit-comment-btn")
        expect(page.locator("#comments-thread .comment")).to_have_count(
            1, timeout=5000
        )

        # AI proposal should appear (mock AI returns proposal for every comment)
        expect(page.locator(".proposal")).to_have_count(1, timeout=5000)
        expect(page.locator(".proposal .proposal-status")).to_have_text("pending")

        # Accept proposal
        page.click(".proposal-actions .btn-success")
        expect(page.locator(".proposal .proposal-status")).to_have_text(
            "accepted", timeout=5000
        )

        # Approve overview section
        page.click("#panel-approve-btn")
        expect(page.locator("#panel-status-badge")).to_contain_text(
            "approved", timeout=5000
        )

        # Navigate to details section
        page.click("#panel-close-btn")
        page.click('.section-card[data-section="details"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Approve details
        page.click("#panel-approve-btn")
        expect(page.locator("#panel-status-badge")).to_contain_text("approved")

        # Navigate to notes section and skip it
        page.click("#panel-close-btn")
        page.click('.section-card[data-section="notes"]')
        page.wait_for_selector("#detail-panel.panel-visible")
        page.click("#panel-skip-btn")
        expect(page.locator("#panel-status-badge")).to_contain_text("skipped")

        # Publish button should be active
        page.click("#panel-close-btn")
        expect(page.locator("#publish-btn")).to_be_enabled(timeout=3000)
        page.click("#publish-btn")

        # Verify published state
        expect(page.locator("#session-info")).to_contain_text(
            "published", timeout=5000
        )

    def test_reject_proposal_keeps_draft(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        page.wait_for_selector("#section-grid")

        # Open overview (bob is assigned)
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Get current draft text
        draft_text = page.locator("#panel-draft").text_content()

        # Comment and wait for proposal
        page.fill("#comment-input", "Maybe change this?")
        page.click("#submit-comment-btn")
        expect(page.locator(".proposal")).to_have_count(1, timeout=5000)

        # Reject proposal
        page.click(".proposal-actions .btn-danger")
        expect(page.locator(".proposal .proposal-status")).to_have_text(
            "rejected", timeout=5000
        )

        # Draft unchanged
        expect(page.locator("#panel-draft")).to_have_text(draft_text)

    def test_reopen_section(self, page, base_url, create_session_via_api):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Approve then reopen
        page.click("#panel-approve-btn")
        expect(page.locator("#panel-status-badge")).to_contain_text("approved")

        page.click("#panel-reopen-btn")
        expect(page.locator("#panel-status-badge")).to_contain_text(
            "in_review", timeout=5000
        )
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/e2e/test_session_workflow.py -v --browser chromium`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_session_workflow.py
git commit -m "test: add single-browser session workflow E2E tests"
```

---

### Task 10: Write permissions UI tests

**Files:**
- Create: `tests/e2e/test_permissions_ui.py`

- [ ] **Step 1: Write test_permissions_ui.py**

```python
# tests/e2e/test_permissions_ui.py
import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


class TestPermissionsUI:
    def test_section_owner_sees_proposal_actions(
        self, page, base_url, create_session_via_api
    ):
        """Bob (owner of overview) should see accept/reject buttons."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        # Create a proposal via API
        httpx.post(
            f"{base_url}/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "alice",
                "text": "Needs revision.",
            },
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        page.wait_for_selector("#section-grid")
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Bob sees proposal actions (accept/reject)
        expect(page.locator(".proposal-actions .btn-success")).to_be_visible(
            timeout=5000
        )
        expect(page.locator(".proposal-actions .btn-danger")).to_be_visible()

    def test_non_owner_does_not_see_proposal_actions(
        self, page, base_url, create_session_via_api
    ):
        """Carol (not owner of overview) should NOT see accept/reject."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        httpx.post(
            f"{base_url}/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "alice",
                "text": "Needs revision.",
            },
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['carol']}")
        page.wait_for_selector("#section-grid")
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # Proposal is visible but actions are not
        expect(page.locator(".proposal")).to_have_count(1, timeout=5000)
        expect(page.locator(".proposal-actions .btn-success")).to_have_count(0)
        expect(page.locator(".proposal-actions .btn-danger")).to_have_count(0)

    def test_coordinator_sees_approve_on_all_sections(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        for section_id in ("overview", "details", "notes"):
            page.click(f'.section-card[data-section="{section_id}"]')
            page.wait_for_selector("#detail-panel.panel-visible")
            expect(page.locator("#panel-approve-btn")).to_be_visible()
            page.click("#panel-close-btn")

    def test_non_coordinator_only_sees_approve_on_own_section(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        page.wait_for_selector("#section-grid")

        # Bob's section (overview) — approve visible
        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")
        expect(page.locator("#panel-approve-btn")).to_be_visible()
        page.click("#panel-close-btn")

        # Carol's section (details) — approve hidden for bob
        page.click('.section-card[data-section="details"]')
        page.wait_for_selector("#detail-panel.panel-visible")
        expect(page.locator("#panel-approve-btn")).to_have_count(0)

    def test_published_session_has_no_controls(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]
        data_url = base_url

        # Approve and publish via API
        httpx.post(
            f"{data_url}/api/sessions/{sid}/sections/overview/approve",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{data_url}/api/sessions/{sid}/sections/details/approve",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{data_url}/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )

        # Need to get data_dir for publish config — use a relative path
        httpx.post(
            f"{data_url}/api/sessions/{sid}/publish",
            json={"config": {"output_path": "/tmp/e2e-pub.md", "allowed_dir": "/tmp"}},
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        page.wait_for_selector("#section-grid")

        page.click('.section-card[data-section="overview"]')
        page.wait_for_selector("#detail-panel.panel-visible")

        # No comment input, no action buttons
        expect(page.locator("#comment-input")).to_have_count(0)
        expect(page.locator("#panel-approve-btn")).to_have_count(0)
```

- [ ] **Step 2: Run all E2E tests**

Run: `pytest tests/e2e/ -v --browser chromium`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_permissions_ui.py
git commit -m "test: add permissions UI E2E tests"
```

---

### Task 11: Write TESTING.md

**Files:**
- Create: `TESTING.md`

- [ ] **Step 1: Write TESTING.md**

````markdown
# Testing

DraftCircle uses three test layers: **unit**, **backend integration**,
and **end-to-end (E2E)**.

## Prerequisites

- Python >= 3.12
- Install all dev dependencies:

```bash
pip install -e ".[dev]"
```

For E2E tests, install Playwright browsers:

```bash
playwright install chromium
```

## Running Tests

```bash
# All tests (unit + integration + E2E)
pytest tests/

# Unit tests only
pytest tests/ --ignore=tests/integration --ignore=tests/e2e

# Backend integration only (fast, no browser)
pytest tests/integration/

# E2E only (requires Playwright browsers)
pytest tests/e2e/ --browser chromium

# Skip E2E in local development
pytest -m "not e2e"
```

## Test Layers

### Unit Tests (`tests/test_*.py`)

Test individual modules in isolation: git store, session manager,
models, AI orchestrator, plugins, user registry, template loader.
Fast. No real server. Mocked dependencies.

### Backend Integration (`tests/integration/`)

Test multi-component workflows through the FastAPI app using
`TestClient`. Covers:

- **test_workflow.py** — full session lifecycle from user creation
  to publish, with git state verification
- **test_multi_client.py** — 3 WebSocket clients verifying broadcast
  delivery for all message types
- **test_authorization.py** — permission enforcement for all
  section actions
- **test_concurrency.py** — concurrent proposals, state transitions,
  race conditions

Uses a mocked AI orchestrator (deterministic proposals, no API calls).

### E2E Tests (`tests/e2e/`)

Browser-level tests with Playwright against a real uvicorn server
(started automatically). Covers:

- **test_realtime_sync.py** — 3 browser contexts verifying DOM updates
  propagate in real time across users
- **test_session_workflow.py** — single-browser walkthrough of the
  entire session lifecycle via UI
- **test_permissions_ui.py** — correct controls visible for owner vs
  non-owner vs coordinator

## Writing New Tests

### Where to put tests

| What you're testing | Directory |
|---|---|
| A single module in isolation | `tests/test_<module>.py` |
| Multi-component workflow via API | `tests/integration/` |
| UI behavior in a real browser | `tests/e2e/` |

### Fixtures

**Integration tests** use fixtures from `tests/integration/conftest.py`:

- `integration_app` — FastAPI app with 3 users and mock AI
- `api` — `TestClient` for HTTP + WebSocket
- `session_with_drafts` — pre-created session (alice coordinator,
  bob owns overview, carol owns details), AI-generated drafts ready

**E2E tests** use fixtures from `tests/e2e/conftest.py`:

- `e2e_server` — auto-started uvicorn on random port
- `base_url` — the server URL
- `create_session_via_api()` — creates a session via HTTP (not the UI)

### Multi-client WebSocket pattern

```python
from tests.integration.conftest import drain_join_messages

def test_my_broadcast(api, session_with_drafts):
    sid = session_with_drafts["id"]
    t = session_with_drafts["tokens"]

    with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                drain_join_messages(ws_a, ws_b, ws_c)

                # Perform action, then assert on ws_a, ws_b, ws_c
```

### Mock AI

The integration and E2E test suites use a deterministic mock AI:
- Comments always trigger a `ProposalResult` with fixed text
- Session creation with `seed_text` generates drafts for all sections
- No Claude API calls

## CI Notes

- Integration tests run in seconds (no browser, no network)
- E2E tests take 10-30s (browser startup + page loads)
- Cache `~/.cache/ms-playwright` for faster Playwright browser setup
- Run `playwright install --with-deps chromium` in CI for headless
````

- [ ] **Step 2: Verify rendering**

Run: `head -20 TESTING.md`
Expected: shows correct markdown header and first section

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: all unit, integration, and E2E tests PASS

- [ ] **Step 4: Commit**

```bash
git add TESTING.md
git commit -m "docs: add TESTING.md contributor guide"
```

---

## Final Verification

- [ ] **Run complete test suite with markers check**

```bash
pytest tests/ -v --co -q | tail -5
pytest tests/ -v
```

Expected: all tests collected and passing, markers correctly applied.
