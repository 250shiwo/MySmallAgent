"""
提示词管理模块 - 从文件加载基础系统提示词，动态拼接 skills index。

设计原则：
  - system prompt 前缀在整个会话中保持不变（缓存友好）
  - 技能激活时指令通过 tool result 进入对话历史，不修改 system prompt
"""

from pathlib import Path
from typing import Optional


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

    def _load_base_prompt(self, path: Optional[Path]) -> str:
        """加载基础提示词文件。默认路径: my_small_agent/system_prompt.md。"""
        if path is None:
            path = Path(__file__).resolve().parent / "system_prompt.md"
        return path.read_text(encoding="utf-8").strip()
