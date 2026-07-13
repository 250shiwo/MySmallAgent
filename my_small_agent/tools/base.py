"""
工具基类模块 - 定义所有工具必须遵守的抽象接口。

设计思路：
  - 使用抽象基类（ABC）强制子类实现特定方法
  - 每个工具需要声明自己的名称、描述、参数格式和安全级别
  - danger_level 决定执行时是否需要用户确认：
      "safe"      → 只读操作，自动执行（如读文件、列目录）
      "dangerous" → 写入/破坏性操作，需要用户确认后才能执行
"""

from abc import ABC, abstractmethod


class Tool(ABC):
    """
    工具抽象基类。所有 Agent 工具都必须继承此类。

    子类必须定义以下类属性：
      name:          工具的唯一标识名（如 "read_file"）
      description:   给 LLM 看的工具描述，帮助模型理解何时使用
      parameters:    JSON Schema 格式的参数定义（OpenAI 要求此格式）
      danger_level:  安全级别，"safe" 或 "dangerous"
      category:      操作分类，"read_only" 或 "write"
                     Plan 模式下仅暴露 read_only 工具，并在执行层拒绝 write 工具

    子类必须实现：
      execute(**kwargs) → str  执行工具逻辑，返回字符串结果
    """

    name: str           # 工具名称，如 "read_file"
    description: str    # 工具描述，展示给 LLM
    parameters: dict    # JSON Schema 参数定义
    danger_level: str   # "safe"（安全，自动执行）| "dangerous"（危险，需确认）
    category: str       # "read_only"（只读）| "write"（写入，Plan 模式下禁用）

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """
        执行工具的核心逻辑。

        参数通过 **kwargs 传入（如 path="/some/file"）。
        返回值必须是字符串，会被作为 tool message 回传给 LLM。
        """
