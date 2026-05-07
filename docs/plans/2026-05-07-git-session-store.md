# Git Session Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Claude Agent SDK session transcripts in the data repo so agent conversations survive server restarts and are portable across worktrees.

**Architecture:** A `GitSessionStore` implements the SDK's `SessionStore` protocol, buffering entries in memory during a query turn and flushing them to git in a single commit when the orchestrator signals turn-end. The store is scoped to one DraftCircle session and writes JSONL files under the session's `agent/` directory.

**Tech Stack:** Python, pygit2 (via GitStore), Claude Agent SDK (`SessionStore` protocol)

**Spec:** `docs/specs/2026-05-07-git-session-store-design.md`

---

### Task 1: Add `delete_files` to GitStore

**Files:**
- Modify: `backend/git_store.py` (add method after `commit`)
- Test: `tests/test_git_store.py`

- [ ] **Step 1: Write failing tests for `delete_files`**

Add a new test class at the end of `tests/test_git_store.py`:

```python
class TestDeleteFiles:
    def test_deletes_single_file(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"a.txt": "content"})
        sha = store.delete_files("remove a", ["a.txt"])
        assert len(sha) == 40
        assert store.read_file("a.txt") is None
        assert store.file_exists("a.txt") is False

    def test_deletes_multiple_files(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"a.txt": "a", "b.txt": "b", "c.txt": "c"})
        store.delete_files("remove a and b", ["a.txt", "b.txt"])
        assert store.read_file("a.txt") is None
        assert store.read_file("b.txt") is None
        assert store.read_file("c.txt") == "c"

    def test_deletes_nested_file(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"d/sub/file.txt": "content", "d/other.txt": "other"})
        store.delete_files("remove nested", ["d/sub/file.txt"])
        assert store.read_file("d/sub/file.txt") is None
        assert store.read_file("d/other.txt") == "other"

    def test_noop_for_missing_file(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"a.txt": "a"})
        sha = store.delete_files("remove missing", ["nonexistent.txt"])
        assert len(sha) == 40

    def test_rejects_path_traversal(self, data_repo):
        store = GitStore(data_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            store.delete_files("bad", ["../../etc/passwd"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_git_store.py::TestDeleteFiles -v`
Expected: FAIL with `AttributeError: 'GitStore' object has no attribute 'delete_files'`

- [ ] **Step 3: Implement `delete_files`**

Add this method to `backend/git_store.py` in the `GitStore` class, after the `commit` method (after line 50):

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

    parents = []
    if not self.repo.head_is_unborn:
        parents = [self.repo.head.target]

    oid = self.repo.create_commit(
        "refs/heads/main", sig, sig, message, tree_oid, parents
    )
    return str(oid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_git_store.py -v`
Expected: All tests PASS, including the new `TestDeleteFiles` class.

- [ ] **Step 5: Commit**

```bash
git add backend/git_store.py tests/test_git_store.py
git commit -m "feat: add delete_files to GitStore"
```

---

### Task 2: Implement GitSessionStore (append, load, flush)

**Files:**
- Create: `backend/git_session_store.py`
- Create: `tests/test_git_session_store.py`

- [ ] **Step 1: Write failing tests for append + flush + load round-trip**

Create `tests/test_git_session_store.py`:

```python
import json

import pytest

from backend.git_session_store import GitSessionStore
from backend.git_store import GitStore


def make_key(project_key="proj", session_id="sess-001", subpath=None):
    key = {"project_key": project_key, "session_id": session_id}
    if subpath is not None:
        key["subpath"] = subpath
    return key


def make_entries(*texts):
    return [{"type": "test", "uuid": f"uuid-{i}", "text": t} for i, t in enumerate(texts)]


class TestAppendFlushLoad:
    @pytest.mark.asyncio
    async def test_round_trip(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        key = make_key()
        entries = make_entries("hello", "world")

        await store.append(key, entries)
        store.flush()

        loaded = await store.load(key)
        assert loaded == entries

    @pytest.mark.asyncio
    async def test_multiple_appends_single_flush(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        key = make_key()

        await store.append(key, make_entries("batch1"))
        await store.append(key, make_entries("batch2"))
        store.flush()

        loaded = await store.load(key)
        assert len(loaded) == 2
        assert loaded[0]["text"] == "batch1"
        assert loaded[1]["text"] == "batch2"

    @pytest.mark.asyncio
    async def test_flush_appends_to_existing(self, data_repo):
        git = GitStore(data_repo)

        store1 = GitSessionStore(git, "test-session")
        key = make_key()
        await store1.append(key, make_entries("first"))
        store1.flush()

        store2 = GitSessionStore(git, "test-session")
        await store2.append(key, make_entries("second"))
        store2.flush()

        store3 = GitSessionStore(git, "test-session")
        loaded = await store3.load(key)
        assert len(loaded) == 2
        assert loaded[0]["text"] == "first"
        assert loaded[1]["text"] == "second"

    @pytest.mark.asyncio
    async def test_flush_no_pending_returns_none(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        assert store.flush() is None

    @pytest.mark.asyncio
    async def test_flush_returns_commit_sha(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        await store.append(make_key(), make_entries("e1"))
        sha = store.flush()
        assert sha is not None
        assert len(sha) == 40

    @pytest.mark.asyncio
    async def test_flush_single_commit_for_multiple_keys(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        main_key = make_key()
        sub_key = make_key(subpath="subagents/agent-42")

        await store.append(main_key, make_entries("main"))
        await store.append(sub_key, make_entries("sub"))
        store.flush()

        log = git.log()
        assert len(log) == 1
        assert "flush transcript" in log[0]["message"]


class TestLoad:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        result = await store.load(make_key())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_file(self, data_repo):
        git = GitStore(data_repo)
        git.commit("add empty", {"sessions/test-session/agent/transcript.jsonl": ""})
        store = GitSessionStore(git, "test-session")
        result = await store.load(make_key())
        assert result is None


class TestPathMapping:
    @pytest.mark.asyncio
    async def test_main_transcript_path(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "my-session")
        key = make_key()
        await store.append(key, make_entries("e"))
        store.flush()
        assert git.file_exists("sessions/my-session/agent/transcript.jsonl")

    @pytest.mark.asyncio
    async def test_subagent_path(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "my-session")
        key = make_key(subpath="subagents/agent-42")
        await store.append(key, make_entries("e"))
        store.flush()
        assert git.file_exists("sessions/my-session/agent/subagents/agent-42.jsonl")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_git_session_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.git_session_store'`

- [ ] **Step 3: Implement GitSessionStore**

Create `backend/git_session_store.py`:

```python
import json
import logging

from claude_agent_sdk import SessionKey, SessionStoreEntry

from backend.git_store import GitStore

logger = logging.getLogger(__name__)


class GitSessionStore:
    def __init__(self, git: GitStore, draftcircle_session_id: str):
        self._git = git
        self._dc_session_id = draftcircle_session_id
        self._pending: dict[str, list[SessionStoreEntry]] = {}

    def _agent_dir(self) -> str:
        return f"sessions/{self._dc_session_id}/agent"

    def _entry_path(self, key: SessionKey) -> str:
        subpath = key.get("subpath")
        if subpath:
            return f"{self._agent_dir()}/{subpath}.jsonl"
        return f"{self._agent_dir()}/transcript.jsonl"

    async def append(
        self, key: SessionKey, entries: list[SessionStoreEntry]
    ) -> None:
        path = self._entry_path(key)
        self._pending.setdefault(path, []).extend(entries)

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        path = self._entry_path(key)
        content = self._git.read_file(path)
        if content is None:
            return None
        entries: list[SessionStoreEntry] = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries or None

    def flush(self) -> str | None:
        if not self._pending:
            return None
        files: dict[str, str] = {}
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_git_session_store.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/git_session_store.py tests/test_git_session_store.py
git commit -m "feat: add GitSessionStore with append, load, flush"
```

---

### Task 3: Add `delete` to GitSessionStore

**Files:**
- Modify: `backend/git_session_store.py`
- Modify: `tests/test_git_session_store.py`

- [ ] **Step 1: Write failing tests for delete**

Add to `tests/test_git_session_store.py`:

```python
class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_main_transcript(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        key = make_key()
        await store.append(key, make_entries("hello"))
        store.flush()

        await store.delete(key)
        assert await store.load(key) is None

    @pytest.mark.asyncio
    async def test_delete_cascades_to_subagents(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        main_key = make_key()
        sub_key = make_key(subpath="subagents/agent-42")
        await store.append(main_key, make_entries("main"))
        await store.append(sub_key, make_entries("sub"))
        store.flush()

        await store.delete(main_key)
        assert await store.load(main_key) is None
        assert await store.load(sub_key) is None

    @pytest.mark.asyncio
    async def test_delete_specific_subpath(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        main_key = make_key()
        sub_key = make_key(subpath="subagents/agent-42")
        await store.append(main_key, make_entries("main"))
        await store.append(sub_key, make_entries("sub"))
        store.flush()

        await store.delete(sub_key)
        loaded_main = await store.load(main_key)
        assert loaded_main is not None
        assert await store.load(sub_key) is None

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "test-session")
        await store.delete(make_key())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_git_session_store.py::TestDelete -v`
Expected: FAIL with `AttributeError: 'GitSessionStore' object has no attribute 'delete'`

- [ ] **Step 3: Implement delete**

Add this method to `GitSessionStore` in `backend/git_session_store.py`, after `load`:

```python
async def delete(self, key: SessionKey) -> None:
    subpath = key.get("subpath")
    if subpath:
        path = self._entry_path(key)
        if self._git.file_exists(path):
            self._git.delete_files(
                f"agent: delete transcript {subpath}",
                [path],
            )
        return

    agent_dir = self._agent_dir()
    all_files: list[str] = []
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_git_session_store.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/git_session_store.py tests/test_git_session_store.py
git commit -m "feat: add delete to GitSessionStore"
```

---

### Task 4: Run SDK conformance suite

**Files:**
- Modify: `tests/test_git_session_store.py`

- [ ] **Step 1: Add conformance test**

Add to the end of `tests/test_git_session_store.py`:

```python
from claude_agent_sdk.testing import run_session_store_conformance


class TestConformance:
    @pytest.mark.asyncio
    async def test_sdk_conformance(self, data_repo):
        git = GitStore(data_repo)

        def make_store():
            return GitSessionStore(git, "conformance-session")

        await run_session_store_conformance(
            make_store,
            skip_optional=frozenset(
                {"list_sessions", "list_subkeys", "list_session_summaries"}
            ),
        )
```

- [ ] **Step 2: Run conformance test**

Run: `pytest tests/test_git_session_store.py::TestConformance -v`
Expected: PASS. If any conformance assertions fail, fix the store implementation and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_git_session_store.py
git commit -m "test: add SDK conformance suite for GitSessionStore"
```

---

### Task 5: Wire GitSessionStore into AIOrchestrator

**Files:**
- Modify: `backend/ai_orchestrator.py`
- Modify: `tests/test_ai_orchestrator.py`

- [ ] **Step 1: Write failing tests for orchestrator changes**

Update `tests/test_ai_orchestrator.py`. First, update the import and add a `data_repo` fixture usage. Replace the `TestGenerateDrafts` and `TestProcessComment` classes with versions that pass a `GitStore` and verify session store behavior.

Add these new tests at the end of the file (before `TestResultDataclasses`):

```python
from backend.git_store import GitStore


class TestSessionStoreIntegration:
    @pytest.mark.asyncio
    async def test_run_query_sets_session_store(self, data_repo):
        git = GitStore(data_repo)
        orchestrator = AIOrchestrator(git=git)
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
                session_id="sess-001",
            )
            await orchestrator.generate_drafts(
                draftcircle_session_id="test-session",
                agent_session_id=None,
                template=template,
                seed_content="Seed.",
            )

            opts = mock_query.call_args.kwargs["options"]
            assert opts.session_store is not None
            assert opts.env.get("CLAUDE_CONFIG_DIR") is not None

    @pytest.mark.asyncio
    async def test_run_query_sets_resume(self, data_repo):
        git = GitStore(data_repo)
        orchestrator = AIOrchestrator(git=git)
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )
            await orchestrator.generate_drafts(
                draftcircle_session_id="test-session",
                agent_session_id="existing-session-42",
                template=template,
                seed_content="Seed.",
            )

            opts = mock_query.call_args.kwargs["options"]
            assert opts.resume == "existing-session-42"

    @pytest.mark.asyncio
    async def test_flush_called_on_success(self, data_repo):
        git = GitStore(data_repo)
        orchestrator = AIOrchestrator(git=git)
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query, \
             patch("backend.git_session_store.GitSessionStore.flush") as mock_flush:
            mock_query.return_value = mock_agent_messages(
                tool_calls=[
                    (
                        "write_section_draft",
                        {"section_id": "overview", "content": "draft"},
                    ),
                ],
            )
            await orchestrator.generate_drafts(
                draftcircle_session_id="test-session",
                agent_session_id=None,
                template=template,
                seed_content="Seed.",
            )
            mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_called_on_error(self, data_repo):
        git = GitStore(data_repo)
        orchestrator = AIOrchestrator(git=git)
        template = Template.model_validate(SAMPLE_TEMPLATE)

        with patch("backend.ai_orchestrator.query") as mock_query, \
             patch("backend.git_session_store.GitSessionStore.flush") as mock_flush:
            mock_query.side_effect = RuntimeError("API down")

            with pytest.raises(RuntimeError):
                await orchestrator.generate_drafts(
                    draftcircle_session_id="test-session",
                    agent_session_id=None,
                    template=template,
                    seed_content="Seed.",
                )
            mock_flush.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_orchestrator.py::TestSessionStoreIntegration -v`
Expected: FAIL because `AIOrchestrator` doesn't accept `git` parameter yet.

- [ ] **Step 3: Update AIOrchestrator**

Replace the full content of `backend/ai_orchestrator.py`. Key changes:
- Constructor takes `git: GitStore`
- `_run_query` takes `draftcircle_session_id`, creates a scoped `GitSessionStore`, sets `CLAUDE_CONFIG_DIR` in env, flushes in `finally`
- `generate_drafts` parameter renamed from `session_id` to `agent_session_id`, adds `draftcircle_session_id`
- `process_comment` threads `draftcircle_session_id` (its existing `session_id` param) to `_run_query`
- Stale session fallback wraps query in try/except

```python
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    ToolUseBlock,
    query,
    create_sdk_mcp_server,
    tool,
)

from backend.git_session_store import GitSessionStore
from backend.git_store import GitStore
from backend.models import Template

logger = logging.getLogger(__name__)


@tool(
    name="write_section_draft",
    description="Write the initial draft for a document section",
    input_schema={
        "type": "object",
        "properties": {
            "section_id": {
                "type": "string",
                "description": "The section identifier",
            },
            "content": {
                "type": "string",
                "description": "The markdown content for this section",
            },
        },
        "required": ["section_id", "content"],
    },
)
async def write_section_draft(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


@tool(
    name="propose_revision",
    description="Propose a revision to the current section draft based on the comment",
    input_schema={
        "type": "object",
        "properties": {
            "revised_text": {
                "type": "string",
                "description": "The complete revised section draft",
            },
            "summary": {
                "type": "string",
                "description": "Brief explanation of what changed and why",
            },
        },
        "required": ["revised_text", "summary"],
    },
)
async def propose_revision(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


@tool(
    name="post_reply",
    description="Reply to the comment without changing the draft",
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The reply text",
            },
        },
        "required": ["text"],
    },
)
async def post_reply(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "Acknowledged."}]}


DRAFT_SERVER = create_sdk_mcp_server(
    name="draftcircle",
    tools=[write_section_draft, propose_revision, post_reply],
)


@dataclass(frozen=True)
class DraftResult:
    section_id: str
    content: str

    def __post_init__(self):
        if not self.section_id:
            raise ValueError("section_id must be non-empty")
        if not self.content:
            raise ValueError("content must be non-empty")


@dataclass(frozen=True)
class ProposalResult:
    revised_text: str
    summary: str

    def __post_init__(self):
        if not self.revised_text:
            raise ValueError("revised_text must be non-empty")
        if not self.summary:
            raise ValueError("summary must be non-empty")


@dataclass(frozen=True)
class ReplyResult:
    text: str

    def __post_init__(self):
        if not self.text:
            raise ValueError("text must be non-empty")


class AIOrchestrator:
    def __init__(self, git: GitStore, model: str = "claude-sonnet-4-6"):
        self._model = model
        self._git = git
        self._section_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
        except ClaudeSDKError as exc:
            if agent_session_id is not None and "session" in str(exc).lower():
                logger.warning(
                    "Stale agent session %s, starting fresh: %s",
                    agent_session_id,
                    exc,
                )
                opts_kwargs.pop("resume", None)
                opts = ClaudeAgentOptions(**opts_kwargs)
                async for message in query(prompt=prompt, options=opts):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            content_blocks.append(block)
                    elif isinstance(message, ResultMessage):
                        session_id = message.session_id
            else:
                raise
        finally:
            store.flush()

        return content_blocks, session_id

    async def generate_drafts(
        self,
        draftcircle_session_id: str,
        agent_session_id: str | None,
        template: Template,
        seed_content: str,
    ) -> tuple[list[DraftResult], str | None]:
        section_descriptions = []
        for i, section in enumerate(template.sections, start=1):
            section_descriptions.append(
                f"{i}. **{section.title}** (id: {section.id}) -- {section.guidance}"
            )
        sections_text = "\n".join(section_descriptions)

        prompt = (
            f"Here is the seed material for this document:\n\n"
            f"{seed_content}\n\n"
            f"Generate initial drafts for each of the following sections. "
            f"Call the write_section_draft tool once for each section.\n\n"
            f"{sections_text}"
        )

        content_blocks, result_session_id = await self._run_query(
            prompt=prompt,
            system_prompt=template.ai_context,
            draftcircle_session_id=draftcircle_session_id,
            agent_session_id=agent_session_id,
            allowed_tools=["mcp__draftcircle__write_section_draft"],
        )

        drafts = []
        for block in content_blocks:
            if isinstance(block, ToolUseBlock) and block.name.endswith(
                "write_section_draft"
            ):
                drafts.append(
                    DraftResult(
                        section_id=block.input["section_id"],
                        content=block.input["content"],
                    )
                )
        return drafts, result_session_id

    async def process_comment(
        self,
        session_id: str | None,
        section_id: str,
        section_title: str,
        section_guidance: str,
        current_draft: str,
        comment_thread: list[dict],
        new_comment_author: str,
        new_comment_text: str,
        system_prompt: str = "",
        agent_session_id: str | None = None,
    ) -> tuple[ProposalResult | ReplyResult, str | None]:
        lock_key = f"{session_id}:{section_id}"
        async with self._section_locks[lock_key]:
            thread_text = ""
            if comment_thread:
                lines = []
                for c in comment_thread:
                    lines.append(f"- **{c['author']}**: {c['text']}")
                thread_text = "Previous comments:\n" + "\n".join(lines) + "\n\n"

            prompt = (
                f'A comment has been posted on section "{section_title}".\n\n'
                f"Section guidance: {section_guidance}\n\n"
                f"Current draft:\n{current_draft}\n\n"
                f"{thread_text}"
                f"New comment by **{new_comment_author}**: {new_comment_text}\n\n"
                f"If this comment warrants a revision to the draft, use the "
                f"propose_revision tool with the complete revised draft. "
                f"If this is a question or discussion point that doesn't require "
                f"a draft change, use the post_reply tool."
            )

            content_blocks, result_session_id = await self._run_query(
                prompt=prompt,
                system_prompt=system_prompt,
                draftcircle_session_id=session_id or "unknown",
                agent_session_id=agent_session_id,
                allowed_tools=[
                    "mcp__draftcircle__propose_revision",
                    "mcp__draftcircle__post_reply",
                ],
            )

            for block in content_blocks:
                if not isinstance(block, ToolUseBlock):
                    continue
                if block.name.endswith("propose_revision"):
                    return (
                        ProposalResult(
                            revised_text=block.input["revised_text"],
                            summary=block.input["summary"],
                        ),
                        result_session_id,
                    )
                if block.name.endswith("post_reply"):
                    return ReplyResult(text=block.input["text"]), result_session_id

            return ReplyResult(text="I've noted your comment."), result_session_id
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest tests/test_ai_orchestrator.py::TestSessionStoreIntegration -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ai_orchestrator.py tests/test_ai_orchestrator.py
git commit -m "feat: wire GitSessionStore into AIOrchestrator"
```

---

### Task 6: Update existing orchestrator tests

**Files:**
- Modify: `tests/test_ai_orchestrator.py`

The existing `TestGenerateDrafts` and `TestProcessComment` tests construct `AIOrchestrator()` without `git`. They need updating to pass a `GitStore`.

- [ ] **Step 1: Update existing tests**

In `tests/test_ai_orchestrator.py`, add a fixture and update every `AIOrchestrator()` call:

Add this fixture near the top of the file (after the imports):

```python
@pytest.fixture()
def orchestrator(data_repo):
    git = GitStore(data_repo)
    return AIOrchestrator(git=git)
```

Then update every test in `TestGenerateDrafts` and `TestProcessComment`:

- Replace `orchestrator = AIOrchestrator()` with the `orchestrator` fixture parameter
- Replace `generate_drafts(session_id=None, ...)` calls with `generate_drafts(draftcircle_session_id="test-session", agent_session_id=None, ...)`
- Replace `generate_drafts(session_id=None, template=template, ...)` with `generate_drafts(draftcircle_session_id="test-session", agent_session_id=None, template=template, ...)`

For example, `test_generates_drafts` becomes:

```python
@pytest.mark.asyncio
async def test_generates_drafts(self, orchestrator):
    template = Template.model_validate(SAMPLE_TEMPLATE)

    with patch("backend.ai_orchestrator.query") as mock_query:
        mock_query.return_value = mock_agent_messages(
            tool_calls=[
                ("write_section_draft", {"section_id": "overview", "content": "# Overview\n\nDraft content."}),
                ("write_section_draft", {"section_id": "details", "content": "# Details\n\nMore content."}),
                ("write_section_draft", {"section_id": "notes", "content": "# Notes\n\nSome notes."}),
            ],
            session_id="sess-123",
        )
        drafts, sid = await orchestrator.generate_drafts(
            draftcircle_session_id="test-session",
            agent_session_id=None,
            template=template,
            seed_content="Feature X enables users to do Y.",
        )

    assert len(drafts) == 3
    assert drafts[0].section_id == "overview"
```

Apply the same pattern to all tests: use the `orchestrator` fixture, pass `draftcircle_session_id="test-session"`, rename `session_id` to `agent_session_id` in `generate_drafts` calls.

- [ ] **Step 2: Run all orchestrator tests**

Run: `pytest tests/test_ai_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ai_orchestrator.py
git commit -m "test: update orchestrator tests for new constructor signature"
```

---

### Task 7: Update main.py and API tests

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update main.py**

In `backend/main.py`, change the orchestrator construction to pass `git`:

Replace:

```python
ai = AIOrchestrator()
```

With:

```python
ai = AIOrchestrator(git=git)
```

Then update the `create_session` endpoint's `stream_drafts` function. Change:

```python
drafts, agent_session_id = await ai.generate_drafts(
    session_id=session.agent_session_id,
    template=template,
    seed_content=req.seed_text,
)
```

To:

```python
drafts, agent_session_id = await ai.generate_drafts(
    draftcircle_session_id=session.id,
    agent_session_id=session.agent_session_id,
    template=template,
    seed_content=req.seed_text,
)
```

- [ ] **Step 2: Run API AI tests**

Run: `pytest tests/test_api_ai.py -v`
Expected: All tests PASS. The `mock_query` patches bypass the session store, so no additional test changes needed here.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py tests/test_api_ai.py
git commit -m "feat: pass GitStore to AIOrchestrator in app wiring"
```

---

### Task 8: Format and lint

**Files:** All modified files.

- [ ] **Step 1: Format**

Run: `ruff format .`
Expected: No errors. Some files may be reformatted.

- [ ] **Step 2: Lint**

Run: `ruff check .`
Expected: No errors. Fix any issues if found.

- [ ] **Step 3: Run full test suite one final time**

Run: `pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration`
Expected: All tests PASS.

- [ ] **Step 4: Commit any formatting changes**

```bash
git add -u
git commit -m "style: format and lint"
```
