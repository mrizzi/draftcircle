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
