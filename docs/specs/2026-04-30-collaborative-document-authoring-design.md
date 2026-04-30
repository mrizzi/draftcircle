# DraftCircle — Collaborative AI-Assisted Document Authoring Platform

A web-based platform for structured, multi-user document authoring with AI as a
first-class participant. Templates define sections with role-based ownership.
Multiple users collaborate in parallel, the AI proposes revisions based on
comments, and approved sections are assembled into outputs for external systems
(Jira, Confluence, etc.).

The Jira Feature Definition template (9 sections) is the first use case.

## 1. Overall Architecture

Three layers:

### 1.1 Static Frontend (plain HTML/CSS/JS)

A single-page workspace served as static files by the backend. No build step, no
framework. Uses CSS grid for layout, vanilla JS for DOM manipulation, and the
native WebSocket API for real-time communication.

### 1.2 Orchestration Backend (Python)

A single-process Python server built with FastAPI. Responsibilities:

- **Session management** — create, list, restore sessions
- **AI orchestration** — receive comments, call the LLM via Claude Agent SDK,
  broadcast proposals via WebSocket
- **Git operations** — every state change is a commit via pygit2
- **Identity** — token-based participant identification via invite links
- **Output plugins** — assemble approved sections and publish to external systems

### 1.3 Git Repository (Persistence Layer)

The data repository is **separate from the application source code**. Its path
is provided at startup via configuration (e.g., environment variable
`DRAFTCIRCLE_DATA_REPO=/path/to/data`). The application initializes or opens
the git repo at that path. This keeps session data, user-uploaded seed material,
and high-volume commits out of the application repository.

Each session is a directory in the data repo. Every mutation (comment, proposal,
accept, reject, status change) is a git commit with a structured message. This
provides full history, diffing, and the ability to restore any point in a
session.

Data repository structure:

```
<data-repo>/
  users.json                # user registry (shared across sessions)
  templates/                # JSON template files
  plugins/                  # custom user-provided output plugins
  sessions/<session-id>/    # format: <template>-<YYYYMMDD>-<HHmmss>
    session.json            # session metadata (see schema below)
  sections/
    01-feature-overview.md
    02-background.md
    03-goals.md
    ...
  comments/
    01-feature-overview.json   # array of comments with author, timestamp, text
  proposals/
    01-feature-overview/
      proposal-001.json        # AI-proposed diff, status: pending/accepted/rejected
  seed/
    <uploaded documents, pasted text, links>
```

`session.json` schema:

```json
{
  "id": "jira-feature-20260430-093000",
  "template": "jira-feature",
  "status": "active",
  "coordinator": "mrizzi",
  "agent_session_id": "sdk-session-uuid",
  "participants": [
    {
      "user_id": "alice",
      "token": "generated-invite-token",
      "assigned_sections": ["feature-overview", "background", "goals"],
      "role": "product-manager"
    },
    {
      "user_id": "bob",
      "token": "generated-invite-token",
      "assigned_sections": ["nfrs"],
      "role": "architect"
    }
  ],
  "created_at": "2026-04-30T09:00:00Z",
  "published_at": null,
  "output_ref": null
}
```

Session statuses: `active`, `published` (read-only).

Session ID format: `<template-name>-<YYYYMMDD>-<HHmmss>`, derived from the
template name and creation timestamp (UTC). This produces human-friendly,
sortable, filesystem-safe identifiers (e.g., `jira-feature-20260430-093000`).
If a collision occurs (two sessions from the same template within the same
second), a numeric suffix is appended (e.g., `jira-feature-20260430-093000-2`).

Commit message convention:

- `init: session created from template jira-feature`
- `draft: AI generated draft for 01-feature-overview`
- `comment: alice on 01-feature-overview`
- `proposal: AI revision for 03-goals`
- `accept: bob accepted proposal-002 on 05-nfrs`
- `reject: bob rejected proposal-003 on 05-nfrs`
- `approve: alice approved 01-feature-overview`
- `reopen: alice reopened 01-feature-overview`
- `publish: session published to TC-4258`

## 2. Workflow & Lifecycle

A session moves through four phases.

### Phase 1 — Initialization

The coordinator creates a session by providing:

- A template (e.g., "Jira Feature Definition")
- Seed material (pasted text, document uploads, URLs)
- Section assignments: which participants own which sections

The backend:

1. Creates the session directory
2. Stores seed material in `seed/`
3. Initializes a Claude Agent SDK session, loading the seed material into context
4. Calls the LLM to generate initial drafts for all sections
5. Commits each draft individually
6. Notifies all participants via WebSocket

### Phase 2 — Collaborative Refinement

All sections are open for work simultaneously.

1. Assigned contributors see the current draft and can post comments
2. Any comment triggers the AI to evaluate whether a revision is warranted
3. If the AI determines a change is needed, it creates a **proposal** — a
   suggested revision with a diff view and explanation
4. If the comment is a question or discussion point, the AI posts a reply
   comment instead (no proposal)
5. The section owner accepts or rejects proposals. Acceptance updates the draft;
   rejection keeps it as-is
6. Non-assigned users can view and comment on any section, but only assigned
   contributors can accept/reject proposals

Each action is a git commit. All connected users see updates in real time via
WebSocket.

When multiple comments arrive concurrently, they are queued and processed
sequentially by the AI — one proposal at a time per section to avoid conflicting
revisions.

### Phase 3 — Section Approval

When a section owner is satisfied, they mark the section as "approved." An
approved section is locked — no further comments or proposals unless explicitly
reopened.

The workspace shows a progress indicator (e.g., "6/9 sections approved, 2 in
review, 1 draft").

Completion rules:

- All **required** sections must reach "approved"
- **Recommended** sections can be approved or skipped
- **Optional** sections can be approved or skipped
- Skipping a section marks it as "skipped" and counts toward completion

### Phase 4 — Publication

Once all required sections are approved, the "Publish" action becomes available.
The backend:

1. Calls the output plugin's `assemble` method to compose the approved sections
2. Calls the output plugin's `publish` method to push to the external system
3. Marks the session as "published" (read-only)
4. Commits the final state

## 3. Template System

Templates are JSON files in the data repository:

```
<data-repo>/
  templates/
    jira-feature.json
    design-review.json
    incident-postmortem.json
```

Template schema:

```json
{
  "name": "Jira Feature Definition",
  "description": "Feature definition template with 9 sections",
  "output_plugin": "jira-feature",
  "ai_context": "You are helping define a Jira Feature issue...",
  "sections": [
    {
      "id": "feature-overview",
      "title": "Feature Overview",
      "priority": "required",
      "guidance": "High-level description covering the What and Why",
      "suggested_roles": ["product-manager"]
    },
    {
      "id": "background",
      "title": "Background and Strategic Fit",
      "priority": "recommended",
      "guidance": "How the feature fits into product strategy",
      "suggested_roles": ["product-manager"]
    },
    {
      "id": "goals",
      "title": "Goals",
      "priority": "recommended",
      "guidance": "Who benefits, current vs. target state, goal statements",
      "suggested_roles": ["product-manager"]
    },
    {
      "id": "requirements",
      "title": "Requirements",
      "priority": "required",
      "guidance": "Requirements table: requirement, notes, MVP flag",
      "suggested_roles": ["product-manager", "architect"]
    },
    {
      "id": "nfrs",
      "title": "Non-Functional Requirements",
      "priority": "recommended",
      "guidance": "Architecture characteristics and NFRs as acceptance criteria",
      "suggested_roles": ["architect", "security-engineer"]
    },
    {
      "id": "use-cases",
      "title": "Use Cases",
      "priority": "recommended",
      "guidance": "Success scenarios with personas, pre-conditions, outcomes",
      "suggested_roles": ["product-manager", "ux-designer"]
    },
    {
      "id": "customer-considerations",
      "title": "Customer Considerations",
      "priority": "optional",
      "guidance": "Prerequisites, dependencies, assumptions",
      "suggested_roles": ["product-manager"]
    },
    {
      "id": "supportability",
      "title": "Customer Information/Supportability",
      "priority": "optional",
      "guidance": "SRE metrics, observability, customer feedback",
      "suggested_roles": ["sre-engineer"]
    },
    {
      "id": "documentation",
      "title": "Documentation Considerations",
      "priority": "optional",
      "guidance": "Doc impact, user purpose, reference material",
      "suggested_roles": ["tech-writer"]
    }
  ]
}
```

Section fields:

- `id` — unique identifier, used for filenames and references
- `title` — display name
- `priority` — `required`, `recommended`, or `optional`
- `guidance` — instructions for the AI when generating drafts and proposals, and
  for contributors when reviewing
- `suggested_roles` — used to auto-suggest participant assignments from the user
  registry

Adding a new template requires no code changes — just a new JSON file.

## 4. AI Interaction Model

The AI participates as a distinct actor with explicit rules.

### 4.1 Context Persistence via Claude Agent SDK

Each collaborative session maps to a Claude Agent SDK session. The seed material
is loaded once during initialization and persists across all subsequent AI
interactions within the session. This avoids re-sending large documents and
preserves the AI's full understanding of the source material.

The Agent SDK session ID is stored in `session.json` and used to save/restore
the AI conversation state between backend restarts.

Reference: https://code.claude.com/docs/en/agent-sdk/sessions

### 4.2 Draft Generation (Phase 1)

When the coordinator provides seed material, the AI processes it against:

- The template's `ai_context`
- Each section's `guidance`

It generates one draft per section. Each draft is committed individually so git
history shows per-section provenance.

### 4.3 Comment-Triggered Proposals (Phase 2)

When a contributor posts a comment, the backend sends the AI:

- The current section draft
- The full comment thread for that section
- The new comment
- The template guidance for that section
- The original seed material (available in the persistent Agent SDK session)

The AI decides one of two outcomes:

1. **Propose a revision** — returns a new draft with a short explanation of what
   changed and why. Stored as a proposal with `status: pending`.
2. **Respond without revising** — posts a reply comment if the input is a
   question or discussion point that doesn't warrant a draft change.

### 4.4 Proposal Format

Each proposal (`proposals/<section-id>/proposal-NNN.json`) contains:

```json
{
  "id": "proposal-001",
  "section_id": "feature-overview",
  "triggered_by_comment": "comment-005",
  "revised_text": "...",
  "summary": "Added rate limiting to NFRs per Alice's comment",
  "status": "pending",
  "created_at": "2026-04-30T10:15:00Z"
}
```

The frontend renders a diff view (old draft vs. proposed text) so the section
owner can see exactly what would change before accepting.

### 4.5 Guardrails

- The AI never modifies a section directly — all changes go through the
  proposal → accept flow
- The AI never fabricates content beyond what's in the seed material and
  contributor comments
- If the LLM provider is unavailable, comments still work normally; proposals
  are queued and generated when the provider recovers

## 5. Output Plugins

Output plugins bridge the collaboration workspace and external systems.

### 5.1 Interface

Every plugin implements two methods:

- `assemble(session) → structured_output` — takes all approved sections and
  composes them into the target format
- `publish(structured_output, config) → result` — pushes to the external system
  and returns a reference (issue key, page URL, file path)

### 5.2 Jira Feature Plugin (First Implementation)

- `assemble` composes sections into a description with headings matching the
  template section titles, converts to ADF format
- `publish` creates the Jira issue via REST API, sets labels, assignee, posts a
  summary comment
- Config: project key, cloud ID, issue type ID, default labels

### 5.3 Future Plugins

- **Confluence page** — assembles sections into a Confluence page
- **Markdown file** — writes output to a file in a git repo
- **PDF export** — generates a formatted document

### 5.4 Plugin Loading

Plugins are Python modules registered by the template's `output_plugin` field.
The backend loads plugins from two locations:

1. **Built-in plugins** (`backend/plugins/` in the application repo) — ship with
   DraftCircle (e.g., Jira, Confluence, markdown)
2. **Custom plugins** (`plugins/` in the data repo) — user-provided plugins
   added without modifying the application

Custom plugins take precedence over built-in plugins with the same name,
allowing users to override default behavior. Both locations follow the same
module structure and interface.

## 6. Frontend UI

### 6.1 Layout

Three areas:

- **Header bar** — session name, template name, progress indicator (e.g., "5/9
  sections approved"), coordinator name, "Publish" button (enabled only when all
  required sections are approved)
- **Section grid** — main area. Each section is a card showing title, status
  badge (draft / in-review / approved / skipped), assigned contributors, and the
  current draft as rendered text
- **Section detail panel** — clicking a card opens a side panel showing the full
  draft, comment thread, pending proposals with diff view, and a comment input
  box. Accept/reject buttons on pending proposals for section owners.

### 6.2 Status Badges

- **Draft** (grey) — initial AI-generated draft, no comments yet
- **In review** (blue) — has comments or pending proposals
- **Approved** (green) — section owner has approved; locked unless reopened
- **Skipped** (light grey) — recommended/optional section explicitly skipped

### 6.3 Interactions

- Coordinator sees all sections and can assign/reassign contributors
- Contributors see all sections but can only accept/reject proposals on assigned
  sections
- Anyone can comment on any section
- Pending proposals show as a highlighted diff (green insertions, red deletions)
  with the AI's explanation
- Status transitions: draft → in-review → approved (can be reopened)

### 6.4 Real-Time Updates

WebSocket messages update the UI live:

- New comment from another user appears instantly
- AI proposal fades in when ready
- Section status change updates badge and progress bar without refresh
- Participant join/leave shown in header

### 6.5 Technology

Plain HTML/CSS/JS. No framework, no build step.

- CSS grid for layout
- Template literals for DOM construction
- Native `WebSocket` API
- `marked` or similar lightweight library for rendering markdown drafts

## 7. Identity & Access

### 7.1 User Registry

A `users.json` file in the data repository root:

```json
{
  "users": [
    {
      "id": "mrizzi",
      "name": "Marco Rizzi",
      "email": "mrizzi@example.com",
      "default_roles": ["coordinator", "architect"]
    },
    {
      "id": "alice",
      "name": "Alice Chen",
      "email": "achen@example.com",
      "default_roles": ["product-manager"]
    },
    {
      "id": "bob",
      "name": "Bob Kumar",
      "email": "bkumar@example.com",
      "default_roles": ["security-engineer"]
    }
  ]
}
```

New users can be added by the coordinator during session creation — they are
appended to `users.json` and committed.

### 7.2 Session-Based Identity via Invite Links

When the coordinator creates a session:

1. They select participants from the user registry
2. The template's `suggested_roles` auto-match against users' `default_roles` to
   pre-fill section assignments
3. The coordinator confirms or adjusts assignments
4. **"Generate All Links"** creates a unique invite link per participant:
   `https://host/session/<session-id>?token=<participant-token>`
5. Each link is copyable individually or as a full list

Each token maps to a participant identity. The token is stored in the browser's
`localStorage` so participants don't need the link on refresh.

### 7.3 Permissions

- **Coordinator** — full access: create session, assign/reassign participants,
  approve any section, publish
- **Section owner** — can accept/reject proposals on assigned sections, approve
  assigned sections
- **Participant** — can view all sections, comment on any section

### 7.4 Future Upgrade Path

When proper auth is needed, the backend adds an OIDC/SSO layer. The participant
model stays the same — tokens are replaced by authenticated sessions, invite
links trigger a login flow.

## 8. Backend Technology Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python | Claude Agent SDK has first-class Python support |
| Web framework | FastAPI | Async, WebSocket support, lightweight |
| Git operations | pygit2 | Thread-safe, typed, actively maintained, native performance via libgit2 |
| AI integration | Claude Agent SDK | Session persistence, native Python API |
| WebSocket | FastAPI WebSocket | Built-in, no additional dependency |
| Markdown rendering | Backend passes raw markdown; frontend renders | Keeps backend simple |

### 8.1 API Endpoints

```
POST   /api/sessions                    # create session
GET    /api/sessions                    # list sessions
GET    /api/sessions/<id>               # get session state
POST   /api/sessions/<id>/comments      # post comment on a section
POST   /api/sessions/<id>/proposals/<pid>/accept
POST   /api/sessions/<id>/proposals/<pid>/reject
POST   /api/sessions/<id>/sections/<sid>/approve
POST   /api/sessions/<id>/sections/<sid>/reopen
POST   /api/sessions/<id>/sections/<sid>/skip
POST   /api/sessions/<id>/publish
GET    /api/sessions/<id>/history       # git log for the session
GET    /api/templates                   # list available templates
GET    /api/users                       # list user registry
POST   /api/users                       # add user to registry
WS     /ws/sessions/<id>                # WebSocket for real-time updates
```

### 8.2 WebSocket Message Types

```json
{"type": "comment_added", "section_id": "...", "comment": {...}}
{"type": "proposal_created", "section_id": "...", "proposal": {...}}
{"type": "proposal_accepted", "section_id": "...", "proposal_id": "..."}
{"type": "proposal_rejected", "section_id": "...", "proposal_id": "..."}
{"type": "section_approved", "section_id": "..."}
{"type": "section_reopened", "section_id": "..."}
{"type": "section_skipped", "section_id": "..."}
{"type": "session_published", "output_ref": "TC-4258"}
{"type": "participant_joined", "user": {...}}
{"type": "participant_left", "user": {...}}
```

### 8.3 pygit2 Wrapper

A thin `git_store.py` module wrapping common operations:

- `commit(session_id, message, files)` — stage files and create commit
- `read_file(session_id, path)` — read file content at HEAD
- `diff(session_id, path, commit_a, commit_b)` — diff a file between commits
- `log(session_id, path=None)` — commit history, optionally filtered by file
- `restore(session_id, commit_sha)` — checkout a specific point in history
