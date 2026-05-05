# Create Session Form UX Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text section assignment with a visual grid so users can assign section owners via dropdowns, with auto-suggestion from template roles.

**Architecture:** Frontend-only change. The `showCreateForm()` function is rewritten to render a section grid when a template is selected. `handleCreateSession()` collects grid state into the existing `participants` API payload. `addParticipantRow()` is removed. A new E2E test validates the form using Playwright.

**Tech Stack:** Vanilla JS (no framework), CSS, Playwright for E2E tests

**Spec:** `docs/specs/2026-05-04-create-session-ux-design.md`

---

### Task 1: Replace participants HTML with section-owners container

**Files:**
- Modify: `frontend/index.html:41-45`

- [ ] **Step 1: Replace the participants section HTML**

Replace lines 41-45 in `index.html`:

```html
        <div id="participants-section">
          <h3>Participants</h3>
          <div id="participants-list"></div>
          <button type="button" id="add-participant-btn" class="btn btn-secondary">Add Participant</button>
        </div>
```

With:

```html
        <div id="section-owners">
          <h3>Section Owners</h3>
          <div id="section-owners-grid"></div>
        </div>
```

- [ ] **Step 2: Verify page loads without JS errors**

Run: Open `http://localhost:8000` in browser, open console
Expected: No errors. "New Session" button still works (form appears, grid is empty).

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "refactor: replace participants HTML with section-owners container"
```

---

### Task 2: Add section-owners grid CSS

**Files:**
- Modify: `frontend/style.css`

- [ ] **Step 1: Add grid styling after the form rules (after line 98)**

Add after the `#create-session-form textarea` block:

```css
#section-owners h3 { font-size: 0.95rem; margin-bottom: 0.5rem; }
.section-owners-table { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.section-owners-header { display: grid; grid-template-columns: 1fr 90px 160px; padding: 0.5rem 0.75rem; background: var(--bg); border-bottom: 1px solid var(--border); font-size: 0.75rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; }
.section-owner-row { display: grid; grid-template-columns: 1fr 90px 160px; padding: 0.5rem 0.75rem; border-bottom: 1px solid #f0f0f0; align-items: center; }
.section-owner-row:last-child { border-bottom: none; }
.section-owner-row.unassigned { background: #fef9ee; }
.section-owner-title { font-size: 0.9rem; font-weight: 500; }
.section-owner-hint { font-size: 0.75rem; color: var(--text-secondary); }
.section-owner-row select { padding: 0.35rem; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; background: white; width: 100%; }
.badge-required { background: #dc2626; color: white; }
.badge-recommended { background: #f59e0b; color: white; }
.badge-optional { background: #d1d5db; color: var(--text-secondary); }
```

- [ ] **Step 2: Verify no lint errors**

Run: `python3 -m ruff check frontend/` (should be no Python in frontend, just a sanity check that ruff doesn't flag anything)

- [ ] **Step 3: Commit**

```bash
git add frontend/style.css
git commit -m "style: add section-owners grid CSS"
```

---

### Task 3: Rewrite showCreateForm() to render the section grid

**Files:**
- Modify: `frontend/app.js:123-135` (showCreateForm function)

- [ ] **Step 1: Rewrite `showCreateForm()` and add `renderSectionOwnersGrid()`**

Replace the `showCreateForm` function (lines 123-135) with:

```javascript
function showCreateForm() {
  const select = document.getElementById('template-select');
  select.textContent = '';
  state.templates.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.slug || t.name;
    opt.textContent = t.name + ' — ' + t.description;
    select.appendChild(opt);
  });
  document.getElementById('seed-text').value = '';

  select.addEventListener('change', renderSectionOwnersGrid);
  renderSectionOwnersGrid();
  showView('create-session');
}

function renderSectionOwnersGrid() {
  const slug = document.getElementById('template-select').value;
  const template = state.templates.find(t => (t.slug || t.name) === slug);
  const container = document.getElementById('section-owners-grid');
  container.textContent = '';

  if (!template) return;

  const table = document.createElement('div');
  table.className = 'section-owners-table';

  const header = document.createElement('div');
  header.className = 'section-owners-header';
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Section' }));
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Priority' }));
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Owner' }));
  table.appendChild(header);

  template.sections.forEach(section => {
    const row = document.createElement('div');
    row.className = 'section-owner-row';
    row.dataset.sectionId = section.id;

    const titleCell = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'section-owner-title';
    title.textContent = section.title;
    titleCell.appendChild(title);
    if (section.suggested_roles && section.suggested_roles.length > 0) {
      const hint = document.createElement('div');
      hint.className = 'section-owner-hint';
      hint.textContent = 'Suggested: ' + section.suggested_roles.join(', ');
      titleCell.appendChild(hint);
    }
    row.appendChild(titleCell);

    const badgeCell = document.createElement('div');
    const badge = document.createElement('span');
    badge.className = 'badge badge-' + section.priority;
    badge.textContent = section.priority;
    badgeCell.appendChild(badge);
    row.appendChild(badgeCell);

    const ownerCell = document.createElement('div');
    const ownerSelect = document.createElement('select');
    ownerSelect.className = 'section-owner-select';
    ownerSelect.dataset.sectionId = section.id;

    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '— unassigned —';
    ownerSelect.appendChild(emptyOpt);

    let autoSelected = '';
    state.users.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.id;
      opt.textContent = u.name + ' (' + u.id + ')';
      ownerSelect.appendChild(opt);

      if (!autoSelected && section.suggested_roles && section.suggested_roles.length > 0) {
        const userRoles = u.default_roles || [];
        if (section.suggested_roles.some(r => userRoles.includes(r))) {
          autoSelected = u.id;
        }
      }
    });

    if (autoSelected) {
      ownerSelect.value = autoSelected;
    } else {
      row.classList.add('unassigned');
    }

    ownerSelect.addEventListener('change', () => {
      row.classList.toggle('unassigned', ownerSelect.value === '');
    });

    ownerCell.appendChild(ownerSelect);
    row.appendChild(ownerCell);
    table.appendChild(row);
  });

  container.appendChild(table);
}
```

- [ ] **Step 2: Remove the `addParticipantRow()` function**

Delete the entire `addParticipantRow` function (lines 137-173 in the original file).

- [ ] **Step 3: Remove the `add-participant-btn` event listener from `init()`**

In the `init()` function, find and delete this line:

```javascript
  document.getElementById('add-participant-btn').addEventListener('click', addParticipantRow);
```

- [ ] **Step 4: Verify the form renders the grid**

Run: Open `http://localhost:8000`, click "New Session"
Expected: The grid appears with section rows, priority badges, and owner dropdowns. Auto-suggestion pre-selects Alice for "Overview" (suggested_roles: product-manager, Alice's default_role: product-manager).

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: render section assignment grid on Create Session form"
```

---

### Task 4: Rewrite handleCreateSession() to collect grid state

**Files:**
- Modify: `frontend/app.js` (handleCreateSession function)

- [ ] **Step 1: Replace the participant collection logic in `handleCreateSession()`**

Replace the block that reads from `participants-list` (lines 188-194 in original):

```javascript
  const rows = document.getElementById('participants-list').children;
  const participants = Array.from(rows).map(row => ({
    user_id: row.querySelector('.participant-user').value,
    role: row.querySelector('.participant-role').value || 'participant',
    assigned_sections: row.querySelector('.participant-sections').value
      .split(',').map(s => s.trim()).filter(Boolean),
  }));
```

With:

```javascript
  const template = state.templates.find(t => (t.slug || t.name) === slug);
  const coordinatorId = state.userId || 'coordinator';

  const assignments = {};
  document.querySelectorAll('.section-owner-select').forEach(sel => {
    const sectionId = sel.dataset.sectionId;
    let userId = sel.value;
    if (!userId) {
      const sectionDef = template && template.sections.find(s => s.id === sectionId);
      if (sectionDef && sectionDef.priority === 'required') {
        userId = coordinatorId;
      }
    }
    if (userId) {
      if (!assignments[userId]) assignments[userId] = [];
      assignments[userId].push(sectionId);
    }
  });

  const participants = Object.entries(assignments).map(([userId, sections]) => {
    const user = state.users.find(u => u.id === userId);
    const role = (user && user.default_roles && user.default_roles[0]) || 'participant';
    return { user_id: userId, assigned_sections: sections, role };
  });
```

Also update the `coordinator` field in the JSON body to use `coordinatorId`:

```javascript
        coordinator: coordinatorId,
```

- [ ] **Step 2: Verify form submission produces correct API payload**

Run: Open browser dev tools Network tab, create a session with the grid, check the POST `/api/sessions` request body
Expected: `participants` array with user_id, assigned_sections, and role derived from default_roles. Required unassigned sections should be assigned to coordinator.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: collect section grid state into participants payload"
```

---

### Task 5: E2E test for the Create Session form

**Files:**
- Create: `tests/e2e/test_create_session_form.py`

The E2E test server uses `SAMPLE_TEMPLATE` with 3 sections:
- `overview` (required, suggested_roles: ["product-manager"]) → should auto-select Alice (default_roles: ["product-manager"])
- `details` (recommended, suggested_roles: ["architect"]) → should auto-select Bob (default_roles: ["architect"])
- `notes` (optional, suggested_roles: []) → should default to unassigned

Users: alice (product-manager), bob (architect), carol (engineer) — from `INTEGRATION_USERS`.

- [ ] **Step 1: Write the E2E test file**

```python
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

        notes_select = page.locator(
            '.section-owner-select[data-section-id="notes"]'
        )
        expect(notes_select).to_have_value("")

    def test_submit_creates_session_with_assignments(self, page, base_url):
        page.goto(base_url)
        page.click("#create-session-btn")
        expect(page.locator(".section-owner-row")).to_have_count(3)

        page.locator(
            '.section-owner-select[data-section-id="notes"]'
        ).select_option("carol")

        page.fill("#seed-text", "E2E test seed content.")

        page.click('button[type="submit"]')

        expect(page.locator("#view-session-list")).to_have_class(
            "view active", timeout=WORKSPACE_TIMEOUT
        )

        expect(page.locator(".session-card")).to_have_count(1, timeout=5000)

    def test_required_unassigned_auto_assigns_to_coordinator(
        self, page, base_url
    ):
        page.goto(base_url)
        page.click("#create-session-btn")
        expect(page.locator(".section-owner-row")).to_have_count(3)

        page.locator(
            '.section-owner-select[data-section-id="overview"]'
        ).select_option("")

        page.fill("#seed-text", "Testing auto-assign.")

        page.click('button[type="submit"]')

        expect(page.locator("#view-session-list")).to_have_class(
            "view active", timeout=WORKSPACE_TIMEOUT
        )

        session_cards = page.locator(".session-card")
        expect(session_cards).to_have_count(
            1, timeout=5000
        )

        session_cards.first.click()
        expect(page.locator("#view-workspace")).to_have_class(
            "view active", timeout=WORKSPACE_TIMEOUT
        )

        overview_card = page.locator('.section-card[data-section="overview"]')
        expect(overview_card.locator(".section-card-assignees")).to_contain_text(
            "coordinator"
        )
```

- [ ] **Step 2: Run the E2E test**

Run: `python3 -m pytest tests/e2e/test_create_session_form.py -v --headed`
Expected: All 4 tests pass. The `--headed` flag shows the browser so you can see the grid in action.

Note: If previous test runs created sessions on the shared E2E server, the session card counts may be off. Run with a fresh server or adjust assertions to use `to_have_count(n, ...)` where n accounts for prior sessions. Alternatively, the `e2e_server` fixture is session-scoped so a fresh `pytest` invocation should start clean.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_create_session_form.py
git commit -m "test: add E2E tests for section assignment grid on Create Session form"
```

---

### Task 6: Clean up and validate

**Files:**
- Modify: `frontend/app.js` (if any dead code remains)

- [ ] **Step 1: Verify no references to old participant UI remain**

Run: `grep -n 'addParticipantRow\|participant-user\|participant-role\|participant-sections\|add-participant-btn\|participants-list' frontend/app.js`
Expected: No output (all old references removed)

- [ ] **Step 2: Run all tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/e2e`
Expected: All unit and integration tests pass (they don't touch the form UI).

Run: `python3 -m pytest tests/e2e/ -v`
Expected: All E2E tests pass (existing + new form tests).

- [ ] **Step 3: Run lint and format**

Run: `python3 -m ruff check . && python3 -m ruff format --check .`
Expected: Clean

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: remove dead participant form code"
```
