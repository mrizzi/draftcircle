# Integration Test Suite Design

Date: 2026-05-02

## Goal

Eliminate manual multi-browser testing by adding two layers of
automated integration tests:

1. **Backend integration tests** — fast, reliable tests using
   FastAPI's TestClient for HTTP + WebSocket against the ASGI app
   directly. No real server needed.
2. **Playwright E2E tests** — browser-level tests with an
   auto-managed uvicorn server. Three browser contexts simulating
   three concurrent users.

Both layers use mocked AI (deterministic responses, no Claude API
calls).

------------------------------------------------------------------------

## Directory Structure

```
tests/
  conftest.py                    # existing shared fixtures
  integration/
    conftest.py                  # TestClient fixtures, mock AI, session helpers
    test_workflow.py             # full session lifecycle via API
    test_multi_client.py         # WebSocket broadcast with 3 connected clients
    test_authorization.py        # permission enforcement across all endpoints
    test_concurrency.py          # concurrent operations on same session
  e2e/
    conftest.py                  # uvicorn server fixture, Playwright browser setup
    test_realtime_sync.py        # 3 browsers, one acts, others see it
    test_session_workflow.py     # single browser walkthrough of full lifecycle
    test_permissions_ui.py       # different users see different UI controls
```

------------------------------------------------------------------------

## Pytest Configuration

```toml
[tool.pytest.ini_options]
markers = [
    "integration: backend integration tests (no browser)",
    "e2e: end-to-end browser tests (requires Playwright)",
]
asyncio_mode = "auto"
```

**Running tests:**

- `pytest tests/` — everything (unit + integration + e2e)
- `pytest tests/integration/` — backend integration only (fast)
- `pytest tests/e2e/` — Playwright only (slower)
- `pytest -m "not e2e"` — skip browser tests in local dev

**New dependencies** (added to `[project.optional-dependencies] dev`):

- `pytest-playwright>=0.6`

Playwright browsers installed via `playwright install` (one-time
setup).

------------------------------------------------------------------------

## Backend Integration Tests

### Fixtures

`tests/integration/conftest.py` provides:

- `integration_app` — FastAPI app with populated data repo (template,
  users) and mocked AI orchestrator that returns deterministic
  proposals.
- `api` — `TestClient(integration_app)` for HTTP + WebSocket calls.
- `session_with_drafts` — pre-created session with 3 participants
  (alice as coordinator, bob and carol as section owners) and
  AI-generated drafts. Returns session ID and token map.

**Mock AI approach:** A deterministic `AIOrchestrator` substitute
injected at the app level. When a comment is posted, it always returns
a `ProposalResult` with predictable revised text. No Claude API calls.
Pattern extends the existing `mock_client` approach in
`tests/conftest.py` but operates at the orchestrator level.

### test_workflow.py — Full Session Lifecycle

Covers the complete path from user creation through publish and git
verification.

**User registry integration:**

- Create users via `POST /api/users`
- Use created users as session participants
- Verify tokens resolve correctly

**Template loading integration:**

- Create sessions from templates with different configurations:
  required-only sections, mix of required/optional/recommended,
  different output plugins
- Verify section metadata matches template definition

**Core workflow:**

- Create session with template and participants
- AI generates initial drafts for all sections
- Post comment -> AI proposes revision -> accept proposal -> draft
  updates
- Post comment -> AI proposes revision -> reject proposal -> draft
  unchanged
- Approve all required sections -> `ready_to_publish` becomes true
- Skip optional section -> counts toward progress
- Publish -> plugin assembles and publishes -> session becomes
  read-only
- Post-publish: comments and proposals fail with appropriate errors

**Git persistence verification:**

- After each major action (comment, accept, approve, publish), verify:
  - Git log contains the expected commit message
  - File content on disk matches expected state
  - Session history endpoint returns correct entries

**Plugin integration:**

- Publish with built-in plugin -> verify `assemble()` and `publish()`
  called correctly
- Custom plugin in data repo overrides built-in -> verify override
  takes effect

### test_multi_client.py — WebSocket Broadcast (3 Clients)

All tests use 3 concurrent WebSocket connections: alice (coordinator),
bob (section owner), carol (section owner of a different section).

A `drain_join_messages()` helper consumes `participant_joined`
messages that fire during connection setup, so test assertions start
clean.

**Scenarios:**

- Three clients connect -> each receives `participant_joined` for
  subsequent joiners
- Bob comments -> alice AND carol receive `comment_added`
- Bob accepts proposal -> alice AND carol receive `proposal_accepted`
- Alice (coordinator) approves section -> bob AND carol receive
  `section_approved`
- Alice publishes -> bob AND carol receive `session_published`
- Carol disconnects -> alice AND bob receive `participant_left`
- AI proposes revision -> all three receive `proposal_created`
- One client disconnects mid-broadcast -> remaining two still receive
  messages (no error propagation)

**Pattern:**

```python
def test_comment_broadcasts_to_all_three(api, session_with_drafts):
    sid = session_with_drafts["id"]
    tokens = session_with_drafts["tokens"]

    with api.websocket_connect(f"/ws/sessions/{sid}?token={tokens['alice']}") as ws_a:
        with api.websocket_connect(f"/ws/sessions/{sid}?token={tokens['bob']}") as ws_b:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={tokens['carol']}") as ws_c:
                drain_join_messages(ws_a, ws_b, ws_c)

                api.post(
                    f"/api/sessions/{sid}/comments",
                    json={"section_id": "01-overview", "text": "Expand this"},
                    params={"token": tokens["bob"]},
                )

                for ws in (ws_a, ws_b, ws_c):
                    msg = ws.receive_json()
                    assert msg["type"] == "comment_added"
```

### test_authorization.py — Permission Enforcement

- Non-owner cannot accept/reject proposals on others' sections (403)
- Non-owner cannot approve/reopen/skip others' sections (403)
- Coordinator can act on any section (200)
- Any participant can comment on any section (200)
- Invalid token on WebSocket -> connects but user_id is null (no
  participant_joined broadcast with a name)
- Invalid token on HTTP endpoints -> user_id unresolved, owner-
  restricted actions return 403
- Non-participant token -> appropriate restrictions on both HTTP and
  WebSocket

### test_concurrency.py — Race Conditions & Edge Cases

- Two proposals pending on same section -> both can exist
- Accept one proposal, reject another -> correct draft wins
- Comment while AI is processing previous comment -> both processed
- Approve section then immediately comment -> comment rejected
  (section locked)
- Reopen approved section -> commenting works again

------------------------------------------------------------------------

## Playwright E2E Tests

### Server Management

A session-scoped fixture starts a real uvicorn server:

```python
@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """Start uvicorn on a random port with a populated data repo."""
    # init git repo, write template + users
    # start uvicorn subprocess on random port
    # yield {"url": f"http://localhost:{port}", "data_dir": data_dir}
    # terminate subprocess on teardown
```

The server uses a fresh temporary data repo populated with the same
template and users used in backend tests. It stays up for all e2e
tests in the session.

### E2E Fixtures

`tests/e2e/conftest.py` provides:

- `server` (session-scoped) — uvicorn subprocess with populated data
  repo. Returns `{"url": ..., "data_dir": ...}`.
- `api_url` — shorthand for `server["url"]`.
- `create_session_via_api(template_slug, participants)` — helper that
  creates a session by calling the HTTP API directly (not through the
  browser). Returns session ID and token map. Used by
  `test_realtime_sync.py` and `test_permissions_ui.py` so they start
  with a ready session instead of navigating the creation UI.
- `test_session_workflow.py` does NOT use this helper — it creates
  sessions through the UI as part of the test.

### Multi-Browser Contexts

Playwright's `new_context` fixture creates isolated browser contexts
(separate cookies, storage, WebSocket connections) without launching
separate browser processes. Three contexts simulate three users.

```python
def test_realtime(page, new_context, server):
    # Alice (default page)
    page.goto(f"{server['url']}/session/{sid}?token={alice_token}")

    # Bob (separate context)
    bob_ctx = new_context()
    bob_page = bob_ctx.new_page()
    bob_page.goto(f"{server['url']}/session/{sid}?token={bob_token}")

    # Carol (third context)
    carol_ctx = new_context()
    carol_page = carol_ctx.new_page()
    carol_page.goto(f"{server['url']}/session/{sid}?token={carol_token}")
```

### Assertions

All assertions use Playwright locators with auto-waiting rather than
fixed sleeps:

```python
expect(bob_page.locator(".comment-item")).to_have_count(1)
expect(bob_page.locator(".comment-item .comment-text")).to_have_text("Expand this")
```

### test_realtime_sync.py — Multi-Browser Real-Time Sync

- Alice comments in browser A -> comment appears in browsers B and C
  without refresh
- Bob accepts a proposal -> alice and carol see the draft update in
  real time
- Alice approves a section -> progress bar updates in all browsers
- Carol disconnects (closes tab) -> participant count updates for
  alice and bob
- Alice publishes -> all browsers show "published" status, controls
  become read-only

### test_session_workflow.py — Single-Browser Full Lifecycle

- Navigate to session list -> see available sessions
- Create a new session from template -> redirected to workspace
- See AI-generated drafts in section grid
- Click section -> detail panel opens with content
- Post a comment -> comment appears in thread, AI proposal appears
- Accept proposal -> draft updates in place
- Reject proposal -> draft stays unchanged
- Approve section -> section card shows "approved" badge
- Reopen section -> badge clears, section editable again
- Skip optional section -> section card shows "skipped"
- All required sections approved -> "Publish" button becomes active
- Click Publish -> success state, session becomes read-only

### test_permissions_ui.py — UI Reflects User Permissions

- Section owner sees accept/reject buttons on proposals for their
  section
- Non-owner does NOT see accept/reject buttons on others' sections
- Coordinator sees approve/skip controls on all sections
- Non-coordinator only sees approve on their own sections
- After publish: no comment box, no action buttons visible

------------------------------------------------------------------------

## Test Scenario Matrix

| Scenario | Backend Integration | Playwright E2E |
|---|---|---|
| User registry -> create via API, use in sessions | test_workflow.py | -- |
| Template loading -> various configs | test_workflow.py | -- |
| Session lifecycle (create -> publish) | test_workflow.py | test_session_workflow.py |
| Git persistence -> verify commits, files, history | test_workflow.py | -- |
| Plugin discovery -> built-in and custom override | test_workflow.py | -- |
| Post-publish lockdown | test_workflow.py | test_session_workflow.py |
| 3-client broadcast -> all message types | test_multi_client.py | test_realtime_sync.py |
| Disconnect handling | test_multi_client.py | test_realtime_sync.py |
| Authorization enforcement | test_authorization.py | test_permissions_ui.py |
| Concurrent operations | test_concurrency.py | -- |
| AI proposal flow (mocked) | test_workflow.py | test_session_workflow.py |

------------------------------------------------------------------------

## Out of Scope

Covered by existing unit tests with no additional integration value:

- **Pydantic model serialization** — exercised implicitly by every API
  call in integration tests.
- **AI tool calling internals** — mocked in integration tests by
  design. Unit tests in `test_ai_orchestrator.py` cover the real
  orchestrator logic.

------------------------------------------------------------------------

## Deliverables

### TESTING.md

A `TESTING.md` file at the project root documenting the test suite
for users and contributors. Contents:

- **Prerequisites** — Python version, how to install dev dependencies
  (`pip install -e ".[dev]"`), Playwright browser installation
  (`playwright install`).
- **Test suite overview** — description of the three test layers
  (unit, integration, e2e) and what each covers.
- **Running tests** — commands for running all tests, just unit tests,
  just integration, just e2e, and how to skip e2e in local dev.
- **Writing new tests** — which directory to put new tests in based on
  what they test, naming conventions, available fixtures and helpers,
  how to use the mock AI, how to set up multi-client WebSocket tests.
- **CI considerations** — notes on Playwright browser caching, test
  parallelism, and expected run times for each layer.
