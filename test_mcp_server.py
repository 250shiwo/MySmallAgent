"""
本地测试用 MCP server（stdio 传输）——用来验证 agent 的 MCP client 链路。

用 mcp SDK 自带的 FastMCP，十几行起一个 server，暴露两个工具。
这也是将来写 MySQL 同步 server（迭代二）的最小模板。

启动方式由 mcp.json 指定：agent 会把它当子进程拉起来。
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """两数相加，返回和。"""
    return a + b


@mcp.tool()
def echo(text: str) -> str:
    """原样回显传入的文本。"""
    return text


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输
