"""Abstract base class for all tools."""

from abc import ABC, abstractmethod


class Tool(ABC):
    """Base class for agent tools.

    Subclasses must define class attributes and implement execute().
    """

    name: str
    description: str
    parameters: dict
    danger_level: str  # "safe" | "dangerous"

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool with given arguments.

        Returns:
            A string representation of the result.
        """
