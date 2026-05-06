import pytest

from backend.plugin_loader import load_plugin
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
        # Markdown plugin will get its own schema in Task 2,
        # but the base class default should be a list
        assert isinstance(plugin.config_schema, list)
