# tests/e2e/test_realtime_sync.py
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

WORKSPACE_TIMEOUT = 15000
WS_TIMEOUT = 10000


def _wait_for_workspace(pg):
    expect(pg.locator("#view-workspace")).to_have_class(
        "view active", timeout=WORKSPACE_TIMEOUT
    )


class TestRealtimeSync:
    def test_comment_appears_in_other_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        _wait_for_workspace(bob_page)

        carol_ctx = new_context()
        carol_page = carol_ctx.new_page()
        carol_page.goto(f"{base_url}/session/{sid}?token={tokens['carol']}")
        _wait_for_workspace(carol_page)

        page.locator('.section-card[data-section="overview"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")

        bob_page.locator('.section-card[data-section="overview"]').click()
        bob_page.wait_for_selector("#detail-panel.panel-visible")

        carol_page.locator('.section-card[data-section="overview"]').click()
        carol_page.wait_for_selector("#detail-panel.panel-visible")

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
        _wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        _wait_for_workspace(bob_page)

        page.locator('.section-card[data-section="overview"]').click()
        page.wait_for_selector("#detail-panel.panel-visible")
        page.click("#panel-approve-btn")

        expect(
            bob_page.locator(
                '.section-card[data-section="overview"] .section-card-header .badge'
            )
        ).to_have_text("approved", timeout=WS_TIMEOUT)

    def test_publish_updates_all_browsers(
        self, page, new_context, base_url, create_session_via_api
    ):
        session = create_session_via_api()
        sid, tokens = session["id"], session["tokens"]

        page.goto(f"{base_url}/session/{sid}?token={tokens['alice']}")
        _wait_for_workspace(page)

        bob_ctx = new_context()
        bob_page = bob_ctx.new_page()
        bob_page.goto(f"{base_url}/session/{sid}?token={tokens['bob']}")
        _wait_for_workspace(bob_page)

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

        page.wait_for_timeout(1000)

        page.on("dialog", lambda dialog: dialog.accept())

        page.click("#publish-btn")

        expect(bob_page.locator("#publish-btn")).to_be_disabled(timeout=WS_TIMEOUT)
