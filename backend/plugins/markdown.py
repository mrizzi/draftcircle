from pathlib import Path
from typing import Any

from backend.models import SectionContent
from backend.plugins.base import OutputPlugin


class Plugin(OutputPlugin):
    def assemble(self, sections: list[SectionContent]) -> str:
        parts = []
        for section in sections:
            parts.append(f"# {section['title']}\n\n{section['content']}")
        return "\n\n".join(parts)

    def publish(self, output: str, config: dict[str, Any]) -> str:
        path = Path(config["output_path"]).resolve()
        allowed_dir = Path(config.get("allowed_dir", "/tmp")).resolve()
        if not path.is_relative_to(allowed_dir):
            raise ValueError(f"output_path must be within {allowed_dir}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output)
        return str(path)


MarkdownPlugin = Plugin
