import json
from pathlib import Path

from backend.models import Template


class TemplateLoader:
    def __init__(self, data_repo_path: str | Path):
        self.templates_dir = Path(data_repo_path) / "templates"

    def list_templates(self) -> list[Template]:
        if not self.templates_dir.is_dir():
            return []
        templates = []
        for path in sorted(self.templates_dir.glob("*.json")):
            data = json.loads(path.read_text())
            template = Template.model_validate(data)
            template.slug = path.stem
            templates.append(template)
        return templates

    def get_template(self, slug: str) -> Template | None:
        path = (self.templates_dir / f"{slug}.json").resolve()
        if not path.is_relative_to(self.templates_dir.resolve()):
            return None
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return Template.model_validate(data)
