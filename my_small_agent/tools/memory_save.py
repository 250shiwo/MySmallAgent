"""
长期记忆保存工具 - LLM 自主调用以持久化重要信息。

安全级别：safe（LLM 自主决策，无需用户确认）

记忆在当前会话中不立即生效（保障 prompt 缓存命中），
新记忆将在下次启动时通过 system 消息注入。
"""

from my_small_agent.memory import MemoryManager
from my_small_agent.tools.base import Tool


class MemorySaveTool(Tool):
    """将重要信息持久化到跨会话的长期记忆中。"""

    name = "memory_save"
    description = (
        "Save important information to long-term memory that persists across sessions. "
        "Use for: user preferences, environment details, tool behaviors, stable conventions. "
        "Do NOT save: task progress, session results, or temporary state "
        "(use session_search to recall those)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember persistently across sessions.",
            }
        },
        "required": ["content"],
    }
    danger_level = "safe"

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    async def execute(self, **kwargs) -> str:
        """保存记忆条目，返回保存结果。"""
        content = kwargs["content"]
        try:
            entry_id = self._memory_manager.save_entry(content)
            return f"Memory saved: {entry_id}"
        except Exception as e:
            return f"Error saving memory: {e}"
