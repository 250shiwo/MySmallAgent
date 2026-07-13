"""Plan 模式生命周期测试 - 审阅、执行、失败处理。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent, AgentResponse
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.plan import Plan, PlanStep, StepStatus, PlanPhase
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
    return reg


def _make_eval_response(verdict: str):
    """构造 LLM 评估响应 mock。"""
    message = MagicMock()
    message.content = verdict
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_agent_response(content: str):
    """构造 AgentResponse。"""
    return AgentResponse(content=content)


class TestEvaluateStepSuccess:
    """Agent.evaluate_step_success 方法测试。"""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, mock_settings, registry):
        """LLM 回答 SUCCESS 时应返回 True。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Task completed successfully.")

        result = await agent.evaluate_step_success(step, response)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self, mock_settings, registry):
        """LLM 回答 FAILURE 时应返回 False。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("FAILURE"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Could not complete the task.")

        result = await agent.evaluate_step_success(step, response)
        assert result is False

    @pytest.mark.asyncio
    async def test_eval_uses_step_and_response_content(self, mock_settings, registry):
        """评估调用应包含步骤标题、描述和执行结果。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="分析代码", description="读取 auth/ 目录")
        response = AgentResponse(content="已读取所有文件。")

        await agent.evaluate_step_success(step, response)

        # 检查 LLM 调用参数
        call_args = llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        eval_text = messages[0]["content"]
        assert "分析代码" in eval_text
        assert "读取 auth/ 目录" in eval_text
        assert "已读取所有文件。" in eval_text

    @pytest.mark.asyncio
    async def test_eval_no_tools_passed(self, mock_settings, registry):
        """评估调用不应传工具定义。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Done.")

        await agent.evaluate_step_success(step, response)

        call_kwargs = llm.chat.call_args.kwargs
        assert call_kwargs.get("tools") is None

    @pytest.mark.asyncio
    async def test_eval_thinking_disabled(self, mock_settings, registry):
        """评估调用应禁用 thinking。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Done.")

        await agent.evaluate_step_success(step, response)

        call_kwargs = llm.chat.call_args.kwargs
        assert call_kwargs.get("thinking_enabled") is False

    @pytest.mark.asyncio
    async def test_eval_truncates_long_response(self, mock_settings, registry):
        """执行结果超过 2000 字符时应截断。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        long_content = "x" * 3000
        response = AgentResponse(content=long_content)

        await agent.evaluate_step_success(step, response)

        call_args = llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        eval_text = messages[0]["content"]
        assert eval_text.count("x") <= 2000
