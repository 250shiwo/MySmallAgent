"""
tree 工具 - 递归展示目录树结构。

安全级别：safe（只读操作）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class TreeTool(Tool):
    """递归展示指定目录的树状结构（类似 Unix tree 命令）。"""

    name = "tree"
    description = "Display directory structure as a tree. Similar to the Unix 'tree' command."

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Root directory path (default: current directory).",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to display (default: 3).",
                "default": 3,
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Show hidden files and directories starting with '.' (default: false).",
                "default": False,
            },
        },
        "required": [],
    }

    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        path = kwargs.get("path", ".")
        max_depth = kwargs.get("max_depth", 3)
        show_hidden = kwargs.get("show_hidden", False)

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        lines: list[str] = [str(root)]
        self._build_tree(root, lines, "", 0, max_depth, show_hidden)
        return "\n".join(lines)

    def _build_tree(
        self,
        path: Path,
        lines: list[str],
        prefix: str,
        depth: int,
        max_depth: int,
        show_hidden: bool,
    ) -> None:
        if depth >= max_depth:
            return
        try:
            # 目录排前，同类按名称排序
            entries = sorted(
                path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())
            )
        except PermissionError:
            return

        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(
                    entry, lines, prefix + extension, depth + 1, max_depth, show_hidden
                )
