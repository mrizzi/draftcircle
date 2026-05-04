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
        first_item_text = lists[0]["content"][0]["content"][0]["content"][0]["text"]
        assert first_item_text == "Item one"

    def test_converts_asterisk_bullet_list(self):
        plugin = JiraFeaturePlugin()
        sections = [
            {"title": "Reqs", "content": "* Item A\n* Item B"},
        ]
        adf = json.loads(plugin.assemble(sections))
        lists = [node for node in adf["content"] if node["type"] == "bulletList"]
        assert len(lists) == 1
        assert len(lists[0]["content"]) == 2

    def test_handles_empty_content(self):
        plugin = JiraFeaturePlugin()
        sections = [{"title": "Empty", "content": ""}]
        adf = json.loads(plugin.assemble(sections))
        assert adf["type"] == "doc"
        assert len(adf["content"]) == 1
        assert adf["content"][0]["type"] == "heading"

    def test_handles_empty_sections_list(self):
        plugin = JiraFeaturePlugin()
        adf = json.loads(plugin.assemble([]))
        assert adf["type"] == "doc"
        assert adf["content"] == []

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
        assert types == ["heading", "paragraph", "bulletList", "paragraph"]


class TestPublish:
    @pytest.fixture(autouse=True)
    def _set_jira_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://myorg.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")

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
                    "project_key": "PROJ",
                    "issue_type_id": "10001",
                    "summary": "New Feature: DraftCircle Test",
                    "labels": ["feature", "draftcircle"],
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
                {"project_key": "TEST"},
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
                    {"project_key": "PROJ"},
                )

    def test_raises_on_missing_project_key(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])
        with pytest.raises(ValueError, match="project_key"):
            plugin.publish(assembled, {})

    def test_raises_on_invalid_json_output(self):
        plugin = JiraFeaturePlugin()
        config = {"project_key": "P"}
        with pytest.raises(json.JSONDecodeError):
            plugin.publish("not valid json", config)

    def test_uses_default_config_values(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "P-1"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            plugin.publish(
                assembled,
                {"project_key": "P"},
            )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["fields"]["issuetype"]["id"] == "10001"
        assert payload["fields"]["summary"] == "DraftCircle Document"
        assert "labels" not in payload["fields"]

    def test_raises_on_connection_error(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        with patch(
            "backend.plugins.jira_feature.httpx.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(httpx.ConnectError):
                plugin.publish(
                    assembled,
                    {"project_key": "P"},
                )


class TestPublishEnvVars:
    def test_reads_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://env.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])

        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "ENV-1"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "backend.plugins.jira_feature.httpx.post", return_value=mock_response
        ) as mock_post:
            result = plugin.publish(assembled, {"project_key": "ENV"})

        assert result == "ENV-1"
        assert mock_post.call_args.kwargs["auth"] == ("env@example.com", "env-token")

    def test_raises_when_base_url_missing(self):
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])
        with pytest.raises(ValueError, match="JIRA_BASE_URL"):
            plugin.publish(assembled, {"project_key": "P"})

    def test_raises_when_email_missing(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
        plugin = JiraFeaturePlugin()
        assembled = plugin.assemble([{"title": "T", "content": "C"}])
        with pytest.raises(ValueError, match="JIRA_EMAIL"):
            plugin.publish(assembled, {"project_key": "P"})
