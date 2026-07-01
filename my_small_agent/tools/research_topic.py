"""
research_topic 组合工具 - 链式编排 web_search + fetch_url 实现深度研究。

工作流程：
  1. 调用 web_search 搜索指定 query
  2. 对搜索结果的前 N 个 URL 调用 fetch_url 获取全文
  3. 将所有结果整合为结构化 JSON 返回
"""

import json

from my_small_agent.tools.base import Tool


class ResearchTopicTool(Tool):
    """深度研究工具：搜索 + 获取页面内容的组合编排。"""

    name = "research_topic"
    description = "Deep research a topic: searches the web, fetches top results, and returns structured sources."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询关键词",
            },
            "max_sources": {
                "type": "integer",
                "description": "最多获取的源数量（默认 3）",
            },
        },
        "required": ["query"],
    }
    danger_level = "safe"

    def __init__(self, registry) -> None:
        """接收 ToolRegistry 引用，用于调用其他工具。"""
        self._registry = registry

    async def execute(self, **kwargs) -> str:
        """执行搜索 + 获取的组合编排。"""
        query = kwargs.get("query", "")
        max_sources = kwargs.get("max_sources", 3)

        # Step 1: 搜索
        search_raw = await self._registry.dispatch("web_search", {"query": query})
        try:
            search_data = json.loads(search_raw)
        except json.JSONDecodeError:
            return json.dumps({"success": False, "error": "Search returned invalid data"})

        if "error" in search_data:
            return json.dumps({"success": False, "error": search_data["error"]})

        # Step 2: 获取页面内容
        results = search_data.get("results", [])[:max_sources]
        sources = []
        for item in results:
            url = item.get("href", "")
            title = item.get("title", "")
            if not url:
                continue
            content = await self._registry.dispatch("fetch_url", {"url": url})
            sources.append({"url": url, "title": title, "content": content})

        # Step 3: 返回整合结果
        return json.dumps({
            "success": True,
            "query": query,
            "sources": sources,
        }, ensure_ascii=False)
