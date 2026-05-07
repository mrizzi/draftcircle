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
            child_contents = self._git.list_directory(child)
            if child_contents:
                for sub_name in child_contents:
                    sub_path = f"{child}/{sub_name}"
                    if self._git.file_exists(sub_path):
                        all_files.append(sub_path)
            else:
                if self._git.file_exists(child):
                    all_files.append(child)
        if all_files:
            self._git.delete_files(
                f"agent: delete all transcripts for {self._dc_session_id}",
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
