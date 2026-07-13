"""
find_file 工具 - 按 glob 模式递归搜索文件。

安全级别：safe（只读操作）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class FindFileTool(Tool):
    """按文件名 glob 模式在目录中递归搜索文件。"""

    name = "find_file"
    description = (
        "Recursively search for files matching a glob pattern (e.g. '*.py', 'config*.json')."
    )

    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match file names, e.g. '*.py', 'config*.json'.",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from (default: current directory).",
                "default": ".",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 50).",
                "default": 50,
            },
        },
        "required": ["pattern"],
    }

    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        path = kwargs.get("path", ".")
        max_results = kwargs.get("max_results", 50)

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        results: list[str] = []
        for match in sorted(root.rglob(pattern)):
            results.append(str(match))
            if len(results) >= max_results:
                results.append(f"... (truncated at {max_results} results)")
                break

        if not results:
            return f"No files found matching '{pattern}'"
        return "\n".join(results)
