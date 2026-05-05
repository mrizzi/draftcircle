from abc import ABC, abstractmethod
from typing import Any

from backend.models import SectionContent


class OutputPlugin(ABC):
    download: bool = False

    @abstractmethod
    def assemble(self, sections: list[SectionContent]) -> str: ...

    @abstractmethod
    def publish(self, output: str, config: dict[str, Any]) -> str: ...
