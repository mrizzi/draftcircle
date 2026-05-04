# tests/e2e/test_permissions_ui.py
import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

WORKSPACE_TIMEOUT = 15000
WS_TIMEOUT = 10000


def _wait_for_workspace(pg):
    expect(pg.locator("#view-workspace")).to_have_class(
        "view active", timeout=WORKSPACE_TIMEOUT
    )


def _open_section(page, section_id):
    page.locator(f'.section-card[data-section="{section_id}"]').click()
    page.wait_for_selector("#detail-panel.panel-visible")


def _close_panel(page):
    page.click("#panel-close-btn")
    page.wait_for_selector("#detail-panel:not(.panel-visible)")


def _post_comment(base_url, session_id, section_id, author, text):
    """Post a comment via API, which triggers the mock AI to create a proposal."""
    httpx.post(
        f"{base_url}/api/sessions/{session_id}/comments",
        json={
            "section_id": section_id,
            "author": author,
            "text": text,
        },
    )


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
        _wait_for_workspace(page)
        _open_section(page, "overview")

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
        _wait_for_workspace(page)
        _open_section(page, "overview")

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
        _wait_for_workspace(page)
        _open_section(page, "overview")

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
        _wait_for_workspace(page)

        for section_id in ("overview", "details", "notes"):
            _open_section(page, section_id)
            # Approve button uses display:inline-block vs display:none
            expect(page.locator("#panel-approve-btn")).to_be_visible()
            _close_panel(page)

    def test_owner_sees_approve_on_own_section(
        self, page, base_url, create_session_via_api
    ):
        """Bob should see approve on overview (his section) but not on others."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        _wait_for_workspace(page)

        # Bob's section (overview) -- approve visible
        _open_section(page, "overview")
        expect(page.locator("#panel-approve-btn")).to_be_visible()
        _close_panel(page)

        # Carol's section (details) -- approve hidden for bob
        _open_section(page, "details")
        expect(page.locator("#panel-approve-btn")).to_be_hidden()
        _close_panel(page)

        # Unassigned section (notes) -- approve hidden for bob
        _open_section(page, "notes")
        expect(page.locator("#panel-approve-btn")).to_be_hidden()

    def test_skip_only_on_non_required_sections(
        self, page, base_url, create_session_via_api
    ):
        """Skip button should only appear on optional/recommended sections, not required."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        # overview is required -- no skip
        _open_section(page, "overview")
        expect(page.locator("#panel-skip-btn")).to_be_hidden()
        _close_panel(page)

        # details is recommended -- skip visible
        _open_section(page, "details")
        expect(page.locator("#panel-skip-btn")).to_be_visible()
        _close_panel(page)

        # notes is optional -- skip visible
        _open_section(page, "notes")
        expect(page.locator("#panel-skip-btn")).to_be_visible()

    def test_reopen_visible_only_after_approval(
        self, page, base_url, create_session_via_api
    ):
        """Reopen button should appear only when a section is approved."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        _open_section(page, "overview")

        # Before approval -- reopen hidden
        expect(page.locator("#panel-reopen-btn")).to_be_hidden()

        # Approve the section
        page.click("#panel-approve-btn")
        expect(page.locator("#panel-reopen-btn")).to_be_visible(timeout=WS_TIMEOUT)

        # Approve button should now be hidden (status is approved)
        expect(page.locator("#panel-approve-btn")).to_be_hidden()


class TestPublishedSessionPermissions:
    """Verify that published sessions disable action controls."""

    def test_published_session_hides_approve_and_skip(
        self, page, base_url, create_session_via_api
    ):
        """After publishing, approve and skip buttons should be hidden."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        # Approve and publish via API
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
            json={
                "config": {
                    "output_path": "/tmp/e2e-pub-perm.md",
                    "allowed_dir": "/tmp",
                }
            },
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        # Check an approved section -- approve and skip hidden
        _open_section(page, "overview")
        expect(page.locator("#panel-approve-btn")).to_be_hidden()
        expect(page.locator("#panel-skip-btn")).to_be_hidden()
        _close_panel(page)

        # Check a skipped section -- approve and skip hidden
        _open_section(page, "notes")
        expect(page.locator("#panel-approve-btn")).to_be_hidden()
        expect(page.locator("#panel-skip-btn")).to_be_hidden()

    def test_published_session_comment_input_disabled_for_approved(
        self, page, base_url, create_session_via_api
    ):
        """Comments should be disabled on approved sections in a published session."""
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
            json={
                "config": {
                    "output_path": "/tmp/e2e-pub-perm2.md",
                    "allowed_dir": "/tmp",
                }
            },
        )

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        _open_section(page, "overview")
        expect(page.locator("#comment-input")).to_be_disabled()
        expect(page.locator("#submit-comment-btn")).to_be_disabled()
