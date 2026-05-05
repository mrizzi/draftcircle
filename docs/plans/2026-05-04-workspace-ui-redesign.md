# Workspace UI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the grid-of-cards workspace with a sidebar + main review area layout, add coordinator invite links, inline section reassignment, and invite links retrieval.

**Architecture:** Backend-first — add the assign endpoint and coordinator token logic, then rewrite the frontend workspace view. The sidebar lists sections with inline owner reassignment; the main area shows the full review content (draft, proposals, comments). All actions (approve, comment, accept/reject) move into the main area.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/CSS/HTML (frontend), Playwright (E2E tests)

**Spec:** `docs/specs/2026-05-04-workspace-ui-redesign.md`

---

### Task 1: Add coordinator as participant with token

When creating a session, the coordinator must also appear in the participants list with a token so they can authenticate via invite link. If the coordinator is already in the participants list, skip. Otherwise add them with all sections assigned and role "coordinator".

**Files:**
- Modify: `backend/session_manager.py:113-163`
- Test: `tests/test_session_manager.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_session_manager.py`:

```python
class TestCoordinatorAsParticipant:
    def test_coordinator_added_as_participant(self, populated_data_repo):
        from backend.git_store import GitStore
        from backend.session_manager import SessionManager
        from backend.template_loader import TemplateLoader

        git = GitStore(populated_data_repo)
        templates = TemplateLoader(populated_data_repo)
        sm = SessionManager(git, templates)

        session = sm.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        user_ids = [p.user_id for p in session.participants]
        assert "alice" in user_ids
        alice_p = next(p for p in session.participants if p.user_id == "alice")
        assert alice_p.role == "coordinator"
        assert alice_p.token
        assert set(alice_p.assigned_sections) == {"overview", "details", "notes"}

    def test_coordinator_not_duplicated_if_already_participant(self, populated_data_repo):
        from backend.git_store import GitStore
        from backend.models import ParticipantInput
        from backend.session_manager import SessionManager
        from backend.template_loader import TemplateLoader

        git = GitStore(populated_data_repo)
        templates = TemplateLoader(populated_data_repo)
        sm = SessionManager(git, templates)

        session = sm.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(user_id="alice", assigned_sections=["overview"], role="coordinator"),
            ],
        )
        alice_entries = [p for p in session.participants if p.user_id == "alice"]
        assert len(alice_entries) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_session_manager.py::TestCoordinatorAsParticipant -v`
Expected: FAIL — coordinator not in participants when participants list is empty

- [ ] **Step 3: Implement in session_manager.py**

In `create_session()`, after building `session_participants` (line 133-141), add:

```python
        coordinator_in_list = any(p.user_id == coordinator for p in session_participants)
        if not coordinator_in_list:
            all_section_ids = [s.id for s in template.sections]
            session_participants.insert(
                0,
                Participant(
                    user_id=coordinator,
                    token=secrets.token_urlsafe(24),
                    assigned_sections=all_section_ids,
                    role="coordinator",
                ),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_manager.py::TestCoordinatorAsParticipant -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/ --ignore=tests/e2e -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/session_manager.py tests/test_session_manager.py
git commit -m "feat: auto-add coordinator as participant with token"
```

---

### Task 2: Add section assign endpoint

New endpoint: `POST /api/sessions/{session_id}/sections/{section_id}/assign` with body `{ "user_id": "bob" }`. Updates the participant list so the target user owns the section (removing it from the previous owner). Broadcasts via WebSocket.

**Files:**
- Modify: `backend/session_manager.py`
- Modify: `backend/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api.py`:

```python
class TestSectionAssignment:
    def test_assign_section_to_user(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/overview/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "assigned"

        session_resp = client.get(f"/api/sessions/{sid}")
        session = session_resp.json()
        bob_p = next((p for p in session["participants"] if p["user_id"] == "bob"), None)
        assert bob_p is not None
        assert "overview" in bob_p["assigned_sections"]

    def test_assign_section_nonexistent_section(self, client, session_with_participant):
        sid = session_with_participant["id"]
        resp = client.post(
            f"/api/sessions/{sid}/sections/nonexistent/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 400

    def test_assign_section_nonexistent_session(self, client):
        resp = client.post(
            "/api/sessions/fake-session/sections/overview/assign",
            json={"user_id": "bob"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_api.py::TestSectionAssignment -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 3: Add `assign_section` to session_manager.py**

```python
    def assign_section(self, session_id: str, section_id: str, user_id: str) -> None:
        session = self._require_session(session_id)
        self._require_active(session)

        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")

        for p in session.participants:
            if section_id in p.assigned_sections:
                p.assigned_sections.remove(section_id)

        target = next((p for p in session.participants if p.user_id == user_id), None)
        if target:
            target.assigned_sections.append(section_id)
        else:
            session.participants.append(
                Participant(
                    user_id=user_id,
                    token=secrets.token_urlsafe(24),
                    assigned_sections=[section_id],
                    role="participant",
                )
            )

        self._save_session(session, f"assign: {section_id} to {user_id}")
```

- [ ] **Step 4: Add endpoint to main.py**

Add `AssignRequest` model at the top with other request models:

```python
class AssignRequest(BaseModel):
    user_id: str
```

Add endpoint after the `reopen_section` endpoint:

```python
    @app.post("/api/sessions/{session_id}/sections/{section_id}/assign")
    async def assign_section(session_id: str, section_id: str, req: AssignRequest):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            sessions.assign_section(session_id, section_id, req.user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {
                "type": "section_assigned",
                "section_id": section_id,
                "user_id": req.user_id,
            },
        )
        return {"status": "assigned"}
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_api.py::TestSectionAssignment -v`
Expected: PASS

Run: `python3 -m pytest tests/ --ignore=tests/e2e -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/session_manager.py backend/main.py tests/test_api.py
git commit -m "feat: add section assignment endpoint"
```

---

### Task 3: Conditional token inclusion for coordinator

When `GET /api/sessions/{id}?token=...` is called with the coordinator's token, include participant tokens in the response. Non-coordinator tokens still get tokens stripped.

**Files:**
- Modify: `backend/main.py:155-168`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api.py`:

```python
class TestCoordinatorTokenAccess:
    def test_coordinator_sees_participant_tokens(self, client, populated_data_repo):
        create_resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {"user_id": "bob", "assigned_sections": ["overview"], "role": "participant"},
                ],
            },
        )
        session = create_resp.json()
        sid = session["id"]
        coordinator_token = next(p["token"] for p in session["participants"] if p["user_id"] == "alice")

        resp = client.get(f"/api/sessions/{sid}?token={coordinator_token}")
        data = resp.json()
        for p in data["participants"]:
            assert "token" in p

    def test_non_coordinator_tokens_stripped(self, client, populated_data_repo):
        create_resp = client.post(
            "/api/sessions",
            json={
                "template": "test-template",
                "coordinator": "alice",
                "participants": [
                    {"user_id": "bob", "assigned_sections": ["overview"], "role": "participant"},
                ],
            },
        )
        session = create_resp.json()
        sid = session["id"]
        bob_token = next(p["token"] for p in session["participants"] if p["user_id"] == "bob")

        resp = client.get(f"/api/sessions/{sid}?token={bob_token}")
        data = resp.json()
        for p in data["participants"]:
            assert "token" not in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_api.py::TestCoordinatorTokenAccess -v`
Expected: FAIL — tokens always stripped

- [ ] **Step 3: Implement in main.py**

Replace the `get_session` endpoint:

```python
    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, token: str | None = None):
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        result = session.model_dump(mode="json")
        result["progress"] = sessions.get_progress(session_id)
        result["ready_to_publish"] = sessions.is_ready_to_publish(session_id)

        is_coordinator = False
        if token:
            for p in session.participants:
                if p.token == token:
                    result["current_user_id"] = p.user_id
                    if session.coordinator == p.user_id:
                        is_coordinator = True
                    break

        if not is_coordinator:
            _strip_tokens(result)

        return result
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_api.py::TestCoordinatorTokenAccess -v`
Expected: PASS

Run: `python3 -m pytest tests/ --ignore=tests/e2e -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api.py
git commit -m "feat: include tokens in session response for coordinator"
```

---

### Task 4: Rewrite workspace HTML structure

Replace the grid + slide-in panel HTML with sidebar + main area structure.

**Files:**
- Modify: `frontend/index.html:54-78`

- [ ] **Step 1: Replace the workspace HTML**

Replace the `#view-workspace` div (lines 54-78) with:

```html
    <div id="view-workspace" class="view">
      <div id="section-sidebar">
        <div id="section-list"></div>
        <div id="sidebar-footer">
          <button id="invite-links-btn" class="btn-link">Invite links</button>
        </div>
      </div>
      <div id="review-area">
        <div id="review-header">
          <h3 id="review-title"></h3>
          <div id="review-actions">
            <button id="review-approve-btn" class="btn btn-success" style="display:none">Approve</button>
            <button id="review-skip-btn" class="btn btn-secondary" style="display:none">Skip</button>
            <button id="review-reopen-btn" class="btn btn-secondary" style="display:none">Reopen</button>
          </div>
        </div>
        <div id="review-status"></div>
        <div id="review-draft" class="review-section"></div>
        <div id="review-proposals" class="review-section"></div>
        <div id="review-comments" class="review-section">
          <h4>Comments</h4>
          <div id="comments-thread"></div>
          <div class="comment-input-row">
            <textarea id="comment-input" rows="2" placeholder="Add a comment..."></textarea>
            <button id="submit-comment-btn" class="btn btn-primary">Send</button>
          </div>
        </div>
        <div id="review-empty" style="display:flex;align-items:center;justify-content:center;min-height:300px;color:var(--text-secondary);">
          Select a section from the sidebar
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "refactor: replace workspace grid+panel HTML with sidebar+main layout"
```

---

### Task 5: Add sidebar + main area CSS

Replace the grid/panel CSS with sidebar layout styles.

**Files:**
- Modify: `frontend/style.css`

- [ ] **Step 1: Replace workspace CSS**

Remove these CSS rules:
- `#view-workspace` (line 99-100)
- `#section-grid` (lines 102-108)
- `#section-grid.panel-open` (line 109)
- `.section-card` through `.section-card-preview` (lines 111-131)
- `#detail-panel` through `.panel-section` (lines 133-144)
- The `@media` rule for `#section-grid.panel-open` (line 184) if present

Replace with:

```css
#view-workspace { display: none; position: relative; }
#view-workspace.active { display: flex; gap: 0; height: calc(100vh - 52px); }

#section-sidebar {
  width: 220px; min-width: 220px; background: var(--surface);
  border-right: 1px solid var(--border); display: flex;
  flex-direction: column; overflow-y: auto;
}
#section-list { flex: 1; padding: 0.5rem; }

.sidebar-item {
  padding: 0.5rem 0.75rem; border-radius: 6px; cursor: pointer;
  margin-bottom: 0.25rem; transition: background 0.1s;
}
.sidebar-item:hover { background: var(--bg); }
.sidebar-item.active { background: #eff6ff; border-left: 3px solid var(--primary); }
.sidebar-item-header { display: flex; justify-content: space-between; align-items: center; }
.sidebar-item-title { font-size: 0.85rem; font-weight: 500; }
.sidebar-item-owner { font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem; cursor: pointer; }
.sidebar-item-owner:hover { color: var(--primary); }
.sidebar-item-owner select {
  font-size: 0.75rem; padding: 0.15rem; border: 1px solid var(--border);
  border-radius: 3px; background: white; width: 100%; margin-top: 0.2rem;
}

#sidebar-footer {
  padding: 0.75rem; border-top: 1px solid var(--border);
  font-size: 0.8rem;
}
.btn-link {
  background: none; border: none; color: var(--primary);
  cursor: pointer; font-size: 0.8rem; padding: 0; text-decoration: underline;
}
.btn-link:hover { color: var(--primary-hover); }

#review-area {
  flex: 1; overflow-y: auto; padding: 1.5rem 2rem;
}
#review-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem;
}
#review-header h3 { font-size: 1.1rem; font-weight: 600; }
#review-actions { display: flex; gap: 0.5rem; }
#review-status { margin-bottom: 1rem; }
.review-section { margin-bottom: 1.5rem; }
.review-section h4 {
  font-size: 0.85rem; font-weight: 600; margin-bottom: 0.75rem;
  color: var(--text-secondary);
}
```

Keep the existing `.badge`, `.comment`, `.proposal`, `.draft-content`, `.diff-*`, `.comment-input-row` rules unchanged.

- [ ] **Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "style: sidebar + main area layout CSS"
```

---

### Task 6: Rewrite workspace JS — sidebar rendering, section selection, review area

This is the main JS rewrite. Replace `renderSectionGrid()`, `openDetailPanel()`, `closeDetailPanel()`, and `renderDetailPanel()` with sidebar-based equivalents. Wire up the invite links button, owner reassignment, and WebSocket handlers.

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Replace `renderWorkspace()` and `renderSectionGrid()` with `renderSidebar()`**

Replace the `renderWorkspace`, `findTemplate`, and `renderSectionGrid` functions with:

```javascript
function renderWorkspace() {
  const firstSection = Object.keys(state.currentSession.section_meta)[0];
  if (!state.activeSection && firstSection) {
    state.activeSection = firstSection;
  }
  renderSidebar();
  renderReviewArea();
}

function renderSidebar() {
  const s = state.currentSession;
  const template = findTemplate();
  const list = document.getElementById('section-list');
  list.textContent = '';

  Object.entries(s.section_meta).forEach(([sid, meta]) => {
    const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
    const owner = (s.participants || []).find(p => p.assigned_sections.includes(sid));
    const pendingCount = (state.sectionProposals[sid] || []).filter(p => p.status === 'pending').length;

    const item = document.createElement('div');
    item.className = 'sidebar-item' + (state.activeSection === sid ? ' active' : '');
    item.dataset.section = sid;

    const header = document.createElement('div');
    header.className = 'sidebar-item-header';
    const title = document.createElement('span');
    title.className = 'sidebar-item-title';
    title.textContent = sectionDef ? sectionDef.title : sid;
    const badge = document.createElement('span');
    badge.className = 'badge badge-' + meta.status.replace(' ', '-');
    badge.textContent = meta.status;
    header.appendChild(title);
    header.appendChild(badge);
    item.appendChild(header);

    if (pendingCount > 0) {
      const pending = document.createElement('div');
      pending.style.cssText = 'font-size:0.7rem;color:var(--primary);margin-top:0.15rem';
      pending.textContent = pendingCount + ' pending';
      item.appendChild(pending);
    }

    const ownerDiv = document.createElement('div');
    ownerDiv.className = 'sidebar-item-owner';
    ownerDiv.textContent = owner ? owner.user_id : '— unassigned —';
    ownerDiv.addEventListener('click', (e) => {
      e.stopPropagation();
      showOwnerDropdown(sid, ownerDiv);
    });
    item.appendChild(ownerDiv);

    item.addEventListener('click', () => selectSection(sid));
    list.appendChild(item);
  });
}

function selectSection(sectionId) {
  state.activeSection = sectionId;
  renderSidebar();
  renderReviewArea();
}

function showOwnerDropdown(sectionId, container) {
  if (container.querySelector('select')) return;
  const s = state.currentSession;
  const currentOwner = (s.participants || []).find(p => p.assigned_sections.includes(sectionId));

  const sel = document.createElement('select');
  const emptyOpt = document.createElement('option');
  emptyOpt.value = '';
  emptyOpt.textContent = '— unassigned —';
  sel.appendChild(emptyOpt);

  state.users.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.id;
    opt.textContent = u.name + ' (' + u.id + ')';
    if (currentOwner && currentOwner.user_id === u.id) opt.selected = true;
    sel.appendChild(opt);
  });

  container.textContent = '';
  container.appendChild(sel);
  sel.focus();

  sel.addEventListener('change', async () => {
    const userId = sel.value;
    if (!userId) return;
    try {
      await apiFetch('/sessions/' + state.currentSession.id + '/sections/' + sectionId + '/assign', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId }),
      });
    } catch (err) {
      alert('Error: ' + err.message);
    }
  });

  sel.addEventListener('blur', () => {
    container.textContent = currentOwner ? currentOwner.user_id : '— unassigned —';
  });
}
```

Keep the `findTemplate()` function as-is.

- [ ] **Step 2: Replace `openDetailPanel()`, `closeDetailPanel()`, `renderDetailPanel()` with `renderReviewArea()`**

Delete `openDetailPanel`, `closeDetailPanel`, and `renderDetailPanel`. Replace with:

```javascript
function renderReviewArea() {
  const sid = state.activeSection;
  const emptyEl = document.getElementById('review-empty');

  if (!sid) {
    emptyEl.style.display = 'flex';
    document.getElementById('review-header').style.display = 'none';
    document.getElementById('review-status').style.display = 'none';
    document.getElementById('review-draft').style.display = 'none';
    document.getElementById('review-proposals').style.display = 'none';
    document.getElementById('review-comments').style.display = 'none';
    return;
  }

  emptyEl.style.display = 'none';
  document.getElementById('review-header').style.display = 'flex';
  document.getElementById('review-status').style.display = 'block';
  document.getElementById('review-draft').style.display = 'block';
  document.getElementById('review-proposals').style.display = 'block';
  document.getElementById('review-comments').style.display = 'block';

  const s = state.currentSession;
  const meta = s.section_meta[sid];
  const template = findTemplate();
  const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
  const content = state.sectionContent[sid] ? state.sectionContent[sid].content : '';
  const comments = state.sectionComments[sid] || [];
  const proposals = state.sectionProposals[sid] || [];
  const isOwner = canActOnSection(sid);

  document.getElementById('review-title').textContent = sectionDef ? sectionDef.title : sid;

  const statusDiv = document.getElementById('review-status');
  statusDiv.textContent = '';
  const badge = document.createElement('span');
  badge.className = 'badge badge-' + meta.status.replace(' ', '-');
  badge.textContent = meta.status;
  statusDiv.appendChild(badge);

  document.getElementById('review-approve-btn').style.display =
    (isOwner && meta.status !== 'approved' && meta.status !== 'skipped') ? 'inline-block' : 'none';
  document.getElementById('review-skip-btn').style.display =
    (isOwner && sectionDef && sectionDef.priority !== 'required' && meta.status !== 'skipped' && meta.status !== 'approved') ? 'inline-block' : 'none';
  document.getElementById('review-reopen-btn').style.display =
    (isOwner && meta.status === 'approved') ? 'inline-block' : 'none';

  const draftEl = document.getElementById('review-draft');
  draftEl.textContent = '';
  const draftH4 = document.createElement('h4');
  draftH4.textContent = 'Draft';
  draftEl.appendChild(draftH4);
  const draftContent = document.createElement('div');
  draftContent.className = 'draft-content';
  if (content) {
    draftContent.textContent = '';
    const rendered = typeof marked !== 'undefined' ? marked.parse(content) : esc(content);
    const wrapper = document.createElement('div');
    wrapper.textContent = '';
    const temp = document.createElement('template');
    temp.innerHTML = rendered;
    wrapper.appendChild(temp.content);
    draftEl.appendChild(wrapper);
  } else {
    const em = document.createElement('em');
    em.textContent = 'No content yet.';
    draftContent.appendChild(em);
    draftEl.appendChild(draftContent);
  }

  const proposalsEl = document.getElementById('review-proposals');
  proposalsEl.textContent = '';
  const pendingProposals = proposals.filter(p => p.status === 'pending');
  const pastProposals = proposals.filter(p => p.status !== 'pending');
  if (pendingProposals.length > 0) {
    const h4 = document.createElement('h4');
    h4.textContent = 'Pending Proposals';
    proposalsEl.appendChild(h4);
    pendingProposals.forEach(p => proposalsEl.appendChild(buildProposalEl(p, content, isOwner)));
  }
  if (pastProposals.length > 0) {
    const h4 = document.createElement('h4');
    h4.textContent = 'Past Proposals';
    h4.style.marginTop = '0.5rem';
    proposalsEl.appendChild(h4);
    pastProposals.forEach(p => proposalsEl.appendChild(buildProposalEl(p, content, false)));
  }

  const thread = document.getElementById('comments-thread');
  thread.textContent = '';
  comments.forEach(c => {
    const div = document.createElement('div');
    div.className = 'comment' + (c.author === 'ai' ? ' comment-ai' : '');
    const headerDiv = document.createElement('div');
    headerDiv.className = 'comment-header';
    const authorSpan = document.createElement('span');
    authorSpan.className = 'comment-author';
    authorSpan.textContent = c.author === 'ai' ? 'AI Assistant' : c.author;
    const timeSpan = document.createElement('span');
    timeSpan.className = 'comment-time';
    timeSpan.textContent = formatTime(c.timestamp);
    headerDiv.appendChild(authorSpan);
    headerDiv.appendChild(timeSpan);
    const textDiv = document.createElement('div');
    textDiv.className = 'comment-text';
    textDiv.textContent = c.text;
    div.appendChild(headerDiv);
    div.appendChild(textDiv);
    thread.appendChild(div);
  });

  const commentInput = document.getElementById('comment-input');
  const commentBtn = document.getElementById('submit-comment-btn');
  const commentDisabled = meta.status === 'approved';
  commentInput.disabled = commentDisabled;
  commentBtn.disabled = commentDisabled;
}
```

- [ ] **Step 3: Update `init()` event listeners**

Remove these lines from `init()`:

```javascript
  document.getElementById('panel-close-btn').addEventListener('click', closeDetailPanel);
  document.getElementById('panel-approve-btn').addEventListener('click', approveSection);
  document.getElementById('panel-reopen-btn').addEventListener('click', reopenSection);
  document.getElementById('panel-skip-btn').addEventListener('click', skipSection);
```

Replace with:

```javascript
  document.getElementById('review-approve-btn').addEventListener('click', approveSection);
  document.getElementById('review-reopen-btn').addEventListener('click', reopenSection);
  document.getElementById('review-skip-btn').addEventListener('click', skipSection);
  document.getElementById('invite-links-btn').addEventListener('click', () => showInviteLinks(state.currentSession));
```

- [ ] **Step 4: Update `handleWsMessage` references**

In `handleWsMessage()`, replace all occurrences:
- `renderSectionGrid()` → `renderSidebar()`
- `renderDetailPanel()` → `renderReviewArea()`
- `if (state.activeSection === sectionId) renderDetailPanel()` → `if (state.activeSection === sectionId) renderReviewArea()`

Add handler for the new `section_assigned` event inside the function:

```javascript
  } else if (msg.type === 'section_assigned') {
    state.currentSession = await apiFetch(sessionPath(sid));
    renderSidebar();
  }
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: rewrite workspace JS with sidebar + review area"
```

---

### Task 7: Update E2E tests for new layout

The existing E2E tests reference old selectors. Update them for the new sidebar layout.

**Files:**
- Modify: `tests/e2e/conftest.py`
- Modify: `tests/e2e/test_session_workflow.py`
- Modify: `tests/e2e/test_permissions_ui.py`

- [ ] **Step 1: Update conftest helpers**

In `tests/e2e/conftest.py`, replace `open_section` and remove `close_panel`:

```python
def open_section(page, section_id):
    page.locator(f'.sidebar-item[data-section="{section_id}"]').click()
    expect(page.locator(f'.sidebar-item[data-section="{section_id}"]')).to_have_class(
        "sidebar-item active", timeout=5000
    )
```

Remove `close_panel` function entirely.

- [ ] **Step 2: Update test_session_workflow.py selectors**

Replace all occurrences:
- `.section-card` → `.sidebar-item`
- `#panel-draft .draft-content` → `#review-draft .draft-content`
- `#panel-approve-btn` → `#review-approve-btn`
- `.section-card[data-section="X"] .section-card-header .badge` → `.sidebar-item[data-section="X"] .badge`
- Remove all `close_panel(page)` calls

- [ ] **Step 3: Update test_permissions_ui.py selectors**

Same replacements:
- `#panel-approve-btn` → `#review-approve-btn`
- `#panel-skip-btn` → `#review-skip-btn`
- `#panel-reopen-btn` → `#review-reopen-btn`
- Remove `close_panel` calls and imports

- [ ] **Step 4: Run E2E tests**

Run: `python3 -m pytest tests/e2e/ -v`
Expected: All E2E tests pass with new selectors

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/
git commit -m "test: update E2E tests for sidebar layout selectors"
```

---

### Task 8: Final validation

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Lint and format**

Run: `python3 -m ruff check . && python3 -m ruff format --check .`
Expected: Clean. Fix any issues.

- [ ] **Step 3: Manual browser test of full workflow**

1. Create session with seed text → AI generates drafts
2. Open coordinator invite link → identity shown in header
3. Sidebar shows all sections with owners → click to navigate
4. Reassign a section via sidebar owner dropdown
5. Post comment → AI proposal appears in review area
6. Accept proposal → draft updates
7. Approve required sections → progress updates in header
8. Click "Invite links" in sidebar footer → modal shows all links
9. Publish → session becomes read-only

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: final cleanup for workspace UI redesign"
```
