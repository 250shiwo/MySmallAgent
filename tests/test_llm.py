"""Tests for LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.openai_api_key = "sk-test"
    settings.openai_base_url = "https://api.test.com/v1"
    settings.openai_model = "gpt-4o-mini"
    return settings


class TestLLMClient:
    def test_init(self, mock_settings):
        """LLMClient should initialize with settings."""
        client = LLMClient(mock_settings)
        assert client.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_chat_calls_openai(self, mock_settings):
        """chat() should call OpenAI API with correct parameters."""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]

        result = await client.chat(messages, tools=tools)

        client.client.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
        )
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_chat_without_tools(self, mock_settings):
        """chat() without tools should not pass tools parameter."""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "hello"}]
        result = await client.chat(messages)

        client.client.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=messages,
        )
