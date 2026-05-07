# Git Session Store Design

Persist Claude Agent SDK session transcripts in the data repo so agent
conversations survive server restarts and are portable across worktrees.

## Problem

The AI orchestrator uses the Claude Agent SDK's `query()` with `resume` to
continue conversations across interactions. The SDK stores session
transcripts locally under `~/.claude/projects/<encoded-cwd>/`. This breaks
when:

- The server restarts from a different working directory (e.g., a git
  worktree) because the encoded-cwd path changes.
- The local session store is ephemeral or gets cleaned up.
- Multiple server instances need to share session state.

Error observed: `"No conversation found with session ID: <uuid>"`

## Solution

Implement a `GitSessionStore` that satisfies the SDK's `SessionStore`
protocol and persists transcripts in the data repo via GitStore. The SDK's
dual-write architecture means the subprocess always writes locally first,
then mirrors entries to the store. On resume, the SDK calls `store.load()`
to retrieve entries regardless of the current working directory.

## SDK Session Store Protocol

Reference: https://code.claude.com/docs/en/agent-sdk/session-storage

The `SessionStore` protocol has two required methods and three optional:

| Method             | Required | Purpose                                        |
|--------------------|----------|------------------------------------------------|
| `append(key, entries)` | Yes  | Mirror transcript entries during a query       |
| `load(key)`        | Yes      | Load entries for resume                        |
| `delete(key)`      | No       | Delete a session (cascade to subagents)        |
| `list_sessions()`  | No       | List sessions by project_key                   |
| `list_subkeys()`   | No       | List subagent transcripts for resume           |

`SessionKey` is a TypedDict with `project_key` (str), `session_id` (str),
and optional `subpath` (str, e.g., `subagents/agent-<id>`).

`SessionStoreEntry` is an opaque JSON-safe dict. Entries must round-trip
through `json.dumps`/`json.loads` as deep-equal (byte-equal serialization
not required).

### Dual-write architecture

The store is a mirror, not a replacement. The subprocess always writes to
local disk first; the SDK then forwards each batch to `append()`. In
Python there is no way to disable local writes (`persistSession: false` is
TypeScript-only).

On resume with a session store present:
1. SDK calls `store.load(key)` to get entries.
2. SDK writes them to a temporary JSONL file.
3. Subprocess spawns and resumes from that temp file.
4. During the turn, subprocess writes new entries to local disk.
5. SDK mirrors those entries to `store.append()`.

### Append cadence

`append()` is called at ~100ms cadence during active turns. Failed appends
are retried (3 attempts) with short backoff, then dropped with a
`mirror_error` message emitted to the iterator. Appends must not block the
agent.

## Scope

Implement: `append`, `load`, `delete`, plus a DraftCircle-specific
`flush()` method.

Not implemented: `list_sessions`, `list_subkeys`,
`list_session_summaries`. DraftCircle uses explicit `resume` with a
session ID (not `continue_conversation`), and does not use subagents.

## Design

### GitSessionStore class

New file: `backend/git_session_store.py`

```python
class GitSessionStore:
    def __init__(self, git: GitStore, draftcircle_session_id: str):
        self._git = git
        self._dc_session_id = draftcircle_session_id
        self._pending: dict[str, list[SessionStoreEntry]] = {}
```

**Constructor** — scoped to one DraftCircle session. Lightweight: holds a
reference to the shared GitStore and the session ID string. A new instance
is created per `_run_query()` call since `ClaudeAgentOptions` is already
per-call.

**Parameters:**
- `git` — the shared GitStore instance for the data repo.
- `draftcircle_session_id` — the DraftCircle session ID (e.g.,
  `jira-feature-20260430-093000`), determines the storage directory.

### File layout in the data repo

```
sessions/<dc-session-id>/
  agent/
    transcript.jsonl                        # main transcript
    subagents/agent-<id>.jsonl              # subagent transcripts (if any)
```

Files use JSONL format (one JSON object per line), matching the SDK's
native on-disk format.

### Path mapping

`_entry_path(key: SessionKey) -> str`:
- No subpath: `sessions/<dc-id>/agent/transcript.jsonl`
- With subpath: `sessions/<dc-id>/agent/<subpath>.jsonl`

The `project_key` and `session_id` from the SessionKey are not used in the
file path because the store is already scoped to one DraftCircle session.

### append(key, entries)

Buffers entries in `self._pending`, keyed by file path. Pure memory
operation — never fails, never does I/O.

```python
async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
    path = self._entry_path(key)
    self._pending.setdefault(path, []).extend(entries)
```

### load(key)

Reads the JSONL file from the data repo via `GitStore.read_file()`. Parses
each non-empty line as JSON. Returns `None` if the file does not exist
(SDK treats this as "session unknown" and starts fresh).

```python
async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
    path = self._entry_path(key)
    content = self._git.read_file(path)
    if content is None:
        return None
    entries = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries or None
```

### delete(key)

If the key has a `subpath`, deletes that one file. If no `subpath` (main
transcript), cascades: deletes `transcript.jsonl` and all files under the
`agent/` directory.

Uses a new `GitStore.delete_files()` method (see below).

```python
async def delete(self, key: SessionKey) -> None:
    subpath = key.get("subpath")
    if subpath:
        path = self._entry_path(key)
        if self._git.file_exists(path):
            self._git.delete_files(
                f"agent: delete transcript {subpath}", [path]
            )
    else:
        agent_dir = self._agent_dir()
        all_files = []
        for name in self._git.list_directory(agent_dir):
            child = f"{agent_dir}/{name}"
            if self._git.file_exists(child):
                all_files.append(child)
            else:
                for sub in self._git.list_directory(child):
                    sub_path = f"{child}/{sub}"
                    if self._git.file_exists(sub_path):
                        all_files.append(sub_path)
        if all_files:
            self._git.delete_files(
                f"agent: delete all transcripts for {self._dc_session_id}",
                all_files,
            )
```

### flush()

DraftCircle-specific method, not part of the SessionStore protocol.
Called by the orchestrator after `query()` completes.

For each file path with pending entries:
1. Read existing content from the data repo (if any).
2. Append buffered entries as JSONL lines.
3. Write the full file content.

All files are committed in a single git commit. Returns the commit SHA,
or `None` if nothing was buffered.

```python
def flush(self) -> str | None:
    if not self._pending:
        return None
    files = {}
    for path, entries in self._pending.items():
        existing = self._git.read_file(path) or ""
        new_lines = [json.dumps(e, separators=(",", ":")) for e in entries]
        content = existing
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(new_lines) + "\n"
        files[path] = content
    self._pending.clear()
    return self._git.commit(
        f"agent: flush transcript for {self._dc_session_id}", files
    )
```

### CLAUDE_CONFIG_DIR

Set `CLAUDE_CONFIG_DIR` to `<data-repo>/.claude-sdk/` via `options.env`.
This directs the SDK's local session file writes into the data repo
filesystem instead of `~/.claude/`. Benefits:

- Local files persist across server restarts on the same machine.
- No pollution of the user's home directory from a server process.
- Everything is co-located in the data repo.

These local files are **not** git-committed. GitStore only commits
explicitly named files, so untracked files in `.claude-sdk/` are safe.
Add `.claude-sdk/` to the data repo's `.gitignore` for extra safety.

The git-committed copy (via flush) remains the primary durable store.
The `.claude-sdk/` files are ephemeral scratch from the SDK's dual-write.

## Orchestrator Changes

### Constructor

```python
class AIOrchestrator:
    def __init__(self, git: GitStore, model: str = "claude-sonnet-4-6"):
        self._model = model
        self._git = git
        self._section_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
```

Gains a `git: GitStore` parameter to create scoped session stores.

### _run_query

Gains a `draftcircle_session_id: str` parameter. Creates a
`GitSessionStore` scoped to that session. Sets `CLAUDE_CONFIG_DIR` in
`options.env`. Calls `store.flush()` in a `finally` block.

```python
async def _run_query(
    self,
    prompt: str,
    system_prompt: str,
    draftcircle_session_id: str,
    agent_session_id: str | None = None,
    allowed_tools: list[str] | None = None,
) -> tuple[list, str | None]:
    store = GitSessionStore(self._git, draftcircle_session_id)
    config_dir = str(self._git.repo_path / ".claude-sdk")

    opts_kwargs: dict = {
        "system_prompt": system_prompt,
        "model": self._model,
        "max_turns": 3,
        "permission_mode": "bypassPermissions",
        "tools": [],
        "mcp_servers": {"draftcircle": DRAFT_SERVER},
        "session_store": store,
        "env": {"CLAUDE_CONFIG_DIR": config_dir},
    }
    if allowed_tools is not None:
        opts_kwargs["allowed_tools"] = allowed_tools
    if agent_session_id is not None:
        opts_kwargs["resume"] = agent_session_id

    opts = ClaudeAgentOptions(**opts_kwargs)

    content_blocks: list = []
    session_id: str | None = None

    try:
        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    content_blocks.append(block)
            elif isinstance(message, ResultMessage):
                session_id = message.session_id
    finally:
        store.flush()

    return content_blocks, session_id
```

### Stale session fallback

If the SDK raises on resume (session data corrupted, incompatible, or
missing from the store), catch the error, log a warning, and retry
`query()` without the `resume` parameter. The orchestrator starts a fresh
conversation and the new `agent_session_id` replaces the old one in
`session.json`.

```python
try:
    async for message in query(prompt=prompt, options=opts):
        ...
except ClaudeSDKError as exc:
    if agent_session_id is not None and "session" in str(exc).lower():
        logger.warning("Stale agent session %s, starting fresh", agent_session_id)
        opts_kwargs.pop("resume", None)
        opts = ClaudeAgentOptions(**opts_kwargs)
        async for message in query(prompt=prompt, options=opts):
            ...
    else:
        raise
finally:
    store.flush()
```

### Caller signature changes

**`generate_drafts`**: Add `draftcircle_session_id: str` parameter. Pass
it to `_run_query`. The first parameter (currently named `session_id` but
actually the agent session ID) is renamed to `agent_session_id` for
clarity.

**`process_comment`**: Already receives the DraftCircle session ID as
`session_id`. Thread it to `_run_query` as `draftcircle_session_id`.

## GitStore Extension

Add `delete_files` method to `backend/git_store.py`:

```python
def delete_files(self, message: str, paths: list[str]) -> str:
    for rel_path in paths:
        full_path = self._check_path(rel_path)
        if full_path.exists():
            full_path.unlink()

    index = self.repo.index
    index.read()
    for rel_path in paths:
        try:
            index.remove(rel_path)
        except KeyError:
            pass
    index.write()

    tree_oid = index.write_tree()
    sig = pygit2.Signature("DraftCircle", "draftcircle@localhost")
    parents = [self.repo.head.target] if not self.repo.head_is_unborn else []

    oid = self.repo.create_commit(
        "refs/heads/main", sig, sig, message, tree_oid, parents
    )
    return str(oid)
```

## main.py Wiring

Pass `git` to the orchestrator constructor:

```python
ai = AIOrchestrator(git=git)
```

Thread `draftcircle_session_id` through the draft generation and comment
processing calls. The DraftCircle session ID is already available at both
call sites (`session.id` for drafts, `session_id` for comments).

Add `.claude-sdk/` to the data repo's `.gitignore` on first app startup
if not already present.

## Testing

### SDK conformance suite

The SDK ships a conformance suite for session store adapters:

```python
from claude_agent_sdk.testing import run_session_store_conformance

@pytest.mark.asyncio
async def test_git_session_store_conformance(tmp_path):
    git = GitStore(tmp_path / "data-repo")
    git.commit("init", {"sessions/test-session/session.json": "{}"})

    async def factory():
        return GitSessionStore(git, "test-session")

    await run_session_store_conformance(factory)
```

This validates the behavioral contract for `append`, `load`, and `delete`.
The conformance suite may require a factory callable rather than a bare
class; the factory creates a properly-scoped store instance backed by a
real git repo. The exact factory signature should be verified against the
SDK's conformance API at implementation time.

### Unit tests for GitSessionStore

- **append + flush + load round-trip**: Append entries, flush, then load.
  Verify entries are deep-equal to what was appended.
- **flush creates a single git commit**: Append multiple batches, flush
  once. Verify one commit with all JSONL files.
- **flush with existing data**: Load → append → flush → load. Verify
  entries are concatenated correctly.
- **flush with no pending entries**: Returns `None`, no commit created.
- **load returns None for missing file**: New session with no prior
  transcript.
- **delete main transcript**: Cascades to subagent files.
- **delete specific subpath**: Removes only that file.
- **subpath mapping**: Verify `_entry_path` produces correct paths for
  main and subagent keys.

### Unit tests for GitStore.delete_files

- Delete a single tracked file.
- Delete multiple files in one commit.
- Delete a file that doesn't exist (no-op, no error).

### Orchestrator tests

- Verify `session_store` is set on `ClaudeAgentOptions`.
- Verify `CLAUDE_CONFIG_DIR` is set in `options.env`.
- Verify `flush()` is called even when the query raises.
- Verify stale session fallback: mock the SDK to raise on resume, verify
  retry without resume succeeds.

## Files Changed

| File | Change |
|------|--------|
| `backend/git_session_store.py` | New — GitSessionStore class |
| `backend/git_store.py` | Add `delete_files` method |
| `backend/ai_orchestrator.py` | Add `git` param, create scoped store per query, flush in finally, stale session fallback |
| `backend/main.py` | Pass `git` to AIOrchestrator, thread session IDs to callers |
| `tests/test_git_session_store.py` | New — unit tests + conformance suite |
| `tests/test_git_store.py` | Add tests for `delete_files` |
| `tests/test_ai_orchestrator.py` | Update for new constructor and method signatures |
| `tests/test_api_ai.py` | Update for new AIOrchestrator constructor |
