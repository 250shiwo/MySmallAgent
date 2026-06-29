"""
grep_search 工具 - 递归搜索项目文件内容。

安全级别：safe（只读操作，不修改文件系统）
"""

import re
from pathlib import Path

from my_small_agent.tools.base import Tool


class GrepSearchTool(Tool):
    """按关键词或正则表达式递归搜索目录下所有文件的内容。"""

    name = "grep_search"
    description = (
        "Recursively search file contents for a keyword or regex pattern. "
        "Returns matching lines with file path and line number."
    )

    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Keyword or regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
                "default": ".",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern to filter file names, e.g. '*.py' (default: '*').",
                "default": "*",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive search (default: false).",
                "default": False,
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

    async def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        path = kwargs.get("path", ".")
        file_pattern = kwargs.get("file_pattern", "*")
        ignore_case = kwargs.get("ignore_case", False)
        max_results = kwargs.get("max_results", 50)

        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        results: list[str] = []
        for file_path in sorted(root.rglob(file_pattern)):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{file_path}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            results.append(f"... (truncated at {max_results} results)")
                            return "\n".join(results)
            except Exception:
                continue

        if not results:
            return f"No matches found for pattern '{pattern}'"
        return "\n".join(results)
