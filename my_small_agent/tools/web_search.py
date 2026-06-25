"""
网页搜索工具 - 使用 DuckDuckGo 搜索引擎查询网页信息。

安全级别：safe（只读搜索，无副作用，自动执行）

使用 ddgs 库（原 duckduckgo-search）的 DDGS 同步接口，
通过 asyncio.to_thread() 包装为异步调用，避免阻塞事件循环。
无需 API Key，免费使用。
"""

import asyncio

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

    async def execute(self, **kwargs) -> str:
        """
        执行搜索并返回格式化结果。

        返回格式示例：
          1. 标题
             URL: https://...
             摘要内容

          2. 标题
             URL: https://...
             摘要内容
        """
        query = kwargs["query"]
        max_results = kwargs.get("max_results", 5)

        try:
            # 在线程池中执行同步的 DDGS.text()，避免阻塞事件循环
            results = await asyncio.to_thread(
                lambda: DDGS().text(query, max_results=max_results)
            )

            if not results:
                return "No results found."

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
