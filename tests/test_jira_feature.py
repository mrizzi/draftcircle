import json
from unittest.mock import MagicMock, patch

import httpx
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
        headings = [node for node in adf["content"] if node["type"] == "heading"]
        assert len(headings) == 2
        assert headings[0]["content"][0]["text"] == "Overview"
        assert headings[1]["content"][0]["text"] == "Details"

    def test_converts_paragraphs(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Title", "content": "First paragraph.\n\nSecond paragraph."},
        ]
        adf = json.loads(plugin.assemble(sections))
        paragraphs = [node for node in adf["content"] if node["type"] == "paragraph"]
        assert len(paragraphs) == 2
        assert paragraphs[0]["content"][0]["text"] == "First paragraph."

    def test_converts_bullet_list(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Reqs", "content": "- Item one\n- Item two\n- Item three"},
        ]
        adf = json.loads(plugin.assemble(sections))
        lists = [node for node in adf["content"] if node["type"] == "bulletList"]
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


class TestPublish:
    def test_creates_jira_issue(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Overview", "content": "Feature description."},
        ]
        assembled = plugin.assemble(sections)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-123", "id": "10001"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            result = plugin.publish(
                assembled,
                {
                    "base_url": "https://myorg.atlassian.net",
                    "project_key": "PROJ",
                    "issue_type_id": "10001",
                    "summary": "New Feature: DraftCircle Test",
                    "labels": ["feature", "draftcircle"],
                    "email": "user@example.com",
                    "api_token": "secret-token",
                },
            )

        assert result == "PROJ-123"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.kwargs["auth"] == ("user@example.com", "secret-token")
        payload = call_args.kwargs["json"]
        assert payload["fields"]["project"]["key"] == "PROJ"
        assert payload["fields"]["summary"] == "New Feature: DraftCircle Test"
        assert payload["fields"]["labels"] == ["feature", "draftcircle"]
        assert payload["fields"]["description"]["type"] == "doc"

    def test_publishes_to_correct_url(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "TEST-1"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            plugin.publish(
                assembled,
                {
                    "base_url": "https://myorg.atlassian.net/",
                    "project_key": "TEST",
                    "email": "u@e.com",
                    "api_token": "tok",
                },
            )

        url = mock_post.call_args.args[0]
        assert url == "https://myorg.atlassian.net/rest/api/3/issue"

    def test_raises_on_api_error(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock()
        )

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ):
            with pytest.raises(httpx.HTTPStatusError):
                plugin.publish(
                    assembled,
                    {
                        "base_url": "https://myorg.atlassian.net",
                        "project_key": "PROJ",
                        "email": "u@e.com",
                        "api_token": "tok",
                    },
                )
