import json
import os
from typing import Any

import httpx

from backend.models import SectionContent
from backend.plugins.base import OutputPlugin


def _text_node(text: str) -> dict:
    return {"type": "text", "text": text}


def _heading(text: str, level: int = 2) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [_text_node(text)],
    }


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [_text_node(text)]}


def _bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [_paragraph(item)],
            }
            for item in items
        ],
    }


def _markdown_to_adf_nodes(text: str) -> list[dict]:
    nodes = []
    lines = text.split("\n")
    bullet_buffer = []

    def flush_bullets():
        nonlocal bullet_buffer
        if bullet_buffer:
            nodes.append(_bullet_list(bullet_buffer))
            bullet_buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullet_buffer.append(stripped[2:])
        else:
            flush_bullets()
            if stripped:
                nodes.append(_paragraph(stripped))

    flush_bullets()
    return nodes


class JiraFeaturePlugin(OutputPlugin):
    def assemble(self, sections: list[SectionContent]) -> str:
        content = []
        for section in sections:
            content.append(_heading(section["title"]))
            if section["content"]:
                content.extend(_markdown_to_adf_nodes(section["content"]))

        adf = {"version": 1, "type": "doc", "content": content}
        return json.dumps(adf)

    def publish(self, output: str, config: dict[str, Any]) -> str:
        base_url = os.environ.get("JIRA_BASE_URL")
        email = os.environ.get("JIRA_EMAIL")
        api_token = os.environ.get("JIRA_API_TOKEN")

        for name, val in [
            ("JIRA_BASE_URL", base_url),
            ("JIRA_EMAIL", email),
            ("JIRA_API_TOKEN", api_token),
        ]:
            if not val:
                raise ValueError(f"Missing required environment variable: '{name}'")

        if "project_key" not in config:
            raise ValueError("Missing required config key: 'project_key'")

        base_url = base_url.rstrip("/")
        project_key = config["project_key"]
        issue_type_id = config.get("issue_type_id", "10001")
        summary = config.get("summary", "DraftCircle Document")
        labels = config.get("labels", [])

        adf = json.loads(output)

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": adf,
                "issuetype": {"id": issue_type_id},
            }
        }
        if labels:
            payload["fields"]["labels"] = labels

        resp = httpx.post(
            f"{base_url}/rest/api/3/issue",
            json=payload,
            auth=(email, api_token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            raise ValueError(
                f"Jira API returned {resp.status_code}: {resp.text[:200]}"
            ) from None
        issue_key = resp.json()["key"]
        return issue_key


Plugin = JiraFeaturePlugin
