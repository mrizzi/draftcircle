# Proposal Diff View — Unified Inline Diff for Prose

## Problem

Proposals currently show two full text blocks — the entire current draft
on a red background and the entire proposed draft on a green background.
For long sections, users must visually scan both blocks to find what
actually changed. There is no highlighting of changed words, and no way
to skip past unchanged content.

## Solution

Add a **unified inline diff view** that shows only changed paragraphs
with word-level highlighting, and collapses unchanged paragraphs behind
expandable separators. The existing full-text side-by-side view is
preserved behind a toggle.

## Diff Library

[jsdiff](https://github.com/kpdecker/jsdiff) loaded from CDN
(`cdnjs.cloudflare.com`). Provides a global `Diff` object. MIT licensed.
No build step required.

Use `Diff.diffWords()` which compares word-by-word and returns an array
of change objects `{ value, added, removed }`. This gives the right
granularity for prose — highlights changed words within sentences rather
than flagging entire lines.

## Paragraph Chunking and Collapse

Split both current and proposed text by double-newlines into paragraphs.
Compare pairwise using positional alignment (paragraph N vs paragraph N):

- **Unchanged paragraphs** — consecutive unchanged paragraphs collapse
  into a single separator: `"— N unchanged paragraphs —"`. Clickable to
  expand and show the hidden paragraphs as plain text.
- **Changed paragraphs** — rendered with word-level diff highlighting.
  Full paragraph shown, deleted words in red/strikethrough, added words
  in green, all inline.
- **Added paragraphs** (new in proposed, no match in current) — entire
  paragraph shown in green.
- **Removed paragraphs** (in current, gone from proposed) — entire
  paragraph shown in red/strikethrough.

Positional alignment works because AI proposals are revisions of the
existing draft and generally preserve structure. If paragraph counts
differ, trailing extras are treated as pure additions or deletions.

## Inline Diff Rendering

`Diff.diffWords()` returns tokens. Each token renders as a `<span>`:

- **Unchanged** — plain text, no styling.
- **Removed** — `<span class="diff-word-removed">` — red background,
  strikethrough.
- **Added** — `<span class="diff-word-added">` — green background.

Result reads left-to-right: "The system ~~must~~ **should** handle
authentication." — old word crossed out, replacement follows inline.

The entire diff output lives in a single scrollable `<div>`, one
continuous stream of paragraphs separated by collapsed-unchanged markers.

## Toggle Between Views

A small toggle at the top of the proposal's diff area, styled like
GitHub's "Unified / Split" pill toggle:

- **"Full text"** — existing two-block layout (current on red, proposed
  on green). No changes to current behavior.
- **"Changes"** — new unified inline diff with collapsed unchanged
  paragraphs and word-level highlighting.

Default: **"Changes"**. Toggle state is per-proposal, not global. No
persistence — resets on page reload.

The toggle replaces only the diff area. Proposal header, summary, and
accept/reject buttons remain unchanged.

## CSS

New CSS variables:

- `--diff-word-add: #bbf7d0` — green highlight for added words.
- `--diff-word-remove: #fecaca` — red highlight for removed words.

New classes:

- `.diff-word-added` — green background, 2px padding, 2px border-radius.
- `.diff-word-removed` — red background, 2px padding, 2px border-radius,
  line-through text decoration.
- `.diff-collapsed` — centered muted text, dashed borders top/bottom,
  pointer cursor. Clickable to expand hidden paragraphs.
- `.diff-toggle` — right-aligned pill button group above the diff area.
- `.diff-unified` — container for the unified view, same monospace font
  and border as existing `.proposal-diff`.

All styles reuse existing CSS variables (`--border`, `--text-secondary`,
etc.).

## Files Changed

- **`frontend/index.html`** — add jsdiff CDN `<script>` tag.
- **`frontend/app.js`** — modify `buildProposalEl()` to add toggle
  control and build both views. New `buildUnifiedDiff(currentText,
  proposedText)` function for paragraph splitting, pairwise comparison,
  collapsed sections, and span rendering.
- **`frontend/style.css`** — add new classes listed above.

No backend changes. No new files. No changes to the proposal data model.
The diff is computed client-side from the existing `currentContent` and
`proposal.revised_text` already available in `buildProposalEl()`.
