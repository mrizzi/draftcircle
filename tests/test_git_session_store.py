import pytest
from claude_agent_sdk.testing import run_session_store_conformance

from backend.git_session_store import GitSessionStore
from backend.git_store import GitStore


def make_key(project_key="proj", session_id="sess-001", subpath=None):
    key = {"project_key": project_key, "session_id": session_id}
    if subpath is not None:
        key["subpath"] = subpath
    return key


def make_entries(*texts):
    return [
        {"type": "test", "uuid": f"uuid-{i}", "text": t} for i, t in enumerate(texts)
    ]


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
        assert git.file_exists(
            "sessions/my-session/agent/proj/sess-001/transcript.jsonl"
        )

    @pytest.mark.asyncio
    async def test_subagent_path(self, data_repo):
        git = GitStore(data_repo)
        store = GitSessionStore(git, "my-session")
        key = make_key(subpath="subagents/agent-42")
        await store.append(key, make_entries("e"))
        store.flush()
        assert git.file_exists(
            "sessions/my-session/agent/proj/sess-001/subagents/agent-42.jsonl"
        )


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
