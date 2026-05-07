# Streaming AI Activity & Progressive Draft Delivery

Combined design for two tightly coupled features:
1. **AI Activity Log Panel** — stream AI reasoning to a collapsible frontend panel during comment processing
2. **Session Creation Streaming** — progressive draft delivery during session creation via background task + WebSocket

Both features share streaming infrastructure in the orchestrator and new WebSocket event types.

---

## 1. Orchestrator Streaming Architecture

### `_run_query_streaming` (replaces `_run_query`)

Async generator that wraps the Claude Agent SDK `query()` call with streaming support.

- Adds `include_partial_messages=True` to `ClaudeAgentOptions` so the SDK yields `StreamEvent` text deltas alongside `AssistantMessage` and `ResultMessage` objects.
- Yields `("text_delta", str)` tuples for each AI reasoning fragment.
- Filters events by `StreamEvent.event["type"]`: only `content_block_delta` with `delta.type == "text_delta"` is yielded. Events with type `tool_use`, `input_json_delta`, or any other type are silently dropped — tool inputs must never be broadcast.
- Internally accumulates `content_blocks` (from `AssistantMessage`) and `session_id` (from `ResultMessage`).
- After iteration completes, yields `("result", (content_blocks, session_id))`.
- Stale-session retry logic preserved: on `ClaudeSDKError` with "session" in the message, retries without resume. The retry also yields streaming events.
- `store.flush()` called in `finally` block (unchanged).

New SDK import: `StreamEvent` from `claude_agent_sdk`.

### `process_comment` (converted to async generator)

- Still acquires `_section_locks[lock_key]` — the lock is held for the generator's lifetime.
- Yields `{"type": "ai_activity", "section_id": ..., "text": ...}` for each text delta from `_run_query_streaming`.
- After streaming completes, extracts `ProposalResult` or `ReplyResult` from content blocks (same logic as current implementation).
- Yields `{"type": "ai_complete", "section_id": ..., "result_type": "proposal"|"reply", "result": ProposalResult|ReplyResult, "session_id": ...}` as final event.

### `generate_drafts` (converted to async generator)

- Yields `{"type": "ai_activity", "section_id": None, "text": ...}` for reasoning fragments.
- After streaming completes, iterates content blocks. For each `write_section_draft` tool call, yields `{"type": "section_drafted", "section_id": ..., "content": ...}`.
- After all sections processed, yields `{"type": "drafts_complete", "session_id": ...}`.
- The intermediate `DraftResult` list is no longer returned — each draft is yielded individually.

---

## 2. Endpoint Changes (main.py)

### `add_comment` — inline streaming

After persisting the human comment and broadcasting `comment_added`:
1. Iterate over `ai.process_comment(...)`.
2. `ai_activity` events: broadcast via `ws_manager.broadcast(session_id, event)` immediately.
3. `ai_complete` event: extract result, create proposal or reply comment, broadcast `proposal_created` or `comment_added` as before.
4. On exception: broadcast `{"type": "ai_activity", "section_id": ..., "text": "AI processing encountered an error.", "error": true}`, then add an error comment: `sessions.add_comment(session_id, section_id, "ai", "I encountered an error processing this comment. Please try again.")`.
5. Endpoint still returns the human comment immediately (201). AI processing is inline (not background) because section locks prevent concurrent processing of the same section.

### `create_session` — background task + WebSocket

1. Create the session and return `JSONResponse(session.model_dump(mode="json"), status_code=201)` immediately. No more NDJSON streaming.
2. If `seed_text` and `ai` are present, start `asyncio.create_task(draft_in_background(...))`.
3. The background task:
   - Sets all sections to `DRAFTING` status, commits, broadcasts `{"type": "drafts_started", "session_id": ...}`.
   - Iterates over `ai.generate_drafts(...)`:
     - `ai_activity` events → broadcast via WebSocket.
     - `section_drafted` events → write draft to git, update section status `DRAFTING` → `DRAFT`, broadcast `{"type": "section_drafted", "section_id": ..., "status": "draft"}`.
   - After generator exhausted, broadcasts `{"type": "drafts_complete", "session_id": ...}`.
   - Stores agent session ID if returned.
4. On failure: log error, set any remaining `DRAFTING` sections to `DRAFT`, broadcast `{"type": "drafts_failed", "session_id": ..., "message": "Draft generation encountered an error."}`.

### Removed: NDJSON streaming

The `stream_drafts()` inner function and `StreamingResponse` are removed. The `StreamingResponse` import can be removed if no other endpoint uses it. `parse_create_session_response` in test conftest simplified to `resp.json()`.

---

## 3. Data Model Changes

### New `SectionStatus` value

```python
class SectionStatus(str, Enum):
    DRAFTING = "drafting"   # new — transient, during AI generation
    DRAFT = "draft"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    SKIPPED = "skipped"
```

### WebSocket event types (new)

| Event | Payload | Context |
|---|---|---|
| `ai_activity` | `{section_id, text, error?}` | Comment processing & draft generation |
| `ai_complete` | `{section_id, result_type}` | Comment processing finished (broadcast is summary only; generator event includes full result for main.py to act on) |
| `drafts_started` | `{session_id}` | Draft generation beginning |
| `section_drafted` | `{section_id, status}` | Individual draft written |
| `drafts_complete` | `{session_id}` | All drafts finished |
| `drafts_failed` | `{session_id, message}` | Draft generation failed |

---

## 4. Frontend — Activity Log Panel

### HTML

A collapsible panel inside `#view-workspace`, after `#review-area`:
- Toggle bar with "AI Activity" label and a pulsing dot indicator (hidden by default).
- Panel body: scrollable log container with max-height.

### CSS

- `.badge-drafting`: amber (`#f59e0b`), white text, pulsing animation.
- `@keyframes pulse`: opacity oscillation for DRAFTING badges and the log panel dot indicator.
- Log panel: bottom bar spanning full width below review area. ~200px max-height with overflow-y scroll. Background: surface color with top border.
- Collapsed state: only toggle bar visible. Expanded: shows log entries.

### JS state additions

```
state.aiLogOpen = false
state.aiLogHasNew = false
state.aiLogAutoOpened = false
```

### Log panel behavior

- **Auto-open**: Panel auto-opens on the first `ai_activity` event in a session (sets `aiLogAutoOpened = true`). After that, it respects the user's open/closed preference.
- **Pulsing dot**: When new `ai_activity` arrives while the panel is collapsed, the dot indicator pulses. Cleared when the panel is opened.
- **Toggle**: Click toggles `state.aiLogOpen`, clears `state.aiLogHasNew`.
- **XSS safety**: All log entries appended via `.textContent`, never `.innerHTML`.
- **Scrolling**: Auto-scroll to bottom on new entries if already scrolled to bottom.

---

## 5. Frontend — Session Creation Streaming

### `handleCreateSession` changes

- Remove the NDJSON stream reader (`contentType.includes('ndjson')` branch and `reader.read()` loop).
- POST response is now plain JSON — parse with `resp.json()`.
- After receiving 201, call `showInviteLinks(session)` and `openSession(session.id)` as before.
- Submit button shows spinner during the POST, resets once session is created. Draft progress shown in workspace via DRAFTING badges and log panel.

### `handleWsMessage` additions

- `drafts_started`: re-fetch session (sections now have DRAFTING status), re-render sidebar.
- `section_drafted`: re-fetch section content for the drafted section, re-fetch session metadata, re-render sidebar. If the drafted section is the active section, re-render review area.
- `drafts_complete`: re-fetch session, update header.
- `drafts_failed`: re-fetch session (DRAFTING sections reverted to DRAFT), log error in activity panel.
- `ai_activity`: append to log panel (already covered in Section 4).
- `ai_complete`: append completion indicator to log panel.

### DRAFTING badge

New sidebar badge for sections with `status === "drafting"`: amber with pulse animation, matching the `badge-drafting` CSS class.

---

## 6. Security

- **Tool input stripping**: `_run_query_streaming` only yields `text_delta` events. All tool-related `StreamEvent` types are filtered out. Tool arguments (which may contain draft content, user comments, or other data) are never broadcast.
- **Error sanitization**: Broadcast messages use fixed strings — `"AI processing encountered an error."` / `"Draft generation encountered an error."` — never `str(e)`. Raw exceptions logged server-side at WARNING with `exc_info=True`.
- **Error comment**: On comment processing failure, an AI comment is added to the thread with a user-friendly message so feedback appears in context.
- **DRAFTING recovery**: If the background draft task fails, any sections still in `DRAFTING` status are set back to `DRAFT` to prevent permanently stuck transient states.

---

## 7. Testing

### `test_ai_orchestrator.py`

- `mock_agent_messages` gains a `stream_events` parameter: when `True`, yields `StreamEvent` objects with text deltas before the `AssistantMessage`.
- Import `StreamEvent` from `claude_agent_sdk`.
- Existing tests updated to consume the async generator (collect events into a list, extract the final result from the last event).
- New tests:
  - `test_process_comment_yields_activity_events` — verify text deltas are yielded.
  - `test_process_comment_filters_tool_inputs` — verify tool-related events are not yielded.
  - `test_generate_drafts_yields_section_drafted` — verify per-section events.
  - `test_generate_drafts_yields_drafts_complete` — verify final event.
  - Section lock test updated for generator pattern.

### `test_api_ai.py`

- Session creation tests updated: response is JSON (not NDJSON), draft events come via WebSocket.
- `parse_create_session_response` simplified (no NDJSON parsing).
- New tests:
  - `test_drafts_started_sets_drafting_status` — verify sections get DRAFTING status.
  - `test_error_broadcasts_sanitized_message` — verify no raw exceptions in broadcasts.
  - `test_drafting_sections_recover_on_failure` — verify DRAFTING → DRAFT on error.

### `conftest.py`

- `parse_create_session_response` simplified to `resp.json()`.

---

## Files Modified

| File | Changes |
|---|---|
| `backend/models.py` | Add `DRAFTING` to `SectionStatus` |
| `backend/ai_orchestrator.py` | Convert `_run_query`, `process_comment`, `generate_drafts` to async generators; add `StreamEvent` import; add `include_partial_messages=True` |
| `backend/main.py` | Consume generators in `add_comment`; background task in `create_session`; remove NDJSON streaming; remove `StreamingResponse` import |
| `frontend/index.html` | Add activity log panel HTML |
| `frontend/style.css` | Add log panel styles, DRAFTING badge, pulse animation |
| `frontend/app.js` | Add log panel JS, new WebSocket handlers, remove NDJSON reader, add DRAFTING badge rendering |
| `tests/conftest.py` | Simplify `parse_create_session_response` |
| `tests/test_ai_orchestrator.py` | Update for async generator pattern, add streaming tests |
| `tests/test_api_ai.py` | Update for JSON response, add WebSocket/DRAFTING tests |
