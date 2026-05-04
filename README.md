# DraftCircle

Collaborative AI-assisted document authoring platform. Multiple users
work on structured document sections in parallel, with an AI proposing
revisions based on comments. Approved sections are assembled and
published to external systems (Jira, Confluence, etc.).

## Prerequisites

- Python 3.12+
- git
- An [Anthropic API key](https://console.anthropic.com/) (optional — the
  server runs without one, but AI features are disabled)

## Install

```bash
pip install -e ".[dev]"
```

## Set up the data repository

DraftCircle stores all runtime data (sessions, templates, users, custom
plugins) in a **separate git repository**. Every mutation is a git
commit, giving you full history and diffing for free.

Create one with a sample template and users:

```bash
mkdir -p /path/to/data-repo && cd /path/to/data-repo
git init
mkdir -p templates plugins sessions

cat > users.json << 'EOF'
{
  "users": [
    {"id": "alice", "name": "Alice", "email": "alice@example.com", "default_roles": ["product-manager"]},
    {"id": "bob", "name": "Bob", "email": "bob@example.com", "default_roles": ["architect"]}
  ]
}
EOF

cat > templates/jira-feature.json << 'EOF'
{
  "name": "Jira Feature",
  "description": "Plan and spec a feature with structured sections",
  "output_plugin": "markdown",
  "ai_context": "You are helping a team plan and document a software feature.",
  "sections": [
    {"id": "overview", "title": "Feature Overview", "priority": "required", "guidance": "Describe what the feature does and why it matters.", "suggested_roles": ["product-manager"]},
    {"id": "requirements", "title": "Requirements", "priority": "required", "guidance": "List functional and non-functional requirements.", "suggested_roles": ["product-manager", "architect"]},
    {"id": "design", "title": "Technical Design", "priority": "recommended", "guidance": "Outline the technical approach and key decisions.", "suggested_roles": ["architect"]}
  ]
}
EOF

git add . && git commit -m "init"
```

Point the server at it via the `DRAFTCIRCLE_DATA_REPO` environment
variable (required). Edit `users.json` and add templates to
`templates/` to match your team.

## Run

```bash
export DRAFTCIRCLE_DATA_REPO=/path/to/data-repo
export ANTHROPIC_API_KEY=sk-...        # optional — or use Vertex AI:
# export CLAUDE_CODE_USE_VERTEX=1
# export CLOUD_ML_REGION=us-east5
# export ANTHROPIC_VERTEX_PROJECT_ID=your-project
uvicorn backend.main:create_app --factory --reload --port 8000
```

Open <http://localhost:8000>. The frontend is served as static files — no
build step.

## Test

```bash
pytest tests/
```

Tests use temporary git repos; no external services required.

## Lint & format

```bash
ruff check .
ruff format .
```

## Project structure

```
backend/
  main.py               # FastAPI app — routes, WebSocket, static files
  session_manager.py     # session lifecycle
  ai_orchestrator.py     # Claude API integration
  git_store.py           # pygit2 wrapper
  models.py              # Pydantic models
  template_loader.py     # loads templates from data repo
  user_registry.py       # user management
  ws_manager.py          # WebSocket broadcast
  plugin_loader.py       # output plugin discovery
  plugins/               # built-in output plugins (jira, confluence, markdown)
frontend/
  index.html             # SPA shell
  app.js                 # all client logic (vanilla JS, WebSocket)
  style.css
tests/
docs/specs/              # design specification
```

## Data repository layout

```
<DRAFTCIRCLE_DATA_REPO>/
  users.json
  templates/             # JSON template definitions
  plugins/               # custom output plugins (override built-in)
  sessions/<id>/
    session.json
    sections/            # markdown files per section
    comments/
    proposals/
    seed/                # uploaded reference material
```

Session IDs follow the format `<template>-<YYYYMMDD>-<HHmmss>`
(e.g. `jira-feature-20260430-093000`).

## Key concepts

| Concept | Description |
|---|---|
| **Template** | JSON file defining sections, roles, and output plugin. No code changes needed to add one. |
| **Session** | A live instance of a template with assigned participants and section drafts. |
| **Coordinator** | Creates sessions, assigns participants, approves any section, publishes. |
| **Section owner** | Contributor who accepts/rejects AI proposals and approves their section. |
| **Proposal** | AI-suggested revision triggered by a comment. Never auto-applied. |
| **Output plugin** | Assembles approved sections and publishes (Jira, Confluence, Markdown). Custom plugins in the data repo override built-in ones. |
