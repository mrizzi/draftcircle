# Workspace UI Redesign

Fix the DraftCircle workspace to support the full end-to-end workflow:
create session → AI drafts → comment → AI proposes → accept/reject →
approve → publish.

## Problems

1. **Bad layout** — section cards in a 2-column grid waste space. The
   review panel is cramped in a narrow sidebar. Most of the page is
   whitespace.
2. **No coordinator identity** — without authentication, opening a
   session from the session list gives no identity. The coordinator
   can't act on sections.
3. **No post-creation reassignment** — section ownership is frozen
   after session creation. If assignments are wrong, there's no way
   to fix them.
4. **Invite links lost** — after the creation modal is dismissed, there
   is no way to retrieve invite links.

## Design

### 1. Sidebar + Main Area Layout

Replace the current grid-of-cards + slide-in panel with a two-column
layout:

- **Left sidebar** (~200px): vertical list of sections. Each item shows
  section title, status badge, and owner name. Clicking a section loads
  it in the main area. The selected section is highlighted.
- **Main area** (~80%): full content for the selected section — draft
  (rendered markdown), pending proposals with accept/reject buttons,
  past proposals, comment thread with input.

The section grid cards and the `#detail-panel` slide-in are both
removed. The sidebar and main area are always visible when viewing a
session.

### 2. Coordinator Invite Link

Session creation already generates tokens for participants. The
coordinator must also get a token and invite link.

**Backend change:** When creating a session, add the coordinator as a
participant with `role: "coordinator"` and their assigned sections (all
sections by default). The coordinator's token is returned in the
response like any other participant's.

**Frontend change:** The invite modal after creation includes the
coordinator's link. The coordinator must open their link to get
identity.

### 3. Inline Section Reassignment

Each section's owner is shown in the sidebar list item. Clicking the
owner name opens a dropdown of all registered users + "— unassigned —".
Anyone can reassign any section — not restricted to the coordinator.

**Backend change:** New endpoint `POST /api/sessions/{id}/sections/{section_id}/assign`
accepting `{ "user_id": "bob" }`. Updates section ownership and
broadcasts via WebSocket.

**Frontend change:** Owner name in sidebar is a clickable element that
reveals a `<select>` dropdown on click.

### 4. Invite Links in Sidebar Footer

A small "Invite links" link at the bottom of the section sidebar. Opens
the existing invite modal with all participant links (including
coordinator). Available to everyone.

**Note:** The invite links modal requires the session data to include
participant tokens. Currently tokens are stripped from `GET /api/sessions/{id}`
responses. The coordinator's view (authenticated via token) should
include tokens so the modal can display links.

## API Contract

### New endpoint

```
POST /api/sessions/{session_id}/sections/{section_id}/assign
Body: { "user_id": "bob" }
Response: { "status": "assigned" }
WebSocket broadcast: { "type": "section_assigned", "section_id": "...", "user_id": "..." }
```

### Modified behavior

- `POST /api/sessions` — coordinator is added as a participant with a
  token (if not already in the participants list)
- `GET /api/sessions/{id}?token=...` — when the token belongs to the
  coordinator, include participant tokens in the response so the invite
  modal can build links

## Scope

- Frontend: rewrite workspace view (sidebar + main area), add
  reassignment UI, add invite links in sidebar footer
- Backend: add assign endpoint, add coordinator as participant with
  token, conditionally include tokens for coordinator
- Tests: update E2E tests for new layout, add tests for reassignment
  and coordinator token

## Files

- Modify: `frontend/app.js` — rewrite workspace rendering
- Modify: `frontend/style.css` — sidebar + main area layout
- Modify: `frontend/index.html` — restructure workspace HTML
- Modify: `backend/main.py` — add assign endpoint, modify create
  session to include coordinator as participant, conditional token
  inclusion
- Modify: `backend/session_manager.py` — add assign_section method
- Update: `tests/e2e/test_session_workflow.py` — adapt to new layout
- Update: `tests/e2e/test_permissions_ui.py` — adapt to new layout
- Create: `tests/test_api.py` — add tests for assign endpoint
