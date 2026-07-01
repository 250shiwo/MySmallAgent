"""组合工具测试 - ToolRegistry.dispatch 和 research_topic。"""

import json
import pytest

from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool
from my_small_agent.tools.research_topic import ResearchTopicTool


class MockSearchTool(Tool):
    """模拟 web_search 工具。"""
    name = "web_search"
    description = "Mock search"
    parameters = {"type": "object", "properties": {}, "required": []}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        return json.dumps({
            "results": [
                {"title": "Result 1", "href": "https://example.com/1", "body": "body1"},
                {"title": "Result 2", "href": "https://example.com/2", "body": "body2"},
            ]
        })


class MockFetchTool(Tool):
    """模拟 fetch_url 工具。"""
    name = "fetch_url"
    description = "Mock fetch"
    parameters = {"type": "object", "properties": {}, "required": []}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        url = kwargs.get("url", "")
        return f"Content from {url}"


class TestToolRegistryDispatch:
    """ToolRegistry.dispatch 方法测试。"""

    @pytest.mark.asyncio
    async def test_dispatch_existing_tool(self):
        registry = ToolRegistry()
        registry.register(MockSearchTool())
        result = await registry.dispatch("web_search", {"query": "test"})
        parsed = json.loads(result)
        assert "results" in parsed

    @pytest.mark.asyncio
    async def test_dispatch_nonexistent_tool(self):
        registry = ToolRegistry()
        result = await registry.dispatch("nonexist", {})
        parsed = json.loads(result)
        assert "error" in parsed


class TestResearchTopicTool:
    """research_topic 组合工具测试。"""

    @pytest.fixture
    def registry_with_mocks(self):
        registry = ToolRegistry()
        registry.register(MockSearchTool())
        registry.register(MockFetchTool())
        return registry

    @pytest.mark.asyncio
    async def test_research_topic_basic(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        result = await tool.execute(query="Python latest version")
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["query"] == "Python latest version"
        assert len(parsed["sources"]) == 2  # mock 返回 2 个结果，max_sources 默认 3

    @pytest.mark.asyncio
    async def test_research_topic_max_sources(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        result = await tool.execute(query="test", max_sources=1)
        parsed = json.loads(result)
        assert len(parsed["sources"]) == 1

    def test_tool_metadata(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        assert tool.name == "research_topic"
        assert tool.danger_level == "safe"
        assert "query" in tool.parameters["properties"]
