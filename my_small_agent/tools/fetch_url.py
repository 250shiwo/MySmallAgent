"""
fetch_url 工具 - 获取 URL 内容并提取纯文本。

安全级别：safe（只读网络请求）
依赖：httpx（异步 HTTP 客户端）
"""

import html
import re

import httpx

from my_small_agent.tools.base import Tool


class FetchUrlTool(Tool):
    """获取指定 URL 的网页内容并提取纯文本（去除 HTML 标签）。"""

    name = "fetch_url"
    description = "Fetch the content of a URL and extract plain text, stripping HTML tags."

    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 15).",
                "default": 15,
            },
        },
        "required": ["url"],
    }

    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        url = kwargs["url"]
        timeout = kwargs.get("timeout", 15)
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 (compatible; MySmallAgent/1.0)"}
                )
                response.raise_for_status()
                text = response.text

            # 移除 <script> 和 <style> 标签及其内容
            text = re.sub(
                r"<(script|style)[^>]*>.*?</(script|style)>",
                " ",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # 移除所有 HTML 标签
            text = re.sub(r"<[^>]+>", " ", text)
            # 解码 HTML 实体（&amp; &lt; 等）
            text = html.unescape(text)
            # 合并空白字符
            text = re.sub(r"\s+", " ", text).strip()
            # 截断过长内容
            if len(text) > 8000:
                text = text[:8000] + "\n...(内容已截断)"
            return text or "(空内容)"

        except httpx.TimeoutException:
            return f"Error: Request timed out after {timeout} seconds"
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} for {url}"
        except Exception as e:
            return f"Error fetching URL: {e}"
