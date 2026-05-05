# tests/e2e/test_permissions_ui.py
import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import WS_TIMEOUT, open_section, wait_for_workspace

pytestmark = pytest.mark.e2e


def _post_comment(base_url, session_id, section_id, author, text):
    resp = httpx.post(
        f"{base_url}/api/sessions/{session_id}/comments",
        json={
            "section_id": section_id,
            "author": author,
            "text": text,
        },
    )
    assert resp.status_code == 201


class TestProposalPermissions:
    """Verify accept/reject buttons on proposals are only shown to authorised users."""

    def test_section_owner_sees_proposal_actions(
        self, page, base_url, create_session_via_api
    ):
        """Bob (owner of overview) should see accept/reject buttons on proposals."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        _post_comment(base_url, sid, "overview", "alice", "Needs revision.")

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(page)
        open_section(page, "overview")

        expect(page.locator(".proposal")).to_have_count(1, timeout=WS_TIMEOUT)
        expect(page.locator(".proposal-actions .btn-success")).to_be_visible()
        expect(page.locator(".proposal-actions .btn-danger")).to_be_visible()

    def test_coordinator_sees_proposal_actions(
        self, page, base_url, create_session_via_api
    ):
        """Alice (coordinator) should see accept/reject buttons on any section."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        _post_comment(base_url, sid, "overview", "bob", "Change this.")

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)
        open_section(page, "overview")

        expect(page.locator(".proposal")).to_have_count(1, timeout=WS_TIMEOUT)
        expect(page.locator(".proposal-actions .btn-success")).to_be_visible()
        expect(page.locator(".proposal-actions .btn-danger")).to_be_visible()

    def test_non_owner_does_not_see_proposal_actions(
        self, page, base_url, create_session_via_api
    ):
        """Carol (not owner of overview) should NOT see accept/reject buttons."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        _post_comment(base_url, sid, "overview", "alice", "Needs revision.")

        page.goto(f"{base_url}/session/{sid}?token={tokens['carol']}")
        wait_for_workspace(page)
        open_section(page, "overview")

        # Proposal is visible but action buttons are not in the DOM
        # (buildProposalEl only appends .proposal-actions when showActions=true)
        expect(page.locator(".proposal")).to_have_count(1, timeout=WS_TIMEOUT)
        expect(page.locator(".proposal-actions .btn-success")).to_have_count(0)
        expect(page.locator(".proposal-actions .btn-danger")).to_have_count(0)


class TestSectionActionPermissions:
    """Verify approve/skip/reopen buttons respect role-based visibility."""

    def test_coordinator_sees_approve_on_all_sections(
        self, page, base_url, create_session_via_api
    ):
        """Alice (coordinator) should see the approve button on every section."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        for section_id in ("overview", "details", "notes"):
            open_section(page, section_id)
            # Approve button uses display:inline-block vs display:none
            expect(page.locator("#review-approve-btn")).to_be_visible()

    def test_owner_sees_approve_on_own_section(
        self, page, base_url, create_session_via_api
    ):
        """Bob should see approve on overview (his section) but not on others."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(page)

        # Bob's section (overview) -- approve visible
        open_section(page, "overview")
        expect(page.locator("#review-approve-btn")).to_be_visible()

        # Carol's section (details) -- approve hidden for bob
        open_section(page, "details")
        expect(page.locator("#review-approve-btn")).to_be_hidden()

        # Unassigned section (notes) -- approve hidden for bob
        open_section(page, "notes")
        expect(page.locator("#review-approve-btn")).to_be_hidden()

    def test_skip_only_on_non_required_sections(
        self, page, base_url, create_session_via_api
    ):
        """Skip button should only appear on optional/recommended sections, not required."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        # overview is required -- no skip
        open_section(page, "overview")
        expect(page.locator("#review-skip-btn")).to_be_hidden()

        # details is recommended -- skip visible
        open_section(page, "details")
        expect(page.locator("#review-skip-btn")).to_be_visible()

        # notes is optional -- skip visible
        open_section(page, "notes")
        expect(page.locator("#review-skip-btn")).to_be_visible()

    def test_reopen_visible_only_after_approval(
        self, page, base_url, create_session_via_api
    ):
        """Reopen button should appear only when a section is approved."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        open_section(page, "overview")

        # Before approval -- reopen hidden
        expect(page.locator("#review-reopen-btn")).to_be_hidden()

        # Approve the section
        page.click("#review-approve-btn")
        expect(page.locator("#review-reopen-btn")).to_be_visible(timeout=WS_TIMEOUT)

        # Approve button should now be hidden (status is approved)
        expect(page.locator("#review-approve-btn")).to_be_hidden()


class TestPublishedSessionPermissions:
    """Verify that published sessions disable action controls."""

    def test_published_session_hides_approve_and_skip(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        for section_id in ("overview", "details"):
            httpx.post(
                f"{base_url}/api/sessions/{sid}/sections/{section_id}/approve",
                json={"user_id": "alice"},
            )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/publish",
            json={"plugin": "markdown", "config": {}},
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        # Check an approved section -- approve and skip hidden
        open_section(page, "overview")
        expect(page.locator("#review-approve-btn")).to_be_hidden()
        expect(page.locator("#review-skip-btn")).to_be_hidden()

        # Check a skipped section -- approve and skip hidden
        open_section(page, "notes")
        expect(page.locator("#review-approve-btn")).to_be_hidden()
        expect(page.locator("#review-skip-btn")).to_be_hidden()

    def test_published_session_comment_input_disabled_for_approved(
        self, page, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        for section_id in ("overview", "details"):
            httpx.post(
                f"{base_url}/api/sessions/{sid}/sections/{section_id}/approve",
                json={"user_id": "alice"},
            )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/sections/notes/skip",
            json={"user_id": "alice"},
        )
        httpx.post(
            f"{base_url}/api/sessions/{sid}/publish",
            json={"plugin": "markdown", "config": {}},
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        open_section(page, "overview")
        expect(page.locator("#comment-input")).to_be_disabled()
        expect(page.locator("#submit-comment-btn")).to_be_disabled()
