import pytest

from backend.template_loader import TemplateLoader


@pytest.fixture()
def loader(populated_data_repo):
    return TemplateLoader(populated_data_repo)


class TestListTemplates:
    def test_returns_available_templates(self, loader):
        templates = loader.list_templates()
        assert len(templates) == 1
        assert templates[0].name == "Test Template"
        assert templates[0].slug == "test-template"

    def test_empty_when_no_templates(self, data_repo):
        (data_repo / "templates").mkdir()
        loader = TemplateLoader(data_repo)
        assert loader.list_templates() == []


class TestGetTemplate:
    def test_returns_template_by_slug(self, loader):
        template = loader.get_template("test-template")
        assert template.name == "Test Template"
        assert template.slug == "test-template"
        assert len(template.sections) == 3

    def test_returns_none_for_missing(self, loader):
        assert loader.get_template("nonexistent") is None

    def test_returns_none_for_path_traversal(self, loader):
        assert loader.get_template("../../../etc/passwd") is None

    def test_sections_have_correct_fields(self, loader):
        template = loader.get_template("test-template")
        overview = template.sections[0]
        assert overview.id == "overview"
        assert overview.priority.value == "required"
        assert overview.suggested_roles == ["product-manager"]
