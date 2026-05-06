import importlib
import importlib.util
import re
from pathlib import Path
from typing import Any

from backend.plugins.base import OutputPlugin

_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_BUILTIN_DIR = Path(__file__).parent / "plugins"
_EXCLUDED = {"base", "__init__"}


def list_plugins(custom_plugins_dir: Path | None = None) -> list[str]:
    names: set[str] = set()
    for path in _BUILTIN_DIR.glob("*.py"):
        if path.stem not in _EXCLUDED:
            names.add(path.stem)
    if custom_plugins_dir and custom_plugins_dir.is_dir():
        for path in custom_plugins_dir.glob("*.py"):
            if _PLUGIN_NAME_RE.match(path.stem):
                names.add(path.stem)
    return sorted(names)


def load_plugin(name: str, custom_plugins_dir: Path | None = None) -> OutputPlugin:
    if not _PLUGIN_NAME_RE.match(name):
        raise ValueError(f"Invalid plugin name '{name}'")
    if custom_plugins_dir:
        custom_path = custom_plugins_dir / f"{name}.py"
        if custom_path.exists():
            spec = importlib.util.spec_from_file_location(
                f"custom_plugin_{name}", custom_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.Plugin()

    try:
        module = importlib.import_module(f"backend.plugins.{name}")
        return module.Plugin()
    except ModuleNotFoundError:
        raise ValueError(f"Plugin '{name}' not found")


_FIELD_NAME_RE = _PLUGIN_NAME_RE


def validate_plugin_config(
    schema: list[dict[str, Any]], config: dict[str, Any]
) -> list[str]:
    errors = []
    for field in schema:
        name = field["name"]
        if not _FIELD_NAME_RE.match(name):
            errors.append(f"Invalid field name: '{name}'")
            continue
        if not field.get("required"):
            continue
        value = config.get(name)
        if value is None or value == "" or value == []:
            errors.append(f"Field '{name}' is required")
    return errors
