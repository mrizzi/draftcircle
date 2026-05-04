# tests/integration/test_concurrency.py
import pytest

pytestmark = pytest.mark.integration


class TestConcurrentProposals:
    def test_two_proposals_can_coexist(self, api, session_with_drafts):
        sid = session_with_drafts["id"]

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
