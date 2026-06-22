"""
列出目录工具 - 列出指定目录下的所有文件和子目录。

安全级别：safe（只读操作，自动执行）
"""

import os

from my_small_agent.tools.base import Tool


class ListDirectoryTool(Tool):
    """列出指定目录下的所有文件和子目录，并显示文件大小。"""

    # --- 工具元数据 ---
    name = "list_directory"
    description = "List all files and subdirectories in the specified directory path."

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the directory to list.",
            },
        },
        "required": ["path"],
    }

    # 安全级别：safe（只读，自动执行）
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        """
        列出目录内容。输出格式示例：
          [DIR]  src
          [FILE] readme.md (1234 bytes)
        """
        path = kwargs["path"]
        try:
            entries = os.listdir(path)
            if not entries:
                return f"Directory is empty: {path}"

            result_lines = []
            for entry in sorted(entries):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    # 目录用 [DIR] 标记
                    result_lines.append(f"[DIR]  {entry}")
                else:
                    # 文件显示名称和大小
                    size = os.path.getsize(full_path)
                    result_lines.append(f"[FILE] {entry} ({size} bytes)")
            return "\n".join(result_lines)
        except FileNotFoundError:
            return f"Error: Directory not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {e}"
