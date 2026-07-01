"""activate_skill / deactivate_skill 工具测试。"""

import json
import pytest

from my_small_agent.skills.registry import SkillInfo, SkillRegistry
from my_small_agent.tools.activate_skill import ActivateSkillTool
from my_small_agent.tools.deactivate_skill import DeactivateSkillTool


@pytest.fixture
def skill_reg():
    reg = SkillRegistry()
    reg.register(SkillInfo(name="research", description="Research expert", prompt_text="Research mode instructions"))
    reg.register(SkillInfo(name="hidden", description="Hidden", prompt_text="Secret", user_invocable=False))
    return reg


class TestActivateSkillTool:
    """activate_skill 工具测试。"""

    @pytest.mark.asyncio
    async def test_activate_existing_skill(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        result = await tool.execute(skill_name="research")
        parsed = json.loads(result)
        assert parsed["name"] == "research"
        assert "Research mode instructions" in parsed["prompt_text"]
        assert skill_reg.get_active().name == "research"

    @pytest.mark.asyncio
    async def test_activate_nonexistent_skill(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        result = await tool.execute(skill_name="nonexist")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_metadata(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        assert tool.name == "activate_skill"
        assert tool.danger_level == "safe"
        assert "skill_name" in tool.parameters["properties"]


class TestDeactivateSkillTool:
    """deactivate_skill 工具测试。"""

    @pytest.mark.asyncio
    async def test_deactivate_active_skill(self, skill_reg):
        skill_reg.activate("research")
        tool = DeactivateSkillTool(skill_reg)
        result = await tool.execute()
        assert skill_reg.get_active() is None
        assert "research" in result.lower() or "deactivat" in result.lower()

    @pytest.mark.asyncio
    async def test_deactivate_when_none_active(self, skill_reg):
        tool = DeactivateSkillTool(skill_reg)
        result = await tool.execute()
        assert skill_reg.get_active() is None

    def test_tool_metadata(self, skill_reg):
        tool = DeactivateSkillTool(skill_reg)
        assert tool.name == "deactivate_skill"
        assert tool.danger_level == "safe"
