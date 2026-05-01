import json

import pygit2
import pytest


@pytest.fixture()
def data_repo(tmp_path):
    repo_path = tmp_path / "data"
    repo_path.mkdir()
    pygit2.init_repository(str(repo_path))
    return repo_path


SAMPLE_TEMPLATE = {
    "name": "Test Template",
    "description": "A test template with 3 sections",
    "output_plugin": "markdown",
    "ai_context": "You are helping write a test document.",
    "sections": [
        {
            "id": "overview",
            "title": "Overview",
            "priority": "required",
            "guidance": "Write an overview",
            "suggested_roles": ["product-manager"],
        },
        {
            "id": "details",
            "title": "Details",
            "priority": "recommended",
            "guidance": "Write the details",
            "suggested_roles": ["architect"],
        },
        {
            "id": "notes",
            "title": "Notes",
            "priority": "optional",
            "guidance": "Add any notes",
            "suggested_roles": [],
        },
    ],
}

SAMPLE_USERS = {
    "users": [
        {
            "id": "alice",
            "name": "Alice Chen",
            "email": "alice@example.com",
            "default_roles": ["product-manager"],
        },
        {
            "id": "bob",
            "name": "Bob Kumar",
            "email": "bob@example.com",
            "default_roles": ["architect"],
        },
    ]
}


@pytest.fixture()
def populated_data_repo(data_repo):
    templates_dir = data_repo / "templates"
    templates_dir.mkdir()
    (templates_dir / "test-template.json").write_text(
        json.dumps(SAMPLE_TEMPLATE, indent=2)
    )
    (data_repo / "users.json").write_text(json.dumps(SAMPLE_USERS, indent=2))
    return data_repo
