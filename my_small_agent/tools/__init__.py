"""Tool registry - central place to register and retrieve tools."""

from my_small_agent.tools.base import Tool
from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.shell_exec import ExecuteShellTool


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance by its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Retrieve a tool by name, or None if not found."""
        return self._tools.get(name)

    def get_openai_tools(self) -> list[dict]:
        """Convert all registered tools to OpenAI tools format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def list_all(self) -> list[Tool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())


def create_default_registry() -> ToolRegistry:
    """Create a registry with all built-in tools registered."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    return registry
