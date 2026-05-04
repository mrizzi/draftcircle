# tests/integration/test_workflow.py
import pytest

from tests.integration.conftest import (
    DRAFT_CONTENT,
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
        assert resp.json()["status"] == "in-review"

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
        output_path = str(session_with_drafts["session"]["id"] + "-output.md")
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

        # Write a custom markdown.py plugin that returns a unique ref
        plugins_dir = data_repo / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        (plugins_dir / "markdown.py").write_text(
            "from backend.plugins.base import OutputPlugin\n"
            "\n"
            "class Plugin(OutputPlugin):\n"
            "    def assemble(self, sections):\n"
            '        return "custom-assembled"\n'
            "    def publish(self, output, config):\n"
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

        api.post(
            f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"}
        )
        api.post(
            f"/api/sessions/{sid}/sections/details/approve", json={"user_id": "alice"}
        )
        api.post(f"/api/sessions/{sid}/sections/notes/skip", json={"user_id": "alice"})

        resp = api.post(
            f"/api/sessions/{sid}/publish",
            json={"config": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["output_ref"] == "custom-override-ref"
