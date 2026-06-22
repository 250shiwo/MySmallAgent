"""Tests for agent conversation loop."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool


class MockSafeTool(Tool):
    name = "safe_tool"
    description = "A safe mock tool"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        return f"safe result: {kwargs['x']}"


class MockDangerousTool(Tool):
    name = "danger_tool"
    description = "A dangerous mock tool"
    parameters = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        return f"executed: {kwargs['cmd']}"


def make_text_response(content: str):
    """Create a mock ChatCompletion with text response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def make_tool_call_response(tool_name: str, arguments: dict):
    """Create a mock ChatCompletion with a single tool call."""
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }
        ],
    }

    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    return settings


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(MockSafeTool())
    reg.register(MockDangerousTool())
    return reg


class TestAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, mock_settings, registry):
        """Agent should return text when LLM responds with text."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("Hello!"))

        agent = Agent(llm, registry, mock_settings)
        result = await agent.run_turn("Hi", confirm_callback=AsyncMock(return_value=True))
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_safe_tool_auto_executes(self, mock_settings, registry):
        """Safe tools should execute without confirmation."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("safe_tool", {"x": "test"}),
                make_text_response("Done! Result was: safe result: test"),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=True)
        result = await agent.run_turn("Use the safe tool", confirm_callback=confirm)

        confirm.assert_not_called()  # safe tool should not ask
        assert "Done!" in result

    @pytest.mark.asyncio
    async def test_dangerous_tool_requires_confirmation(self, mock_settings, registry):
        """Dangerous tools should call confirm_callback before executing."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("danger_tool", {"cmd": "rm -rf /"}),
                make_text_response("Executed."),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=True)
        result = await agent.run_turn("Run danger", confirm_callback=confirm)

        confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_dangerous_tool_rejected(self, mock_settings, registry):
        """When user rejects dangerous tool, agent should report rejection."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("danger_tool", {"cmd": "rm -rf /"}),
                make_text_response("OK, I won't do that."),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=False)
        result = await agent.run_turn("Run danger", confirm_callback=confirm)
        assert "won't" in result.lower() or "ok" in result.lower()

    @pytest.mark.asyncio
    async def test_clear_history(self, mock_settings, registry):
        """clear_history should reset messages but keep system prompt."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("Hi"))

        agent = Agent(llm, registry, mock_settings)
        await agent.run_turn("Hello", confirm_callback=AsyncMock())

        assert len(agent.messages) > 1
        agent.clear_history()
        assert len(agent.messages) == 1
        assert agent.messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self, mock_settings, registry):
        """Agent should stop after max_iterations to prevent infinite loops."""
        mock_settings.max_iterations = 2
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            return_value=make_tool_call_response("safe_tool", {"x": "loop"})
        )

        agent = Agent(llm, registry, mock_settings)
        result = await agent.run_turn("loop forever", confirm_callback=AsyncMock())
        assert "maximum" in result.lower() or "iteration" in result.lower() or "limit" in result.lower()
