"""Tests for agent conversation loop."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent, AgentResponse
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
    settings.enable_streaming = True
    settings.enable_thinking = True
    settings.max_context_tokens = 200000
    settings.head_keep = 3
    settings.tail_keep = 20
    settings.compression_threshold = 0.8
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
        assert result.content == "Hello!"

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
        assert "Done!" in result.content

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
        assert "won't" in result.content.lower() or "ok" in result.content.lower()

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
        assert "maximum" in result.content.lower() or "iteration" in result.content.lower() or "limit" in result.content.lower()


def test_agent_response_dataclass():
    """AgentResponse 应正确存储 content 和 thinking。"""
    resp = AgentResponse(content="hello", thinking="let me think...")
    assert resp.content == "hello"
    assert resp.thinking == "let me think..."


def test_agent_response_default_thinking():
    """AgentResponse 的 thinking 字段默认为空字符串。"""
    resp = AgentResponse(content="hello")
    assert resp.thinking == ""


@pytest.mark.asyncio
async def test_strip_thinking_from_history():
    """strip_thinking_from_history 应移除历史中的 reasoning_content。"""
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)

    # 模拟带 thinking 的历史
    agent.messages.append({
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "thinking process",
    })

    agent.strip_thinking_from_history()

    assistant_msg = agent.messages[-1]
    assert "reasoning_content" not in assistant_msg
    assert assistant_msg["content"] == "answer"


@pytest.mark.asyncio
async def test_agent_runtime_state_from_settings():
    """Agent 应从 Settings 初始化 streaming 和 thinking 状态。"""
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = False
    settings.enable_thinking = False
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)

    assert agent.streaming_enabled is False
    assert agent.thinking_enabled is False


# ---- 会话元数据测试 ----

def test_agent_has_session_id():
    """Agent 初始化后应有非空 session_id。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    assert isinstance(agent.session_id, str)
    assert len(agent.session_id) > 0


def test_agent_session_ids_are_unique():
    """每次创建 Agent 实例应生成不同的 session_id。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    a1 = Agent(llm, registry, settings)
    a2 = Agent(llm, registry, settings)
    assert a1.session_id != a2.session_id


def test_agent_has_empty_session_title_by_default():
    """初始 session_title 应为空字符串。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    assert agent.session_title == ""


def test_agent_has_created_at():
    """Agent 初始化后应有非空 created_at 时间戳。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    assert isinstance(agent.created_at, str)
    assert len(agent.created_at) > 0


def test_reset_session_keeps_system_prompt_clears_rest():
    """reset_session() 应保留 messages[0]（system prompt），清空其余。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    system_msg = agent.messages[0]
    agent.messages.append({"role": "user", "content": "hello"})
    agent.reset_session()
    assert len(agent.messages) == 1
    assert agent.messages[0] is system_msg


def test_reset_session_loads_provided_messages():
    """reset_session(messages=...) 应在 system prompt 后追加传入的消息。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    agent.reset_session(messages=msgs)
    assert len(agent.messages) == 3   # system + 2
    assert agent.messages[1] == msgs[0]
    assert agent.messages[2] == msgs[1]


def test_reset_session_generates_new_id():
    """reset_session() 不传 session_id 时应生成新 UUID。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    old_id = agent.session_id
    agent.reset_session()
    assert agent.session_id != old_id


def test_reset_session_with_explicit_metadata():
    """reset_session() 传入 session_id/title/created_at 时应使用传入值。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    agent.reset_session(
        session_id="custom-id-abc",
        title="My Title",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert agent.session_id == "custom-id-abc"
    assert agent.session_title == "My Title"
    assert agent.created_at == "2026-01-01T00:00:00+00:00"


def test_clear_history_generates_new_session_id():
    """clear_history() 应生成新的 session_id（不再复用旧 ID）。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    old_id = agent.session_id
    agent.clear_history()
    assert agent.session_id != old_id
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"


# ---- 记忆注入测试 ----

def test_agent_without_memory_manager_has_one_system_message():
    """不传 memory_manager 时，messages 应只有 1 条 system 消息。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"


def test_agent_with_memory_manager_no_entries_has_one_system_message(tmp_path):
    """MemoryManager 无条目时，messages 应仍只有 1 条 system 消息（不注入空记忆）。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)  # 无条目
    agent = Agent(llm, registry, settings, memory_manager=mm)
    assert len(agent.messages) == 1


def test_agent_with_memory_injects_second_system_message(tmp_path):
    """MemoryManager 有条目时，应注入第二条 system 消息。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)
    mm.save_entry("User prefers Python")
    agent = Agent(llm, registry, settings, memory_manager=mm)
    assert len(agent.messages) == 2
    assert agent.messages[1]["role"] == "system"
    assert "Python" in agent.messages[1]["content"]
    assert "[长期记忆" in agent.messages[1]["content"]


def test_reset_session_preserves_memory_system_message(tmp_path):
    """reset_session() 应保留所有 system 消息（含记忆注入消息）。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)
    mm.save_entry("test memory")
    agent = Agent(llm, registry, settings, memory_manager=mm)
    # 添加一条用户消息
    agent.messages.append({"role": "user", "content": "hello"})
    agent.reset_session()
    # 重置后应保留 2 条 system 消息（SYSTEM_PROMPT + 记忆注入）
    system_msgs = [m for m in agent.messages if m["role"] == "system"]
    assert len(system_msgs) == 2
    # 非 system 消息应被清空
    assert len(agent.messages) == 2


class TestEstimateTokens:
    def test_empty_messages_returns_zero(self, mock_settings, registry):
        """只有 system prompt 时应返回合理的估算值（大于 0）。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        tokens = agent.estimate_tokens()
        assert tokens > 0  # system prompt 有内容

    def test_estimate_grows_with_messages(self, mock_settings, registry):
        """添加消息后 token 估算值应增大。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        before = agent.estimate_tokens()
        agent.messages.append({"role": "user", "content": "a" * 400})
        after = agent.estimate_tokens()
        assert after > before
        # 400 chars / 4 = 100 tokens, 应有近似增量
        assert after - before == pytest.approx(100, abs=5)

    def test_estimate_counts_all_string_fields(self, mock_settings, registry):
        """tool_calls 等非 content 字段也应计入估算。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        baseline = agent.estimate_tokens()
        agent.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "x" * 40, "arguments": "{}"}}],
        })
        after = agent.estimate_tokens()
        assert after > baseline


COMPACT_SUMMARY_PROMPT_FRAGMENT = "## Goal"  # LLM 收到的 prompt 应含此结构


class TestCompactContext:
    def _make_agent_with_many_messages(self, mock_settings, registry, n_extra=25):
        """创建一个消息数 > head_keep + tail_keep 的 agent。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        for i in range(n_extra):
            agent.messages.append({"role": "user", "content": f"user msg {i}"})
            agent.messages.append({"role": "assistant", "content": f"assistant reply {i}"})
        return agent, llm

    @pytest.mark.asyncio
    async def test_compact_reduces_message_count(self, mock_settings, registry):
        """压缩后消息总数应 < 压缩前。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry)
        before_count = len(agent.messages)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "## Goal\n- 测试目标\n## Key Actions\n- 无"
        llm.chat = AsyncMock(return_value=summary_response)

        before, after = await agent.compact_context()
        assert before == before_count
        assert after < before
        # after = head_keep + 1(summary) + tail_keep = 3 + 1 + 20 = 24
        assert after == mock_settings.head_keep + 1 + mock_settings.tail_keep

    @pytest.mark.asyncio
    async def test_compact_preserves_head_and_tail(self, mock_settings, registry):
        """压缩应保留前 head_keep 条和后 tail_keep 条消息。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)
        first_msgs = agent.messages[:mock_settings.head_keep]
        last_msgs = agent.messages[-mock_settings.tail_keep:]

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "summary"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        assert agent.messages[:mock_settings.head_keep] == first_msgs
        assert agent.messages[-mock_settings.tail_keep:] == last_msgs

    @pytest.mark.asyncio
    async def test_compact_inserts_summary_message(self, mock_settings, registry):
        """压缩后中间应有一条含摘要内容的消息。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "## Goal\n压缩测试"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        summary_msg = agent.messages[mock_settings.head_keep]
        assert "压缩历史摘要" in summary_msg["content"]
        assert "## Goal" in summary_msg["content"]

    @pytest.mark.asyncio
    async def test_compact_calls_llm_with_structured_prompt(self, mock_settings, registry):
        """compact_context 应调用 LLM 且 prompt 含结构化模板关键词。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "ok"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        llm.chat.assert_called_once()
        call_args = llm.chat.call_args
        prompt_msgs = call_args.kwargs.get("messages") or call_args.args[0]
        prompt_text = prompt_msgs[0]["content"]
        assert "## Goal" in prompt_text
        assert "## Key Actions" in prompt_text
        assert "## Current State" in prompt_text

    @pytest.mark.asyncio
    async def test_compact_boundary_avoids_orphaned_tool(self, mock_settings, registry):
        """压缩后不应出现孤立的 tool 消息（没有对应的 assistant(tool_calls)）。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)

        # 构造含 tool_call 序列的消息列表
        # system(1) + user(1) + assistant(tool_calls)(1) + tool(1) = 4 条开头
        # 然后填充中间消息到 > 23 条
        agent.messages = [{"role": "system", "content": "system prompt"}]
        agent.messages.append({"role": "user", "content": "do something"})
        agent.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "safe_tool", "arguments": "{}"}}],
        })
        agent.messages.append({"role": "tool", "tool_call_id": "tc1", "content": "result"})
        # 中间填充到足够多
        for i in range(20):
            agent.messages.append({"role": "user", "content": f"msg {i}"})
            agent.messages.append({"role": "assistant", "content": f"reply {i}"})
        # 末尾构造另一个 tool_call 序列，确保 tail 边界会落在 tool 消息上
        agent.messages.append({"role": "user", "content": "last request"})
        agent.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc2", "type": "function", "function": {"name": "safe_tool", "arguments": "{}"}}],
        })
        agent.messages.append({"role": "tool", "tool_call_id": "tc2", "content": "last result"})
        agent.messages.append({"role": "assistant", "content": "final reply"})

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "summary"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        # 验证：不存在孤立的 tool 消息
        for i, msg in enumerate(agent.messages):
            if msg.get("role") == "tool":
                # 前一条必须是含 tool_calls 的 assistant
                assert i > 0, "tool 消息不能是第一条"
                prev = agent.messages[i - 1]
                assert prev.get("role") == "assistant" and prev.get("tool_calls"), \
                    f"tool 消息（索引 {i}）前缺少对应的 assistant(tool_calls)"
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # 后面必须紧跟 tool 消息
                assert i + 1 < len(agent.messages), \
                    f"assistant(tool_calls) 消息（索引 {i}）后缺少 tool 响应"
                assert agent.messages[i + 1].get("role") == "tool", \
                    f"assistant(tool_calls) 消息（索引 {i}）后不是 tool 消息"
