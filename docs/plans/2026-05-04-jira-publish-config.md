# Jira Publish Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Jira credentials to env vars and add a publish form modal so users can publish to Jira from the UI.

**Architecture:** The Jira plugin reads `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` from environment. The frontend publish button opens a modal with project key, summary, and labels fields. The modal sends config to the existing publish endpoint.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/HTML/CSS (frontend)

**Spec:** `docs/specs/2026-05-04-jira-publish-config-design.md`

---

### Task 1: Move Jira credentials to env vars

**Files:**
- Modify: `backend/plugins/jira_feature.py`
- Test: `tests/test_jira_feature.py`

- [ ] **Step 1: Write failing test for env var auth**

Add to `tests/test_jira_feature.py`:

```python
class TestPublishEnvVars:
    def test_reads_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "ENV-1"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            result = plugin.publish(assembled, {"project_key": "ENV"})

        assert result == "ENV-1"
        assert mock_post.call_args.kwargs["auth"] == ("env@example.com", "env-token")
        url = mock_post.call_args.args[0]
        assert url == "https://env.atlassian.net/rest/api/3/issue"

    def test_raises_when_env_vars_missing(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])
        with pytest.raises(ValueError, match="JIRA_BASE_URL"):
            plugin.publish(assembled, {"project_key": "P"})

    def test_config_only_needs_project_key(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "u@e.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")

        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "X-1"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            plugin.publish(assembled, {"project_key": "X"})

        payload = mock_post.call_args.kwargs["json"]
        assert payload["fields"]["project"]["key"] == "X"
        assert payload["fields"]["summary"] == "DraftCircle Document"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_jira_feature.py::TestPublishEnvVars -v`
Expected: FAIL — publish() still requires credentials in config

- [ ] **Step 3: Rewrite publish() to use env vars**

Replace the `publish` method in `backend/plugins/jira_feature.py`:

```python
    def publish(self, output: str, config: dict[str, Any]) -> str:
        import os

        base_url = os.environ.get("JIRA_BASE_URL")
        email = os.environ.get("JIRA_EMAIL")
        api_token = os.environ.get("JIRA_API_TOKEN")

        for name, val in [("JIRA_BASE_URL", base_url), ("JIRA_EMAIL", email), ("JIRA_API_TOKEN", api_token)]:
            if not val:
                raise ValueError(f"Missing required environment variable: '{name}'")

        if "project_key" not in config:
            raise ValueError("Missing required config key: 'project_key'")

        base_url = base_url.rstrip("/")
        project_key = config["project_key"]
        issue_type_id = config.get("issue_type_id", "10001")
        summary = config.get("summary", "DraftCircle Document")
        labels = config.get("labels", [])

        adf = json.loads(output)

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": adf,
                "issuetype": {"id": issue_type_id},
            }
        }
        if labels:
            payload["fields"]["labels"] = labels

        resp = httpx.post(
            f"{base_url}/rest/api/3/issue",
            json=payload,
            auth=(email, api_token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        issue_key = resp.json()["key"]
        return issue_key
```

- [ ] **Step 4: Update existing tests to use env vars**

The existing `TestPublish` tests pass credentials in config. Update them to use `monkeypatch.setenv` instead. For every test in `TestPublish`, add the monkeypatch fixture and set env vars:

```python
class TestPublish:
    @pytest.fixture(autouse=True)
    def _set_jira_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://myorg.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
```

Then remove `base_url`, `email`, and `api_token` from all config dicts in `TestPublish` tests. Keep only `project_key`, `summary`, `labels`, `issue_type_id` in config.

Update `test_raises_on_missing_config_key` to only test `project_key` (no longer testing `base_url`, `email`, `api_token` in config — those are env vars now):

```python
    def test_raises_on_missing_project_key(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])
        with pytest.raises(ValueError, match="project_key"):
            plugin.publish(assembled, {})
```

Remove the old `test_raises_on_missing_config_key` parametrized test.

- [ ] **Step 5: Run all Jira tests**

Run: `python3 -m pytest tests/test_jira_feature.py -v`
Expected: All pass

- [ ] **Step 6: Format and commit**

```bash
python3 -m ruff format backend/plugins/jira_feature.py tests/test_jira_feature.py
git add backend/plugins/jira_feature.py tests/test_jira_feature.py
git commit -m "feat: move Jira credentials to environment variables"
```

---

### Task 2: Add publish form modal

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/style.css`

- [ ] **Step 1: Add publish modal HTML**

In `frontend/index.html`, add after the `invite-modal` div (before `<script>`):

```html
  <div id="publish-modal" class="modal" style="display:none">
    <div class="modal-content">
      <h3>Publish Session</h3>
      <form id="publish-form">
        <div id="publish-jira-fields">
          <label for="publish-project-key">Project Key</label>
          <input id="publish-project-key" type="text" required placeholder="e.g. PROJ">
          <label for="publish-summary">Summary</label>
          <input id="publish-summary" type="text" placeholder="Issue title">
          <label for="publish-labels">Labels (comma-separated)</label>
          <input id="publish-labels" type="text" placeholder="e.g. feature, draftcircle">
        </div>
        <div id="publish-markdown-fields" style="display:none">
          <label for="publish-output-path">Output Path</label>
          <input id="publish-output-path" type="text" placeholder="/tmp/output.md">
        </div>
        <div class="form-actions">
          <button type="button" id="cancel-publish-btn" class="btn btn-secondary">Cancel</button>
          <button type="submit" class="btn btn-primary">Publish</button>
        </div>
      </form>
    </div>
  </div>
```

- [ ] **Step 2: Add publish modal CSS**

In `frontend/style.css`, add after the existing modal styles:

```css
#publish-form { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 0.75rem; }
#publish-form label { font-weight: 600; font-size: 0.85rem; }
#publish-form input { width: 100%; padding: 0.5rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.9rem; font-family: inherit; }
```

- [ ] **Step 3: Replace publishSession() in app.js**

Replace the current `publishSession()` function with:

```javascript
function showPublishModal() {
  const template = findTemplate();
  const isJira = template && template.output_plugin === 'jira';

  document.getElementById('publish-jira-fields').style.display = isJira ? 'block' : 'none';
  document.getElementById('publish-markdown-fields').style.display = isJira ? 'none' : 'block';

  if (isJira) {
    document.getElementById('publish-summary').value = state.currentSession.id;
  } else {
    document.getElementById('publish-output-path').value = '/tmp/draftcircle-' + state.currentSession.id + '.md';
  }

  document.getElementById('publish-modal').style.display = 'flex';
}

async function handlePublish(e) {
  e.preventDefault();
  const template = findTemplate();
  const isJira = template && template.output_plugin === 'jira';

  let config;
  if (isJira) {
    const projectKey = document.getElementById('publish-project-key').value.trim();
    const summary = document.getElementById('publish-summary').value.trim();
    const labelsRaw = document.getElementById('publish-labels').value.trim();
    const labels = labelsRaw ? labelsRaw.split(',').map(l => l.trim()).filter(Boolean) : [];
    config = { project_key: projectKey, summary: summary || state.currentSession.id, labels };
  } else {
    config = { output_path: document.getElementById('publish-output-path').value.trim() };
  }

  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Publishing…';

  try {
    const result = await apiFetch('/sessions/' + state.currentSession.id + '/publish', {
      method: 'POST',
      body: JSON.stringify({ config }),
    });
    document.getElementById('publish-modal').style.display = 'none';
    alert('Published. Reference: ' + result.output_ref);
    await openSession(state.currentSession.id);
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Publish';
  }
}
```

- [ ] **Step 4: Update init() event listeners**

Replace the publish button listener. Find:
```javascript
  document.getElementById('publish-btn').addEventListener('click', publishSession);
```

Replace with:
```javascript
  document.getElementById('publish-btn').addEventListener('click', showPublishModal);
  document.getElementById('cancel-publish-btn').addEventListener('click', () => {
    document.getElementById('publish-modal').style.display = 'none';
  });
  document.getElementById('publish-form').addEventListener('submit', handlePublish);
```

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/style.css
git commit -m "feat: add publish form modal with Jira/markdown fields"
```

---

### Task 3: Final validation

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest tests/ --ignore=tests/e2e -q`
Expected: All pass

- [ ] **Step 2: Lint and format**

Run: `python3 -m ruff check . && python3 -m ruff format --check .`
Expected: Clean

- [ ] **Step 3: Manual browser test**

1. Create a session with `output_plugin: "jira"` template
2. Approve required sections
3. Click Publish → verify modal shows Jira fields (project key, summary, labels)
4. Fill in project key → click Publish
5. Expected: error about missing `JIRA_BASE_URL` env var (since no real Jira configured) — this confirms the flow works up to the HTTP call

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: final cleanup for Jira publish config"
```
