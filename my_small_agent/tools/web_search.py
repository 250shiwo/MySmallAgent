"""
网页搜索工具 - 使用 DuckDuckGo 搜索引擎查询网页信息。

安全级别：safe（只读搜索，无副作用，自动执行）

使用 ddgs 库（原 duckduckgo-search）的 DDGS 同步接口，
通过 asyncio.to_thread() 包装为异步调用，避免阻塞事件循环。
无需 API Key，免费使用。
"""

import asyncio
import json

from ddgs import DDGS

from my_small_agent.tools.base import Tool


class WebSearchTool(Tool):
    """使用 DuckDuckGo 搜索网页并返回结构化结果。"""

    # --- 工具元数据 ---
    name = "web_search"
    description = "Search the web using DuckDuckGo and return top results with titles, URLs, and snippets."

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }

    # 安全级别：safe（只读搜索，自动执行）
    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        """
        执行搜索并返回结果。

        raw=False（默认，供 LLM 使用）：返回人类可读的格式化文本。
        raw=True（供组合工具内部使用）：返回 JSON 格式以便程序化解析。
        """
        query = kwargs["query"]
        max_results = kwargs.get("max_results", 5)
        raw = kwargs.get("raw", False)

        try:
            # 在线程池中执行同步的 DDGS.text()，避免阻塞事件循环
            results = await asyncio.to_thread(
                lambda: DDGS().text(query, max_results=max_results)
            )

            if not results:
                return json.dumps({"results": []}) if raw else "No results found."

            if raw:
                return json.dumps({"results": results}, ensure_ascii=False)

            formatted = []
            for i, r in enumerate(results, 1):
                formatted.append(
                    f"{i}. {r['title']}\n"
                    f"   URL: {r['href']}\n"
                    f"   {r['body']}"
                )
            return "\n\n".join(formatted)

        except Exception as e:
            return f"Error searching: {e}"
