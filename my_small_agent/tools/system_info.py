"""
system_info 工具 - 获取当前运行环境信息。

安全级别：safe（只读操作）
"""

import os
import platform
import sys
from pathlib import Path

from my_small_agent.tools.base import Tool


class SystemInfoTool(Tool):
    """获取当前系统和运行时环境的关键信息，帮助 LLM 做出合理决策。"""

    name = "system_info"
    description = (
        "Get current system and runtime environment information "
        "(OS, Python version, working directory, etc.)."
    )

    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        info = {
            "OS": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "Python": sys.version.split()[0],
            "CWD": str(Path.cwd()),
            "Home": str(Path.home()),
            "Shell": os.environ.get("SHELL") or os.environ.get("COMSPEC", "unknown"),
            "PATH entries": str(len(os.environ.get("PATH", "").split(os.pathsep))),
        }
        return "\n".join(f"{k}: {v}" for k, v in info.items())
