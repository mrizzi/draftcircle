from datetime import datetime, timezone
from pathlib import Path

import pygit2


class GitStore:
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            self.repo_path.mkdir(parents=True)
        git_dir = self.repo_path / ".git"
        if git_dir.exists():
            self.repo = pygit2.Repository(str(self.repo_path))
        else:
            self.repo = pygit2.init_repository(str(self.repo_path))

    def _check_path(self, path: str) -> Path:
        resolved = (self.repo_path / path).resolve()
        if not resolved.is_relative_to(self.repo_path.resolve()):
            raise ValueError(f"Path '{path}' escapes repository")
        return resolved

    def _create_commit(self, message: str) -> str:
        tree_oid = self.repo.index.write_tree()
        sig = pygit2.Signature("DraftCircle", "draftcircle@localhost")
        parents = [] if self.repo.head_is_unborn else [self.repo.head.target]

        oid = self.repo.create_commit(
            "refs/heads/main", sig, sig, message, tree_oid, parents
        )

        if self.repo.head_is_unborn:
            self.repo.set_head("refs/heads/main")

        return str(oid)

    def commit(self, message: str, files: dict[str, str]) -> str:
        for rel_path, content in files.items():
            full_path = self._check_path(rel_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        index = self.repo.index
        index.read()
        for rel_path in files:
            index.add(rel_path)
        index.write()

        return self._create_commit(message)

    def delete_files(self, message: str, paths: list[str]) -> str:
        for rel_path in paths:
            full_path = self._check_path(rel_path)
            full_path.unlink(missing_ok=True)

        index = self.repo.index
        index.read()
        for rel_path in paths:
            try:
                index.remove(rel_path)
            except (KeyError, OSError):
                pass
        index.write()

        return self._create_commit(message)

    def read_file(self, path: str) -> str | None:
        full_path = self._check_path(path)
        if not full_path.exists():
            return None
        return full_path.read_text()

    def file_exists(self, path: str) -> bool:
        return self._check_path(path).exists()

    def list_directory(self, path: str) -> list[str]:
        target = self._check_path(path) if path else self.repo_path
        if not target.is_dir():
            return []
        return [e.name for e in target.iterdir() if not e.name.startswith(".")]

    def log(self, path: str | None = None, limit: int = 50) -> list[dict]:
        if self.repo.head_is_unborn:
            return []

        entries = []
        for commit in self.repo.walk(self.repo.head.target, pygit2.GIT_SORT_TIME):
            if len(entries) >= limit:
                break

            if path and commit.parents:
                parent_tree = commit.parents[0].tree
                diff = self.repo.diff(parent_tree, commit.tree)
                changed = {p.delta.new_file.path for p in diff}
                prefix = path + "/"
                if not any(f == path or f.startswith(prefix) for f in changed):
                    continue

            if path and not commit.parents:
                prefix = path + "/"
                all_paths = self._tree_paths(commit.tree)
                if not any(f == path or f.startswith(prefix) for f in all_paths):
                    continue

            entries.append(
                {
                    "sha": str(commit.id),
                    "message": commit.message.strip(),
                    "author": commit.author.name,
                    "timestamp": datetime.fromtimestamp(
                        commit.commit_time, tz=timezone.utc
                    ).isoformat(),
                }
            )

        return entries

    def _tree_paths(self, tree, prefix="") -> list[str]:
        paths = []
        for entry in tree:
            full = f"{prefix}{entry.name}" if not prefix else f"{prefix}/{entry.name}"
            if entry.type_str == "tree":
                subtree = self.repo.get(entry.id)
                paths.extend(self._tree_paths(subtree, full))
            else:
                paths.append(full)
        return paths
