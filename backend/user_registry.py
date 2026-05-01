import json

from backend.git_store import GitStore
from backend.models import User, UserRegistry

USERS_PATH = "users.json"


class UserRegistryManager:
    def __init__(self, git: GitStore):
        self.git = git

    def _load(self) -> UserRegistry:
        content = self.git.read_file(USERS_PATH)
        if content is None:
            return UserRegistry(users=[])
        return UserRegistry.model_validate(json.loads(content))

    def _save(self, registry: UserRegistry, message: str) -> str:
        content = registry.model_dump_json(indent=2)
        return self.git.commit(message, {USERS_PATH: content})

    def list_users(self) -> list[User]:
        return self._load().users

    def get_user(self, user_id: str) -> User | None:
        for user in self._load().users:
            if user.id == user_id:
                return user
        return None

    def add_user(self, user: User) -> str:
        registry = self._load()
        if any(u.id == user.id for u in registry.users):
            raise ValueError(f"User '{user.id}' already exists")
        registry.users.append(user)
        return self._save(registry, f"user: add {user.id}")
