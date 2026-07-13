"""Tests for tool base class and registry."""

import pytest

from my_small_agent.tools.base import Tool
from my_small_agent.tools import ToolRegistry


class MockTool(Tool):
    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Test input"},
        },
        "required": ["input"],
    }
    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        return f"mock result: {kwargs.get('input', '')}"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.tool = MockTool()

    def test_register_and_get(self):
        self.registry.register(self.tool)
        retrieved = self.registry.get("mock_tool")
        assert retrieved is self.tool

    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_list_all(self):
        self.registry.register(self.tool)
        tools = self.registry.list_all()
        assert len(tools) == 1
        assert tools[0].name == "mock_tool"

    def test_get_openai_tools_format(self):
        self.registry.register(self.tool)
        openai_tools = self.registry.get_openai_tools()
        assert len(openai_tools) == 1
        tool_def = openai_tools[0]
        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "mock_tool"
        assert tool_def["function"]["description"] == "A mock tool for testing"
        assert tool_def["function"]["parameters"] == self.tool.parameters

    @pytest.mark.asyncio
    async def test_tool_execute(self):
        result = await self.tool.execute(input="hello")
        assert result == "mock result: hello"
