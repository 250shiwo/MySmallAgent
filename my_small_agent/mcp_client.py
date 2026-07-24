"""
MCP client 模块 - 连接外部 MCP server，把其 tools 包装为本地 Tool。

设计：
  - 仅 stdio 传输
  - 每次调用即时连接（连→调→断，自包含），不维持持久连接
  - 全程降级不阻断：MCP 不可用时 agent 正常运行
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from my_small_agent.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """单个 MCP server 的启动参数（来自 mcp.json 的一项）。"""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def load_mcp_config(path: str = "mcp.json") -> dict[str, MCPServerConfig]:
    """
    读取 mcp.json，返回 {name: MCPServerConfig}。

    降级不阻断：文件不存在/坏 JSON/结构非法 → 记 warning 返回 {}；
    单条缺 command → 跳过该项。
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"mcp.json 解析失败，忽略 MCP 配置：{e}")
        return {}

    if not isinstance(data, dict):
        logger.warning("mcp.json 结构非法，忽略 MCP 配置")
        return {}

    servers_raw = data.get("mcpServers")
    if not isinstance(servers_raw, dict):
        logger.warning("mcp.json 缺少 mcpServers 对象，忽略 MCP 配置")
        return {}

    result: dict[str, MCPServerConfig] = {}
    for name, entry in servers_raw.items():
        if not isinstance(entry, dict) or "command" not in entry:
            logger.warning(f"MCP server '{name}' 缺少 command，已跳过")
            continue
        result[name] = MCPServerConfig(
            name=name,
            command=entry["command"],
            args=list(entry.get("args", [])),
            env=dict(entry.get("env", {})),
        )
    return result


def _make_tool_name(server: str, tool: str) -> str:
    """拼 mcp_{server}_{tool}，净化非法字符，保留前 64 字符。"""
    raw = f"mcp_{server}_{tool}"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    return cleaned[:64]


def _stringify_result(result) -> str:
    """把 CallToolResult 的 content 块拼为字符串；无文本时回退 JSON。"""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    try:
        return json.dumps(
            getattr(result, "content", []), default=str, ensure_ascii=False
        )
    except (TypeError, ValueError):
        return str(result)


async def _call_remote_tool(cfg: MCPServerConfig, tool_name: str, arguments: dict) -> str:
    """即时连接远程 server，调用 tool，返回文本结果（连→调→断，自包含）。"""
    params = StdioServerParameters(
        command=cfg.command, args=cfg.args, env=cfg.env or None
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _stringify_result(result)


class MCPTool(Tool):
    """包装单个远程 MCP tool。execute 时即时连接。"""

    danger_level = "dangerous"
    category = "write"

    def __init__(
        self, registered_name, remote_tool_name, description, parameters, server_config
    ):
        self.name = registered_name
        self._remote_tool_name = remote_tool_name
        self.description = description
        self.parameters = parameters
        self._server_config = server_config

    async def execute(self, **kwargs) -> str:
        try:
            return await _call_remote_tool(
                self._server_config, self._remote_tool_name, kwargs
            )
        except Exception as e:
            return json.dumps(
                {"error": f"MCP tool '{self.name}' failed: {e}"},
                ensure_ascii=False,
            )


async def _discover_tools(cfg: MCPServerConfig, timeout: float = 30.0) -> list:
    """一次性连接 server 拉取 tool 列表（带超时），连→列→断。"""
    async def _connect():
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.list_tools()).tools

    return await asyncio.wait_for(_connect(), timeout=timeout)


async def register_mcp_tools(registry, config_path: str = "mcp.json") -> None:
    """
    启动时发现并注册所有 MCP server 的 tools。

    降级不阻断：单个 server 连接失败 → 记 warning、跳过、其余照常。
    """
    servers = load_mcp_config(config_path)
    for name, cfg in servers.items():
        try:
            tools = await _discover_tools(cfg)
        except Exception as e:
            logger.warning(f"MCP server '{name}' 连接失败，已跳过：{e}")
            continue
        registered_count = 0
        for t in tools:
            registered = _make_tool_name(name, t.name)
            if registry.get(registered) is not None:
                logger.warning(f"工具名冲突，跳过：{registered}")
                continue
            registry.register(MCPTool(
                registered_name=registered,
                remote_tool_name=t.name,
                description=t.description or "",
                parameters=t.inputSchema or {"type": "object", "properties": {}},
                server_config=cfg,
            ))
            registered_count += 1
        logger.info(f"MCP server '{name}' 已注册 {registered_count}/{len(tools)} 个工具")
