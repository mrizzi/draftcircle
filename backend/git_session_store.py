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

    @staticmethod
    def _validate_key_segment(value: str, name: str) -> None:
        if ".." in value or value.startswith("/"):
            raise ValueError(f"SessionKey {name} contains unsafe path segment: {value}")

    def _entry_path(self, key: SessionKey) -> str:
        project_key = key["project_key"]
        session_id = key["session_id"]
        self._validate_key_segment(project_key, "project_key")
        self._validate_key_segment(session_id, "session_id")

        base_dir = self._agent_dir()
        key_prefix = f"{project_key}/{session_id}"

        subpath = key.get("subpath")
        if subpath:
            self._validate_key_segment(subpath, "subpath")
            return f"{base_dir}/{key_prefix}/{subpath}.jsonl"
        return f"{base_dir}/{key_prefix}/transcript.jsonl"

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        path = self._entry_path(key)
        self._pending.setdefault(path, []).extend(entries)

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        path = self._entry_path(key)
        entries: list[SessionStoreEntry] = []

        content = self._git.read_file(path)
        if content:
            for line in content.splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        pending = self._pending.get(path, [])
        entries.extend(pending)

        return entries or None

    async def delete(self, key: SessionKey) -> None:
        subpath = key.get("subpath")
        if subpath:
            path = self._entry_path(key)
            self._pending.pop(path, None)
            if self._git.file_exists(path):
                self._git.delete_files(
                    f"agent: delete transcript {subpath}",
                    [path],
                )
            return

        project_key = key["project_key"]
        session_id = key["session_id"]
        key_prefix = f"{project_key}/{session_id}"
        agent_dir = self._agent_dir()
        prefix_dir = f"{agent_dir}/{key_prefix}"

        paths_to_remove = [p for p in self._pending if p.startswith(prefix_dir + "/")]
        for p in paths_to_remove:
            del self._pending[p]

        all_files: list[str] = []
        for name in self._git.list_directory(prefix_dir):
            child = f"{prefix_dir}/{name}"
            child_contents = self._git.list_directory(child)
            if child_contents:
                all_files.extend(f"{child}/{sub}" for sub in child_contents)
            else:
                all_files.append(child)
        if all_files:
            self._git.delete_files(
                f"agent: delete all transcripts for {key_prefix}",
                all_files,
            )

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
