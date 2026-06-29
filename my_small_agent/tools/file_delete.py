"""
file_delete 工具 - 删除指定路径的文件。

安全级别：dangerous（破坏性操作，执行前需用户确认）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class DeleteFileTool(Tool):
    """删除指定路径的文件（不支持删除目录）。"""

    name = "file_delete"
    description = "Delete a file at the specified path. Directories are not supported."

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the file to delete.",
            },
        },
        "required": ["path"],
    }

    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        path = Path(kwargs["path"])
        try:
            if not path.exists():
                return f"Error: File not found: {path}"
            if path.is_dir():
                return f"Error: '{path}' is a directory, not a file. Use shell commands to remove directories."
            path.unlink()
            return f"Successfully deleted: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error deleting file: {e}"
