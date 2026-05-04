# tests/e2e/conftest.py
import asyncio
import json
import socket
from threading import Thread
from unittest.mock import AsyncMock, MagicMock

import httpx
import pygit2
import pytest
import uvicorn
from playwright.sync_api import expect

from backend.main import create_app
from tests.conftest import SAMPLE_TEMPLATE
from tests.integration.conftest import INTEGRATION_USERS, _ai_side_effect

WORKSPACE_TIMEOUT = 15000
WS_TIMEOUT = 10000


def wait_for_workspace(page):
    expect(page.locator("#view-workspace")).to_have_class(
        "view active", timeout=WORKSPACE_TIMEOUT
    )


def open_section(page, section_id):
    page.locator(f'.section-card[data-section="{section_id}"]').click()
    page.wait_for_selector("#detail-panel.panel-visible")


def close_panel(page):
    page.click("#panel-close-btn")
    page.wait_for_selector("#detail-panel:not(.panel-visible)")


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url, timeout=10):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/api/templates", timeout=1)
            return
        except httpx.ConnectError:
            time.sleep(0.1)
    raise RuntimeError(f"Server at {url} did not start within {timeout}s")


@pytest.fixture(scope="session")
def e2e_server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("e2e_data")
    pygit2.init_repository(str(data_dir))

    from backend.git_store import GitStore

    git = GitStore(data_dir)
    git.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE, indent=2),
            "users.json": json.dumps(INTEGRATION_USERS, indent=2),
        },
    )

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=_ai_side_effect)

    app = create_app(data_repo_path=str(data_dir), anthropic_client=mock_client)

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    thread = Thread(target=_run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    _wait_for_server(base_url)

    yield {"url": base_url, "port": port, "data_dir": data_dir, "server": server}

    server.should_exit = True
    thread.join(timeout=10)
    if thread.is_alive():
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
    if not loop.is_closed():
        loop.close()


@pytest.fixture(scope="session")
def base_url(e2e_server):
    return e2e_server["url"]


@pytest.fixture()
def create_session_via_api(base_url):
    def _create(
        template_slug="test-template",
        coordinator="alice",
        participants=None,
        seed_text="E2E test seed content.",
    ):
        if participants is None:
            participants = [
                {
                    "user_id": "alice",
                    "assigned_sections": ["overview", "details", "notes"],
                    "role": "coordinator",
                },
                {
                    "user_id": "bob",
                    "assigned_sections": ["overview"],
                    "role": "participant",
                },
                {
                    "user_id": "carol",
                    "assigned_sections": ["details"],
                    "role": "participant",
                },
            ]
        resp = httpx.post(
            f"{base_url}/api/sessions",
            json={
                "template": template_slug,
                "coordinator": coordinator,
                "participants": participants,
                "seed_text": seed_text,
            },
        )
        assert resp.status_code == 201
        session = resp.json()
        tokens = {p["user_id"]: p["token"] for p in session["participants"]}
        return {"id": session["id"], "tokens": tokens, "session": session}

    return _create
