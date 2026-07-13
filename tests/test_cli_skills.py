"""CLI 技能命令测试。"""

from unittest.mock import MagicMock, patch

import pytest

from my_small_agent.agent import Agent
from my_small_agent.cli import CLI
from my_small_agent.skills.registry import SkillInfo, SkillRegistry


def _extract_text(obj) -> str:
    """从 console.print 的参数中提取可断言的文本。

    rich Panel 对象的 str() 只返回 repr，需通过 renderable 取实际内容；
    普通字符串直接返回。
    """
    if hasattr(obj, "renderable"):
        return str(obj.renderable)
    return str(obj)


@pytest.fixture
def mock_cli():
    """创建一个用于测试的 CLI 实例（mock Agent 和 SessionManager）。"""
    agent = MagicMock(spec=Agent)
    agent.streaming_enabled = True
    agent.thinking_enabled = True
    agent.plan_mode = False
    agent.session_id = "test-session-id"
    agent.session_title = "Test"
    agent.messages = [{"role": "system", "content": "prompt"}]
    agent.settings = MagicMock()
    agent.settings.max_context_tokens = 100000
    agent.estimate_tokens = MagicMock(return_value=5000)
    agent.llm = MagicMock()
    agent.llm.model = "test-model"

    # Skill registry
    skill_reg = SkillRegistry()
    skill_reg.register(
        SkillInfo(name="research", description="Research expert", prompt_text="Research mode")
    )
    skill_reg.register(
        SkillInfo(name="code_assistant", description="Code helper", prompt_text="Code mode")
    )
    skill_reg.register(
        SkillInfo(
            name="auto_skill", description="Auto only", prompt_text="Auto", user_invocable=False
        )
    )
    agent._skill_registry = skill_reg

    agent.activate_skill = MagicMock(return_value="Skill 'research' activated.")
    agent.deactivate_skill = MagicMock(return_value="Skill 'research' deactivated.")

    session_manager = MagicMock()
    # patch Console 使 console.print 成为可断言的 mock；
    # patch PromptSession 避免在无 TTY 环境下构造失败
    with patch("my_small_agent.cli.Console"), patch("my_small_agent.cli.PromptSession"):
        cli = CLI(agent, session_manager)
    return cli


class TestSkillsCommand:
    """测试 /skills 命令。"""

    @pytest.mark.asyncio
    async def test_skills_lists_all(self, mock_cli):
        await mock_cli._handle_command("/skills")
        # 验证 console 输出（通过 mock 的 print 调用检查）
        # 由于 rich Console 直接输出到终端，我们检查 print 被调用
        mock_cli.console.print.assert_called()

    @pytest.mark.asyncio
    async def test_skill_activate(self, mock_cli):
        await mock_cli._handle_command("/skill research")
        mock_cli.agent.activate_skill.assert_called_once_with("research")

    @pytest.mark.asyncio
    async def test_skill_no_args_shows_usage(self, mock_cli):
        await mock_cli._handle_command("/skill")
        mock_cli.console.print.assert_called()

    @pytest.mark.asyncio
    async def test_unskill(self, mock_cli):
        await mock_cli._handle_command("/unskill")
        mock_cli.agent.deactivate_skill.assert_called_once()


class TestSkillsStatusEnhancement:
    """测试 /status 面板中当前技能行的展示。"""

    @pytest.mark.asyncio
    async def test_status_shows_skill_label_when_inactive(self, mock_cli):
        # 无激活技能时，/status 面板应包含 "当前技能" 行
        mock_cli._print_status()
        last_call_args = mock_cli.console.print.call_args
        assert last_call_args is not None
        panel_arg = last_call_args.args[0]
        assert "当前技能" in _extract_text(panel_arg)

    @pytest.mark.asyncio
    async def test_status_shows_no_when_inactive(self, mock_cli):
        # 无激活技能时，技能显示为 "无"
        mock_cli._print_status()
        last_call_args = mock_cli.console.print.call_args
        content = _extract_text(last_call_args.args[0])
        assert "无" in content

    @pytest.mark.asyncio
    async def test_status_shows_active_skill_name(self, mock_cli):
        # 激活技能后，/status 面板应显示技能名称
        mock_cli.agent._skill_registry.activate("research")
        mock_cli._print_status()
        last_call_args = mock_cli.console.print.call_args
        content = _extract_text(last_call_args.args[0])
        assert "research" in content


class TestSkillsListingContent:
    """测试 /skills 输出内容。"""

    @pytest.mark.asyncio
    async def test_skills_panel_contains_all_skill_names(self, mock_cli):
        await mock_cli._handle_command("/skills")
        # 取最后一次 print 调用，提取 Panel 的内容文本
        last_call_args = mock_cli.console.print.call_args
        panel_arg = last_call_args.args[0]
        content_text = _extract_text(panel_arg)
        assert "research" in content_text
        assert "code_assistant" in content_text
        assert "auto_skill" in content_text

    @pytest.mark.asyncio
    async def test_skills_marks_auto_only(self, mock_cli):
        await mock_cli._handle_command("/skills")
        last_call_args = mock_cli.console.print.call_args
        panel_arg = last_call_args.args[0]
        # auto_skill 应标注 auto-only
        assert "auto-only" in _extract_text(panel_arg)

    @pytest.mark.asyncio
    async def test_skills_marks_active_skill(self, mock_cli):
        # 先激活一个技能，再列出，应在激活项前显示标记
        mock_cli.agent._skill_registry.activate("research")
        await mock_cli._handle_command("/skills")
        last_call_args = mock_cli.console.print.call_args
        content = _extract_text(last_call_args.args[0])
        assert "▶" in content


class TestSkillActivateEdgeCases:
    """测试 /skill 命令的边界情况。"""

    @pytest.mark.asyncio
    async def test_skill_activate_with_extra_spaces(self, mock_cli):
        await mock_cli._handle_command("/skill   research")
        # 多个空格也只取第一个参数
        mock_cli.agent.activate_skill.assert_called_once_with("research")

    @pytest.mark.asyncio
    async def test_skill_activate_error_displayed_in_red(self, mock_cli):
        # 模拟激活返回错误信息
        mock_cli.agent.activate_skill = MagicMock(return_value="Error: Skill 'x' not found.")
        await mock_cli._handle_command("/skill x")
        mock_cli.agent.activate_skill.assert_called_once_with("x")
        # 错误信息应通过 console.print 输出
        mock_cli.console.print.assert_called()
