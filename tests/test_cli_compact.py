"""Tests for /compact command and auto-compaction in CLI layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_small_agent.cli import CLI


def _make_cli(head_keep=3, tail_keep=20, max_context_tokens=200000,
              compression_threshold=0.8):
    """构造一个 CLI 实例，agent 和 session_manager 均为 mock。"""
    agent = MagicMock()
    agent.settings = MagicMock()
    agent.settings.head_keep = head_keep
    agent.settings.tail_keep = tail_keep
    agent.settings.max_context_tokens = max_context_tokens
    agent.settings.compression_threshold = compression_threshold
    agent.messages = []
    agent.compact_context = AsyncMock(return_value=(30, 24))
    agent.estimate_tokens = MagicMock(return_value=0)
    agent.streaming_enabled = False
    agent.thinking_enabled = False
    agent.session_id = "abcdef1234567890"
    agent.session_title = "test"

    session_manager = MagicMock()
    # PromptSession 在无控制台环境（如 CI）下构造会失败，这里 patch 掉
    with patch("my_small_agent.cli.PromptSession"):
        cli = CLI(agent, session_manager)
    return cli, agent


class TestCompactContextCommand:
    """手动 /compact 命令行为测试。"""

    @pytest.mark.asyncio
    async def test_compact_shows_skip_when_messages_below_threshold(self):
        """消息数 <= head_keep + tail_keep 时应跳过压缩。"""
        cli, agent = _make_cli(head_keep=3, tail_keep=20)
        agent.messages = [{"role": "user", "content": "hi"}] * 23  # 等于阈值

        await cli._compact_context()

        agent.compact_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_invokes_agent_when_messages_exceed_threshold(self):
        """消息数 > head_keep + tail_keep 时应调用 agent.compact_context。"""
        cli, agent = _make_cli(head_keep=3, tail_keep=20)
        agent.messages = [{"role": "user", "content": "msg"}] * 24  # 大于阈值

        await cli._compact_context()

        agent.compact_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_compact_handles_exception_gracefully(self):
        """compact_context 抛异常时应捕获并打印错误，不向上传播。"""
        cli, agent = _make_cli(head_keep=3, tail_keep=20)
        agent.messages = [{"role": "user", "content": "msg"}] * 24
        agent.compact_context = AsyncMock(side_effect=RuntimeError("boom"))

        # 不应抛出异常
        await cli._compact_context()


class TestAutoCompactIfNeeded:
    """自动压缩触发逻辑测试。"""

    @pytest.mark.asyncio
    async def test_no_compact_when_tokens_below_threshold(self):
        """token 用量低于阈值时不应压缩。"""
        cli, agent = _make_cli(max_context_tokens=200000, compression_threshold=0.8)
        # threshold = 200000 * 0.8 = 160000
        agent.estimate_tokens = MagicMock(return_value=1000)
        agent.messages = [{"role": "user", "content": "msg"}] * 24

        await cli._auto_compact_if_needed()

        agent.compact_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_compact_when_tokens_high_but_messages_few(self):
        """token 超阈值但消息数不足时不应压缩。"""
        cli, agent = _make_cli(head_keep=3, tail_keep=20,
                               max_context_tokens=200000, compression_threshold=0.8)
        agent.estimate_tokens = MagicMock(return_value=200000)  # 远超阈值
        agent.messages = [{"role": "user", "content": "msg"}] * 10  # 不足

        await cli._auto_compact_if_needed()

        agent.compact_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_when_tokens_and_messages_both_meet(self):
        """token 超阈值且消息数足够时应触发压缩。"""
        cli, agent = _make_cli(head_keep=3, tail_keep=20,
                               max_context_tokens=200000, compression_threshold=0.8)
        agent.estimate_tokens = MagicMock(return_value=200000)  # >= 160000
        agent.messages = [{"role": "user", "content": "msg"}] * 24

        await cli._auto_compact_if_needed()

        agent.compact_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_compact_at_exact_threshold_boundary(self):
        """token 恰好等于阈值时应触发（>= 判断）。"""
        cli, agent = _make_cli(max_context_tokens=100000, compression_threshold=0.8)
        # threshold = 100000 * 0.8 = 80000
        agent.estimate_tokens = MagicMock(return_value=80000)  # 恰好等于
        agent.messages = [{"role": "user", "content": "msg"}] * 24

        await cli._auto_compact_if_needed()

        agent.compact_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_compact_handles_exception(self):
        """自动压缩失败时应捕获异常不传播。"""
        cli, agent = _make_cli(max_context_tokens=100000, compression_threshold=0.8)
        agent.estimate_tokens = MagicMock(return_value=90000)
        agent.messages = [{"role": "user", "content": "msg"}] * 24
        agent.compact_context = AsyncMock(side_effect=RuntimeError("fail"))

        await cli._auto_compact_if_needed()  # 不应抛出


class TestCompactCommandRegistration:
    """验证 /compact 命令在 _handle_command 中已注册。"""

    @pytest.mark.asyncio
    async def test_handle_compact_command_calls_method(self):
        """/compact 命令应调用 _compact_context。"""
        cli, agent = _make_cli()
        agent.messages = [{"role": "user", "content": "msg"}] * 24

        await cli._handle_command("/compact")

        agent.compact_context.assert_called_once()
