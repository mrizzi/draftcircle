# tests/e2e/test_session_workflow.py
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import WS_TIMEOUT, open_section, wait_for_workspace

pytestmark = pytest.mark.e2e


class TestSessionWorkflow:
    def test_full_lifecycle_through_ui(self, page, base_url, create_session_via_api):
        """Walk through the complete session lifecycle in a single browser."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        # Verify section grid shows all 3 sections
        expect(page.locator(".sidebar-item")).to_have_count(3)

        open_section(page, "overview")

        # Verify draft content is visible (rendered markdown inside .draft-content)
        expect(page.locator("#review-draft .draft-content")).to_contain_text("Overview")

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
        page.click("#review-approve-btn")
        # Wait for section status to update via WebSocket
        expect(
            page.locator('.sidebar-item[data-section="overview"] .badge')
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        open_section(page, "details")

        # Approve details
        page.click("#review-approve-btn")
        expect(
            page.locator('.sidebar-item[data-section="details"] .badge')
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        open_section(page, "notes")

        # Skip notes (priority=optional so skip button is visible)
        page.click("#review-skip-btn")
        expect(page.locator('.sidebar-item[data-section="notes"] .badge')).to_have_text(
            "skipped", timeout=WS_TIMEOUT
        )

        # Publish -- click publish button to open modal, fill form, submit
        # Publish via API to avoid modal/alert complexity in E2E
        import httpx

        httpx.post(
            f"{base_url}/api/sessions/{sid}/publish",
            json={"config": {"output_path": f"/tmp/e2e-{sid}.md"}},
        )

        # Wait for published state -- button should become disabled
        expect(page.locator("#publish-btn")).to_be_disabled(timeout=WS_TIMEOUT)

    def test_reject_proposal_keeps_draft(self, page, base_url, create_session_via_api):
        """Rejecting a proposal should leave the draft unchanged."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(page)

        open_section(page, "overview")

        # Get current draft text
        draft_text = page.locator("#review-draft .draft-content").text_content()

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
        expect(page.locator("#review-draft .draft-content")).to_have_text(draft_text)

    def test_reopen_section(self, page, base_url, create_session_via_api):
        """Approving and then reopening a section should restore it to draft status."""
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        open_section(page, "overview")

        page.click("#review-approve-btn")
        expect(
            page.locator('.sidebar-item[data-section="overview"] .badge')
        ).to_have_text("approved", timeout=WS_TIMEOUT)

        # Reopen button should appear after approval
        expect(page.locator("#review-reopen-btn")).to_be_visible(timeout=WS_TIMEOUT)
        page.click("#review-reopen-btn")

        # Section should return to in-review status (reopen transitions to in-review)
        expect(
            page.locator('.sidebar-item[data-section="overview"] .badge')
        ).to_have_text("in-review", timeout=WS_TIMEOUT)
