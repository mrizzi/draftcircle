# tests/e2e/test_create_session_form.py
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import WORKSPACE_TIMEOUT

pytestmark = pytest.mark.e2e


class TestCreateSessionForm:
    def test_template_selection_shows_section_grid(self, page, base_url):
        page.goto(base_url)
        expect(page.locator("#view-session-list")).to_have_class("view active")

        page.click("#create-session-btn")
        expect(page.locator("#view-create-session")).to_have_class("view active")

        expect(page.locator(".section-owner-row")).to_have_count(3)

        titles = page.locator(".section-owner-title").all_text_contents()
        assert "Overview" in titles
        assert "Details" in titles
        assert "Notes" in titles

    def test_auto_suggestion_preselects_matching_users(self, page, base_url):
        page.goto(base_url)
        page.click("#create-session-btn")
        expect(page.locator(".section-owner-row")).to_have_count(3)

        overview_select = page.locator(
            '.section-owner-select[data-section-id="overview"]'
        )
        expect(overview_select).to_have_value("alice")

        details_select = page.locator(
            '.section-owner-select[data-section-id="details"]'
        )
        expect(details_select).to_have_value("bob")

        notes_select = page.locator('.section-owner-select[data-section-id="notes"]')
        expect(notes_select).to_have_value("")

    def test_submit_creates_session_with_assignments(self, page, base_url):
        page.goto(base_url)
        page.click("#create-session-btn")
        expect(page.locator(".section-owner-row")).to_have_count(3)

        page.locator('.section-owner-select[data-section-id="notes"]').select_option(
            "carol"
        )

        page.fill("#seed-text", "E2E test seed content.")

        page.click('button[type="submit"]')

        expect(page.locator("#view-session-list")).to_have_class(
            "view active", timeout=WORKSPACE_TIMEOUT
        )

    def test_required_unassigned_auto_assigns_to_coordinator(self, page, base_url):
        page.goto(base_url)
        page.click("#create-session-btn")
        expect(page.locator(".section-owner-row")).to_have_count(3)

        page.locator('.section-owner-select[data-section-id="overview"]').select_option(
            ""
        )

        page.fill("#seed-text", "Testing auto-assign.")

        page.click('button[type="submit"]')

        expect(page.locator("#view-session-list")).to_have_class(
            "view active", timeout=WORKSPACE_TIMEOUT
        )
