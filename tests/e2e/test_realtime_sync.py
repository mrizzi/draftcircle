# tests/e2e/test_realtime_sync.py
import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import WS_TIMEOUT, open_section, wait_for_workspace

pytestmark = pytest.mark.e2e


class TestRealtimeSync:
    def test_comment_appears_in_other_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(bob_page)

        carol_ctx = new_context()
        carol_page = carol_ctx.new_page()
        carol_page.goto(f"{base_url}/session/{sid}?token={tokens['carol']}")
        wait_for_workspace(carol_page)

        for p in (page, bob_page, carol_page):
            open_section(p, "overview")

        page.fill("#comment-input", "This needs more detail.")
        page.click("#submit-comment-btn")

        for p in (page, bob_page, carol_page):
            expect(p.locator("#comments-thread .comment")).to_have_count(
                1, timeout=WS_TIMEOUT
            )

    def test_section_approval_updates_all_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(bob_page)

        open_section(page, "overview")
        page.click("#review-approve-btn")

        expect(
            bob_page.locator('.sidebar-item[data-section="overview"] .badge')
        ).to_have_text("approved", timeout=WS_TIMEOUT)

    def test_publish_updates_all_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        wait_for_workspace(bob_page)

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

        expect(page.locator("#publish-btn")).to_be_enabled(timeout=WS_TIMEOUT)

        # Publish via API to avoid modal/alert complexity in E2E
        httpx.post(
            f"{base_url}/api/sessions/{sid}/publish",
            json={"config": {}},
        )

        expect(bob_page.locator("#publish-btn")).to_be_disabled(timeout=WS_TIMEOUT)
