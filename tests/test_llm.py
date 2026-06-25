"""Tests for LLM client."""

import os
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

    @pytest.mark.asyncio
    async def test_chat_with_thinking_enabled(self, mock_settings):
        """thinking_enabled=True 时应传递 thinking 参数给 API。"""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            thinking_enabled=True,
        )

        call_kwargs = client.client.chat.completions.create.call_args[1]
        assert call_kwargs["thinking"] == {"type": "enabled"}

    @pytest.mark.asyncio
    async def test_chat_without_thinking(self, mock_settings):
        """thinking_enabled=False 时不应传递 thinking 参数。"""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            thinking_enabled=False,
        )

        call_kwargs = client.client.chat.completions.create.call_args[1]
        assert "thinking" not in call_kwargs

    @pytest.mark.asyncio
    async def test_chat_stream_returns_stream(self, mock_settings):
        """chat_stream() 应传递 stream=True 给 API。"""
        client = LLMClient(mock_settings)
        mock_stream = AsyncMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_stream)

        result = await client.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            thinking_enabled=True,
        )

        call_kwargs = client.client.chat.completions.create.call_args[1]
        assert call_kwargs["stream"] is True
        assert call_kwargs["thinking"] == {"type": "enabled"}
        assert result is mock_stream
