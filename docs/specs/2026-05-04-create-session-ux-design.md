# Create Session Form UX Redesign

Replace the free-text section assignment with a visual grid that makes
ownership obvious and prevents unowned sections.

## Problem

The current form has a text input where users type comma-separated
section IDs (e.g. `overview, requirements`). Users don't know the IDs,
skip the step, and create sessions with all sections unowned — breaking
the approve/reject workflow.

## Design

### Section Assignment Grid

When a template is selected, the form renders a grid with one row per
section defined in the template. Each row shows:

- **Section title** (from template)
- **Suggested role** (from `suggested_roles` in template, shown as hint text)
- **Priority badge** (required / recommended / optional)
- **Owner dropdown** populated from the registered users list

### Auto-suggestion

When the grid renders, each section's `suggested_roles` are matched
against each user's `default_roles` from `users.json`. The first
matching user is pre-selected in the dropdown. If no match, the
dropdown defaults to "— unassigned —".

### Required section fallback

Required sections that remain unassigned when the form is submitted are
automatically assigned to the coordinator. No warning or blocking needed.

### Role field removed

The per-participant role field is removed from the form. Roles are
derived from `default_roles` in `users.json`.

### No "Add Participant" button

The separate participant-adding flow is removed. Participants are
derived from the section assignments: each unique user selected in the
grid becomes a participant with their assigned sections.

### Participant construction on submit

When the form is submitted, the frontend collects the grid state and
builds the `participants` array:

```
{ user_id: "alice", assigned_sections: ["overview"], role: "product-manager" }
{ user_id: "bob", assigned_sections: ["requirements", "design"], role: "architect" }
```

The role is the user's first `default_role`. Unassigned optional
sections are omitted from any participant's `assigned_sections`.

## API contract (unchanged)

The backend `POST /api/sessions` payload stays the same:

```json
{
  "template": "jira-feature",
  "coordinator": "alice",
  "participants": [
    { "user_id": "alice", "assigned_sections": ["overview"], "role": "product-manager" },
    { "user_id": "bob", "assigned_sections": ["requirements", "design"], "role": "architect" }
  ],
  "seed_text": "optional"
}
```

All integration tests (`tests/integration/`) and E2E tests
(`tests/e2e/`) create sessions via API with this structure, not
through the form UI. As long as the form submits this shape, existing
tests are unaffected.

## Scope

Frontend-only change. No backend modifications needed. The template
and user data needed for the grid are already fetched by
`loadSessionList()`.

## Test coverage

No existing test exercises the Create Session form UI — all
integration and E2E tests use `create_session_via_api()` or direct
`POST /api/sessions` calls. This change should add an E2E test
(`tests/e2e/test_create_session_form.py`) that:

- Selects a template and verifies the section grid appears
- Verifies auto-suggestion pre-selects owners from `suggested_roles`
- Submits the form and verifies the session is created with correct
  participant assignments
- Verifies required sections auto-assign to coordinator when left
  unassigned

## Files

- Modify: `frontend/app.js` — rewrite `showCreateForm()` and
  `handleCreateSession()`, remove `addParticipantRow()`
- Modify: `frontend/index.html` — replace participants section HTML
- Modify: `frontend/style.css` — add grid styling
- Create: `tests/e2e/test_create_session_form.py` — E2E tests for
  the new form
