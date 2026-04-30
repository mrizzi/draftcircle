# DraftCircle

Collaborative AI-assisted document authoring platform. Multiple users
work on structured document sections in parallel, with AI proposing
revisions based on comments. Approved sections are assembled and
published to external systems (Jira, Confluence, etc.).

------------------------------------------------------------------------

# Architecture

Three layers:

- **Frontend** — plain HTML/CSS/JS single-page workspace served as static
  files. No framework, no build step. WebSocket for real-time updates.
- **Backend** — Python, FastAPI, async. Manages sessions, AI orchestration
  via Claude Agent SDK, git persistence via pygit2, WebSocket broadcast,
  output plugins.
- **Persistence** — a **separate** git repository (not this repo).
  Configured at startup via `DRAFTCIRCLE_DATA_REPO` env var. Stores
  sessions, templates, user registry, custom plugins, comments, and
  proposals. Every mutation is a commit.

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python |
| Web framework | FastAPI |
| Git operations | pygit2 |
| AI integration | Claude Agent SDK (session persistence) |
| WebSocket | FastAPI built-in |
| Frontend | Vanilla HTML/CSS/JS |
| Markdown rendering | Client-side (marked or similar) |

------------------------------------------------------------------------

# Key Concepts

- **Template** — JSON file in the data repo defining sections, roles,
  output plugin. Adding a template requires no code changes.
- **Session** — an instance of a template with assigned participants,
  seed material, and section drafts persisted in the data repo.
  ID format: `<template>-<YYYYMMDD>-<HHmmss>` (e.g.,
  `jira-feature-20260430-093000`).
- **Coordinator** — creates sessions, assigns participants, can approve
  any section, publishes.
- **Section owner** — assigned contributor who can accept/reject AI
  proposals and approve their sections.
- **Proposal** — AI-suggested revision triggered by a comment. Never
  auto-applied; must be accepted or rejected by the section owner.
- **Output plugin** — assembles approved sections and publishes to an
  external system. Implements `assemble()` and `publish()`.
- **Data repo** — separate git repository for all runtime data. Path
  set via `DRAFTCIRCLE_DATA_REPO`. Contains `users.json`, `templates/`,
  `plugins/`, and `sessions/`.

------------------------------------------------------------------------

# Project Structure

```
draftcircle/                  # this repo — application source code
  docs/specs/                 # design specs
  backend/
    main.py                   # FastAPI app entry point
    git_store.py              # pygit2 wrapper
    session_manager.py        # session lifecycle
    ai_orchestrator.py        # Claude Agent SDK integration
    plugins/                  # built-in output plugins (jira, confluence, etc.)
  frontend/
    index.html
    style.css
    app.js
  tests/

<DRAFTCIRCLE_DATA_REPO>/      # separate repo — configured at startup
  users.json                  # user registry
  templates/                  # JSON template files
  plugins/                   # custom user-provided output plugins
  sessions/<session-id>/      # per-session data
    session.json
    sections/
    comments/
    proposals/
    seed/
```

Plugin loading: built-in plugins (`backend/plugins/`) are loaded first,
then custom plugins (`<data-repo>/plugins/`). Custom plugins with the
same name override built-in ones.

------------------------------------------------------------------------

# Design Spec

The full design specification is at:
`docs/specs/2026-04-30-collaborative-document-authoring-design.md`

It covers: architecture, workflow lifecycle (4 phases), template system,
AI interaction model, output plugins, frontend UI, identity & access,
and backend technology stack.

------------------------------------------------------------------------

# Development Commands

```bash
# Install dependencies
pip install fastapi uvicorn pygit2 anthropic

# Run the backend (serves frontend static files too)
DRAFTCIRCLE_DATA_REPO=/path/to/data-repo uvicorn backend.main:app --reload --port 8000

# Run tests
pytest tests/

# Format
ruff format .

# Lint
ruff check .
```

------------------------------------------------------------------------

# Conventions

- Python code follows ruff defaults for formatting and linting.
- No comments unless the WHY is non-obvious.
- Frontend: no framework, no build step. Plain JS with template literals
  for DOM construction. CSS grid for layout.
- Git commit messages: imperative mood, concise.
