"""
写入文件工具 - 将内容写入指定路径的文件。

安全级别：dangerous（写入操作，会修改文件系统，需要用户确认后才能执行）
"""

import os

from my_small_agent.tools.base import Tool


class WriteFileTool(Tool):
    """将内容写入指定路径的文件，自动创建不存在的父目录。"""

    # --- 工具元数据 ---
    name = "write_file"
    description = "Write content to a file at the specified path. Creates directories if needed."

    # 两个必填参数：文件路径 和 要写入的内容
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }

    # 安全级别：dangerous 表示写入操作，Agent 执行前会弹出确认框
    danger_level = "dangerous"
    category = "write"      # 写入工具，Plan 模式下禁用

    async def execute(self, **kwargs) -> str:
        """将内容写入文件。自动创建不存在的目录。"""
        path = kwargs["path"]
        content = kwargs["content"]
        try:
            # 如果文件在子目录中，先确保目录存在
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # 写入文件内容
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {e}"
