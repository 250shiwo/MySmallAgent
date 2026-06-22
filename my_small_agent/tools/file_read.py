"""Tool for reading file contents."""

from my_small_agent.tools.base import Tool


class ReadFileTool(Tool):
    """Read the contents of a file at the given path."""

    name = "read_file"
    description = "Read the contents of a file at the specified path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the file to read.",
            },
        },
        "required": ["path"],
    }
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"
