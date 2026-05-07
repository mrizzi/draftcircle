# Dynamic Plugin Config Forms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded per-plugin publish modal fields with schema-driven dynamic form generation so adding a new output plugin requires zero frontend changes.

**Architecture:** Each plugin declares a `config_schema` class attribute describing its config fields. The `/api/plugins` endpoint returns these schemas. The frontend renders form fields dynamically from the schema and collects config generically. The backend validates required fields against the schema before calling `publish()`.

**Tech Stack:** Python/FastAPI backend, vanilla HTML/CSS/JS frontend.

**Spec:** `docs/specs/2026-05-06-dynamic-plugin-forms-design.md`

---

### Task 1: Add `config_schema` to `OutputPlugin` base class

**Files:**
- Modify: `backend/plugins/base.py:7-8`
- Test: `tests/test_plugin_loader.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plugin_loader.py`:

```python
class TestPluginConfigSchema:
    def test_base_plugin_has_empty_config_schema(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert hasattr(plugin, "config_schema")

    def test_default_config_schema_is_empty_list(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        # Markdown plugin will get its own schema in Task 2,
        # but the base class default should be a list
        assert isinstance(plugin.config_schema, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_loader.py::TestPluginConfigSchema -v`
Expected: FAIL — `OutputPlugin` has no `config_schema` attribute

- [ ] **Step 3: Write minimal implementation**

In `backend/plugins/base.py`, add `config_schema` to the base class:

```python
from abc import ABC, abstractmethod
from typing import Any

from backend.models import SectionContent


class OutputPlugin(ABC):
    download: bool = False
    config_schema: list[dict[str, Any]] = []

    @abstractmethod
    def assemble(self, sections: list[SectionContent]) -> str: ...

    @abstractmethod
    def publish(self, output: str, config: dict[str, Any]) -> str: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plugin_loader.py::TestPluginConfigSchema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/plugins/base.py tests/test_plugin_loader.py
git commit -m "feat: add config_schema to OutputPlugin base class"
```

---

### Task 2: Add `config_schema` to Jira and Markdown plugins

**Files:**
- Modify: `backend/plugins/jira_feature.py:64`
- Modify: `backend/plugins/markdown.py:7`
- Test: `tests/test_plugin_loader.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plugin_loader.py`:

```python
class TestJiraConfigSchema:
    def test_jira_has_config_schema(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        assert len(plugin.config_schema) == 3

    def test_jira_project_key_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[0]
        assert field["name"] == "project_key"
        assert field["type"] == "text"
        assert field["required"] is True

    def test_jira_summary_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[1]
        assert field["name"] == "summary"
        assert field["type"] == "text"
        assert field["default"] == "DraftCircle Document"

    def test_jira_labels_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[2]
        assert field["name"] == "labels"
        assert field["type"] == "list"


class TestMarkdownConfigSchema:
    def test_markdown_has_config_schema(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert len(plugin.config_schema) == 1

    def test_markdown_filename_field(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        field = plugin.config_schema[0]
        assert field["name"] == "filename"
        assert field["type"] == "text"
        assert field["default"] == "document.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plugin_loader.py::TestJiraConfigSchema tests/test_plugin_loader.py::TestMarkdownConfigSchema -v`
Expected: FAIL — schemas are empty lists

- [ ] **Step 3: Add schema to Jira plugin**

In `backend/plugins/jira_feature.py`, add `config_schema` to the `JiraFeaturePlugin` class (after line 64, before `def assemble`):

```python
class JiraFeaturePlugin(OutputPlugin):
    config_schema = [
        {
            "name": "project_key",
            "type": "text",
            "label": "Project Key",
            "required": True,
            "placeholder": "e.g. PROJ",
        },
        {
            "name": "summary",
            "type": "text",
            "label": "Summary",
            "default": "DraftCircle Document",
        },
        {
            "name": "labels",
            "type": "list",
            "label": "Labels",
            "placeholder": "bug, feature",
        },
    ]
```

- [ ] **Step 4: Add schema to Markdown plugin**

In `backend/plugins/markdown.py`, add `config_schema` to the `Plugin` class:

```python
class Plugin(OutputPlugin):
    download = True
    config_schema = [
        {
            "name": "filename",
            "type": "text",
            "label": "Filename",
            "default": "document.md",
        },
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_plugin_loader.py::TestJiraConfigSchema tests/test_plugin_loader.py::TestMarkdownConfigSchema -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/plugins/jira_feature.py backend/plugins/markdown.py tests/test_plugin_loader.py
git commit -m "feat: add config_schema to jira and markdown plugins"
```

---

### Task 3: Add `validate_plugin_config()` to plugin_loader

**Files:**
- Modify: `backend/plugin_loader.py`
- Test: `tests/test_plugin_loader.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plugin_loader.py`:

```python
from backend.plugin_loader import validate_plugin_config


class TestValidatePluginConfig:
    def test_passes_when_required_fields_present(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": "PROJ"})
        assert errors == []

    def test_fails_when_required_field_missing(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "Project Key", "required": True},
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 1
        assert "project_key" in errors[0]

    def test_fails_when_required_field_is_empty_string(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": ""})
        assert len(errors) == 1

    def test_fails_when_required_field_is_none(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": None})
        assert len(errors) == 1

    def test_fails_when_required_list_field_is_empty(self):
        schema = [
            {"name": "tags", "type": "list", "label": "Tags", "required": True},
        ]
        errors = validate_plugin_config(schema, {"tags": []})
        assert len(errors) == 1

    def test_passes_when_optional_field_missing(self):
        schema = [
            {"name": "summary", "type": "text", "label": "Summary"},
        ]
        errors = validate_plugin_config(schema, {})
        assert errors == []

    def test_passes_with_empty_schema(self):
        errors = validate_plugin_config([], {"anything": "goes"})
        assert errors == []

    def test_collects_multiple_errors(self):
        schema = [
            {"name": "a", "type": "text", "label": "A", "required": True},
            {"name": "b", "type": "text", "label": "B", "required": True},
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_plugin_loader.py::TestValidatePluginConfig -v`
Expected: FAIL — `validate_plugin_config` does not exist

- [ ] **Step 3: Implement `validate_plugin_config`**

Add `Any` to the imports at the top of `backend/plugin_loader.py`:

```python
from typing import Any
```

Add the function after the `load_plugin` function:

```python
def validate_plugin_config(
    schema: list[dict[str, Any]], config: dict[str, Any]
) -> list[str]:
    errors = []
    for field in schema:
        if not field.get("required"):
            continue
        name = field["name"]
        value = config.get(name)
        if value is None or value == "" or value == []:
            errors.append(f"Field '{name}' is required")
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_plugin_loader.py::TestValidatePluginConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/plugin_loader.py tests/test_plugin_loader.py
git commit -m "feat: add validate_plugin_config to plugin_loader"
```

---

### Task 4: Update `/api/plugins` to return `config_schema`

**Files:**
- Modify: `backend/main.py:89-105`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
class TestPluginEndpoints:
    def test_list_plugins_includes_config_schema(self, client):
        resp = client.get("/api/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        assert len(plugins) >= 2
        jira = next(p for p in plugins if p["name"] == "jira_feature")
        assert "config_schema" in jira
        assert len(jira["config_schema"]) == 3
        assert jira["config_schema"][0]["name"] == "project_key"

    def test_list_plugins_markdown_schema(self, client):
        resp = client.get("/api/plugins")
        plugins = resp.json()
        md = next(p for p in plugins if p["name"] == "markdown")
        assert md["download"] is True
        assert len(md["config_schema"]) == 1
        assert md["config_schema"][0]["name"] == "filename"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::TestPluginEndpoints -v`
Expected: FAIL — response has no `config_schema` key

- [ ] **Step 3: Update the endpoint**

In `backend/main.py`, modify the `get_plugins` function (around line 89). Change the `result.append` line to include `config_schema`:

```python
    @app.get("/api/plugins")
    def get_plugins():
        custom_dir = repo_path / "plugins"
        names = list_plugins(
            custom_plugins_dir=custom_dir if custom_dir.is_dir() else None
        )
        result = []
        for name in names:
            try:
                plugin = load_plugin(
                    name,
                    custom_plugins_dir=custom_dir if custom_dir.is_dir() else None,
                )
                result.append({
                    "name": name,
                    "download": plugin.download,
                    "config_schema": plugin.config_schema,
                })
            except ValueError:
                pass
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py::TestPluginEndpoints -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api.py
git commit -m "feat: return config_schema from /api/plugins endpoint"
```

---

### Task 5: Add backend config validation to publish endpoint

**Files:**
- Modify: `backend/main.py:436-457`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py`. This test needs a session that's ready to publish. Use the same `session_with_participant` fixture used by the existing publish tests:

```python
class TestPublishValidation:
    def test_publish_rejects_missing_required_field(
        self, client, session_with_participant
    ):
        sid, uid = session_with_participant
        for section_id in ["overview", "details", "notes"]:
            client.post(
                f"/api/sessions/{sid}/sections/{section_id}/content",
                json={"user_id": uid, "content": "Approved content"},
            )
            client.post(
                f"/api/sessions/{sid}/sections/{section_id}/approve",
                json={"user_id": uid},
            )

        resp = client.post(
            f"/api/sessions/{sid}/publish",
            json={"plugin": "jira_feature", "config": {}},
        )
        assert resp.status_code == 422
        assert "project_key" in resp.json()["detail"][0]

    def test_publish_passes_validation_with_required_fields(
        self, client, session_with_participant
    ):
        sid, uid = session_with_participant
        for section_id in ["overview", "details", "notes"]:
            client.post(
                f"/api/sessions/{sid}/sections/{section_id}/content",
                json={"user_id": uid, "content": "Content"},
            )
            client.post(
                f"/api/sessions/{sid}/sections/{section_id}/approve",
                json={"user_id": uid},
            )

        resp = client.post(
            f"/api/sessions/{sid}/publish",
            json={"plugin": "markdown", "config": {}},
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::TestPublishValidation -v`
Expected: `test_publish_rejects_missing_required_field` fails — currently returns 500 instead of 422.

- [ ] **Step 3: Add validation to publish endpoint**

In `backend/main.py`, update the import to include `validate_plugin_config`:

```python
from backend.plugin_loader import list_plugins, load_plugin, validate_plugin_config
```

In the `publish_session` function, add validation between the plugin load and the assemble call. Insert after the `except ValueError` block and before `approved_sections = sessions.get_approved_sections(session_id)`:

```python
        errors = validate_plugin_config(plugin.config_schema, req.config)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py::TestPublishValidation -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/test_api.py tests/test_plugin_loader.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_api.py
git commit -m "feat: validate plugin config against schema before publish"
```

---

### Task 6: Replace hardcoded frontend HTML with dynamic container

**Files:**
- Modify: `frontend/index.html:109-120`

- [ ] **Step 1: Replace hardcoded plugin field blocks**

In `frontend/index.html`, replace the two hardcoded field divs (`#publish-jira-fields` and `#publish-markdown-fields`, lines 109-120) with a single empty container. The publish modal form should become:

```html
      <form id="publish-form">
        <label for="publish-plugin-select">Output Format</label>
        <select id="publish-plugin-select" required></select>
        <div id="publish-plugin-fields"></div>
        <div class="form-actions">
          <button type="button" id="cancel-publish-btn" class="btn btn-secondary">Cancel</button>
          <button type="submit" class="btn btn-primary">Publish</button>
        </div>
      </form>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "refactor: replace hardcoded plugin fields with dynamic container"
```

---

### Task 7: Replace hardcoded frontend JS with dynamic form logic

**Files:**
- Modify: `frontend/app.js:834-932`

- [ ] **Step 1: Replace `PLUGIN_FIELDS`, `showPluginFields`, and `buildPluginConfig`**

In `frontend/app.js`, replace the block from `const PLUGIN_FIELDS` (line 834) through the end of `buildPluginConfig` (line 885) with two new functions:

```javascript
function renderPluginFields(schema) {
  var container = document.getElementById('publish-plugin-fields');
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!schema || schema.length === 0) return;
  schema.forEach(function(field) {
    var label = document.createElement('label');
    label.textContent = field.label;
    container.appendChild(label);
    if (field.type === 'select') {
      var select = document.createElement('select');
      select.dataset.fieldName = field.name;
      if (field.required) select.required = true;
      if (!field.required) {
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = 'Select…';
        select.appendChild(blank);
      }
      (field.options || []).forEach(function(opt) {
        var option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        if (field.default === opt) option.selected = true;
        select.appendChild(option);
      });
      container.appendChild(select);
    } else {
      var input = document.createElement('input');
      input.type = 'text';
      input.dataset.fieldName = field.name;
      if (field.placeholder) input.placeholder = field.placeholder;
      if (field.default) input.value = field.default;
      if (field.required) input.required = true;
      container.appendChild(input);
      if (field.type === 'list') {
        var hint = document.createElement('small');
        hint.textContent = '(comma-separated)';
        hint.style.display = 'block';
        hint.style.marginTop = '-0.25rem';
        hint.style.marginBottom = '0.5rem';
        hint.style.opacity = '0.7';
        container.appendChild(hint);
      }
    }
  });
}

function collectPluginConfig(schema) {
  var config = {};
  if (!schema) return config;
  var container = document.getElementById('publish-plugin-fields');
  schema.forEach(function(field) {
    var el = container.querySelector('[data-field-name="' + field.name + '"]');
    if (!el) return;
    var raw = el.value.trim();
    if (field.type === 'list') {
      config[field.name] = raw ? raw.split(',').map(function(s) { return s.trim(); }).filter(Boolean) : [];
    } else {
      config[field.name] = raw;
    }
  });
  return config;
}
```

- [ ] **Step 2: Update `showPublishModal` to use `renderPluginFields`**

Replace the `showPublishModal` function (lines 852-870) with:

```javascript
async function showPublishModal() {
  if (state.plugins.length === 0) {
    state.plugins = await apiFetch('/plugins');
  }

  var select = document.getElementById('publish-plugin-select');
  select.textContent = '';
  state.plugins.forEach(function(p) {
    var opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name.replace(/_/g, ' ');
    select.appendChild(opt);
  });

  function onPluginChange() {
    var plugin = state.plugins.find(function(p) { return p.name === select.value; });
    renderPluginFields(plugin ? plugin.config_schema : []);
    var sessionId = state.currentSession ? state.currentSession.id : '';
    var summaryInput = document.querySelector('[data-field-name="summary"]');
    if (summaryInput && !summaryInput.value) summaryInput.value = sessionId;
    var filenameInput = document.querySelector('[data-field-name="filename"]');
    if (filenameInput && !filenameInput.value) filenameInput.value = sessionId + '.md';
  }

  select.onchange = onPluginChange;
  onPluginChange();

  document.getElementById('publish-modal').style.display = 'flex';
}
```

- [ ] **Step 3: Update `handlePublish` to use `collectPluginConfig`**

In the `handlePublish` function (around line 887), replace the line:

```javascript
  const config = buildPluginConfig(pluginName);
```

with:

```javascript
  var pluginData = state.plugins.find(function(p) { return p.name === pluginName; });
  var config = collectPluginConfig(pluginData ? pluginData.config_schema : []);
```

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat: dynamic plugin form rendering from config_schema"
```

---

### Task 8: End-to-end verification

**Files:**
- No new files — verification only

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --ignore=tests/e2e`
Expected: All tests PASS

- [ ] **Step 2: Run linting**

Run: `ruff check . && ruff format --check .`
Expected: No errors

- [ ] **Step 3: Fix any issues found, then commit if needed**

If lint or test failures are found, fix them and commit:

```bash
git add -u
git commit -m "fix: address lint/test issues from dynamic forms implementation"
```
