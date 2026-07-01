"""
deactivate_skill 工具 - 取消当前激活的技能，回到基础模式。
"""

from my_small_agent.skills.registry import SkillRegistry
from my_small_agent.tools.base import Tool


class DeactivateSkillTool(Tool):
    """取消当前激活的技能。"""

    name = "deactivate_skill"
    description = "Deactivate the currently active skill and return to base mode."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    danger_level = "safe"

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._skill_registry = skill_registry

    async def execute(self, **kwargs) -> str:
        """取消激活并返回确认消息。"""
        return self._skill_registry.deactivate()
