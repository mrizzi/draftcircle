import json

import pytest

from backend.plugins.jira_feature import JiraFeaturePlugin


class TestAssemble:
    def test_produces_valid_adf(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Feature Overview", "content": "This feature does X."},
            {"title": "Requirements", "content": "- Must do A\n- Must do B"},
        ]
        result = plugin.assemble(sections)
        adf = json.loads(result)
        assert adf["type"] == "doc"
        assert adf["version"] == 1

    def test_creates_heading_per_section(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Overview", "content": "Content A."},
            {"title": "Details", "content": "Content B."},
        ]
        adf = json.loads(plugin.assemble(sections))
        headings = [
            node for node in adf["content"] if node["type"] == "heading"
        ]
        assert len(headings) == 2
        assert headings[0]["content"][0]["text"] == "Overview"
        assert headings[1]["content"][0]["text"] == "Details"

    def test_converts_paragraphs(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Title", "content": "First paragraph.\n\nSecond paragraph."},
        ]
        adf = json.loads(plugin.assemble(sections))
        paragraphs = [
            node for node in adf["content"] if node["type"] == "paragraph"
        ]
        assert len(paragraphs) == 2
        assert paragraphs[0]["content"][0]["text"] == "First paragraph."

    def test_converts_bullet_list(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Reqs", "content": "- Item one\n- Item two\n- Item three"},
        ]
        adf = json.loads(plugin.assemble(sections))
        lists = [
            node for node in adf["content"] if node["type"] == "bulletList"
        ]
        assert len(lists) == 1
        assert len(lists[0]["content"]) == 3

    def test_handles_empty_content(self):
        plugin = JiraFeaturePlugin()
        sections = [{"title": "Empty", "content": ""}]
        adf = json.loads(plugin.assemble(sections))
        assert adf["type"] == "doc"

    def test_handles_mixed_content(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {
                "title": "Mixed",
                "content": "Intro paragraph.\n\n- Bullet 1\n- Bullet 2\n\nClosing paragraph.",
            },
        ]
        adf = json.loads(plugin.assemble(sections))
        types = [node["type"] for node in adf["content"]]
        assert "heading" in types
        assert "paragraph" in types
        assert "bulletList" in types
