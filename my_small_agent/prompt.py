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

你当前处于计划模式。请严格遵循两阶段流程：

### 阶段一 — 探索与信息收集
1. 使用只读工具（read_file、list_directory、grep_search、tree、find_file 等）充分探索代码库
2. 读取所有相关文件，搜索已有模式和工具函数，追踪依赖关系
3. 记录精确的文件路径、行号、函数名和变量名
4. 识别每个需要创建或修改的文件
5. 如果用户请求存在歧义，基于代码上下文做出合理推断

### 阶段二 — 生成计划
仅在阶段一完成后才输出计划。输出格式必须严格如下：

## Plan
**Goal**: <一句话目标>

### Steps
1. **<标题>** -- <详细描述，含文件路径、行号或函数名、具体变更内容、预期结果>
2. **<标题>** -- <详细描述>
...

### 计划要求
- 步骤数 3-10 个，按依赖排序
- 标题不超过 60 字符
- 每个步骤描述必须包含：具体文件路径、行号或函数名、具体变更内容、预期结果
- 禁止出现"确认"、"询问用户"、"根据用户选择"、"待定"等需要运行时交互的措辞
- 结尾包含验证步骤
- 如果信息确实不足，明确标注假设前提，而非推迟到执行时询问用户
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
