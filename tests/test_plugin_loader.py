from pathlib import Path

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

    def test_markdown_publish_writes_file(self, tmp_path):
        plugin = MarkdownPlugin()
        content = "# Doc\n\nContent here."
        config = {
            "output_path": str(tmp_path / "output.md"),
            "allowed_dir": str(tmp_path),
        }
        ref = plugin.publish(content, config)
        assert Path(ref).exists()
        assert Path(ref).read_text() == content

    def test_markdown_publish_rejects_path_traversal(self, tmp_path):
        plugin = MarkdownPlugin()
        config = {
            "output_path": "/etc/evil.md",
            "allowed_dir": str(tmp_path),
        }
        with pytest.raises(ValueError, match="must be within"):
            plugin.publish("content", config)


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
