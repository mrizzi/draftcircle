import pytest

from backend.git_store import GitStore
from backend.models import User
from backend.user_registry import UserRegistryManager


@pytest.fixture()
def registry(populated_data_repo):
    git = GitStore(populated_data_repo)
    git.commit(
        "init users", {"users.json": (populated_data_repo / "users.json").read_text()}
    )
    return UserRegistryManager(git)


class TestListUsers:
    def test_returns_all_users(self, registry):
        users = registry.list_users()
        assert len(users) == 2
        ids = [u.id for u in users]
        assert "alice" in ids
        assert "bob" in ids

    def test_empty_when_no_file(self, data_repo):
        git = GitStore(data_repo)
        reg = UserRegistryManager(git)
        assert reg.list_users() == []


class TestGetUser:
    def test_returns_user_by_id(self, registry):
        user = registry.get_user("alice")
        assert user.name == "Alice Chen"

    def test_returns_none_for_missing(self, registry):
        assert registry.get_user("nobody") is None


class TestAddUser:
    def test_adds_new_user(self, registry):
        user = User(
            id="carol",
            name="Carol Davis",
            email="carol@example.com",
            default_roles=["tech-writer"],
        )
        registry.add_user(user)
        assert registry.get_user("carol") is not None
        assert len(registry.list_users()) == 3

    def test_rejects_duplicate_id(self, registry):
        user = User(id="alice", name="Dup", email="d@e.com")
        with pytest.raises(ValueError, match="already exists"):
            registry.add_user(user)
