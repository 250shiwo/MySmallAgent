"""Agent 流式对话循环的单元测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry


@pytest.fixture
def agent_setup():
    """创建测试用的 Agent 实例。"""
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    return agent


@pytest.mark.asyncio
async def test_run_turn_stream_text_response(agent_setup):
    """流式模式下，纯文本响应应 yield content 事件。"""
    agent = agent_setup

    # 模拟流式 chunk
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = "Hello"
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].delta.reasoning_content = None

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = " World"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].delta.reasoning_content = None

    # 模拟异步迭代器
    async def mock_stream():
        for chunk in [chunk1, chunk2]:
            yield chunk

    agent.llm.chat_stream = AsyncMock(return_value=mock_stream())

    events = []
    async for event_type, content in agent.run_turn_stream("hi", AsyncMock()):
        events.append((event_type, content))

    assert ("content", "Hello") in events
    assert ("content", " World") in events


@pytest.mark.asyncio
async def test_run_turn_stream_thinking_events(agent_setup):
    """流式模式下，thinking 内容应 yield thinking 事件。"""
    agent = agent_setup

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = None
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].delta.reasoning_content = "Let me think"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = "Answer"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].delta.reasoning_content = None

    async def mock_stream():
        for chunk in [chunk1, chunk2]:
            yield chunk

    agent.llm.chat_stream = AsyncMock(return_value=mock_stream())

    events = []
    async for event_type, content in agent.run_turn_stream("hi", AsyncMock()):
        events.append((event_type, content))

    assert ("thinking", "Let me think") in events
    assert ("content", "Answer") in events
