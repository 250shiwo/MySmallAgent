"""Integration tests - verify all components work together."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry, create_default_registry


def make_text_response(content: str):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def make_tool_call_response(tool_name: str, arguments: dict, call_id: str = "call_1"):
    tool_call = MagicMock()
    tool_call.id = call_id
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
                "id": call_id,
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
def settings():
    env = {"OPENAI_API_KEY": "sk-test", "MAX_ITERATIONS": "5"}
    with patch.dict(os.environ, env):
        return Settings(_env_file=None)


@pytest.fixture
def registry():
    return create_default_registry()


class TestIntegration:
    @pytest.mark.asyncio
    async def test_agent_reads_file(self, settings, registry, tmp_path):
        """Agent should be able to read a file via tool call."""
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello from file!")

        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("read_file", {"path": str(test_file)}),
                make_text_response("The file contains: Hello from file!"),
            ]
        )

        agent = Agent(llm, registry, settings)
        result = await agent.run_turn(
            "Read hello.txt", confirm_callback=AsyncMock(return_value=True)
        )
        assert "Hello from file!" in result

    @pytest.mark.asyncio
    async def test_agent_writes_file_with_confirmation(self, settings, registry, tmp_path):
        """Agent should ask confirmation before writing file."""
        output_file = tmp_path / "output.txt"

        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response(
                    "write_file",
                    {"path": str(output_file), "content": "new content"},
                ),
                make_text_response("File written successfully."),
            ]
        )

        confirm = AsyncMock(return_value=True)
        agent = Agent(llm, registry, settings)
        result = await agent.run_turn("Write to output.txt", confirm_callback=confirm)

        confirm.assert_called_once()
        assert output_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_registry_has_all_tools(self, registry):
        """Default registry should have all 4 built-in tools."""
        tools = registry.list_all()
        names = {t.name for t in tools}
        assert names == {"read_file", "write_file", "list_directory", "execute_shell"}

    @pytest.mark.asyncio
    async def test_openai_tools_format_valid(self, registry):
        """OpenAI tools format should be valid for API calls."""
        openai_tools = registry.get_openai_tools()
        assert len(openai_tools) == 4
        for tool_def in openai_tools:
            assert tool_def["type"] == "function"
            assert "name" in tool_def["function"]
            assert "description" in tool_def["function"]
            assert "parameters" in tool_def["function"]
