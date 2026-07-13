"""Plan 模式生命周期测试 - 审阅、执行、失败处理。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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


# === CLI Plan 轮次与审阅流程测试 ===

from my_small_agent.cli import CLI
from my_small_agent.session import SessionManager
from my_small_agent.plan import parse_plan


@pytest.fixture
def cli_instance(mock_settings, registry):
    """构造 CLI 实例（非流式模式）。"""
    llm = MagicMock(spec=LLMClient)
    llm.model = "test-model"
    agent = Agent(llm, registry, mock_settings)
    agent.streaming_enabled = False  # 非流式，简化测试
    session_mgr = MagicMock()
    with patch("my_small_agent.cli.PromptSession"), \
         patch("my_small_agent.cli.patch_stdout"):
        cli = CLI(agent, session_mgr)
    cli.session = MagicMock()  # 替换为 mock
    cli.session.prompt_async = AsyncMock()
    return cli


class TestRunPlanTurn:
    """_run_plan_turn 方法测试。"""

    @pytest.mark.asyncio
    async def test_plan_turn_parses_plan_and_enters_review(self, cli_instance):
        """Plan 模式下 Agent 返回可解析计划时应进入审阅流程。"""
        cli = cli_instance
        cli.agent.plan_mode = True

        plan_text = """## Plan
**Goal**: 测试目标

### Steps
1. **步骤A** -- 做A
2. **步骤B** -- 做B
"""
        # mock Agent.run_turn 返回包含计划的响应
        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response(plan_text)
        )
        # mock _review_plan 避免实际执行审阅
        cli._review_plan = AsyncMock()

        await cli._run_plan_turn("测试目标")

        # 验证 _review_plan 被调用，且传入了 Plan 对象
        cli._review_plan.assert_called_once()
        plan_arg = cli._review_plan.call_args.args[0]
        assert plan_arg.goal == "测试目标"
        assert len(plan_arg.steps) == 2

    @pytest.mark.asyncio
    async def test_plan_turn_no_plan_returns_silently(self, cli_instance):
        """Plan 模式下 Agent 返回不可解析的文本时不进入审阅。"""
        cli = cli_instance
        cli.agent.plan_mode = True

        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("这是一段普通回复，不是计划。")
        )
        cli._review_plan = AsyncMock()

        await cli._run_plan_turn("随便聊聊")

        # _review_plan 不应被调用
        cli._review_plan.assert_not_called()


class TestReviewPlan:
    """_review_plan 方法测试。"""

    @pytest.mark.asyncio
    async def test_review_accept_proceeds_to_execute(self, cli_instance):
        """用户选择 Accept 时应进入执行阶段。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        # mock questionary.select 返回 "Accept"
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Accept")
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            cli._execute_plan.assert_called_once_with(plan)
            assert plan.phase == PlanPhase.EXECUTING

    @pytest.mark.asyncio
    async def test_review_cancel_does_not_execute(self, cli_instance):
        """用户选择 Cancel 时不应执行计划。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Cancel")
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            cli._execute_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_modify_sends_feedback_to_llm(self, cli_instance):
        """用户选择 Modify 时应将反馈发送给 LLM 生成修订版。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        revised_text = """## Plan
**Goal**: Test

### Steps
1. **Revised A** -- Do A better
2. **Revised B** -- Do B better
"""
        # mock questionary: 第一次返回 Modify，第二次返回 Accept
        with patch("my_small_agent.cli.questionary") as mock_q, \
             patch("my_small_agent.cli.patch_stdout"):
            mock_q.select.return_value.ask_async = AsyncMock(
                side_effect=["Modify", "Accept"]
            )
            # mock prompt_async 获取用户反馈
            cli.session.prompt_async = AsyncMock(return_value="请修改步骤A")
            # mock Agent 生成修订版
            cli.agent.run_turn = AsyncMock(
                return_value=_make_agent_response(revised_text)
            )
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            # 验证执行了修订后的计划
            cli._execute_plan.assert_called_once()
            executed_plan = cli._execute_plan.call_args.args[0]
            assert executed_plan.steps[0].title == "Revised A"

    @pytest.mark.asyncio
    async def test_review_modify_max_3_rounds(self, cli_instance):
        """修改超过 3 轮后第 4 次 Modify 被阻断，最终 Accept。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="A", description="d"),
                PlanStep(index=2, title="B", description="d"),
            ],
        )
        revised_text = """## Plan
**Goal**: Test

### Steps
1. **A** -- d
2. **B** -- d
"""
        with patch("my_small_agent.cli.questionary") as mock_q, \
             patch("my_small_agent.cli.patch_stdout"):
            # 3 次 Modify（成功）+ 第 4 次 Modify（被阻断）+ Accept
            mock_q.select.return_value.ask_async = AsyncMock(
                side_effect=["Modify", "Modify", "Modify", "Modify", "Accept"]
            )
            cli.session.prompt_async = AsyncMock(return_value="修改")
            cli.agent.run_turn = AsyncMock(
                return_value=_make_agent_response(revised_text)
            )
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            # 验证 prompt_async 只被调用 3 次（第 4 次 Modify 被阻断，不会请求反馈）
            assert cli.session.prompt_async.call_count == 3
            # 验证最终执行了
            cli._execute_plan.assert_called_once()
