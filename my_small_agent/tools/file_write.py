"""Tool for writing content to files."""

import os

from my_small_agent.tools.base import Tool


class WriteFileTool(Tool):
    """Write content to a file at the given path."""

    name = "write_file"
    description = "Write content to a file at the specified path. Creates directories if needed."
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
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        content = kwargs["content"]
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {e}"
