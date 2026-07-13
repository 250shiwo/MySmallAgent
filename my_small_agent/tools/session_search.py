"""
会话历史搜索工具 - 通过关键词搜索过去的对话记录。

安全级别：safe（只读操作，自动执行）

搜索逻辑：遍历 .genesis/sessions/ 下所有 .json 文件，
对每条消息的 content 做大小写不敏感关键词匹配，
返回匹配消息的摘要（含 session_id 前缀和时间戳）。
"""

import json
from pathlib import Path

from my_small_agent.tools.base import Tool


class SessionSearchTool(Tool):
    """通过关键词搜索历史会话消息。"""

    name = "session_search"
    description = (
        "Search past conversation history by keyword. "
        "Returns matching messages with session ID and timestamp context. "
        "Use to recall previous discussions, decisions, or task details."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to search for in past conversations.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }
    danger_level = "safe"
    category = "read_only"

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir

    async def execute(self, **kwargs) -> str:
        """执行关键词搜索，返回格式化结果列表。"""
        query = kwargs["query"]
        max_results = kwargs.get("max_results", 5)
        query_lower = query.lower()

        if not self._sessions_dir.exists():
            return "No session history found."

        matches = []
        for path in self._sessions_dir.glob("*.json"):
            if len(matches) >= max_results:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                continue

            session_id = data.get("session_id", path.stem)
            short_id = session_id[:8]
            # 格式化时间戳：YYYY-MM-DD HH:MM
            updated = data.get("updated_at", "")[:16].replace("T", " ")

            for msg in data.get("messages", []):
                if len(matches) >= max_results:
                    break
                content = msg.get("content") or ""
                if not isinstance(content, str):
                    continue
                if query_lower in content.lower():
                    role = msg.get("role", "?")
                    snippet = content[:100] + ("..." if len(content) > 100 else "")
                    matches.append(f"[{short_id} | {updated}] {role}: {snippet}")

        if not matches:
            return f"No results found for: {query}"

        return "\n".join(f"{i + 1}. {m}" for i, m in enumerate(matches))
