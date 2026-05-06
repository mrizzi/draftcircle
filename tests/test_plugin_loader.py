import pytest

from backend.plugin_loader import load_plugin, validate_plugin_config
from backend.plugins.base import OutputPlugin
from backend.plugins.jira_feature import JiraFeaturePlugin
from backend.plugins.markdown import MarkdownPlugin


class TestOutputPluginInterface:
    def test_markdown_plugin_implements_interface(self):
        plugin = MarkdownPlugin()
        assert isinstance(plugin, OutputPlugin)

    def test_markdown_assemble(self):
        plugin = MarkdownPlugin()
        sections = [
            {"title": "Overview", "content": "This is the overview."},
            {"title": "Details", "content": "These are details."},
        ]
        result = plugin.assemble(sections)
        assert "# Overview" in result
        assert "This is the overview." in result
        assert "# Details" in result


class TestPluginLoader:
    def test_loads_builtin_plugin(self):
        plugin = load_plugin("markdown")
        assert isinstance(plugin, MarkdownPlugin)

    def test_custom_plugin_overrides_builtin(self, tmp_path):
        custom_dir = tmp_path / "plugins"
        custom_dir.mkdir()
        (custom_dir / "markdown.py").write_text(
            "from backend.plugins.base import OutputPlugin\n\n"
            "class Plugin(OutputPlugin):\n"
            "    def assemble(self, sections): return 'custom'\n"
            "    def publish(self, output, config): return 'custom-ref'\n"
        )
        plugin = load_plugin("markdown", custom_plugins_dir=custom_dir)
        assert plugin.assemble([]) == "custom"

    def test_raises_for_unknown_plugin(self):
        with pytest.raises(ValueError, match="not found"):
            load_plugin("nonexistent")

    def test_rejects_traversal_in_plugin_name(self):
        with pytest.raises(ValueError, match="Invalid plugin name"):
            load_plugin("../evil")

    def test_rejects_hyphens_in_plugin_name(self):
        with pytest.raises(ValueError, match="Invalid plugin name"):
            load_plugin("my-plugin")


class TestJiraPluginLoading:
    def test_loads_jira_feature_plugin(self):
        plugin = load_plugin("jira_feature")
        assert isinstance(plugin, JiraFeaturePlugin)


class TestPluginDownloadFlag:
    def test_default_download_is_false(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        assert plugin.download is False


class TestMarkdownPluginDownload:
    def test_download_flag_is_true(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert plugin.download is True

    def test_publish_returns_content_unchanged(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        content = "# Title\n\nSome content."
        result = plugin.publish(content, {})
        assert result == content

    def test_assemble_concatenates_sections(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        sections = [
            {"title": "Overview", "content": "First section."},
            {"title": "Details", "content": "Second section."},
        ]
        result = plugin.assemble(sections)
        assert result == "# Overview\n\nFirst section.\n\n# Details\n\nSecond section."


class TestPluginConfigSchema:
    def test_base_plugin_has_empty_config_schema(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert hasattr(plugin, "config_schema")

    def test_default_config_schema_is_empty_list(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert isinstance(plugin.config_schema, list)


class TestJiraConfigSchema:
    def test_jira_has_config_schema(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        assert len(plugin.config_schema) == 3

    def test_jira_project_key_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[0]
        assert field["name"] == "project_key"
        assert field["type"] == "text"
        assert field["required"] is True

    def test_jira_summary_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[1]
        assert field["name"] == "summary"
        assert field["type"] == "text"
        assert field["default"] == "DraftCircle Document"

    def test_jira_labels_field(self):
        from backend.plugins.jira_feature import JiraFeaturePlugin

        plugin = JiraFeaturePlugin()
        field = plugin.config_schema[2]
        assert field["name"] == "labels"
        assert field["type"] == "list"


class TestMarkdownConfigSchema:
    def test_markdown_has_config_schema(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        assert len(plugin.config_schema) == 1

    def test_markdown_filename_field(self):
        from backend.plugins.markdown import Plugin

        plugin = Plugin()
        field = plugin.config_schema[0]
        assert field["name"] == "filename"
        assert field["type"] == "text"
        assert field["default"] == "document.md"


class TestValidatePluginConfig:
    def test_passes_when_required_fields_present(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": "PROJ"})
        assert errors == []

    def test_fails_when_required_field_missing(self):
        schema = [
            {
                "name": "project_key",
                "type": "text",
                "label": "Project Key",
                "required": True,
            },
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 1
        assert "project_key" in errors[0]

    def test_fails_when_required_field_is_empty_string(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": ""})
        assert len(errors) == 1

    def test_fails_when_required_field_is_none(self):
        schema = [
            {"name": "project_key", "type": "text", "label": "PK", "required": True},
        ]
        errors = validate_plugin_config(schema, {"project_key": None})
        assert len(errors) == 1

    def test_fails_when_required_list_field_is_empty(self):
        schema = [
            {"name": "tags", "type": "list", "label": "Tags", "required": True},
        ]
        errors = validate_plugin_config(schema, {"tags": []})
        assert len(errors) == 1

    def test_passes_when_optional_field_missing(self):
        schema = [
            {"name": "summary", "type": "text", "label": "Summary"},
        ]
        errors = validate_plugin_config(schema, {})
        assert errors == []

    def test_passes_with_empty_schema(self):
        errors = validate_plugin_config([], {"anything": "goes"})
        assert errors == []

    def test_collects_multiple_errors(self):
        schema = [
            {"name": "a", "type": "text", "label": "A", "required": True},
            {"name": "b", "type": "text", "label": "B", "required": True},
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 2

    def test_rejects_invalid_field_name(self):
        schema = [
            {"name": 'x"][onclick="alert', "type": "text", "label": "X"},
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 1
        assert "Invalid field name" in errors[0]

    def test_rejects_field_name_with_special_chars(self):
        schema = [
            {"name": "field-name", "type": "text", "label": "F"},
        ]
        errors = validate_plugin_config(schema, {})
        assert len(errors) == 1
