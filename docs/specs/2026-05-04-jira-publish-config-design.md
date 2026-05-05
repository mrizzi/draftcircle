# Jira Publish Config Redesign

Move Jira credentials to environment variables and add a publish form
for per-session settings (project key, summary, labels).

## Problem

The Jira plugin expects credentials (base_url, email, api_token) in the
publish request config. There's no frontend UI to enter these, so
publishing to Jira is impossible from the UI. Credentials should not be
passed from the frontend.

## Design

### Credentials from environment variables

The Jira plugin reads auth credentials from env vars at publish time:

- `JIRA_BASE_URL` — e.g. `https://mycompany.atlassian.net`
- `JIRA_EMAIL` — Jira account email
- `JIRA_API_TOKEN` — Jira API token

If any are missing, `publish()` raises `ValueError` with a clear
message naming the missing variable.

The `config` dict passed to `publish()` no longer carries credentials.
It only contains:

- `project_key` (required) — target Jira project
- `summary` (optional, default: session ID) — issue summary
- `labels` (optional, default: `[]`) — issue labels

### Publish form modal

When the user clicks Publish, a modal appears with:

- **Project Key** — text input, required
- **Summary** — text input, pre-filled with the session ID
- **Labels** — text input, comma-separated, optional
- **Publish** and **Cancel** buttons

The form collects these values and sends them as the `config` in the
`POST /api/sessions/{id}/publish` request. No credentials leave the
browser.

### Template output_plugin

Templates continue to specify `"output_plugin": "jira"` or
`"output_plugin": "markdown"`. The publish form adapts based on the
plugin:

- **jira** — shows project key, summary, labels fields
- **markdown** — shows output path field (existing behavior)

The frontend reads `template.output_plugin` to decide which form to
render.

### No changes to plugin system

The `OutputPlugin` interface (`assemble()` + `publish()`) stays the
same. The Jira plugin's internal implementation changes to read env
vars instead of config for credentials.

## Scope

- Modify: `backend/plugins/jira_feature.py` — read env vars for auth
- Modify: `frontend/app.js` — add publish form modal with
  plugin-specific fields
- Modify: `frontend/index.html` — add publish modal HTML
- Update: `tests/test_jira_feature.py` — mock env vars instead of
  config credentials
- Update: `tests/test_api.py` — update publish test config

## API contract (unchanged)

```
POST /api/sessions/{session_id}/publish
Body: { "config": { "project_key": "PROJ", "summary": "...", "labels": ["draft"] } }
Response: { "status": "published", "output_ref": "PROJ-123" }
```
