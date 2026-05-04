# Testing

DraftCircle uses three test layers: **unit**, **backend integration**,
and **end-to-end (E2E)**.

## Prerequisites

- Python >= 3.12
- Install all dev dependencies:

```bash
pip install -e ".[dev]"
```

For E2E tests, install Playwright browsers:

```bash
python3 -m playwright install chromium
```

## Running Tests

```bash
# All tests (unit + integration + E2E)
pytest tests/

# Unit tests only
pytest tests/ --ignore=tests/integration --ignore=tests/e2e

# Backend integration only (fast, no browser)
pytest tests/integration/

# E2E only (requires Playwright browsers)
pytest tests/e2e/ --browser chromium

# Skip E2E in local development
pytest -m "not e2e"
```

## Test Layers

### Unit Tests (`tests/test_*.py`)

Test individual modules in isolation: git store, session manager,
models, AI orchestrator, plugins, user registry, template loader.
Fast. No real server. Mocked dependencies.

### Backend Integration (`tests/integration/`)

Test multi-component workflows through the FastAPI app using
`TestClient`. Covers:

- **test_workflow.py** — full session lifecycle from user creation
  to publish, with git state verification
- **test_multi_client.py** — 3 WebSocket clients verifying broadcast
  delivery for all message types
- **test_authorization.py** — permission enforcement for all
  section actions
- **test_concurrency.py** — concurrent proposals, state transitions,
  race conditions

Uses a mocked AI orchestrator (deterministic proposals, no API calls).

### E2E Tests (`tests/e2e/`)

Browser-level tests with Playwright against a real uvicorn server
(started automatically). Covers:

- **test_realtime_sync.py** — 3 browser contexts verifying DOM updates
  propagate in real time across users
- **test_session_workflow.py** — single-browser walkthrough of the
  entire session lifecycle via UI
- **test_permissions_ui.py** — correct controls visible for owner vs
  non-owner vs coordinator

## Writing New Tests

### Where to put tests

| What you're testing | Directory |
|---|---|
| A single module in isolation | `tests/test_<module>.py` |
| Multi-component workflow via API | `tests/integration/` |
| UI behavior in a real browser | `tests/e2e/` |

### Fixtures

**Integration tests** use fixtures from `tests/integration/conftest.py`:

- `integration_app` — FastAPI app with 3 users and mock AI
- `api` — `TestClient` for HTTP + WebSocket
- `session_with_drafts` — pre-created session (alice coordinator,
  bob owns overview, carol owns details), AI-generated drafts ready

**E2E tests** use fixtures from `tests/e2e/conftest.py`:

- `e2e_server` — auto-started uvicorn on random port
- `base_url` — the server URL
- `create_session_via_api()` — creates a session via HTTP (not the UI)

### Multi-client WebSocket pattern

```python
from tests.integration.conftest import drain_join_messages

def test_my_broadcast(api, session_with_drafts):
    sid = session_with_drafts["id"]
    t = session_with_drafts["tokens"]

    with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                drain_join_messages(ws_a, ws_b, ws_c)

                # Perform action, then assert on ws_a, ws_b, ws_c
```

### Mock AI

The integration and E2E test suites use a deterministic mock AI:
- Comments always trigger a `ProposalResult` with fixed text
- Session creation with `seed_text` generates drafts for all sections
- No Claude API calls

## CI Notes

- Integration tests run in seconds (no browser, no network)
- E2E tests take 10-30s (browser startup + page loads)
- Cache `~/.cache/ms-playwright` for faster Playwright browser setup
- Run `python3 -m playwright install --with-deps chromium` in CI for headless
