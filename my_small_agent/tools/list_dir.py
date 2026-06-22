"""Tool for listing directory contents."""

import os

from my_small_agent.tools.base import Tool


class ListDirectoryTool(Tool):
    """List files and subdirectories in the given path."""

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
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        try:
            entries = os.listdir(path)
            if not entries:
                return f"Directory is empty: {path}"
            result_lines = []
            for entry in sorted(entries):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    result_lines.append(f"[DIR]  {entry}")
                else:
                    size = os.path.getsize(full_path)
                    result_lines.append(f"[FILE] {entry} ({size} bytes)")
            return "\n".join(result_lines)
        except FileNotFoundError:
            return f"Error: Directory not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {e}"
