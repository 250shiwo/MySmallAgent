"""Agent 技能激活集成测试。"""

import pytest
from unittest.mock import MagicMock

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.tools import ToolRegistry
from my_small_agent.prompt import PromptManager
from my_small_agent.skills.registry import SkillInfo, SkillRegistry


@pytest.fixture
def mock_settings():
    """创建测试用的 Settings mock（与 test_agent.py 一致的 MagicMock 模式）。"""
    s = MagicMock(spec=Settings)
    s.max_iterations = 5
    s.enable_streaming = False
    s.enable_thinking = False
    s.timezone = "UTC"
    s.max_context_tokens = 100000
    s.head_keep = 3
    s.tail_keep = 20
    s.compression_threshold = 0.8
    return s


@pytest.fixture
def mock_prompt_manager(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Base prompt.", encoding="utf-8")
    pm = PromptManager(base_prompt_path=prompt_file)
    pm.update_skills_index("## Available Skills\n- research: Expert")
    return pm


@pytest.fixture
def skill_reg():
    reg = SkillRegistry()
    reg.register(SkillInfo(name="research", description="Expert", prompt_text="Research instructions here."))
    reg.register(SkillInfo(name="auto_only", description="Auto", prompt_text="Auto only.", user_invocable=False))
    return reg


class TestAgentWithPromptManager:
    """Agent 使用 PromptManager 初始化测试。"""

    def test_system_prompt_from_prompt_manager(self, mock_settings, mock_prompt_manager):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        # system prompt 应包含 base + skills index
        system_msg = agent.messages[0]
        assert system_msg["role"] == "system"
        assert "Base prompt." in system_msg["content"]
        assert "## Available Skills" in system_msg["content"]

    def test_without_prompt_manager_uses_default(self, mock_settings):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings)
        # 应回退到默认 PromptManager（从 system_prompt.md 加载）
        assert agent.messages[0]["role"] == "system"
        assert len(agent.messages[0]["content"]) > 50


class TestAgentSkillActivation:
    """Agent 手动技能激活测试。"""

    def test_activate_skill_injects_messages(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("research")
        assert "research" in result.lower() or "Research instructions" in result

        # 检查消息注入：应有 assistant(tool_calls) + tool(result) 一对
        # 倒数第二条是 assistant with tool_calls
        assistant_msg = agent.messages[-2]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "activate_skill"
        # 倒数第一条是 tool result
        tool_msg = agent.messages[-1]
        assert tool_msg["role"] == "tool"
        assert "Research instructions here." in tool_msg["content"]

    def test_activate_nonexistent_skill(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("nonexist")
        assert "error" in result.lower() or "not found" in result.lower()

    def test_activate_non_invocable_skill_rejected(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("auto_only")
        assert "error" in result.lower() or "auto" in result.lower() or "拒绝" in result

    def test_deactivate_skill(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        agent.activate_skill("research")
        result = agent.deactivate_skill()
        assert skill_reg.get_active() is None


class TestResetSessionSkillState:
    """reset_session 后技能状态重置测试。"""

    def test_reset_session_deactivates_skill(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        # 激活技能，确认已激活
        agent.activate_skill("research")
        assert skill_reg.get_active() is not None

        # 重置会话后，技能应被取消激活
        agent.reset_session()
        assert skill_reg.get_active() is None

    def test_reset_session_without_skill_registry(self, mock_settings, mock_prompt_manager):
        """未注入 skill_registry 时 reset_session 不应报错。"""
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        # _skill_registry 保持 None
        agent.reset_session()
        assert agent._skill_registry is None
        assert len(agent.messages) == 1  # 仅 system prompt
