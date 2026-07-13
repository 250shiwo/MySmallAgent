"""
当前时间工具 - 返回配置时区下的当前日期时间。

安全级别：safe（只读操作，自动执行）

配合 web_search 使用，让 LLM 知道"现在"是什么时候，
从而能搜索最新信息或判断时效性。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from my_small_agent.tools.base import Tool


class CurrentTimeTool(Tool):
    """返回配置时区下的当前日期和时间。"""

    # --- 工具元数据 ---
    name = "current_time"
    description = "Get the current date and time in the configured timezone."

    # 无需参数
    parameters = {
        "type": "object",
        "properties": {},
    }

    # 安全级别：safe（只读，自动执行）
    danger_level = "safe"
    category = "read_only"

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        """初始化时接收时区字符串（如 'Asia/Shanghai'）。"""
        self._timezone = timezone

    async def execute(self, **kwargs) -> str:
        """返回当前时间的格式化字符串，如 '2026-06-25 14:30:00 CST (Thursday)'。"""
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
