"""
activate_skill 工具 - LLM 自主激活技能。

当 LLM 判断当前任务匹配某个技能时，调用此工具获取技能详细指令。
返回的指令作为 tool result 进入对话历史，system prompt 不变。
"""

from my_small_agent.skills.registry import SkillRegistry
from my_small_agent.tools.base import Tool


class ActivateSkillTool(Tool):
    """激活指定技能并返回其详细指令。"""

    name = "activate_skill"
    description = "Activate a skill by name. Returns the skill's detailed instructions."
    parameters = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "技能名称（从 Available Skills 列表中选择）",
            }
        },
        "required": ["skill_name"],
    }
    danger_level = "safe"
    category = "write"       # 修改技能状态，Plan 模式下禁用

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._skill_registry = skill_registry

    async def execute(self, **kwargs) -> str:
        """激活技能并返回含指令的 JSON。"""
        skill_name = kwargs.get("skill_name", "")
        return self._skill_registry.activate(skill_name)
