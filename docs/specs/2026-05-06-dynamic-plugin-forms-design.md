# Dynamic Plugin Config Forms

Replace hardcoded per-plugin publish modal fields with schema-driven
dynamic form generation. Plugins declare their config schema; the
frontend renders forms from it; the backend validates against it.

---

## Plugin Schema Declaration

Each plugin declares a `config_schema` class attribute on its `Plugin`
class. `OutputPlugin` base class defaults to `config_schema = []`.

Each entry is a dict with these keys:

| Key           | Type        | Required | Description                                      |
|---------------|-------------|----------|--------------------------------------------------|
| `name`        | `str`       | yes      | Field identifier, matches key in `config` dict   |
| `type`        | `str`       | yes      | `"text"`, `"list"`, or `"select"`                |
| `label`       | `str`       | yes      | Human-readable label for the form                |
| `required`    | `bool`      | no       | Defaults to `false`                              |
| `placeholder` | `str`       | no       | Input placeholder text                           |
| `default`     | `str`       | no       | Default value pre-filled (must be in `options` for `select`) |
| `options`     | `list[str]` | no       | Choices for `select` type only                   |

### Type Semantics

- **`text`** — `<input type="text">`, value is a string.
- **`list`** — `<input type="text">` with "(comma-separated)" hint.
  Frontend splits into a list of strings before sending.
- **`select`** — `<select>` populated from `options`. Value is a string.

### Schema Examples

Jira plugin:

```python
config_schema = [
    {"name": "project_key", "type": "text", "label": "Project Key",
     "required": True, "placeholder": "e.g. PROJ"},
    {"name": "summary", "type": "text", "label": "Summary",
     "default": "DraftCircle Document"},
    {"name": "labels", "type": "list", "label": "Labels",
     "placeholder": "bug, feature"},
]
```

Markdown plugin:

```python
config_schema = [
    {"name": "filename", "type": "text", "label": "Filename",
     "default": "document.md"},
]
```

---

## API Changes

### `GET /api/plugins`

Response adds `config_schema` to each plugin entry:

```json
[
  {
    "name": "jira_feature",
    "download": false,
    "config_schema": [
      {"name": "project_key", "type": "text", "label": "Project Key",
       "required": true, "placeholder": "e.g. PROJ"},
      {"name": "summary", "type": "text", "label": "Summary",
       "default": "DraftCircle Document"},
      {"name": "labels", "type": "list", "label": "Labels",
       "placeholder": "bug, feature"}
    ]
  },
  {
    "name": "markdown",
    "download": true,
    "config_schema": [
      {"name": "filename", "type": "text", "label": "Filename",
       "default": "document.md"}
    ]
  }
]
```

### `POST /api/sessions/{session_id}/publish`

No change to request/response contract. Still receives
`{plugin, config}`. Backend now validates `config` against the plugin's
`config_schema` before calling `publish()`.

---

## Backend Validation

A new function `validate_plugin_config(schema, config)` in
`backend/plugin_loader.py`:

1. Iterates the plugin's `config_schema`.
2. For each field where `required` is `True`: checks the key exists in
   `config` and the value is non-empty (not `None`, not `""`, not `[]`).
3. Returns a list of error strings (e.g., `"Field 'project_key' is required"`).
4. If errors, the publish endpoint returns 422 with `{"detail": errors}`.

Runs before `plugin.publish()`. Plugins can still do domain-specific
validation in their own code (e.g., Jira verifying the project key
exists via API).

No type coercion at the validation layer. Frontend sends correct types.

---

## Frontend Changes

### HTML

Remove the hardcoded `#publish-jira-fields` and
`#publish-markdown-fields` blocks from the publish modal in
`index.html`. Replace with a single empty container:

```html
<div id="publish-plugin-fields"></div>
```

### JavaScript

**Remove:**
- `PLUGIN_FIELDS` mapping
- `showPluginFields()` function
- `buildPluginConfig()` function

**Add:**

`renderPluginFields(schema)` — clears `#publish-plugin-fields` and
builds form elements from the schema:

- `text` / `list`: `<label>` + `<input type="text">` with `placeholder`,
  `required`, and `data-field-name` attributes. `list` fields get a
  "(comma-separated)" hint appended.
- `select`: `<label>` + `<select>` from `options`, with a blank
  "Select..." default if not required.
- Fills `default` values.

`collectPluginConfig(schema)` — iterates schema, reads inputs by
`data-field-name`:

- `list`: splits by comma, trims whitespace, filters empties → array
- `text` / `select`: string value as-is
- Returns config dict.

**Validation:** Before submission, iterates schema and checks required
fields are non-empty. Uses native form validation on the first empty
required field.

**Session-context defaults:** After `renderPluginFields()` runs,
`showPublishModal()` sets known defaults by field name (e.g., `summary`
and `filename` to the session ID). This is generic caller logic, not
per-plugin knowledge.

---

## Schema Extensibility

The schema is designed so that conditional field visibility (e.g., "show
field X only when field Y has value Z") can be added later via an
optional `depends_on` key without breaking existing schemas. This is
not built now — flat fields only.
