"""
提示词管理模块 - 从文件加载基础系统提示词，动态拼接 skills index。

设计原则：
  - system prompt 前缀在整个会话中保持不变（缓存友好）
  - 技能激活时指令通过 tool result 进入对话历史，不修改 system prompt
"""

from pathlib import Path
from typing import Optional

# Plan 模式系统消息中的标识标记，用于注入/移除时定位
PLAN_MODE_MARKER = "[PLAN_MODE_ACTIVE]"

# Plan 模式提示词：指导 LLM 在只读环境下分析任务并生成结构化计划
_PLAN_PROMPT = f"""{PLAN_MODE_MARKER}

## 计划模式（Plan Mode）

你当前处于计划模式。在此模式下：

1. **只读探索**：只能使用只读工具（read_file、list_directory、grep_search、tree、find_file、fetch_url、web_search、current_time、system_info 等）来探索和分析任务环境
2. **禁止修改**：不得执行任何写入、删除或破坏性操作（write_file、file_delete、execute_shell 等均不可用）
3. **输出结构化计划**：分析完任务后，输出一个结构化的执行计划，包含：
   - 任务目标概述
   - 需要修改的文件列表及修改说明
   - 每个步骤的具体操作描述
   - 潜在风险和注意事项
4. **等待确认**：计划生成后等待用户确认，用户确认后退出计划模式才开始执行

请先充分探索和分析，然后给出完整、可执行的计划。
"""


class PromptManager:
    """
    提示词管理器。

    职责：
      - 从 .md 文件加载基础 system prompt
      - 启动时拼接 skills index
      - 提供统一的 get_system_prompt() 接口给 Agent
    """

    def __init__(self, base_prompt_path: Optional[Path] = None) -> None:
        self._base_prompt = self._load_base_prompt(base_prompt_path)
        self._skills_index: str = ""

    def update_skills_index(self, skills_index: str) -> None:
        """启动时调用一次，设置 skills 列表文本。"""
        self._skills_index = skills_index

    def get_system_prompt(self) -> str:
        """返回完整 system prompt = base + skills index。"""
        if self._skills_index:
            return self._base_prompt + "\n\n" + self._skills_index
        return self._base_prompt

    def get_plan_prompt(self) -> str:
        """返回 Plan 模式的系统提示词（注入为 system 消息）。"""
        return _PLAN_PROMPT

    def _load_base_prompt(self, path: Optional[Path]) -> str:
        """加载基础提示词文件。默认路径: my_small_agent/system_prompt.md。"""
        if path is None:
            path = Path(__file__).resolve().parent / "system_prompt.md"
        return path.read_text(encoding="utf-8").strip()
