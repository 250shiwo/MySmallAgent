"""Plan 模式测试 - 工具过滤、提示词注入、模式切换。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.prompt import PLAN_MODE_MARKER, PromptManager
from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool


class MockSafeTool(Tool):
    name = "safe_tool"
    description = "A safe mock tool"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        return f"safe result: {kwargs['x']}"


class MockDangerousTool(Tool):
    name = "danger_tool"
    description = "A dangerous mock tool"
    parameters = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    danger_level = "dangerous"
    category = "write"

    async def execute(self, **kwargs) -> str:
        return f"executed: {kwargs['cmd']}"


class MockSafeWriteTool(Tool):
    """模拟 safe 但 write 的工具（如 memory_save）：danger_level 和 category 不同。"""
    name = "safe_write_tool"
    description = "A safe but write tool"
    parameters = {"type": "object", "properties": {"data": {"type": "string"}}, "required": ["data"]}
    danger_level = "safe"
    category = "write"

    async def execute(self, **kwargs) -> str:
        return f"saved: {kwargs['data']}"


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
    tool_call.id = "call_plan_001"
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
                "id": "call_plan_001",
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
    reg.register(MockSafeWriteTool())
    return reg


# ---- ToolRegistry: readonly_only 过滤 ----


class TestToolRegistryReadonlyFilter:
    def test_readonly_only_excludes_dangerous(self, registry):
        """readonly_only=True 时应排除 dangerous 工具。"""
        tools = registry.get_openai_tools(readonly_only=True)
        names = [t["function"]["name"] for t in tools]
        assert "safe_tool" in names
        assert "danger_tool" not in names

    def test_readonly_only_false_includes_all(self, registry):
        """readonly_only=False（默认）时应包含所有工具。"""
        tools = registry.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        assert "safe_tool" in names
        assert "danger_tool" in names

    def test_readonly_only_returns_correct_count(self, registry):
        """readonly_only=True 时返回的工具数应等于 read_only 工具数。"""
        all_tools = registry.get_openai_tools()
        readonly_tools = registry.get_openai_tools(readonly_only=True)
        assert len(readonly_tools) < len(all_tools)
        assert len(readonly_tools) == 1  # 只有 MockSafeTool

    def test_readonly_only_excludes_safe_write_tool(self, registry):
        """readonly_only=True 时应排除 safe+write 工具（category 优先于 danger_level）。"""
        tools = registry.get_openai_tools(readonly_only=True)
        names = [t["function"]["name"] for t in tools]
        assert "safe_write_tool" not in names  # safe 但 write，应被排除

    def test_normal_mode_includes_safe_write_tool(self, registry):
        """Normal 模式应包含 safe+write 工具。"""
        tools = registry.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        assert "safe_write_tool" in names


# ---- PromptManager: plan prompt ----


class TestPromptManagerPlanPrompt:
    def test_get_plan_prompt_contains_marker(self):
        """get_plan_prompt 返回的内容应包含 PLAN_MODE_MARKER。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert PLAN_MODE_MARKER in prompt

    def test_get_plan_prompt_contains_instructions(self):
        """get_plan_prompt 应包含关键指令。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert "计划模式" in prompt
        assert "探索与信息收集" in prompt
        assert "生成计划" in prompt

    def test_plan_prompt_contains_format_specification(self):
        """plan prompt 应包含输出格式规范。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert "## Plan" in prompt
        assert "**Goal**" in prompt
        assert "### Steps" in prompt
        assert "<标题>" in prompt


# ---- Agent: plan_mode 切换 ----


class TestAgentPlanMode:
    def test_plan_mode_default_false(self, mock_settings, registry):
        """Agent 初始化后 plan_mode 应为 False。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        assert agent.plan_mode is False

    def test_toggle_plan_mode_on(self, mock_settings, registry):
        """toggle_plan_mode 首次调用应开启 Plan 模式。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        result = agent.toggle_plan_mode()
        assert result == "plan_on"
        assert agent.plan_mode is True

    def test_toggle_plan_mode_off(self, mock_settings, registry):
        """toggle_plan_mode 二次调用应关闭 Plan 模式。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        agent.toggle_plan_mode()  # 开启
        result = agent.toggle_plan_mode()  # 关闭
        assert result == "plan_off"
        assert agent.plan_mode is False

    def test_plan_mode_on_injects_system_message(self, mock_settings, registry):
        """开启 Plan 模式应注入一条含 PLAN_MODE_MARKER 的 system 消息。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        initial_count = len(agent.messages)
        agent.toggle_plan_mode()
        assert len(agent.messages) == initial_count + 1
        # 最后一条应是 system 消息且含标记
        last_msg = agent.messages[-1]
        assert last_msg["role"] == "system"
        assert PLAN_MODE_MARKER in last_msg["content"]

    def test_plan_mode_off_removes_system_message(self, mock_settings, registry):
        """关闭 Plan 模式应移除含 PLAN_MODE_MARKER 的 system 消息。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        initial_count = len(agent.messages)
        agent.toggle_plan_mode()  # 开启 → +1 条
        agent.toggle_plan_mode()  # 关闭 → -1 条
        assert len(agent.messages) == initial_count
        # 不应再有含标记的 system 消息
        plan_msgs = [
            m for m in agent.messages
            if m.get("role") == "system" and PLAN_MODE_MARKER in m.get("content", "")
        ]
        assert len(plan_msgs) == 0

    @pytest.mark.asyncio
    async def test_plan_mode_filters_tools_in_run_turn(self, mock_settings, registry):
        """Plan 模式下 run_turn 应只传只读工具给 LLM。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("plan response"))

        agent = Agent(llm, registry, mock_settings)
        agent.plan_mode = True

        await agent.run_turn("analyze this", confirm_callback=AsyncMock())

        # 检查 LLM 调用时传入的 tools 参数
        call_kwargs = llm.chat.call_args.kwargs
        tools = call_kwargs.get("tools")
        assert tools is not None
        names = [t["function"]["name"] for t in tools]
        assert "safe_tool" in names
        assert "danger_tool" not in names

    @pytest.mark.asyncio
    async def test_normal_mode_passes_all_tools_in_run_turn(self, mock_settings, registry):
        """Normal 模式下 run_turn 应传所有工具给 LLM。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("response"))

        agent = Agent(llm, registry, mock_settings)
        # plan_mode 默认为 False

        await agent.run_turn("do something", confirm_callback=AsyncMock())

        call_kwargs = llm.chat.call_args.kwargs
        tools = call_kwargs.get("tools")
        assert tools is not None
        names = [t["function"]["name"] for t in tools]
        assert "safe_tool" in names
        assert "danger_tool" in names


# ---- Agent: Plan 模式执行层拒绝 ----


class TestPlanModeExecutionRejection:
    """测试 Plan 模式下执行层对写工具调用的拒绝（安全网）。"""

    @pytest.mark.asyncio
    async def test_plan_mode_rejects_write_tool_call(self, mock_settings, registry):
        """Plan 模式下 LLM 幻觉调用写工具时，执行层应拒绝并返回错误信息。"""
        llm = MagicMock(spec=LLMClient)
        # 第一轮：LLM 请求调用 danger_tool（write 工具）
        # 第二轮：LLM 收到拒绝后回复文本
        llm.chat = AsyncMock(side_effect=[
            make_tool_call_response("danger_tool", {"cmd": "rm -rf /"}),
            make_text_response("好的，我不会执行写操作。"),
        ])

        agent = Agent(llm, registry, mock_settings)
        agent.plan_mode = True

        result = await agent.run_turn("delete everything", confirm_callback=AsyncMock())

        # 验证：工具结果消息中包含拒绝信息
        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "not available in Plan mode" in tool_msgs[0]["content"]
        assert "danger_tool" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_plan_mode_rejects_safe_write_tool_call(self, mock_settings, registry):
        """Plan 模式下 LLM 调用 safe+write 工具时也应被拒绝。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(side_effect=[
            make_tool_call_response("safe_write_tool", {"data": "test"}),
            make_text_response("好的，Plan 模式下不保存。"),
        ])

        agent = Agent(llm, registry, mock_settings)
        agent.plan_mode = True

        result = await agent.run_turn("save this", confirm_callback=AsyncMock())

        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "not available in Plan mode" in tool_msgs[0]["content"]
        assert "safe_write_tool" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_plan_mode_allows_readonly_tool_call(self, mock_settings, registry):
        """Plan 模式下 LLM 调用只读工具时应正常执行。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(side_effect=[
            make_tool_call_response("safe_tool", {"x": "test"}),
            make_text_response("分析完成。"),
        ])

        agent = Agent(llm, registry, mock_settings)
        agent.plan_mode = True

        result = await agent.run_turn("analyze", confirm_callback=AsyncMock())

        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "safe result: test" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_normal_mode_allows_write_tool_call(self, mock_settings, registry):
        """Normal 模式下写工具应正常执行（不拒绝）。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(side_effect=[
            make_tool_call_response("safe_write_tool", {"data": "test"}),
            make_text_response("已保存。"),
        ])

        agent = Agent(llm, registry, mock_settings)
        # plan_mode 默认为 False

        result = await agent.run_turn("save this", confirm_callback=AsyncMock())

        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "saved: test" in tool_msgs[0]["content"]
