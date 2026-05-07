import pytest

from backend.git_store import GitStore


class TestGitStoreInit:
    def test_opens_existing_repo(self, data_repo):
        store = GitStore(data_repo)
        assert store.repo_path == data_repo

    def test_initializes_new_repo(self, tmp_path):
        repo_path = tmp_path / "new-repo"
        GitStore(repo_path)
        assert (repo_path / ".git").exists()


class TestCommitAndRead:
    def test_commit_creates_file_and_returns_sha(self, data_repo):
        store = GitStore(data_repo)
        sha = store.commit("test commit", {"hello.txt": "world"})
        assert len(sha) == 40

    def test_read_file_returns_committed_content(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add file", {"dir/file.txt": "content here"})
        assert store.read_file("dir/file.txt") == "content here"

    def test_read_file_returns_none_for_missing(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add file", {"a.txt": "a"})
        assert store.read_file("nonexistent.txt") is None

    def test_read_file_returns_none_on_empty_repo(self, data_repo):
        store = GitStore(data_repo)
        assert store.read_file("anything.txt") is None

    def test_multiple_commits_update_content(self, data_repo):
        store = GitStore(data_repo)
        store.commit("v1", {"file.txt": "version 1"})
        store.commit("v2", {"file.txt": "version 2"})
        assert store.read_file("file.txt") == "version 2"

    def test_commit_multiple_files(self, data_repo):
        store = GitStore(data_repo)
        store.commit("batch", {"a.txt": "aaa", "b.txt": "bbb"})
        assert store.read_file("a.txt") == "aaa"
        assert store.read_file("b.txt") == "bbb"


class TestListDirectory:
    def test_list_entries(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"d/a.txt": "a", "d/b.txt": "b", "root.txt": "r"})
        entries = store.list_directory("d")
        assert sorted(entries) == ["a.txt", "b.txt"]

    def test_list_root(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"a.txt": "a", "sub/b.txt": "b"})
        entries = store.list_directory("")
        assert "a.txt" in entries
        assert "sub" in entries

    def test_list_missing_directory(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"a.txt": "a"})
        assert store.list_directory("nonexistent") == []

    def test_list_empty_repo(self, data_repo):
        store = GitStore(data_repo)
        assert store.list_directory("") == []


class TestLog:
    def test_returns_commit_history(self, data_repo):
        store = GitStore(data_repo)
        store.commit("first", {"a.txt": "1"})
        store.commit("second", {"a.txt": "2"})
        entries = store.log()
        assert len(entries) == 2
        assert entries[0]["message"] == "second"
        assert entries[1]["message"] == "first"

    def test_log_empty_repo(self, data_repo):
        store = GitStore(data_repo)
        assert store.log() == []

    def test_log_with_path_filter(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add a", {"a.txt": "a"})
        store.commit("add b", {"b.txt": "b"})
        store.commit("update a", {"a.txt": "a2"})
        entries = store.log(path="a.txt")
        assert len(entries) == 2
        messages = [e["message"] for e in entries]
        assert "add a" in messages
        assert "update a" in messages

    def test_log_with_directory_prefix(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add session", {"sessions/s1/session.json": "{}"})
        store.commit("add other", {"other/file.txt": "x"})
        store.commit("update session", {"sessions/s1/sections/01.md": "text"})
        entries = store.log(path="sessions/s1")
        assert len(entries) == 2
        messages = [e["message"] for e in entries]
        assert "add session" in messages
        assert "update session" in messages

    def test_log_respects_limit(self, data_repo):
        store = GitStore(data_repo)
        for i in range(10):
            store.commit(f"commit {i}", {"f.txt": str(i)})
        entries = store.log(limit=3)
        assert len(entries) == 3


class TestFileExists:
    def test_exists(self, data_repo):
        store = GitStore(data_repo)
        store.commit("add", {"file.txt": "content"})
        assert store.file_exists("file.txt") is True
        assert store.file_exists("missing.txt") is False


class TestPathTraversal:
    def test_read_file_rejects_traversal(self, data_repo):
        store = GitStore(data_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            store.read_file("../outside.txt")

    def test_commit_rejects_traversal(self, data_repo):
        store = GitStore(data_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            store.commit("bad", {"../../escape.txt": "content"})

    def test_file_exists_rejects_traversal(self, data_repo):
        store = GitStore(data_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            store.file_exists("../../../etc/passwd")

    def test_list_directory_rejects_traversal(self, data_repo):
        store = GitStore(data_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            store.list_directory("../../")


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
