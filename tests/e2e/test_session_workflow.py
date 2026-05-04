# tests/e2e/test_session_workflow.py
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

WORKSPACE_TIMEOUT = 15000
WS_TIMEOUT = 10000


def _wait_for_workspace(pg):
    expect(pg.locator("#view-workspace")).to_have_class(
        "view active", timeout=WORKSPACE_TIMEOUT
    )


class TestSessionWorkflow:
    def test_full_lifecycle_through_ui(
        self, page, base_url, create_session_via_api
    ):
        """Walk through the complete session lifecycle in a single browser."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        # Verify section grid shows all 3 sections
        expect(page.locator(".section-card")).to_have_count(3)

        # Click overview section -- detail panel opens
        page.locator('.section-card[data-section="overview"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        # Verify draft content is visible (rendered markdown inside .draft-content)
        expect(page.locator("#panel-draft .draft-content")).to_contain_text("Overview")

        # Post a comment
        page.fill("#comment-input", "Needs more detail here.")
        page.click("#submit-comment-btn")
        expect(page.locator("#comments-thread .comment")).to_have_count(
            1, timeout=WS_TIMEOUT
        )

        # AI proposal should appear (mock AI returns proposal for every comment)
        expect(page.locator(".proposal")).to_have_count(1, timeout=WS_TIMEOUT)

        # Accept proposal -- alice is coordinator, can accept any section
        page.locator(".proposal-actions .btn-success").click()

        # Wait for proposal to be processed and panel to re-render
        expect(page.locator(".proposal-actions .btn-success")).to_have_count(
            0, timeout=WS_TIMEOUT
        )

        # Approve overview section
        page.click("#panel-approve-btn")
        # Wait for section status to update via WebSocket
        expect(
            page.locator(
                '.section-card[data-section="overview"] .section-card-header .badge'
            )
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        # Close panel and navigate to details section
        page.click("#panel-close-btn")
        page.wait_for_selector("#detail-panel:not(.panel-visible)")
        page.locator('.section-card[data-section="details"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        # Approve details
        page.click("#panel-approve-btn")
        expect(
            page.locator(
                '.section-card[data-section="details"] .section-card-header .badge'
            )
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        # Close panel and navigate to notes section (optional -- can be skipped)
        page.click("#panel-close-btn")
        page.wait_for_selector("#detail-panel:not(.panel-visible)")
        page.locator('.section-card[data-section="notes"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        # Skip notes (priority=optional so skip button is visible)
        page.click("#panel-skip-btn")
        expect(
            page.locator(
                '.section-card[data-section="notes"] .section-card-header .badge'
            )
        ).to_have_text("skipped", timeout=WS_TIMEOUT)

        # Close panel
        page.click("#panel-close-btn")
        page.wait_for_selector("#detail-panel:not(.panel-visible)")

        # Publish -- handle both confirm() and alert() dialogs
        page.on("dialog", lambda d: d.accept())
        page.click("#publish-btn")

        # Wait for published state -- button should become disabled
        expect(page.locator("#publish-btn")).to_be_disabled(timeout=WS_TIMEOUT)

    def test_reject_proposal_keeps_draft(
        self, page, base_url, create_session_via_api
    ):
        """Rejecting a proposal should leave the draft unchanged."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        _wait_for_workspace(page)

        # Open overview (bob is assigned to overview)
        page.locator('.section-card[data-section="overview"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        # Get current draft text
        draft_text = page.locator("#panel-draft .draft-content").text_content()

        # Comment and wait for proposal
        page.fill("#comment-input", "Maybe change this?")
        page.click("#submit-comment-btn")
        expect(page.locator(".proposal")).to_have_count(1, timeout=WS_TIMEOUT)

        # Reject proposal
        page.locator(".proposal-actions .btn-danger").click()

        # Wait for proposal to be processed
        expect(page.locator(".proposal-actions .btn-danger")).to_have_count(
            0, timeout=WS_TIMEOUT
        )

        # Draft unchanged
        expect(page.locator("#panel-draft .draft-content")).to_have_text(draft_text)

    def test_reopen_section(self, page, base_url, create_session_via_api):
        """Approving and then reopening a section should restore it to draft status."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        page.locator('.section-card[data-section="overview"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        # Approve
        page.click("#panel-approve-btn")
        expect(
            page.locator(
                '.section-card[data-section="overview"] .section-card-header .badge'
            )
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        # Reopen button should appear after approval
        expect(page.locator("#panel-reopen-btn")).to_be_visible(timeout=WS_TIMEOUT)
        page.click("#panel-reopen-btn")

        # Section should return to in-review status (reopen transitions to in-review)
        expect(
            page.locator(
                '.section-card[data-section="overview"] .section-card-header .badge'
            )
        ).to_have_text("in-review", timeout=WS_TIMEOUT)
