"""新增工具（web_search, current_time）的单元测试。"""

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_current_time_returns_formatted_time():
    """current_time 工具应返回格式化的当前时间字符串。"""
    from my_small_agent.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(timezone="Asia/Shanghai")
    result = await tool.execute()

    # 验证返回格式包含年份和时间信息
    assert "202" in result  # 年份
    assert ":" in result    # 时间
    assert tool.name == "current_time"
    assert tool.danger_level == "safe"


@pytest.mark.asyncio
async def test_current_time_respects_timezone():
    """current_time 工具应尊重传入的时区配置。"""
    from my_small_agent.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(timezone="UTC")
    result = await tool.execute()
    assert "UTC" in result


@pytest.mark.asyncio
async def test_web_search_tool_metadata():
    """web_search 工具的元数据应正确设置。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()
    assert tool.name == "web_search"
    assert tool.danger_level == "safe"
    assert "query" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_web_search_formats_results():
    """web_search 工具应格式化搜索结果。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()

    mock_results = [
        {"title": "Result 1", "href": "https://example.com/1", "body": "First result"},
        {"title": "Result 2", "href": "https://example.com/2", "body": "Second result"},
    ]

    with patch("my_small_agent.tools.web_search.DDGS") as MockDDGS:
        mock_instance = MockDDGS.return_value
        mock_instance.text.return_value = mock_results

        result = await tool.execute(query="test query", max_results=2)

    assert "Result 1" in result
    assert "https://example.com/1" in result
    assert "Result 2" in result


@pytest.mark.asyncio
async def test_web_search_handles_no_results():
    """web_search 工具在无结果时应返回提示。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()

    with patch("my_small_agent.tools.web_search.DDGS") as MockDDGS:
        mock_instance = MockDDGS.return_value
        mock_instance.text.return_value = []

        result = await tool.execute(query="nonexistent query")

    assert "No results found" in result
