"""
工具注册表模块 - 中心化注册和管理所有可用工具。

设计思路：
  - ToolRegistry 是一个字典容器，以工具名称为 key 存储工具实例
  - 注册后的工具可以转换为 OpenAI 要求的 tools 参数格式
  - create_default_registry(settings) 工厂函数一键注册所有内置工具
  - 未来添加新工具只需：1) 继承 Tool 基类  2) 在注册表中 register
"""

from pathlib import Path

from my_small_agent.config import Settings
from my_small_agent.memory import MemoryManager
from my_small_agent.tools.base import Tool
from my_small_agent.tools.current_time import CurrentTimeTool
from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.memory_save import MemorySaveTool
from my_small_agent.tools.session_search import SessionSearchTool
from my_small_agent.tools.shell_exec import ExecuteShellTool
from my_small_agent.tools.web_search import WebSearchTool


class ToolRegistry:
    """
    中心化工具注册表。

    职责：
      - register(): 注册新工具
      - get():      按名称查找工具
      - get_openai_tools(): 将所有工具转为 OpenAI API 格式
      - list_all(): 列出所有已注册工具
    """

    def __init__(self) -> None:
        # 内部字典：工具名称 → 工具实例
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例到注册表（以 tool.name 作为键）。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """通过名称查找工具，找不到返回 None。"""
        return self._tools.get(name)

    def get_openai_tools(self) -> list[dict]:
        """
        将所有已注册工具转换为 OpenAI API 的 tools 参数格式。

        输出示例：
        [
          {
            "type": "function",
            "function": {
              "name": "read_file",
              "description": "Read the contents of a file...",
              "parameters": {"type": "object", "properties": {...}, ...}
            }
          }
        ]
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def list_all(self) -> list[Tool]:
        """返回所有已注册工具的列表。"""
        return list(self._tools.values())


def create_default_registry(
    settings: Settings,
    memory_manager: MemoryManager | None = None,
    sessions_dir: Path | None = None,
) -> ToolRegistry:
    """
    创建并返回一个包含所有内置工具的注册表。

    内置工具（始终注册）：
      - read_file:       读取文件（安全）
      - write_file:      写入文件（危险，需确认）
      - list_directory:  列出目录（安全）
      - execute_shell:   执行命令（危险，需确认）
      - web_search:      网页搜索（安全）
      - current_time:    当前时间（安全）

    可选工具（需提供对应参数）：
      - memory_save:     保存长期记忆（safe，需 memory_manager）
      - session_search:  搜索历史会话（safe，需 sessions_dir）
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    registry.register(WebSearchTool())
    registry.register(CurrentTimeTool(timezone=settings.timezone))
    if memory_manager is not None:
        registry.register(MemorySaveTool(memory_manager))
    if sessions_dir is not None:
        registry.register(SessionSearchTool(sessions_dir))
    return registry
"""
工具注册表模块 - 中心化注册和管理所有可用工具。

设计思路：
  - ToolRegistry 是一个字典容器，以工具名称为 key 存储工具实例
  - 注册后的工具可以转换为 OpenAI 要求的 tools 参数格式
  - create_default_registry(settings) 工厂函数一键注册所有内置工具
  - 未来添加新工具只需：1) 继承 Tool 基类  2) 在注册表中 register
"""

from my_small_agent.config import Settings
from my_small_agent.tools.base import Tool
from my_small_agent.tools.current_time import CurrentTimeTool
from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.shell_exec import ExecuteShellTool
from my_small_agent.tools.web_search import WebSearchTool


class ToolRegistry:
    """
    中心化工具注册表。

    职责：
      - register(): 注册新工具
      - get():      按名称查找工具
      - get_openai_tools(): 将所有工具转为 OpenAI API 格式
      - list_all(): 列出所有已注册工具
    """

    def __init__(self) -> None:
        # 内部字典：工具名称 → 工具实例
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例到注册表（以 tool.name 作为键）。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """通过名称查找工具，找不到返回 None。"""
        return self._tools.get(name)

    def get_openai_tools(self) -> list[dict]:
        """
        将所有已注册工具转换为 OpenAI API 的 tools 参数格式。

        输出示例：
        [
          {
            "type": "function",
            "function": {
              "name": "read_file",
              "description": "Read the contents of a file...",
              "parameters": {"type": "object", "properties": {...}, ...}
            }
          }
        ]
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def list_all(self) -> list[Tool]:
        """返回所有已注册工具的列表。"""
        return list(self._tools.values())


def create_default_registry(settings: Settings) -> ToolRegistry:
    """
    创建并返回一个包含所有内置工具的注册表。

    内置工具：
      - read_file:       读取文件（安全）
      - write_file:      写入文件（危险，需确认）
      - list_directory:  列出目录（安全）
      - execute_shell:   执行命令（危险，需确认）
      - web_search:      网页搜索（安全）
      - current_time:    当前时间（安全）
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    registry.register(WebSearchTool())
    registry.register(CurrentTimeTool(timezone=settings.timezone))
    return registry
