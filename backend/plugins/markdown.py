from typing import Any

from backend.models import SectionContent
from backend.plugins.base import OutputPlugin


class Plugin(OutputPlugin):
    download = True
    config_schema = [
        {
            "name": "filename",
            "type": "text",
            "label": "Filename",
            "default": "document.md",
        },
    ]

    def assemble(self, sections: list[SectionContent]) -> str:
        parts = []
        for section in sections:
            parts.append(f"# {section['title']}\n\n{section['content']}")
        return "\n\n".join(parts)

    def publish(self, output: str, config: dict[str, Any]) -> str:
        return output


MarkdownPlugin = Plugin
